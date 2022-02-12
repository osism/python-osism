from celery import Celery
from celery.signals import worker_process_init
from redis import Redis

from osism.tasks import Config

app = Celery('ironic')
app.config_from_object(Config)

redis = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global redis

    redis = Redis(host="redis", port="6379")


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass
