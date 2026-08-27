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

import importlib
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from osism import utils as osism_utils
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


# --- non-destructive peek at a STARTED task's output stream -----------------


def test_peek_reports_last_line_and_stall_without_consuming():
    """A populated stream yields its line count, last line and stall age.

    The peek must never consume: ``fetch_task_output`` is destructive
    (``xdel`` per entry), and draining here would steal output from the
    ``--live`` path and from the operator.
    """
    r = MagicMock()
    r.xrevrange.return_value = [
        (
            b"1787674033907-0",
            {b"type": b"stdout", b"content": b"TASK [k3s_download : Download]\n"},
        )
    ]
    r.xlen.return_value = 142

    peek = wait.peek_task_output(r, "taskid1", now=1787674100.0)

    assert peek.lines == 142
    assert peek.last_line == "TASK [k3s_download : Download]"
    assert round(peek.stalled_for) == 66
    r.xdel.assert_not_called()
    # Pin the redis-py call contract: a MagicMock accepts any argument
    # order, so without this the helper could be calling xrevrange wrongly
    # and the test would still pass.
    r.xrevrange.assert_called_once_with("taskid1", "+", "-", count=1)


def _entry(ms_ago, content=b"TASK [k3s_download : Download]\n", seq=0):
    """Build a stream entry whose ID is ``ms_ago`` milliseconds in the past.

    Deriving the timestamp from the real clock keeps the tests off
    ``time.time`` -- ``wait.time`` is the shared ``time`` module, so
    patching it also patches Celery's internals (and made this suite take
    40s).
    """
    # ``seq`` distinguishes entries produced inside the same millisecond,
    # which is otherwise easy to do by accident and makes two "different"
    # entries share an ID.
    entry_id = f"{int(time.time() * 1000) - ms_ago}-{seq}".encode()
    return (entry_id, {b"type": b"stdout", b"content": content})


def _run_started_peek(
    *,
    entries=(),
    entries_sequence=None,
    xlen=0,
    args=None,
    redis_error=None,
    states=("STARTED", "SUCCESS"),
):
    """Drive one STARTED -> SUCCESS cycle with a controlled output stream.

    ``osism.utils.redis`` is a lazy ``__getattr__`` that caches the
    connection into module globals, so it is patched directly rather than
    via ``_init_redis``.
    """
    cmd = wait.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args or ["taskid1"])

    conn = MagicMock()
    if redis_error is not None:
        conn.xrevrange.side_effect = redis_error
    elif entries_sequence is not None:
        conn.xrevrange.side_effect = [list(e) for e in entries_sequence]
        conn.xlen.return_value = xlen
    else:
        conn.xrevrange.return_value = list(entries)
        conn.xlen.return_value = xlen

    # ``utils.redis`` caches the resolved connection into module globals;
    # drop it so ``__getattr__`` re-runs and picks up the patched factory
    # (letting mock resolve the real attribute opens a live connection).
    osism_utils.__dict__.pop("redis", None)

    with patch("celery.Celery"), patch(
        "celery.result.AsyncResult",
        side_effect=[_make_result(state) for state in states],
    ), patch("osism.commands.wait.time.sleep"), patch(
        "osism.utils._init_redis", return_value=conn
    ):
        rc = cmd.take_action(parsed_args)

    osism_utils.__dict__.pop("redis", None)

    return SimpleNamespace(rc=rc, conn=conn)


def test_started_task_silent_past_threshold_reports_its_last_line(loguru_logs):
    """The whole point: name what the stuck task was last doing."""
    _run_started_peek(entries=[_entry(ms_ago=3_600_000)], xlen=142)

    assert any(
        "k3s_download" in record["message"] and "142" in record["message"]
        for record in loguru_logs
    )


def test_peek_failure_never_breaks_wait_and_is_not_retried(loguru_logs):
    """A broken or unreachable Redis must not take ``wait`` down with it.

    The non-``--live`` path never touched Redis before, so the peek must
    not turn it into a hard dependency. After one failure the peek is
    disabled rather than retried on every poll cycle.
    """
    mocks = _run_started_peek(
        redis_error=RuntimeError("redis down"),
        states=("STARTED", "STARTED", "SUCCESS"),
    )

    assert mocks.rc == 0
    assert mocks.conn.xrevrange.call_count == 1
    assert any("STARTED" in record["message"] for record in loguru_logs)


def _report_stall_directly(task_id, conn, first_seen=None):
    """Call ``_report_stall`` in isolation with a controlled clock.

    Task age cannot be driven through ``take_action`` without patching
    ``time.time`` globally, which also patches Celery's internals.
    """
    cmd = wait.Run(MagicMock(), MagicMock())
    cmd._reset_peek_state()
    if first_seen is not None:
        cmd._first_seen[task_id] = first_seen

    osism_utils.__dict__.pop("redis", None)
    with patch("osism.utils._init_redis", return_value=conn):
        cmd._report_stall(task_id)
    osism_utils.__dict__.pop("redis", None)


def test_task_that_emitted_nothing_at_all_is_reported_as_such(loguru_logs):
    """An empty stream is a diagnosis too.

    It separates a task hung mid-play (partial output recoverable) from
    one that hung before writing its first line.
    """
    conn = MagicMock()
    conn.xrevrange.return_value = []

    _report_stall_directly("taskid1", conn, first_seen=time.time() - 3600)

    assert any("no output at all" in record["message"] for record in loguru_logs)


def test_started_task_with_recent_output_stays_quiet(loguru_logs):
    """Healthy runs must not get noisier.

    A nutshell run polls thousands of times across ~22 concurrent tasks;
    reporting on tasks that are making progress would swamp the job log.
    """
    _run_started_peek(entries=[_entry(ms_ago=5_000)], xlen=12)

    assert not any("no output" in record["message"] for record in loguru_logs)


def test_script_format_is_unchanged_and_does_not_peek(capsys):
    """``--format script`` is machine-read; it must stay byte-identical."""
    mocks = _run_started_peek(
        entries=[_entry(ms_ago=3_600_000)],
        xlen=142,
        args=["taskid1", "--format", "script"],
    )

    assert mocks.conn.xrevrange.call_count == 0
    assert "taskid1 = STARTED" in capsys.readouterr().out


def test_stalled_task_is_not_reported_on_every_poll_cycle(loguru_logs):
    """An unchanged stall is not news on every cycle.

    The loop sleeps only once per pass over all tasks, so with the
    default one-second delay a wedged task would otherwise emit one
    warning per second for as long as it stays wedged.
    """
    _run_started_peek(
        entries=[_entry(ms_ago=3_600_000)],
        xlen=142,
        states=("STARTED",) * 10 + ("SUCCESS",),
    )

    reports = [r for r in loguru_logs if "emitted no output" in r["message"]]
    assert len(reports) == 1


def test_stall_is_reported_again_once_output_has_advanced(loguru_logs):
    """A new stall is news even inside the restate window.

    Suppression is keyed on the last line, not on time alone, so a task
    that emits something and then wedges again is reported immediately
    rather than being swallowed by the previous report's window.
    """
    first = [_entry(ms_ago=3_600_000, content=b"TASK [one]\n", seq=0)]
    second = [_entry(ms_ago=3_600_000, content=b"TASK [two]\n", seq=1)]

    _run_started_peek(
        entries_sequence=[first, first, second, second],
        xlen=142,
        states=("STARTED",) * 4 + ("SUCCESS",),
    )

    reports = [r for r in loguru_logs if "emitted no output" in r["message"]]
    assert len(reports) == 2
    assert "TASK [one]" in reports[0]["message"]
    assert "TASK [two]" in reports[1]["message"]


# --- configuration robustness ----------------------------------------------


def test_valid_stall_threshold_is_used(monkeypatch):
    monkeypatch.setenv("OSISM_WAIT_STALL_REPORT", "42")

    assert wait.stall_report_seconds() == 42


def test_unparseable_stall_threshold_falls_back_and_says_so(monkeypatch, loguru_logs):
    """A typo in the variable must not brick ``osism wait``."""
    monkeypatch.setenv("OSISM_WAIT_STALL_REPORT", "abc")

    assert wait.stall_report_seconds() == wait.DEFAULT_STALL_REPORT_SECONDS
    assert any("OSISM_WAIT_STALL_REPORT" in r["message"] for r in loguru_logs)


def test_non_positive_stall_threshold_falls_back(monkeypatch):
    """Zero would report every poll cycle -- the flood the throttle prevents."""
    monkeypatch.setenv("OSISM_WAIT_STALL_REPORT", "0")

    assert wait.stall_report_seconds() == wait.DEFAULT_STALL_REPORT_SECONDS


def test_module_still_imports_with_an_invalid_threshold(monkeypatch):
    """The value must not be parsed at import time."""
    monkeypatch.setenv("OSISM_WAIT_STALL_REPORT", "not-a-number")

    importlib.reload(wait)  # must not raise


def test_peek_failure_is_reported_at_a_visible_level(loguru_logs):
    """``osism`` pins loguru to INFO, so a debug line is never seen.

    Silently dropping the diagnosis reproduces, in miniature, the problem
    this feature exists to solve.
    """
    _run_started_peek(redis_error=RuntimeError("redis down"))

    notices = [r for r in loguru_logs if "stall reporting" in r["message"].lower()]
    assert len(notices) == 1
    assert notices[0]["level"] in ("WARNING", "ERROR")


# terminal failure states


def test_failed_task_sets_nonzero_exit_code(loguru_logs):
    """A FAILURE task must set a non-zero exit code.

    Before the fix the loop branched on PENDING/SUCCESS/STARTED only, so a
    FAILURE task fell through every branch, was dropped from the queue without
    being re-queued, and ``rc`` stayed 0 -- which is why an aborted collection
    chain still let ``deploy-in-a-nutshell.sh`` exit 0 under ``set -e``.
    """
    mocks = _run_states(
        ["taskid1"],
        results=[_make_result("FAILURE")],
    )

    assert mocks.rc == 1
    assert mocks.async_result.call_count == 1
    mocks.sleep.assert_not_called()
    assert "Task taskid1 is in state FAILURE" in [
        record["message"] for record in loguru_logs
    ]


def test_revoked_task_sets_nonzero_exit_code(loguru_logs):
    mocks = _run_states(
        ["taskid1"],
        results=[_make_result("REVOKED")],
    )

    assert mocks.rc == 1
    assert "Task taskid1 is in state REVOKED" in [
        record["message"] for record in loguru_logs
    ]


def test_failure_is_not_reset_by_a_later_successful_task():
    """``rc`` has to survive the rest of the queue.

    IDs are sorted and popped from the end, so ``taskid2`` is inspected first;
    the SUCCESS branch that follows must not clear the recorded failure.
    """
    mocks = _run_states(
        ["taskid1", "taskid2"],
        results=[_make_result("FAILURE"), _make_result("SUCCESS")],
    )

    assert mocks.rc == 1


def test_failed_task_with_output_does_not_fetch_the_result():
    """``--output`` must not call ``result.get()`` on a failed task: Celery
    re-raises the task's exception there, which would replace the exit code
    with a traceback."""
    result = _make_result("FAILURE")
    mocks = _run_states(["taskid1", "--output"], results=[result])

    assert mocks.rc == 1
    result.get.assert_not_called()


def test_script_format_prints_failure_state(capsys, loguru_logs):
    mocks = _run_states(
        ["taskid1", "--format", "script"],
        results=[_make_result("FAILURE")],
    )

    assert mocks.rc == 1
    assert capsys.readouterr().out == "taskid1 = FAILURE\n"
    assert not any("taskid1" in record["message"] for record in loguru_logs)
