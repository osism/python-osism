from celery import Celery

from osism.tasks import Config, run_ansible_in_environment

app = Celery('ansible')
app.config_from_object(Config)


@app.task(bind=True, name="osism.tasks.ansible.run")
def run(self, environment, playbook, arguments):
    run_ansible_in_environment(self.request.id, environment, playbook, arguments)
