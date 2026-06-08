# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism wait`` command.

These focus on the exit-code contract for the ``--live`` path, which streams a
STARTED task's output and should propagate that task's result as the process
exit code:

- a timeout while streaming is an operational failure -> non-zero exit;
- a task that finishes with a non-zero rc -> that rc;
- a task that finishes successfully -> exit 0.

The pre-fix code only returned an exit code under a ``len(task_ids) == 1``
guard, which never fired for a single task (so a timeout was ignored) and
raised ``UnboundLocalError`` on a timeout with two tasks.
"""

from unittest.mock import MagicMock, patch

from osism.commands import wait


def _run(args, *, state, fetch):
    cmd = wait.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)

    result_obj = MagicMock()
    result_obj.state = state

    with patch("celery.Celery"), patch(
        "celery.result.AsyncResult", return_value=result_obj
    ), patch("osism.utils._init_redis", return_value=MagicMock()), patch(
        "osism.commands.wait.utils.fetch_task_output", **fetch
    ):
        return cmd.take_action(parsed_args)


def test_live_returns_nonzero_on_timeout_single_task():
    result = _run(
        ["taskid1", "--live"],
        state="STARTED",
        fetch={"side_effect": TimeoutError},
    )
    assert result == 1


def test_live_returns_nonzero_on_timeout_multiple_tasks():
    result = _run(
        ["taskid1", "taskid2", "--live"],
        state="STARTED",
        fetch={"side_effect": TimeoutError},
    )
    assert result == 1


def test_live_returns_task_rc_when_task_fails():
    result = _run(
        ["taskid1", "--live"],
        state="STARTED",
        fetch={"return_value": 2},
    )
    assert result == 2


def test_live_returns_zero_when_task_succeeds():
    result = _run(
        ["taskid1", "--live"],
        state="STARTED",
        fetch={"return_value": 0},
    )
    assert result == 0
