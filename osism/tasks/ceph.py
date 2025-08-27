# SPDX-License-Identifier: Apache-2.0

from celery import Celery

from osism import utils
from osism.tasks import Config, run_ansible_in_environment

app = Celery("ceph")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.ceph.run")
def run(self, environment, playbook, arguments, publish=True, auto_release_time=3600):
    # Check if tasks are locked before execution
    utils.check_task_lock_and_exit()

    return run_ansible_in_environment(
        self.request.id,
        "ceph-ansible",
        environment,
        playbook,
        arguments,
        publish,
        False,
        auto_release_time,
    )
