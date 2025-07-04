# SPDX-License-Identifier: Apache-2.0

import time
import os
from contextlib import redirect_stdout, redirect_stderr
from cryptography.fernet import Fernet
import keystoneauth1
from loguru import logger
import openstack
import pynetbox
from pottery import Redlock
from redis import Redis
import urllib3
import yaml

from osism import settings


def get_netbox_connection(netbox_url, netbox_token, ignore_ssl_errors=False):
    if netbox_url and netbox_token:
        nb = pynetbox.api(netbox_url, token=netbox_token)

        if ignore_ssl_errors and nb:
            import requests

            urllib3.disable_warnings()
            session = requests.Session()
            session.verify = False
            nb.http_session = session

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
    supported_secondary_nb_keys = ["NETBOX_URL", "NETBOX_TOKEN", "IGNORE_SSL_ERRORS"]
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
            or not secondary_nb_settings["NETBOX_TOKEN"]
        ):
            raise ValueError(
                "All NETBOX_TOKEN values in the elements of setting NETBOX_SECONDARIES need to be valid NetBox tokens"
            )

        secondary_nb_list.append(
            get_netbox_connection(
                secondary_nb_settings["NETBOX_URL"],
                secondary_nb_settings["NETBOX_TOKEN"],
                secondary_nb_settings.get("IGNORE_SSL_ERRORS", True),
            )
        )
except (yaml.YAMLError, TypeError, ValueError) as exc:
    logger.error(f"Error parsing settings NETBOX_SECONDARIES: {exc}")
    secondary_nb_list = []


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
        ansible_vault_password = f.decrypt(encrypted_ansible_vault_password)
        return ansible_vault_password.decode("utf-8")
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
