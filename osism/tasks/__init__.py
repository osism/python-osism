import os

import ansible_runner


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
        'osism.tasks.kolla.*': {
            'queue': 'kolla-ansible'
        },
        'osism.tasks.osism.*': {
            'queue': 'osism-ansible'
        }
    }


def run_ansible_in_environment(request_id, environment, playbook, arguments):
    os.mkdir(f"/tmp/{request_id}")

    # NOTE: check for existence of ansible.cfg inside the used environment

    envvars = {
        "ANSIBLE_CONFIG": "/opt/configuration/environments/ansible.cfg",
        "ANSIBLE_DIRECTORY": "/ansible",
        "ANSIBLE_INVENTORY": "/ansible/inventory",
        "CONFIGURATION_DIRECTORY": "/opt/configuration",
        "ENVIRONMENTS_DIRECTORY": "/opt/configuration/environments",
        "ANSIBLE_CALLBACK_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/callback",
        "ANSIBLE_ACTION_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/action",
        "ANSIBLE_LOOKUP_PLUGINS": "/usr/local/lib/python3.8/dist-packages/ara/plugins/lookup"
    }

    extravars = {}

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

    ansible_runner.interface.run(
        private_data_dir=f"/tmp/{request_id}",
        ident=request_id,
        project_dir="/opt/configuration/environments",
        inventory="/ansible/inventory",
        playbook=f"/ansible/{environment}-{playbook}.yml",
        envvars=envvars,
        extravars=extravars,
        cmdline=" ".join(cmdline + arguments)
    )
