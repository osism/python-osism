# SPDX-License-Identifier: Apache-2.0

import os
import re
import subprocess

from loguru import logger

from osism import utils


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

    if type(arguments) == list:
        joined_arguments = " ".join(arguments)
    else:
        joined_arguments = arguments

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

    # execute roles from kubernetes
    elif worker == "kubernetes":
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
        if publish:
            utils.push_task_output(request_id, line)
        result += line

    rc = p.wait(timeout=60)

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

    else:
        if format == "log":
            logger.info(
                f"Task {t.task_id} is running in background. No more output. Check ARA for logs."
            )
        elif format == "script":
            print(f"{t.task_id}")

        return 0
