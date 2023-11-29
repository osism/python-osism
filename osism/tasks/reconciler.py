# SPDX-License-Identifier: Apache-2.0

import functools
import io
import subprocess
from threading import RLock

from celery import Celery
from celery.signals import worker_process_init
import kombu.utils
from loguru import logger
from pottery import Redlock
from redis import Redis

from osism import settings
from osism.tasks import Config


# https://github.com/celery/kombu/issues/1804
if not getattr(kombu.utils.cached_property, "lock", None):
    setattr(
        kombu.utils.cached_property,
        "lock",
        functools.cached_property(lambda _: RLock()),
    )
    # Must call __set_name__ here since this cached property is not defined in the context of a class
    # Refer to https://docs.python.org/3/reference/datamodel.html#object.__set_name__
    kombu.utils.cached_property.lock.__set_name__(kombu.utils.cached_property, "lock")

app = Celery("reconciler")
app.config_from_object(Config)

redis = None


@worker_process_init.connect
def celery_init_worker(**kwargs):
    global redis

    redis = Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        socket_keepalive=True,
    )
    redis.ping()


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.INVENTORY_RECONCILER_SCHEDULE, run_on_change.s(), expires=10
    )


@app.task(bind=True, name="osism.tasks.reconciler.run")
def run(self, publish=True):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_run", masters={redis}, auto_release_time=60
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")
        p = subprocess.Popen(
            "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            if publish:
                redis.xadd(self.request.id, {"type": "stdout", "content": line})

        rc = p.wait(timeout=60)

        if publish:
            redis.xadd(self.request.id, {"type": "rc", "content": rc})
            redis.xadd(self.request.id, {"type": "action", "content": "quit"})

        lock.release()


@app.task(bind=True, name="osism.tasks.reconciler.run_on_change")
def run_on_change(self):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_run_on_change",
        masters={redis},
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")
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
            redis.publish(
                "netbox-sync-inventory-with-netbox", {"type": "stdout", "content": line}
            )

        lock.release()

    # NOTE: use task_id or request_id in future
    redis.publish(
        "netbox-sync-inventory-with-netbox", {"type": "action", "content": "quit"}
    )
