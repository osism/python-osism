from celery import Celery

from osism.tasks import Config, run_ansible_in_environment

app = Celery("kolla")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.kolla.run")
def run(self, environment, playbook, arguments, publish=True):
    return run_ansible_in_environment(
        self.request.id, "kolla-ansible", environment, playbook, arguments, publish
    )
