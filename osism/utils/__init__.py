# SPDX-License-Identifier: Apache-2.0

import atexit
import threading
import time
import uuid
import os
from contextlib import redirect_stdout, redirect_stderr
from cryptography.fernet import Fernet
import keystoneauth1
from loguru import logger
import openstack
import pynetbox
from pottery import Redlock
from redis import Redis
import requests
from requests.adapters import HTTPAdapter
import urllib3
import yaml

from osism import settings


class RedisSemaphore:
    """Redis-based distributed semaphore for limiting concurrent operations.

    This implementation uses Redis sorted sets to track active holders and enforce
    a maximum concurrency limit.
    """

    def __init__(self, redis_client, key, maxsize, timeout=None):
        """Initialize the semaphore.

        Args:
            redis_client: Redis client instance
            key: Redis key for this semaphore
            maxsize: Maximum number of concurrent holders
            timeout: Optional timeout for acquisition in seconds
        """
        self.redis = redis_client
        self.key = f"semaphore:{key}"
        self.maxsize = maxsize
        self.timeout = timeout
        self.identifier = None

    def acquire(self, timeout=None):
        """Acquire the semaphore.

        Args:
            timeout: Optional timeout in seconds (overrides instance timeout)

        Returns:
            bool: True if acquired, False if timeout
        """
        timeout = timeout or self.timeout or 10
        identifier = str(uuid.uuid4())
        now = time.time()
        end_time = now + timeout

        while time.time() < end_time:
            # Clean up expired holders
            self.redis.zremrangebyscore(self.key, 0, now - 60)

            # Try to acquire
            if self.redis.zcard(self.key) < self.maxsize:
                self.redis.zadd(self.key, {identifier: now})
                self.identifier = identifier
                return True

            time.sleep(0.01)  # Wait 10ms before retry

        return False

    def release(self):
        """Release the semaphore."""
        if self.identifier:
            self.redis.zrem(self.key, self.identifier)
            self.identifier = None

    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            raise TimeoutError(f"Could not acquire semaphore {self.key}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False


class TimeoutHTTPAdapter(HTTPAdapter):
    """HTTPAdapter that sets a default timeout for all requests."""

    def __init__(
        self, timeout=None, pool_connections=10, pool_maxsize=10, *args, **kwargs
    ):
        self.timeout = timeout
        super().__init__(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            *args,
            **kwargs,
        )

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None and self.timeout is not None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


class NetBoxSessionManager:
    """Manages a shared HTTP session for all NetBox connections.

    This class implements lazy initialization of a single shared session
    to prevent file descriptor exhaustion from multiple session instances.
    """

    _session = None
    _lock = None

    @classmethod
    def get_session(cls, ignore_ssl_errors=False, timeout=20):
        """Get or create the shared session (lazy initialization).

        Args:
            ignore_ssl_errors: Whether to ignore SSL certificate errors
            timeout: Request timeout in seconds (default: 20)

        Returns:
            requests.Session: The shared session instance
        """
        if cls._session is None:
            if cls._lock is None:
                cls._lock = threading.Lock()
            with cls._lock:
                if cls._session is None:
                    cls._session = requests.Session()
                    adapter = TimeoutHTTPAdapter(
                        timeout=timeout, pool_connections=10, pool_maxsize=10
                    )
                    cls._session.mount("http://", adapter)
                    cls._session.mount("https://", adapter)
                    if ignore_ssl_errors:
                        urllib3.disable_warnings()
                        cls._session.verify = False
        return cls._session

    @classmethod
    def close_session(cls):
        """Close the shared session and release resources."""
        if cls._session is not None:
            cls._session.close()
            cls._session = None


def cleanup_netbox_sessions():
    """Cleanup function to close all NetBox sessions."""
    NetBoxSessionManager.close_session()


def get_netbox_connection(
    netbox_url, netbox_token, ignore_ssl_errors=False, timeout=20
):
    """Create a NetBox API connection with shared session.

    Args:
        netbox_url: NetBox URL
        netbox_token: NetBox API token
        ignore_ssl_errors: Whether to ignore SSL certificate errors
        timeout: Request timeout in seconds (default: 20)

    Returns:
        pynetbox.api instance or None
    """
    if netbox_url and netbox_token:
        nb = pynetbox.api(netbox_url, token=netbox_token)

        if nb:
            # Use shared session instead of creating new one
            nb.http_session = NetBoxSessionManager.get_session(
                ignore_ssl_errors=ignore_ssl_errors, timeout=timeout
            )

    else:
        nb = None

    return nb


redis = Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    socket_keepalive=True,
)
redis.ping()

nb = get_netbox_connection(
    settings.NETBOX_URL, settings.NETBOX_TOKEN, settings.IGNORE_SSL_ERRORS
)

try:
    secondary_nb_settings_list = yaml.safe_load(settings.NETBOX_SECONDARIES)
    supported_secondary_nb_keys = [
        "NETBOX_URL",
        "NETBOX_TOKEN",
        "IGNORE_SSL_ERRORS",
        "NETBOX_NAME",
        "NETBOX_SITE",
    ]
    secondary_nb_list = []
    if type(secondary_nb_settings_list) is not list:
        raise TypeError(
            f"Setting NETBOX_SECONDARIES needs to be an array of mappings containing supported NetBox API configuration: {supported_secondary_nb_keys}"
        )
    for secondary_nb_settings in secondary_nb_settings_list:
        if type(secondary_nb_settings) is not dict:
            raise TypeError(
                f"Elements in setting NETBOX_SECONDARIES need to be mappings containing supported NetBox API configuration: {supported_secondary_nb_keys}"
            )
        for key in list(secondary_nb_settings.keys()):
            if key not in supported_secondary_nb_keys:
                raise ValueError(
                    f"Unknown key in element of setting NETBOX_SECONDARIES. Supported keys: {supported_secondary_nb_keys}"
                )
        if (
            "NETBOX_URL" not in secondary_nb_settings
            or not secondary_nb_settings["NETBOX_URL"]
        ):
            raise ValueError(
                "All NETBOX_URL values in the elements of setting NETBOX_SECONDARIES need to be valid NetBox URLs"
            )
        if (
            "NETBOX_TOKEN" not in secondary_nb_settings
            or not str(secondary_nb_settings["NETBOX_TOKEN"]).strip()
        ):
            raise ValueError(
                "All NETBOX_TOKEN values in the elements of setting NETBOX_SECONDARIES need to be valid NetBox tokens"
            )

        secondary_nb = get_netbox_connection(
            secondary_nb_settings["NETBOX_URL"],
            str(secondary_nb_settings["NETBOX_TOKEN"]).strip(),
            secondary_nb_settings.get("IGNORE_SSL_ERRORS", True),
        )

        # Store optional metadata as attributes
        if "NETBOX_NAME" in secondary_nb_settings:
            secondary_nb.netbox_name = secondary_nb_settings["NETBOX_NAME"]
        if "NETBOX_SITE" in secondary_nb_settings:
            secondary_nb.netbox_site = secondary_nb_settings["NETBOX_SITE"]

        secondary_nb_list.append(secondary_nb)
except (yaml.YAMLError, TypeError, ValueError) as exc:
    logger.error(f"Error parsing settings NETBOX_SECONDARIES: {exc}")
    secondary_nb_list = []


# Register cleanup handler to close sessions on program exit
atexit.register(cleanup_netbox_sessions)


def get_openstack_connection():
    try:
        conn = openstack.connect()
    except keystoneauth1.exceptions.auth_plugins.MissingRequiredOptions:
        pass

    return conn


def get_ansible_vault_password():
    keyfile = "/share/ansible_vault_password.key"

    try:
        with open(keyfile, "r") as fp:
            key = fp.read()
        f = Fernet(key)

        encrypted_ansible_vault_password = redis.get("ansible_vault_password")
        if encrypted_ansible_vault_password is None:
            raise ValueError("Ansible vault password is not set in Redis")

        ansible_vault_password = f.decrypt(encrypted_ansible_vault_password)
        password = ansible_vault_password.decode("utf-8")

        if not password or password.strip() == "":
            raise ValueError(
                "Ansible vault password is empty or contains only whitespace"
            )

        return password
    except Exception as exc:
        logger.error("Unable to get ansible vault password")
        raise exc


# https://stackoverflow.com/questions/2361426/get-the-first-item-from-an-iterable-that-matches-a-condition
def first(iterable, condition=lambda x: True):
    """
    Returns the first item in the `iterable` that
    satisfies the `condition`.

    If the condition is not given, returns the first item of
    the iterable.

    Raises `StopIteration` if no item satysfing the condition is found.

    >>> first( (1,2,3), condition=lambda x: x % 2 == 0)
    2
    >>> first(range(3, 100))
    3
    >>> first( () )
    Traceback (most recent call last):
    ...
    StopIteration
    """

    return next(x for x in iterable if condition(x))


def fetch_task_output(
    task_id, timeout=os.environ.get("OSISM_TASK_TIMEOUT", 300), enable_play_recap=False
):
    rc = 0
    stoptime = time.time() + timeout
    last_id = 0
    while time.time() < stoptime:
        data = redis.xread({str(task_id): last_id}, count=1, block=(timeout * 1000))
        if data:
            stoptime = time.time() + timeout
            messages = data[0]
            for message_id, message in messages[1]:
                last_id = message_id.decode()
                message_type = message[b"type"].decode()
                message_content = message[b"content"].decode()

                logger.debug(f"Processing message {last_id} of type {message_type}")
                redis.xdel(str(task_id), last_id)

                if message_type == "stdout":
                    print(message_content, end="")
                    if enable_play_recap and "PLAY RECAP" in message_content:
                        logger.info(
                            "Play has been completed. There may now be a delay until "
                            "all logs have been written."
                        )
                        logger.info("Please wait and do not abort execution.")
                elif message_type == "rc":
                    rc = int(message_content)
                elif message_type == "action" and message_content == "quit":
                    redis.close()
                    return rc
    raise TimeoutError


def push_task_output(task_id, line):
    redis.xadd(task_id, {"type": "stdout", "content": line})


def finish_task_output(task_id, rc=None):
    if rc:
        redis.xadd(task_id, {"type": "rc", "content": rc})
    redis.xadd(task_id, {"type": "action", "content": "quit"})


def revoke_task(task_id):
    """
    Revoke a running Celery task.

    Args:
        task_id (str): The ID of the task to revoke

    Returns:
        bool: True if revocation was successful, False otherwise
    """
    try:
        from celery import Celery
        from osism.tasks import Config

        app = Celery("task")
        app.config_from_object(Config)
        app.control.revoke(task_id, terminate=True)
        return True
    except Exception as e:
        logger.error(f"Failed to revoke task {task_id}: {e}")
        return False


def create_redlock(key, auto_release_time=3600):
    """
    Create a Redlock instance with output suppression during initialization.

    Args:
        key (str): The lock key
        auto_release_time (int): Auto release time in seconds (default: 3600)

    Returns:
        Redlock: The configured Redlock instance
    """
    import logging

    # Permanently suppress pottery logger output
    pottery_logger = logging.getLogger("pottery")
    pottery_logger.setLevel(logging.CRITICAL)

    with open(os.devnull, "w") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            return Redlock(
                key=key,
                masters={redis},
                auto_release_time=auto_release_time,
            )


def create_netbox_semaphore(netbox_url, max_connections=None):
    """
    Create a Redis semaphore for limiting concurrent NetBox connections.

    Args:
        netbox_url (str): The NetBox URL to create a semaphore for
        max_connections (int): Maximum concurrent connections (default: from settings.NETBOX_MAX_CONNECTIONS)

    Returns:
        RedisSemaphore: The configured semaphore instance
    """
    if max_connections is None:
        max_connections = settings.NETBOX_MAX_CONNECTIONS

    # Create unique key per NetBox instance based on URL
    import hashlib

    url_hash = hashlib.md5(netbox_url.encode()).hexdigest()[:8]
    key = f"netbox_semaphore_{url_hash}"

    return RedisSemaphore(
        key=key,
        maxsize=max_connections,
        redis_client=redis,
        timeout=30,
    )


def set_task_lock(user=None, reason=None):
    """
    Set task lock to prevent new tasks from starting.

    Args:
        user (str): User who set the lock (optional)
        reason (str): Reason for the lock (optional)

    Returns:
        bool: True if lock was set successfully
    """
    try:
        import json
        from datetime import datetime

        lock_data = {
            "locked": True,
            "timestamp": datetime.now().isoformat(),
            "user": user or "dragon",
            "reason": reason,
        }

        redis.set("osism:task_lock", json.dumps(lock_data))
        return True
    except Exception as e:
        logger.error(f"Failed to set task lock: {e}")
        return False


def remove_task_lock():
    """
    Remove task lock to allow new tasks to start.

    Returns:
        bool: True if lock was removed successfully
    """
    try:
        redis.delete("osism:task_lock")
        return True
    except Exception as e:
        logger.error(f"Failed to remove task lock: {e}")
        return False


def is_task_locked():
    """
    Check if tasks are currently locked.

    Returns:
        dict: Lock status information or None if not locked
    """
    try:
        import json

        lock_data = redis.get("osism:task_lock")
        if lock_data:
            return json.loads(lock_data.decode("utf-8"))
        return None
    except Exception as e:
        logger.error(f"Failed to check task lock status: {e}")
        return None


def check_task_lock_and_exit():
    """
    Check if tasks are locked and exit with error message if they are.
    Used by commands that should not run when tasks are locked.
    """
    lock_info = is_task_locked()
    if lock_info and lock_info.get("locked"):
        user = lock_info.get("user", "unknown")
        timestamp = lock_info.get("timestamp", "unknown")
        reason = lock_info.get("reason")

        logger.error(f"Tasks are currently locked by {user} at {timestamp}")
        if reason:
            logger.error(f"Reason: {reason}")
        logger.error("Use 'osism unlock' to remove the lock")
        exit(1)
