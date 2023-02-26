from celery import Celery

from osism.tasks import Config, run_ansible_in_environment

app = Celery("ceph")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.ceph.run")
def run(self, environment, playbook, arguments, publish=True):
    return run_ansible_in_environment(
        self.request.id, "ceph-ansible", environment, playbook, arguments, publish
    )
