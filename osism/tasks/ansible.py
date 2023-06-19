from celery import Celery

from osism import settings
from osism.tasks import Config, run_ansible_in_environment

app = Celery("ansible")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.GATHER_FACTS_SCHEDULE, gather_facts.s(), expires=10
    )


@app.task(bind=True, name="osism.tasks.ansible.gather_facts")
def gather_facts(self, publish=True):
    return run_ansible_in_environment(
        self.request.id, "osism-ansible", "generic", "facts", [], publish
    )


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(self, environment, playbook, arguments, publish=True, locking=True):
    return run_ansible_in_environment(
        self.request.id, "osism-ansible", environment, playbook, arguments, publish, locking
    )
