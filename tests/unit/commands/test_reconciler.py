# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism reconciler`` commands.

``Run`` is the deprecated foreground worker runner; ``Sync`` schedules an
inventory sync via Celery and (by default) waits for its output. The exit-code
contract matters most: a command must return a non-zero exit status when it
gives up waiting for a task (a timeout is an operational failure), rather than
falling through to an implicit success.
"""

from unittest.mock import MagicMock, patch

from osism.commands import reconciler

from ._helpers import assert_not_called_before_lock_check, parse_args


def _run_worker(monkeypatch, *, env=None, cpu_count=16):
    monkeypatch.delenv("OSISM_CELERY_CONCURRENCY", raising=False)
    if env is not None:
        monkeypatch.setenv("OSISM_CELERY_CONCURRENCY", env)

    cmd, parsed_args = parse_args(reconciler.Run, [])

    with patch(
        "osism.commands.reconciler.utils.check_task_lock_and_exit"
    ) as mock_check, patch(
        "osism.commands.reconciler.subprocess.Popen"
    ) as mock_popen, patch(
        "osism.commands.reconciler.multiprocessing.cpu_count",
        return_value=cpu_count,
    ):
        mock_check.side_effect = assert_not_called_before_lock_check(mock_popen)
        cmd.take_action(parsed_args)

    return mock_check, mock_popen


def _run_sync(args, *, fetch_return=0):
    cmd, parsed_args = parse_args(reconciler.Sync, args)

    with patch(
        "osism.commands.reconciler.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.tasks.reconciler.run.delay") as mock_delay, patch(
        "osism.commands.reconciler.utils.fetch_task_output",
        return_value=fetch_return,
    ) as mock_fetch:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        result = cmd.take_action(parsed_args)

    return result, mock_check, mock_delay, mock_fetch


def test_run_logs_deprecation_warning(loguru_logs, monkeypatch):
    _run_worker(monkeypatch)
    assert any(
        "deprecated" in record["message"]
        and "osism service reconciler" in record["message"]
        for record in loguru_logs
    )


def test_run_checks_task_lock_before_starting_worker(monkeypatch):
    mock_check, mock_popen = _run_worker(monkeypatch)
    mock_check.assert_called_once()
    mock_popen.assert_called_once()


def test_run_concurrency_defaults_to_cpu_count_capped_at_four(monkeypatch):
    _, mock_popen = _run_worker(monkeypatch, cpu_count=16)
    mock_popen.assert_called_once_with(
        "celery -A osism.tasks.reconciler worker -n reconciler --loglevel=INFO -Q reconciler -c 4",
        shell=True,
    )
    mock_popen.return_value.wait.assert_called_once_with()


def test_run_concurrency_from_env(monkeypatch):
    _, mock_popen = _run_worker(monkeypatch, env="2")
    assert "-c 2" in mock_popen.call_args[0][0]


def test_sync_waits_for_task_output_and_returns_its_result():
    result, mock_check, mock_delay, mock_fetch = _run_sync([], fetch_return=0)

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with(publish=True)
    mock_fetch.assert_called_once_with(mock_delay.return_value.id, timeout=300)
    assert result == 0


def test_sync_no_wait_schedules_without_fetching_output(loguru_logs):
    result, _, mock_delay, mock_fetch = _run_sync(["--no-wait"])

    mock_delay.assert_called_once_with(publish=False)
    mock_fetch.assert_not_called()
    assert result is None
    assert any("No more output" in record["message"] for record in loguru_logs)


def test_sync_task_timeout_argument_is_forwarded():
    _, _, _, mock_fetch = _run_sync(["--task-timeout", "60"])
    mock_fetch.assert_called_once()
    assert mock_fetch.call_args[1]["timeout"] == 60


def test_sync_task_timeout_default_from_env(monkeypatch):
    # The environment variable is read at parser-build time; argparse applies
    # ``type=int`` to string defaults, so the value arrives as an int.
    monkeypatch.setenv("OSISM_TASK_TIMEOUT", "600")
    _, parsed_args = parse_args(reconciler.Sync, [])
    assert parsed_args.task_timeout == 600


def test_sync_returns_nonzero_on_task_timeout():
    cmd, parsed_args = parse_args(reconciler.Sync, [])

    with patch("osism.commands.reconciler.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.reconciler.run.delay", return_value=MagicMock()
    ), patch(
        "osism.commands.reconciler.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
