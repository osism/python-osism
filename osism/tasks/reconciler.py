# SPDX-License-Identifier: Apache-2.0

import io
import os
import subprocess

from celery import Celery
from loguru import logger

from osism import settings, utils
from osism.tasks import Config

app = Celery("reconciler")
app.config_from_object(Config)


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    lock = utils.create_redlock(
        key="lock_osism_tasks_reconciler_setup_periodic_tasks",
    )
    if settings.INVENTORY_RECONCILER_SCHEDULE > 0 and lock.acquire(timeout=10):
        sender.add_periodic_task(
            settings.INVENTORY_RECONCILER_SCHEDULE, run_on_change.s(), expires=10
        )


@app.task(bind=True, name="osism.tasks.reconciler.run")
def run(self, publish=True, flush_cache=False):
    lock = utils.create_redlock(
        key="lock_osism_tasks_reconciler_run",
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")

        env = os.environ.copy()
        if flush_cache:
            env["FLUSH_CACHE"] = "true"

        p = subprocess.Popen(
            "/run.sh",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )

        if publish:
            for line in io.TextIOWrapper(p.stdout, encoding="utf-8"):
                utils.push_task_output(self.request.id, line)

        rc = p.wait(timeout=60)

        if publish:
            utils.finish_task_output(self.request.id, rc=rc)

        lock.release()


@app.task(bind=True, name="osism.tasks.reconciler.run_on_change")
def run_on_change(self):
    lock = utils.create_redlock(
        key="lock_osism_tasks_reconciler_run_on_change",
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")
        p = subprocess.Popen(
            "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        p.wait()

        lock.release()
