from celery import Celery

from osism.tasks import Config, run_ansible_in_environment

app = Celery('ceph')
app.config_from_object(Config)


@app.task(bind=True, name="osism.tasks.ceph.run")
def run(self, playbook, arguments):
    run_ansible_in_environment(self.request.id, "ceph", playbook, arguments)
