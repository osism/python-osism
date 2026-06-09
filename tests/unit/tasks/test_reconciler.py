# SPDX-License-Identifier: Apache-2.0

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
