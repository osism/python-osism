# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism worker`` command.

``Run`` maps a worker type to a Celery tasks module and starts the worker
process via ``subprocess.Popen``. The concurrency default is derived from
``OSISM_CELERY_CONCURRENCY`` (or the CPU count, capped at 4) at parser-build
time.
"""

from unittest.mock import patch

import pytest

from osism.commands import worker

from ._helpers import assert_not_called_before_lock_check, parse_args


def _run_worker(args):
    cmd, parsed_args = parse_args(worker.Run, args)

    with patch(
        "osism.commands.worker.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.commands.worker.subprocess.Popen") as mock_popen:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_popen)
        result = cmd.take_action(parsed_args)

    return result, mock_check, mock_popen


@pytest.mark.parametrize("cpu_count, expected", [(2, 2), (16, 4)])
def test_parser_default_workers_is_cpu_count_capped_at_four(
    monkeypatch, cpu_count, expected
):
    monkeypatch.delenv("OSISM_CELERY_CONCURRENCY", raising=False)
    with patch(
        "osism.commands.worker.multiprocessing.cpu_count", return_value=cpu_count
    ):
        _, parsed_args = parse_args(worker.Run, ["openstack"])
    assert parsed_args.number_of_workers == expected


def test_parser_default_workers_from_env(monkeypatch):
    # The environment variable is read at parser-build time.
    monkeypatch.setenv("OSISM_CELERY_CONCURRENCY", "7")
    _, parsed_args = parse_args(worker.Run, ["openstack"])
    assert parsed_args.number_of_workers == 7


@pytest.mark.parametrize(
    "worker_type, expected_command",
    [
        (
            "openstack",
            "celery -A osism.tasks.openstack worker -n openstack --loglevel=INFO -Q openstack -c 1",
        ),
        (
            "netbox",
            "celery -A osism.tasks.netbox worker -n netbox --loglevel=INFO -Q netbox -c 1",
        ),
        (
            "conductor",
            "celery -A osism.tasks.conductor worker -n conductor --loglevel=INFO -Q conductor -c 1",
        ),
        (
            "osism-kubernetes",
            "celery -A osism.tasks.kubernetes worker -n kubernetes --loglevel=INFO -Q kubernetes -c 1",
        ),
        (
            "kolla-ansible",
            "celery -A osism.tasks.kolla worker -n kolla-ansible --loglevel=INFO -Q kolla-ansible -c 1",
        ),
        (
            "ceph-ansible",
            "celery -A osism.tasks.ceph worker -n ceph-ansible --loglevel=INFO -Q ceph-ansible -c 1",
        ),
        (
            "osism-ansible",
            "celery -A osism.tasks.ansible worker -n osism-ansible --loglevel=INFO -Q osism-ansible -c 1",
        ),
    ],
)
def test_take_action_maps_worker_type_to_celery_command(worker_type, expected_command):
    _, mock_check, mock_popen = _run_worker(["--number-of-workers", "1", worker_type])

    mock_check.assert_called_once()
    mock_popen.assert_called_once_with(expected_command, shell=True)
    mock_popen.return_value.wait.assert_called_once_with()


def test_take_action_respects_number_of_workers():
    _, _, mock_popen = _run_worker(["--number-of-workers", "3", "openstack"])
    assert "-c 3" in mock_popen.call_args[0][0]


def test_take_action_rejects_unknown_worker_type(loguru_logs):
    result, mock_check, mock_popen = _run_worker(["--number-of-workers", "1", "foo"])

    mock_check.assert_called_once()
    mock_popen.assert_not_called()
    assert result == 1
    assert any(
        record["level"] == "ERROR" and "foo" in record["message"]
        for record in loguru_logs
    )
