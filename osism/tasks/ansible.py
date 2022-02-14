from celery import Celery

from osism.tasks import Config, run_ansible_in_environment

app = Celery('ansible')
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(600.0, gather_facts.s(), expires=10)


@app.task(bind=True, name="osism.tasks.ansible.gather_facts")
def gather_facts(self):
    return run_ansible_in_environment(self.request.id, "generic", "facts", [])


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(self, environment, playbook, arguments):
    return run_ansible_in_environment(self.request.id, environment, playbook, arguments)
