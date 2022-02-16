from celery import Celery
from celery.signals import worker_process_init
from redis import Redis
import yaml

from osism.tasks import Config

app = Celery('conductor')
app.config_from_object(Config)


configuration = {}
redis = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global configuration
    global redis

    redis = Redis(host="redis", port="6379")

    with open("/etc/conductor.yml") as fp:
        configuration = yaml.load(fp, Loader=yaml.SafeLoader)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@app.task(bind=True, name="osism.tasks.conductor.get_ironic_parameters")
def get_ironic_parameters(self):
    if "ironic_parameters" in configuration:
        return configuration["ironic_parameters"]

    return {}
