import io
import subprocess

from celery import Celery
from celery.signals import worker_process_init
from pottery import Redlock
from redis import Redis

from osism import settings
from osism.tasks import Config

app = Celery("reconciler")
app.config_from_object(Config)

redis = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global redis

    redis = Redis(host="redis", port="6379")


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(settings.INVENTORY_RECONCILER_SCHEDULE,  run.s(), expires=10)


@app.task(bind=True, name="osism.tasks.reconciler.run")
def run(self):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_run", masters={redis}, auto_release_time=60
    )

    if lock.acquire(timeout=20):
        p = subprocess.Popen(
            "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        p.wait()

        lock.release()


@app.task(bind=True, name="osism.tasks.reconciler.sync_inventory_with_netbox")
def sync_inventory_with_netbox(self):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_sync_inventory_with_netbox",
        masters={redis},
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        p = subprocess.Popen(
            "/sync-inventory-with-netbox.sh",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            # NOTE: use task_id or request_id in future
            redis.publish("netbox-sync-inventory-with-netbox", line)

        lock.release()

    # NOTE: use task_id or request_id in future
    redis.publish("netbox-sync-inventory-with-netbox", "QUIT")
