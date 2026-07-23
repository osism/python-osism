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

# How long an explicit run waits for the execution lock before giving up.
LOCK_ACQUIRE_TIMEOUT = 20
# Result reported when a run cannot start (admin lock or lock contention).
LOCK_TIMEOUT_RC = 1


def _publish_lock_failure(task_id, message):
    # Publish a terminal marker so a client waiting on the output stream
    # (osism sync inventory) fails fast with this message instead of blocking
    # until its own output timeout expires.
    utils.push_task_output(task_id, f"{message}\n")
    utils.finish_task_output(task_id, rc=LOCK_TIMEOUT_RC)


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
def run(self, publish=True):
    try:
        utils.check_task_lock_and_exit()
    except SystemExit:
        # check_task_lock_and_exit() calls exit(1) when tasks are
        # administratively locked. Convert that into a terminal result rather
        # than letting SystemExit propagate out of the Celery task: a bare
        # SystemExit churns the prefork worker and leaves a waiting client
        # without an outcome.
        message = "Tasks are locked; reconciler did not run"
        logger.error(message)
        if publish:
            _publish_lock_failure(self.request.id, message)
        return LOCK_TIMEOUT_RC

    lock = utils.create_redlock(
        key="lock_osism_tasks_reconciler_run",
        auto_release_time=60,
    )

    if not lock.acquire(timeout=LOCK_ACQUIRE_TIMEOUT):
        # Another reconciler run holds the execution lock. Fail fast with a
        # terminal marker instead of blocking or silently returning: a waiting
        # client must see a definite outcome. We do not retry here -- a retry
        # could acquire a lease the in-flight run let expire and start a second
        # concurrent /run.sh.
        message = "Reconciler busy; another run holds the execution lock"
        logger.error(message)
        if publish:
            _publish_lock_failure(self.request.id, message)
        return LOCK_TIMEOUT_RC

    logger.info("RUN /run.sh")

    env = os.environ.copy()

    p = subprocess.Popen(
        "/run.sh",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )

    # Always drain stdout so a chatty /run.sh cannot fill the pipe buffer
    # and deadlock on wait(); only forward the lines when publishing.
    with io.TextIOWrapper(p.stdout, encoding="utf-8") as stdout:
        for line in stdout:
            if publish:
                utils.push_task_output(self.request.id, line)

    rc = p.wait(timeout=60)

    if publish:
        utils.finish_task_output(self.request.id, rc=rc)

    from pottery import ReleaseUnlockedLock

    try:
        lock.release()
    except ReleaseUnlockedLock:
        logger.warning(
            "Lock auto-released before explicit release (auto_release_time exceeded)"
        )

    return rc


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

        # Drain stdout into the log so a chatty /run.sh cannot fill the pipe
        # buffer and deadlock on wait(); run_on_change publishes nowhere.
        with io.TextIOWrapper(p.stdout, encoding="utf-8") as stdout:
            for line in stdout:
                logger.info(line.rstrip())

        p.wait(timeout=60)

        from pottery import ReleaseUnlockedLock

        try:
            lock.release()
        except ReleaseUnlockedLock:
            logger.warning(
                "Lock auto-released before explicit release (auto_release_time exceeded)"
            )
