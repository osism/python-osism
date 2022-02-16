from celery import Celery

from osism.tasks import Config

app = Celery('conductor')
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.conductor.run")
def run(self):
    pass
