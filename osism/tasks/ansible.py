# SPDX-License-Identifier: Apache-2.0

from celery import Celery

from osism import settings, utils
from osism.tasks import Config, run_ansible_in_environment

app = Celery("ansible")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    lock = utils.create_redlock(
        key="lock_osism_tasks_ansible_setup_periodic_tasks",
    )
    if settings.GATHER_FACTS_SCHEDULE > 0 and lock.acquire(timeout=10):
        sender.add_periodic_task(
            settings.GATHER_FACTS_SCHEDULE, gather_facts.s(), expires=10
        )


@app.task(bind=True, name="osism.tasks.ansible.gather_facts")
def gather_facts(self, publish=True):
    return run_ansible_in_environment(
        self.request.id, "osism-ansible", "generic", "facts", [], publish, False
    )


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(
    self,
    environment,
    playbook,
    arguments,
    publish=True,
    locking=False,
    auto_release_time=3600,
):
    return run_ansible_in_environment(
        self.request.id,
        "osism-ansible",
        environment,
        playbook,
        arguments,
        publish,
        locking,
        auto_release_time,
    )


@app.task(bind=True, name="osism.tasks.ansible.noop")
def noop(self):
    return True
