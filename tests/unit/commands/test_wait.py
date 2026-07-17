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

The remaining tests characterize the non-``--live`` loop: task-id discovery
via the Celery inspect API, the PENDING/STARTED re-queue behaviour, the
``--output`` and ``--refresh`` options, and the script output format.
"""

from types import SimpleNamespace
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


def _make_result(state, output=None):
    """Build an ``AsyncResult`` stand-in reporting ``state``."""
    result = MagicMock()
    result.state = state
    if output is not None:
        result.get.return_value = output
    return result


def _run_states(args, *, results, query=None, scheduled=None, active=None):
    """Drive ``take_action`` through the non-``--live`` loop.

    ``results`` is consumed one entry per ``AsyncResult`` construction, so
    state transitions between loop iterations are modelled by consecutive
    entries. ``query``, ``scheduled`` and ``active`` configure the mocked
    Celery inspect API.
    """
    cmd = wait.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)

    with patch("celery.Celery") as mock_celery, patch(
        "celery.result.AsyncResult", side_effect=results
    ) as mock_async, patch("osism.commands.wait.time.sleep") as mock_sleep, patch(
        "osism.utils._init_redis", return_value=MagicMock()
    ):
        inspect = mock_celery.return_value.control.inspect.return_value
        inspect.scheduled.return_value = scheduled if scheduled is not None else {}
        inspect.active.return_value = active if active is not None else {}
        if query is not None:
            inspect.query_task.return_value = query
        rc = cmd.take_action(parsed_args)

    return SimpleNamespace(
        rc=rc, async_result=mock_async, sleep=mock_sleep, inspect=inspect
    )


def test_get_all_task_ids_merges_scheduled_and_active_sorted():
    cmd = wait.Run(MagicMock(), MagicMock())
    inspect = MagicMock()
    inspect.scheduled.return_value = {
        "worker1": [{"id": "task-c"}],
        "worker2": [{"id": "task-a"}],
    }
    inspect.active.return_value = {"worker1": [{"id": "task-b"}]}

    assert cmd.get_all_task_ids(inspect) == ["task-a", "task-b", "task-c"]


def test_no_task_ids_on_cli_waits_for_all_running_tasks(loguru_logs):
    mocks = _run_states(
        [],
        results=[_make_result("SUCCESS"), _make_result("SUCCESS")],
        scheduled={"worker1": [{"id": "taskid2"}]},
        active={"worker1": [{"id": "taskid1"}]},
    )

    assert mocks.rc == 0
    waited = [call.args[0] for call in mocks.async_result.call_args_list]
    assert sorted(waited) == ["taskid1", "taskid2"]
    assert any("No task IDs specified" in record["message"] for record in loguru_logs)


def test_pending_task_unknown_to_any_worker_is_not_requeued(loguru_logs):
    mocks = _run_states(
        ["taskid1"],
        results=[_make_result("PENDING")],
        query={"worker1": []},
    )

    assert mocks.rc == 0
    assert mocks.async_result.call_count == 1
    mocks.inspect.query_task.assert_called_once_with("taskid1")
    mocks.sleep.assert_not_called()
    assert any(
        record["message"] == "Task taskid1 is unavailable" for record in loguru_logs
    )


def test_pending_task_known_to_worker_is_requeued_until_success(loguru_logs):
    mocks = _run_states(
        ["taskid1"],
        results=[_make_result("PENDING"), _make_result("SUCCESS")],
        query={"worker1": [["taskid1", {}]]},
    )

    assert mocks.rc == 0
    assert mocks.async_result.call_count == 2
    mocks.sleep.assert_called_once_with(1)
    messages = [record["message"] for record in loguru_logs]
    assert "Task taskid1 is in state PENDING" in messages
    assert "Task taskid1 is in state SUCCESS" in messages


def test_success_with_output_prints_task_result(capsys):
    mocks = _run_states(
        ["taskid1", "--output"],
        results=[_make_result("SUCCESS", output="task output")],
    )

    assert mocks.rc == 0
    assert "task output" in capsys.readouterr().out


def test_started_task_without_live_is_requeued_until_success(loguru_logs):
    mocks = _run_states(
        ["taskid1"],
        results=[_make_result("STARTED"), _make_result("SUCCESS")],
    )

    assert mocks.rc == 0
    assert mocks.async_result.call_count == 2
    mocks.sleep.assert_called_once_with(1)
    messages = [record["message"] for record in loguru_logs]
    assert "Task taskid1 is in state STARTED" in messages
    assert "Task taskid1 is in state SUCCESS" in messages


def test_refresh_consults_task_list_again_after_queue_drains():
    # NOTE: ``--refresh`` only takes effect when no task IDs are given on the
    # command line: with explicit IDs ``do_refresh`` stays False and the loop
    # exits as soon as the queue drains, so the refresh branch never runs.
    cmd = wait.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--refresh", "1"])

    with patch("celery.Celery"), patch(
        "celery.result.AsyncResult", side_effect=[_make_result("SUCCESS")]
    ), patch("osism.commands.wait.time.sleep") as mock_sleep, patch(
        "osism.utils._init_redis", return_value=MagicMock()
    ), patch.object(
        cmd, "get_all_task_ids", side_effect=[["taskid1"], []]
    ) as mock_ids:
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    assert mock_ids.call_count == 2
    mock_sleep.assert_called_once_with(1)


def test_script_format_prints_state_lines_instead_of_log_output(capsys, loguru_logs):
    mocks = _run_states(
        ["taskid1", "--format", "script"],
        results=[_make_result("SUCCESS")],
    )

    assert mocks.rc == 0
    assert capsys.readouterr().out == "taskid1 = SUCCESS\n"
    assert not any("taskid1" in record["message"] for record in loguru_logs)


def test_script_format_prints_unavailable_for_unknown_pending_task(capsys):
    mocks = _run_states(
        ["taskid1", "--format", "script"],
        results=[_make_result("PENDING")],
        query={"worker1": []},
    )

    assert mocks.rc == 0
    assert capsys.readouterr().out == "taskid1 = UNAVAILABLE\n"
