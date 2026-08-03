# SPDX-License-Identifier: Apache-2.0

"""Celery task-lifecycle integration tests: failure, STARTED and revocation.

These extend the noop round-trip in ``test_celery.py`` with the result-backend
behaviour the operator-facing flows rely on: an exception raised in the worker
reaches the caller through ``AsyncResult.get()``, ``task_track_started``
reports ``STARTED`` while a task runs, and ``osism.utils.revoke_task``
terminates a running task. The tasks they dispatch are registered on the
worker via ``tests/integration/worker_tasks.py``.
"""

import time
import uuid

import pytest

from osism import utils
from tests.integration.worker_tasks import itest_block, itest_fail

pytestmark = pytest.mark.integration

# Timeouts in seconds, sized for slow CI machines: how long a dispatched task
# may take to deliver its result, and how long a state transition may take to
# become visible in the result backend.
RESULT_TIMEOUT = 60
STATE_TIMEOUT = 30
# Task durations in seconds: long enough that polling cannot miss STARTED, and
# far enough past the revoke that the revoke test never races its task's
# natural end. ``itest_block`` carries its own hard time limit, so a test that
# fails before revoking does not block the worker for the full duration.
BLOCK_SHORT = 3
BLOCK_LONG = 300


def _wait_for_state(result, states, timeout=STATE_TIMEOUT):
    """Poll ``result.state`` until it is one of ``states`` and return it.

    Fails the test instead of hanging when the deadline passes.
    """
    deadline = time.monotonic() + timeout
    state = result.state
    while time.monotonic() < deadline:
        state = result.state
        if state in states:
            return state
        time.sleep(0.1)
    pytest.fail(
        f"task {result.id} did not reach {states} within {timeout}s "
        f"(last state: {state})"
    )


def test_failing_task_propagates_exception(celery_worker):
    """An exception raised in the worker reaches the caller via ``get()``.

    ``RuntimeError`` is a builtin, so the result backend re-raises the
    original exception class with the original message.
    """
    message = f"itest-fail-{uuid.uuid4()}"

    result = itest_fail.delay(message)

    with pytest.raises(RuntimeError, match=message):
        result.get(timeout=RESULT_TIMEOUT)
    assert result.failed() is True
    assert result.state == "FAILURE"


def test_started_state_is_reported(celery_worker):
    """``task_track_started`` reports ``STARTED`` while a task runs.

    The task body runs for ``BLOCK_SHORT`` seconds against a 0.1 s poll
    interval, so a run that observes ``SUCCESS`` or ``FAILURE`` first either
    never reported ``STARTED`` or lost the whole task duration to a stalled
    poll loop.
    """
    result = itest_block.delay(BLOCK_SHORT)

    state = _wait_for_state(result, {"STARTED", "SUCCESS", "FAILURE"})

    assert state == "STARTED", (
        f"got {state} first -- either task_track_started stopped working, "
        f"or this poll loop stalled for the full {BLOCK_SHORT}s window"
    )
    assert result.get(timeout=RESULT_TIMEOUT) == BLOCK_SHORT
    assert result.state == "SUCCESS"


def test_revoke_running_task(celery_worker):
    """``osism.utils.revoke_task`` terminates a running task.

    The revoke is issued only after ``STARTED`` was observed: revoking a
    still-queued task would merely discard it from the queue and never
    exercise ``terminate=True`` against a running pool child.
    """
    from celery.exceptions import TaskRevokedError

    from osism.tasks import ansible

    result = itest_block.delay(BLOCK_LONG)
    state = _wait_for_state(result, {"STARTED", "SUCCESS", "FAILURE"})
    assert state == "STARTED"

    assert utils.revoke_task(result.id) is True

    assert _wait_for_state(result, {"REVOKED", "SUCCESS", "FAILURE"}) == "REVOKED"
    with pytest.raises(TaskRevokedError):
        result.get(timeout=RESULT_TIMEOUT)

    # The prefork pool replaces the terminated child; prove the session-scoped
    # worker stays usable for tests that run after this one.
    assert ansible.noop.delay().get(timeout=RESULT_TIMEOUT) is True
