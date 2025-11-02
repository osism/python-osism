# SPDX-License-Identifier: Apache-2.0

import fcntl
import json
import os
import re
import subprocess
import yaml
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from osism import utils

# Regex pattern for extracting hosts from Ansible output
HOST_PATTERN = re.compile(r"^(ok|changed|failed|skipping|unreachable):\s+\[([^\]]+)\]")


class Config:
    broker_connection_retry_on_startup = True
    enable_utc = True
    enable_ironic = os.environ.get("ENABLE_IRONIC", "True")
    broker_url = "redis://redis"
    result_backend = "redis://redis"
    task_create_missing_queues = True
    task_default_queue = "default"
    task_track_started = (True,)
    task_routes = {
        "osism.tasks.ansible.*": {"queue": "osism-ansible"},
        "osism.tasks.ceph.*": {"queue": "ceph-ansible"},
        "osism.tasks.conductor.*": {"queue": "conductor"},
        "osism.tasks.kolla.*": {"queue": "kolla-ansible"},
        "osism.tasks.kubernetes.*": {"queue": "kubernetes"},
        "osism.tasks.netbox.*": {"queue": "netbox"},
        "osism.tasks.openstack.*": {"queue": "openstack"},
        "osism.tasks.reconciler.*": {"queue": "reconciler"},
    }


def get_container_version(worker):
    """Read container version from YAML version file.

    Args:
        worker: The runtime container name (osism-ansible, kolla-ansible, ceph-ansible, osism-kubernetes)

    Returns:
        str: The container version, "latest" if empty, or "unknown" if not found

    Examples:
        >>> get_container_version("osism-ansible")
        "7.0.5a"
        >>> get_container_version("kolla-ansible")
        "18.1.0"
        >>> get_container_version("osism-kubernetes")
        "1.29.0"

    Note:
        If the version parameter in the YAML file is an empty string (""),
        the function returns "latest" as the default value.
    """
    version_file = Path(f"/interface/versions/{worker}.yml")

    try:
        if not version_file.exists():
            logger.debug(f"Version file not found: {version_file}")
            return "unknown"

        with open(version_file, "r") as f:
            version_data = yaml.safe_load(f)

        # Convert worker name to version parameter name
        # osism-ansible -> osism_ansible_version
        # kolla-ansible -> kolla_ansible_version
        # ceph-ansible -> ceph_ansible_version
        version_key = f"{worker.replace('-', '_')}_version"

        version = version_data.get(version_key, "unknown")

        # If version is empty string, use "latest" as default
        if version == "":
            version = "latest"
            logger.debug(f"Version parameter empty for {worker}, using 'latest'")

        logger.debug(f"Read version {version} for {worker} from {version_file}")
        return version

    except Exception as e:
        logger.warning(f"Failed to read version from {version_file}: {e}")
        return "unknown"


def log_play_execution(
    request_id, worker, environment, role, hosts=None, arguments=None, result="started"
):
    """Log Ansible play execution to central tracking file.

    Args:
        request_id: The Celery task request ID for correlation
        worker: The runtime container (osism-ansible, kolla-ansible, ceph-ansible, osism-kubernetes)
        environment: The environment parameter
        role: The playbook/role that was executed
        hosts: List of hosts the play was executed against (default: empty list)
        arguments: Command-line arguments passed to ansible-playbook (default: None)
        result: Execution result - "started", "success", or "failure"
    """
    log_file = Path("/share/ansible-execution-history.json")

    # Get runtime version from YAML version file
    runtime_version = get_container_version(worker)

    # Use provided hosts or empty list
    if hosts is None:
        hosts = []

    execution_record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "worker": worker,
        "worker_version": runtime_version,
        "environment": environment,
        "role": role,
        "hosts": hosts,
        "arguments": arguments if arguments else "",
        "result": result,
    }

    try:
        # Create directory if it doesn't exist
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Append with file locking for thread safety
        with open(log_file, "a") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json.dumps(execution_record) + "\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        # Log warning but don't fail the execution
        logger.warning(f"Failed to log play execution to {log_file}: {e}")


def run_ansible_in_environment(
    request_id,
    worker,
    environment,
    role,
    arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
):
    result = ""
    extracted_hosts = set()  # Local set for host deduplication

    if type(arguments) == list:
        joined_arguments = " ".join(arguments)
    else:
        joined_arguments = arguments

    # Add kolla_action_stop_ignore_missing=true for kolla-ansible stop actions
    if worker == "kolla-ansible" and "-e kolla_action=stop" in joined_arguments:
        if "-e kolla_action_stop_ignore_missing=true" not in joined_arguments:
            joined_arguments += " -e kolla_action_stop_ignore_missing=true"

    env = os.environ.copy()

    # Bring back colored Ansible output, thanks to
    # https://www.jeffgeerling.com/blog/2020/getting-colorized-output-molecule-and-ansible-on-github-actions-ci
    env["ANSIBLE_FORCE_COLOR"] = "1"
    env["PY_COLORS"] = "1"

    # handle sub environments
    if "." in environment:
        sub_name = environment.split(".")[1]
        env["SUB"] = environment
        environment = environment.split(".")[0]
        logger.info(
            f"worker = {worker}, environment = {environment}, sub = {sub_name}, role = {role}"
        )
    else:
        logger.info(f"worker = {worker}, environment = {environment}, role = {role}")

    env["ENVIRONMENT"] = environment

    # NOTE: This is a first step to make Ansible Vault usable via OSISM workers.
    #       It's not ready in that form yet.
    ansible_vault_password = utils.redis.get("ansible_vault_password")
    if ansible_vault_password:
        env["VAULT"] = "/ansible-vault.py"

    # Log play execution start
    log_play_execution(
        request_id=request_id,
        worker=worker,
        environment=environment,
        role=role,
        hosts=None,  # Hosts will be empty at start, filled at completion
        arguments=joined_arguments,
        result="started",
    )

    # NOTE: Consider arguments in the future
    if locking:
        lock = utils.create_redlock(
            key=f"lock-ansible-{environment}-{role}",
            auto_release_time=auto_release_time,
        )

    # NOTE: use python interface in the future, something with ansible-runner and the fact cache is
    #       not working out of the box

    # execute roles from kolla-ansible
    if worker == "kolla-ansible":
        if locking:
            lock.acquire()

        if role in ["mariadb-backup", "mariadb_backup"]:
            action = "backup"
            role = "mariadb"
            # Hacky workaround. The handling of kolla_action will be revised in the future.
            joined_arguments = re.sub(
                r"-e kolla_action=(bootstrap|config|deploy|precheck|pull|reconfigure|refresh-containers|start|stop|upgrade)",
                r"-e kolla_action=backup",
                joined_arguments,
            )
        else:
            action = "deploy"

        command = f"/run.sh {action} {role} {joined_arguments}"
        logger.info(f"RUN {command}")
        p = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            env=env,
        )

    # execute roles from osism-kubernetes
    elif worker == "osism-kubernetes":
        if locking:
            lock.acquire()

        command = f"/run.sh {role} {joined_arguments}"
        logger.info(f"RUN {command}")
        p = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            env=env,
        )

    # execute roles from ceph-ansible
    elif worker == "ceph-ansible":
        if locking:
            lock.acquire()

        command = f"/run.sh {role} {joined_arguments}"
        logger.info(f"RUN {command}")
        p = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            env=env,
        )

    # execute all other roles
    else:
        if locking:
            lock.acquire()

        command = f"/run-{environment}.sh {role} {joined_arguments}"
        logger.info(f"RUN {command}")
        p = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
            env=env,
        )

    while p.poll() is None:
        line = p.stdout.readline().decode("utf-8")

        # Extract hosts from Ansible output
        match = HOST_PATTERN.match(line.strip())
        if match:
            hostname = match.group(2)
            extracted_hosts.add(hostname)  # Local set (automatic deduplication)

        if publish:
            utils.push_task_output(request_id, line)
        result += line

    rc = p.wait(timeout=60)

    # Log play execution result
    log_play_execution(
        request_id=request_id,
        worker=worker,
        environment=environment,
        role=role,
        hosts=sorted(list(extracted_hosts)),  # Direct pass of extracted hosts
        arguments=joined_arguments,
        result="success" if rc == 0 else "failure",
    )

    if publish:
        utils.finish_task_output(request_id, rc=rc)

    if locking:
        lock.release()

    return result


def run_command(
    request_id,
    command,
    env,
    *arguments,
    publish=True,
    locking=False,
    ignore_env=False,
    auto_release_time=3600,
):
    result = ""

    if ignore_env:
        command_env = env
    else:
        command_env = os.environ.copy()
        command_env.update(env)

    if locking:
        lock = utils.create_redlock(
            key=f"lock-{command}",
            auto_release_time=auto_release_time,
        )

    p = subprocess.Popen(
        [command] + list(arguments),
        env=command_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    while p.poll() is None:
        line = p.stdout.readline().decode("utf-8")
        if publish:
            utils.push_task_output(request_id, line)
        result += line

    rc = p.wait(timeout=60)

    if publish:
        utils.finish_task_output(request_id, rc=rc)

    if locking:
        lock.release()

    return result


def handle_task(t, wait=True, format="log", timeout=3600):
    if wait:
        try:
            return utils.fetch_task_output(t.id, timeout=timeout)
        except TimeoutError:
            logger.info(
                f"There has been no output from the task {t.task_id} for {timeout} second(s)."
            )
            logger.info(
                f"The task timeout of {timeout} second(s) can be adjusted using the --timeout parameter."
            )
            logger.info(
                f"Task {t.task_id} is still running in background. Check ARA for further logs. "
            )
            logger.info(
                "Use this command to continue waiting for this task: "
                f"osism wait --output --live --delay 2 {t.task_id}"
            )
            return 1
        except KeyboardInterrupt:
            logger.info(f"\nTask {t.task_id} interrupted by user (CTRL+C)")

            # Prompt user for task revocation in interactive mode using prompt-toolkit
            try:
                from prompt_toolkit import prompt

                # Use prompt-toolkit for better UX with yes/no options and default
                response = (
                    prompt(
                        "Do you want to revoke the running task? [y/N]: ", default="n"
                    )
                    .strip()
                    .lower()
                )

                if response in ["y", "yes"]:
                    logger.info(f"Revoking task {t.task_id}...")
                    if utils.revoke_task(t.task_id):
                        logger.info(f"Task {t.task_id} has been revoked")
                    else:
                        logger.error(f"Failed to revoke task {t.task_id}")
                else:
                    logger.info(f"Task {t.task_id} continues running in background")
                    logger.info(
                        "Use this command to continue waiting for this task: "
                        f"osism wait --output --live --delay 2 {t.task_id}"
                    )
            except KeyboardInterrupt:
                # Handle second CTRL+C during prompt
                logger.info(f"\nTask {t.task_id} continues running in background")
                logger.info(
                    "Use this command to continue waiting for this task: "
                    f"osism wait --output --live --delay 2 {t.task_id}"
                )
            except EOFError:
                # Handle EOF (e.g., when input is not available)
                logger.info(f"Task {t.task_id} continues running in background")
                logger.info(
                    "Use this command to continue waiting for this task: "
                    f"osism wait --output --live --delay 2 {t.task_id}"
                )
            return 1

    else:
        if format == "log":
            logger.info(
                f"Task {t.task_id} is running in background. No more output. Check ARA for logs."
            )
        elif format == "script":
            print(f"{t.task_id}")

        return 0
