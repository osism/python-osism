# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism service`` command.

``Run`` launches one of the long-running OSISM services (API, listener,
Celery beat/flower, reconciler worker, inventory watchdog) as subprocesses,
except for the watchdog, which polls the inventory directory in-process.
"""

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import service

from ._helpers import assert_not_called_before_lock_check, make_command, parse_args


class _Stop(Exception):
    """Sentinel to escape the watchdog ``while True`` loop."""


def _run_service(args):
    cmd, parsed_args = parse_args(service.Run, args)

    with patch(
        "osism.commands.service.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.commands.service.subprocess.Popen") as mock_popen:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_popen)
        result = cmd.take_action(parsed_args)

    return result, mock_check, mock_popen


def test_api_starts_uvicorn():
    result, mock_check, mock_popen = _run_service(["api"])

    mock_check.assert_called_once()
    mock_popen.assert_called_once_with(
        "uvicorn osism.api:app --host 0.0.0.0 --port 8000", shell=True
    )
    mock_popen.return_value.wait.assert_called_once_with()
    assert result is None


def test_listener_starts_listener_service():
    result, mock_check, mock_popen = _run_service(["listener"])

    mock_check.assert_called_once()
    mock_popen.assert_called_once_with(
        "python3 -c 'from osism.services import listener; listener.main()'",
        shell=True,
    )
    mock_popen.return_value.wait.assert_called_once_with()
    assert result is None


def test_beat_starts_one_scheduler_per_task_module():
    from osism.tasks import Config

    result, mock_check, mock_popen = _run_service(["beat"])

    mock_check.assert_called_once()
    modules = [
        "ansible",
        "ceph",
        "conductor",
        "kolla",
        "netbox",
        "openstack",
        "reconciler",
    ]
    assert mock_popen.call_count == len(modules)
    for popen_call, module in zip(mock_popen.call_args_list, modules):
        assert popen_call[0][0] == [
            "celery",
            "-A",
            f"osism.tasks.{module}",
            "--broker",
            Config.broker_url,
            "beat",
            "-s",
            f"/tmp/celerybeat-schedule-osism.tasks.{module}.db",
        ]
    assert mock_popen.return_value.wait.call_count == len(modules)
    assert result is None


def test_flower_starts_celery_flower():
    from osism.tasks import Config

    result, mock_check, mock_popen = _run_service(["flower"])

    mock_check.assert_called_once()
    mock_popen.assert_called_once_with(
        ["celery", "--broker", Config.broker_url, "flower"]
    )
    mock_popen.return_value.wait.assert_called_once_with()
    assert result is None


def test_reconciler_concurrency_defaults_to_cpu_count_capped_at_four(monkeypatch):
    monkeypatch.delenv("OSISM_CELERY_CONCURRENCY", raising=False)
    with patch("osism.commands.service.multiprocessing.cpu_count", return_value=16):
        result, mock_check, mock_popen = _run_service(["reconciler"])

    mock_check.assert_called_once()
    mock_popen.assert_called_once_with(
        "celery -A osism.tasks.reconciler worker -n reconciler --loglevel=INFO -Q reconciler -c 4",
        shell=True,
    )
    mock_popen.return_value.wait.assert_called_once_with()
    assert result is None


def test_reconciler_concurrency_from_env(monkeypatch):
    monkeypatch.setenv("OSISM_CELERY_CONCURRENCY", "2")
    _, _, mock_popen = _run_service(["reconciler"])
    assert "-c 2" in mock_popen.call_args[0][0]


def test_unknown_service_type_errors(loguru_logs):
    result, mock_check, mock_popen = _run_service(["bogus"])

    mock_check.assert_called_once()
    mock_popen.assert_not_called()
    assert result == 1
    assert any(
        record["level"] == "ERROR" and "bogus" in record["message"]
        for record in loguru_logs
    )


def test_watchdog_observes_inventory_and_cleans_up():
    cmd, parsed_args = parse_args(service.Run, ["watchdog"])

    with patch(
        "osism.commands.service.utils.check_task_lock_and_exit"
    ) as mock_check, patch(
        "watchdog.observers.polling.PollingObserver"
    ) as mock_observer_class, patch(
        "osism.commands.service.time.sleep", side_effect=_Stop
    ):
        with pytest.raises(_Stop):
            cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    observer = mock_observer_class.return_value

    event_handler = observer.schedule.call_args[0][0]
    assert event_handler.on_any_event == cmd.watchdog_inventory_on_any_event
    observer.schedule.assert_called_once_with(
        event_handler, "/opt/configuration/inventory", recursive=True
    )
    observer.start.assert_called_once_with()
    # The ``finally`` block must stop and join the observer even when the
    # loop exits via an exception.
    observer.stop.assert_called_once_with()
    observer.join.assert_called_once_with()


def test_watchdog_inventory_event_triggers_inventory_sync():
    cmd = make_command(service.Run)

    with patch("osism.tasks.reconciler.run.delay") as mock_delay:
        cmd.watchdog_inventory_on_any_event(MagicMock())

    mock_delay.assert_called_once_with()
