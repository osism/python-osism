# SPDX-License-Identifier: Apache-2.0

from subprocess import TimeoutExpired
from unittest.mock import MagicMock

import pytest
from celery.exceptions import MaxRetriesExceededError, Retry

from osism.tasks import reconciler


def _task(*, retries=0, retry_exception=None):
    task = MagicMock()
    task.request.id = "task-1"
    task.request.retries = retries
    task.retry.side_effect = retry_exception or Retry()
    return task


def test_lock_timeout_retries_same_task_with_status(mocker):
    task = _task()
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    with pytest.raises(Retry):
        reconciler._retry_after_lock_timeout(task, publish=True)

    push.assert_called_once_with(
        "task-1",
        f"Reconciler busy; retrying lock acquisition in {reconciler.LOCK_RETRY_DELAY}s\n",
    )
    finish.assert_not_called()
    task.retry.assert_called_once_with(countdown=reconciler.LOCK_RETRY_DELAY)


def test_retry_status_publication_failure_does_not_prevent_retry(mocker):
    task = _task()
    mocker.patch(
        "osism.tasks.reconciler.utils.push_task_output",
        side_effect=RuntimeError("redis unavailable"),
    )
    with pytest.raises(Retry):
        reconciler._retry_after_lock_timeout(task, publish=True)

    task.retry.assert_called_once_with(countdown=reconciler.LOCK_RETRY_DELAY)


def test_lock_retry_exhaustion_publishes_failure_and_raises(mocker):
    task = _task(
        retries=reconciler.LOCK_RETRY_MAX_RETRIES,
        retry_exception=MaxRetriesExceededError("exhausted"),
    )
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    with pytest.raises(MaxRetriesExceededError):
        reconciler._retry_after_lock_timeout(task, publish=True)

    push.assert_called_once()
    assert "could not be acquired" in push.call_args.args[1]
    finish.assert_called_once_with("task-1", rc=reconciler.LOCK_TIMEOUT_RC)


def test_publish_false_retries_without_stream_output(mocker):
    task = _task()
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    with pytest.raises(Retry):
        reconciler._retry_after_lock_timeout(task, publish=False)

    push.assert_not_called()
    finish.assert_not_called()


def test_publish_false_exhaustion_raises_without_stream_output(mocker):
    task = _task(retry_exception=MaxRetriesExceededError("exhausted"))
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    with pytest.raises(MaxRetriesExceededError):
        reconciler._retry_after_lock_timeout(task, publish=False)

    push.assert_not_called()
    finish.assert_not_called()


def test_execute_reconciler_publishes_success_and_releases_lock(mocker):
    task = _task()
    lock = MagicMock()
    lock.acquire.return_value = True
    process = MagicMock()
    process.stdout = [b"line\n"]
    process.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=process)
    mocker.patch("osism.tasks.reconciler.io.TextIOWrapper", return_value=["line\n"])
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler._execute_reconciler(task, publish=True)

    assert result == 0
    push.assert_called_once_with("task-1", "line\n")
    finish.assert_called_once_with("task-1", rc=0)
    lock.release.assert_called_once_with()


def test_execute_reconciler_popen_failure_publishes_and_releases(mocker):
    task = _task()
    lock = MagicMock()
    lock.acquire.return_value = True
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch(
        "osism.tasks.reconciler.subprocess.Popen",
        side_effect=OSError("cannot start"),
    )
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    with pytest.raises(OSError, match="cannot start"):
        reconciler._execute_reconciler(task, publish=True)

    assert "cannot start" in push.call_args.args[1]
    finish.assert_called_once_with("task-1", rc=1)
    lock.release.assert_called_once_with()


def test_execute_reconciler_timeout_kills_process(mocker):
    task = _task()
    lock = MagicMock()
    lock.acquire.return_value = True
    process = MagicMock()
    process.stdout = []
    process.wait.side_effect = [TimeoutExpired("/run.sh", 60), 0]
    process.poll.return_value = None
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=process)
    mocker.patch("osism.tasks.reconciler.io.TextIOWrapper", return_value=[])
    mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    with pytest.raises(TimeoutExpired):
        reconciler._execute_reconciler(task, publish=True)

    process.kill.assert_called_once_with()
    finish.assert_called_once_with("task-1", rc=1)
    lock.release.assert_called_once_with()


def test_execute_reconciler_task_lock_system_exit_publishes_failure(mocker):
    task = _task()
    mocker.patch(
        "osism.tasks.reconciler.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )
    create_lock = mocker.patch("osism.tasks.reconciler.utils.create_redlock")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    with pytest.raises(SystemExit):
        reconciler._execute_reconciler(task, publish=True)

    create_lock.assert_not_called()
    finish.assert_called_once_with("task-1", rc=1)


def test_execute_reconciler_does_not_convert_retry_to_failure(mocker):
    task = _task()
    lock = MagicMock()
    lock.acquire.return_value = False
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch(
        "osism.tasks.reconciler._retry_after_lock_timeout",
        side_effect=Retry(),
    )
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    with pytest.raises(Retry):
        reconciler._execute_reconciler(task, publish=True)

    finish.assert_not_called()
    lock.release.assert_not_called()
