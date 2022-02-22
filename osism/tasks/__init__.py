import io
import os
from pathlib import Path
import subprocess

# import ansible_runner
from celery.signals import worker_process_init
from redis import Redis
from pottery import Redlock


redis = None


class Config:
    enable_utc = True
    broker_url = "redis://redis"
    result_backend = "redis://redis"
    task_create_missing_queues = True
    task_default_queue = "default"
    task_routes = {
        'osism.tasks.ceph.*': {
            'queue': 'ceph-ansible'
        },
        'osism.tasks.conductor.*': {
            'queue': 'conductor'
        },
        'osism.tasks.kolla.*': {
            'queue': 'kolla-ansible'
        },
        'osism.tasks.netbox.*': {
            'queue': 'netbox'
        },
        'osism.tasks.ansible.*': {
            'queue': 'osism-ansible'
        },
        'osism.tasks.reconciler.*': {
            'queue': 'reconciler'
        },
        'osism.tasks.openstack.*': {
            'queue': 'openstack'
        }
    }


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global redis

    redis = Redis(host="redis", port="6379")


def run_ansible_in_environment(request_id, environment, role, arguments):
    result = None

    if type(arguments) == list:
        joined_arguments = " ".join(arguments)
    else:
        joined_arguments = arguments

    # NOTE: Consider arguments in the future
    lock = Redlock(key=f"lock-ansible-{environment}-{role}",
                   masters={redis},
                   auto_release_time=3600)

    # NOTE: use python interface in the future, something with ansible-runner and the fact cache is
    #       not working out of the box

    # execute roles from Kolla
    if environment == "kolla":
        lock.acquire()
        p = subprocess.Popen(f"/run.sh deploy {role} {joined_arguments}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # execute roles from Ceph
    elif environment == "ceph":
        lock.acquire()
        p = subprocess.Popen(f"/run.sh {role} {joined_arguments}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # execute the bifrost-command role
    elif environment == "manager" and role == "bifrost-command":
        p = subprocess.Popen(f"/run-manager.sh bifrost-command \"-e bifrost_arguments='{joined_arguments}'\" \"-e bifrost_result_id={request_id}\"",
                             shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # execute all other roles
    else:
        lock.acquire()
        p = subprocess.Popen(f"/run-{environment}.sh {role} {joined_arguments}", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    # process the bifrost-command result
    if environment == "manager" and role == "bifrost-command":
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
            # NOTE: use task_id or request_id in future
            redis.publish(f"{environment}-{role}", line)

        # NOTE: use task_id or request_id in future
        redis.publish(f"{environment}-{role}", "QUIT")
        lock.release()

    return result


""" def run_ansible_in_environment(request_id, environment, playbook, arguments):
    os.mkdir(f"/tmp/{request_id}")

    # NOTE: check for existence of ansible.cfg inside the used environment

    # NOTE: https://docs.ansible.com/ansible/latest/reference_appendices/config.html
    envvars = {
        "ANSIBLE_CONFIG": "/opt/configuration/environments/ansible.cfg",
        "ANSIBLE_DIRECTORY": "/ansible",
        "ANSIBLE_INVENTORY": "/ansible/inventory",
        "CACHE_PLUGIN": "redis",
        "CACHE_PLUGIN_CONNECTION": "cache:6379:0",
        "CACHE_PLUGIN_TIMEOUT": "86400",
        "CONFIGURATION_DIRECTORY": "/opt/configuration",
        "ENVIRONMENTS_DIRECTORY": "/opt/configuration/environments",
        "ANSIBLE_CALLBACK_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/callback",
        "ANSIBLE_ACTION_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/action",
        "ANSIBLE_LOOKUP_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/lookup"
    }

    extravars = {}

    # NOTE: https://ansible-runner.readthedocs.io/en/stable/intro.html#env-settings-settings-for-runner-itself
    settings = {
        "fact_cache_type": "json"
    }

    cmdline = [
        "--vault-password-file /opt/configuration/environments/.vault_pass",
        f"-e @/opt/configuration/environments/{environment}/configuration.yml",
        f"-e @/opt/configuration/environments/{environment}/secrets.yml",
        "-e @secrets.yml",
        "-e @images.yml",
        "-e @configuration.yml"
    ]

    if environment == "kolla":
        extravars["CONFIG_DIR"] = f"/opt/configuration/environments/{environment}"
        extravars["kolla_action"] = "deploy"

    if environment == "ceph":
        cmdline.append("--skip-tags=with_pkg")

    # NOTE: https://github.com/ansible/ansible-runner/blob/devel/ansible_runner/interface.py
    ansible_runner.interface.run(
        private_data_dir=f"/tmp/{request_id}",
        ident=request_id,
        project_dir="/opt/configuration/environments",
        inventory="/ansible/inventory",
        playbook=f"/ansible/{environment}-{playbook}.yml",
        envvars=envvars,
        extravars=extravars,
        cmdline=" ".join(cmdline + arguments),
        settings=settings
    )
 """
