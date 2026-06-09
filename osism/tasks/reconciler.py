# SPDX-License-Identifier: Apache-2.0

import io
import os
import subprocess

from celery import Celery
from celery.exceptions import MaxRetriesExceededError, Retry
from loguru import logger
from osism import settings, utils
from osism.tasks import Config

app = Celery("reconciler")
app.config_from_object(Config)

LOCK_RETRY_MAX_RETRIES = 5
LOCK_RETRY_DELAY = 5
LOCK_TIMEOUT_RC = 1
RECONCILER_LOCK_KEY = "lock_osism_tasks_reconciler_execution"


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    lock = utils.create_redlock(
        key="lock_osism_tasks_reconciler_setup_periodic_tasks",
    )
    if settings.INVENTORY_RECONCILER_SCHEDULE > 0 and lock.acquire(timeout=10):
        sender.add_periodic_task(
            settings.INVENTORY_RECONCILER_SCHEDULE, run_on_change.s(), expires=10
        )


def _push_task_output_best_effort(task_id, line):
    try:
        utils.push_task_output(task_id, line)
    except Exception:
        logger.exception(f"Failed to publish output for reconciler task {task_id}")


def _finish_task_output_best_effort(task_id, rc):
    try:
        utils.finish_task_output(task_id, rc=rc)
    except Exception:
        logger.exception(f"Failed to finish output for reconciler task {task_id}")


def _publish_failure_best_effort(task_id, exc):
    _push_task_output_best_effort(task_id, f"Reconciler failed: {exc}\n")
    _finish_task_output_best_effort(task_id, 1)


def _release_lock_best_effort(lock):
    from pottery import ReleaseUnlockedLock

    try:
        lock.release()
    except ReleaseUnlockedLock:
        logger.warning(
            "Lock auto-released before explicit release (auto_release_time exceeded)"
        )
    except Exception:
        logger.exception("Failed to release reconciler lock")


def _terminate_process_best_effort(process):
    try:
        if process.poll() is None:
            process.kill()
            process.wait()
    except Exception:
        logger.exception("Failed to terminate reconciler subprocess")


def _retry_after_lock_timeout(task, publish):
    if publish and task.request.retries < LOCK_RETRY_MAX_RETRIES:
        _push_task_output_best_effort(
            task.request.id,
            f"Reconciler busy; retrying lock acquisition in {LOCK_RETRY_DELAY}s\n",
        )

    try:
        raise task.retry(countdown=LOCK_RETRY_DELAY)
    except MaxRetriesExceededError:
        message = (
            "Reconciler lock could not be acquired after "
            f"{LOCK_RETRY_MAX_RETRIES + 1} attempts\n"
        )
        logger.error(message.rstrip())
        if publish:
            _push_task_output_best_effort(task.request.id, message)
            _finish_task_output_best_effort(task.request.id, LOCK_TIMEOUT_RC)
        raise


def _execute_reconciler(task, publish):
    lock = None
    lock_acquired = False
    process = None

    try:
        utils.check_task_lock_and_exit()

        lock = utils.create_redlock(
            key=RECONCILER_LOCK_KEY,
            auto_release_time=60,
        )

        if not lock.acquire(timeout=20):
            return _retry_after_lock_timeout(task, publish)

        lock_acquired = True
        logger.info("RUN /run.sh")

        process = subprocess.Popen(
            "/run.sh",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        )

        if publish:
            for line in io.TextIOWrapper(process.stdout, encoding="utf-8"):
                utils.push_task_output(task.request.id, line)

        rc = process.wait(timeout=60)

        if publish:
            utils.finish_task_output(task.request.id, rc=rc)

        return rc
    except (Retry, MaxRetriesExceededError):
        raise
    except BaseException as exc:
        if process is not None:
            _terminate_process_best_effort(process)
        logger.exception(f"Reconciler task {task.request.id} failed")
        if publish:
            _publish_failure_best_effort(task.request.id, exc)
        raise
    finally:
        if lock_acquired:
            _release_lock_best_effort(lock)


@app.task(
    bind=True,
    name="osism.tasks.reconciler.run",
    max_retries=LOCK_RETRY_MAX_RETRIES,
)
def run(self, publish=True):
    return _execute_reconciler(self, publish)


@app.task(bind=True, name="osism.tasks.reconciler.run_on_change")
def run_on_change(self):
    lock = utils.create_redlock(
        key=RECONCILER_LOCK_KEY,
        auto_release_time=60,
    )

    if lock.acquire(timeout=20):
        logger.info("RUN /run.sh")
        p = subprocess.Popen(
            "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        p.wait()

        from pottery import ReleaseUnlockedLock

        try:
            lock.release()
        except ReleaseUnlockedLock:
            logger.warning(
                "Lock auto-released before explicit release (auto_release_time exceeded)"
            )
