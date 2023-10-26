# SPDX-License-Identifier: Apache-2.0

import io
import os
from pathlib import Path
import subprocess
from osism import settings
from celery.signals import worker_process_init
from loguru import logger
from redis import Redis
from pottery import Redlock

redis = None


class Config:
    enable_utc = True
    enable_bifrost = os.environ.get("ENABLE_BIFROST", "False")
    enable_ironic = os.environ.get("ENABLE_IRONIC", "True")
    broker_url = "redis://redis"
    result_backend = "redis://redis"
    task_create_missing_queues = True
    task_default_queue = "default"
    task_track_started = (True,)
    task_routes = {
        "osism.tasks.ceph.*": {"queue": "ceph-ansible"},
        "osism.tasks.conductor.*": {"queue": "conductor"},
        "osism.tasks.kolla.*": {"queue": "kolla-ansible"},
        "osism.tasks.netbox.*": {"queue": "netbox"},
        "osism.tasks.ansible.*": {"queue": "osism-ansible"},
        "osism.tasks.reconciler.*": {"queue": "reconciler"},
        "osism.tasks.openstack.*": {"queue": "openstack"},
    }


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global redis

    redis = Redis(
        host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB
    )
    redis.ping()


def run_ansible_in_environment(
    request_id, worker, environment, role, arguments, publish=True, locking=True, auto_release_time=3600
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
    ansible_vault_password = redis.get("ansible_vault_password")
    if ansible_vault_password:
        env["VAULT"] = "/ansible-vault.py"

    # NOTE: Consider arguments in the future
    if locking:
        lock = Redlock(
            key=f"lock-ansible-{environment}-{role}",
            masters={redis},
            auto_release_time=auto_release_time,
        )

    # NOTE: use python interface in the future, something with ansible-runner and the fact cache is
    #       not working out of the box

    # execute roles from kolla-ansible
    if worker == "kolla-ansible":
        if locking:
            lock.acquire()

        if role == "mariadb_backup":
            p = subprocess.Popen(
                f"/run.sh backup {role} {joined_arguments}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        else:
            p = subprocess.Popen(
                f"/run.sh deploy {role} {joined_arguments}",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

    # execute roles from ceph-ansible
    elif worker == "ceph-ansible":
        if locking:
            lock.acquire()

        p = subprocess.Popen(
            f"/run.sh {role} {joined_arguments}",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    # execute the bifrost-command role
    elif (
        worker == "osism-ansible"
        and environment == "manager"
        and role == "bifrost-command"
    ):
        p = subprocess.Popen(
            f'/run-manager.sh bifrost-command "-e bifrost_arguments=\'{joined_arguments}\'" "-e bifrost_result_id={request_id}"',
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    # execute local netbox playbooks
    elif worker == "osism-ansible" and environment == "netbox-local":
        if locking:
            lock.acquire()

        p = subprocess.Popen(
            f"/run-{environment}.sh {role} {joined_arguments}",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    # execute all other roles
    else:
        if locking:
            lock.acquire()

        p = subprocess.Popen(
            f"/run-{environment}.sh {role} {joined_arguments}",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    # process the bifrost-command result
    if (
        worker == "osism-ansible"
        and environment == "manager"
        and role == "bifrost-command"
    ):
        p.wait()

        # Check for JSON result
        resultpath = f"/tmp/bifrost-command-{request_id}.json"
        if os.path.exists(resultpath):
            result = Path(resultpath).read_text()
            os.remove(resultpath)

        # Check for non-JSON result
        resultpath = f"/tmp/bifrost-command-{request_id}.log"
        if os.path.exists(resultpath):
            result = Path(resultpath).read_text()
            os.remove(resultpath)

    # process all other results
    else:
        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            if publish:
                redis.xadd(request_id, {"type": "stdout", "content": line})
            result += line

        rc = p.wait(timeout=60)

        if publish:
            redis.xadd(request_id, {"type": "rc", "content": rc})
            redis.xadd(request_id, {"type": "action", "content": "quit"})

        if locking:
            lock.release()

    return result
