# SPDX-License-Identifier: Apache-2.0

import io
import subprocess

from celery import Celery
from loguru import logger
from pottery import Redlock
from osism import settings, utils
from osism.tasks import Config

app = Celery("reconciler")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    sender.add_periodic_task(
        settings.INVENTORY_RECONCILER_SCHEDULE, run_on_change.s(), expires=10
    )


@app.task(bind=True, name="osism.tasks.reconciler.run")
def run(self, publish=True):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_run",
        masters={utils.redis},
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")
        p = subprocess.Popen(
            "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
            if publish:
                utils.redis.xadd(self.request.id, {"type": "stdout", "content": line})

        rc = p.wait(timeout=60)

        if publish:
            utils.redis.xadd(self.request.id, {"type": "rc", "content": rc})
            utils.redis.xadd(self.request.id, {"type": "action", "content": "quit"})

        lock.release()


@app.task(bind=True, name="osism.tasks.reconciler.run_on_change")
def run_on_change(self):
    lock = Redlock(
        key="lock_osism_tasks_reconciler_run_on_change",
        masters={utils.redis},
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
        masters={utils.redis},
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
            utils.redis.publish(
                "netbox-sync-inventory-with-netbox", {"type": "stdout", "content": line}
            )

        lock.release()

    # NOTE: use task_id or request_id in future
    utils.redis.publish(
        "netbox-sync-inventory-with-netbox", {"type": "action", "content": "quit"}
    )
