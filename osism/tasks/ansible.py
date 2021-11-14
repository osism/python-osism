import os

import ansible_runner
from celery import Celery


class Config:
    enable_utc = True
    broker_url = "redis://redis"
    result_backend = "redis://redis"
    task_create_missing_queues = True
    task_default_queue = "default"
    task_routes = {'osism.tasks.ansible.*': {'queue': 'ansible'}}


app = Celery('ansible')
app.config_from_object(Config)


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(self, environment, playbook, arguments):

    request_id = self.request.id
    os.mkdir(f"/tmp/{request_id}")

    # NOTE: check for existence of ansible.cfg inside the used environment

    envvars = {
        "ANSIBLE_CONFIG": "/opt/configuration/environments/ansible.cfg",
        "ANSIBLE_DIRECTORY": "/ansible",
        "ANSIBLE_INVENTORY": "/ansible/inventory",
        "CONFIGURATION_DIRECTORY": "/opt/configuration",
        "ENVIRONMENTS_DIRECTORY": "/opt/configuration/environments"
    }

    cmdline = [
        f"-e @/opt/configuration/environments/{environment}/configuration.yml",
        f"-e @/opt/configuration/environments/{environment}/secrets.yml",
        "-e @secrets.yml",
        "-e @images.yml",
        "-e @configuration.yml"
    ]

    runner = ansible_runner.interface.run(
        private_data_dir=f"/tmp/{request_id}",
        ident=request_id,
        project_dir="/opt/configuration/environments",
        inventory="/ansible/inventory",
        playbook=f"/ansible/{environment}-{playbook}.yml",
        envvars=envvars,
        cmdline=" ".join(cmdline + arguments)
    )
    return request_id
