# SPDX-License-Identifier: Apache-2.0

"""Tests for the reconciler Celery tasks.

The explicit ``run`` task must always hand a waiting client a definite
outcome: when it cannot run (administrative lock or execution-lock
contention) it publishes a terminal marker and reports a non-zero result
instead of blocking or silently returning ``None``. The periodic
``run_on_change`` task keeps its coalescing silent-skip behaviour.
"""

import io
from unittest.mock import ANY, MagicMock

from osism.tasks import reconciler


def test_run_fails_fast_on_contention_with_terminal_marker(mocker):
    lock = MagicMock()
    lock.acquire.return_value = False
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=True)

    assert result == reconciler.LOCK_TIMEOUT_RC
    push.assert_called_once()
    assert push.call_args.args[1].strip()
    finish.assert_called_once_with(ANY, rc=reconciler.LOCK_TIMEOUT_RC)
    popen.assert_not_called()
    lock.release.assert_not_called()


def test_run_contention_without_publish_logs_and_returns_nonzero(mocker):
    lock = MagicMock()
    lock.acquire.return_value = False
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=False)

    assert result == reconciler.LOCK_TIMEOUT_RC
    push.assert_not_called()
    finish.assert_not_called()
    popen.assert_not_called()


def test_run_converts_admin_lock_exit_to_terminal_marker(mocker):
    mocker.patch(
        "osism.tasks.reconciler.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )
    create_lock = mocker.patch("osism.tasks.reconciler.utils.create_redlock")
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=True)

    assert result == reconciler.LOCK_TIMEOUT_RC
    push.assert_called_once()
    finish.assert_called_once_with(ANY, rc=reconciler.LOCK_TIMEOUT_RC)
    # the admin-lock check short-circuits before the execution lock is taken
    create_lock.assert_not_called()


def test_run_admin_lock_without_publish_returns_nonzero_quietly(mocker):
    mocker.patch(
        "osism.tasks.reconciler.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=False)

    assert result == reconciler.LOCK_TIMEOUT_RC
    push.assert_not_called()
    finish.assert_not_called()


def test_run_publishes_success_and_releases_lock(mocker):
    lock = MagicMock()
    lock.acquire.return_value = True
    process = MagicMock()
    # Real bytes so the production ``TextIOWrapper`` drain loop consumes the pipe.
    process.stdout = io.BytesIO(b"line\n")
    process.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=process)
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=True)

    assert result == 0
    push.assert_called_once_with(ANY, "line\n")
    finish.assert_called_once_with(ANY, rc=0)
    lock.release.assert_called_once_with()


def test_run_without_publish_does_not_stream_but_releases(mocker):
    lock = MagicMock()
    lock.acquire.return_value = True
    process = MagicMock()
    # Real bytes so the production ``TextIOWrapper`` drain loop consumes the pipe.
    process.stdout = io.BytesIO(b"noise\n")
    process.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=process)
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")

    result = reconciler.run.run(publish=False)

    assert result == 0
    push.assert_not_called()
    finish.assert_not_called()
    lock.release.assert_called_once_with()


def test_run_on_change_runs_and_releases_when_acquired(mocker):
    lock = MagicMock()
    lock.acquire.return_value = True
    process = MagicMock()
    # Real bytes so the production ``TextIOWrapper`` drain loop consumes the pipe.
    process.stdout = io.BytesIO(b"noise\n")
    process.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    popen = mocker.patch(
        "osism.tasks.reconciler.subprocess.Popen", return_value=process
    )

    reconciler.run_on_change.run()

    popen.assert_called_once()
    process.wait.assert_called_once()
    lock.release.assert_called_once_with()


def test_run_on_change_skips_silently_when_contended(mocker):
    lock = MagicMock()
    lock.acquire.return_value = False
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")

    result = reconciler.run_on_change.run()

    assert result is None
    popen.assert_not_called()
