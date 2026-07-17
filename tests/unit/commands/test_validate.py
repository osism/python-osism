# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism validate`` commands.

Covered here:

- the exit-code contract: ``_handle_task`` is what ``take_action`` returns, so
  a timeout while waiting for task output must yield a non-zero exit status
  rather than an implicit ``None`` (exit 0);
- ``Run.take_action``: dispatch of validators to the matching runtime
  (kolla-ansible, ceph-ansible, osism-ansible), the ``--environment``
  override, and the task-lock check before any task is scheduled;
- ``Run._handle_task``: rc passthrough when waiting and the log/script output
  modes when not waiting;
- ``Scs.take_action``: compliance-check command construction, error handling,
  and cloud environment cleanup on every post-setup path.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import validate

from ._helpers import assert_not_called_before_lock_check, parse_args


def test_handle_task_returns_nonzero_on_timeout():
    cmd = validate.Run(MagicMock(), MagicMock())
    task = MagicMock()

    with patch(
        "osism.commands.validate.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd._handle_task(
            task, wait=True, format="log", timeout=1, playbook="validate-x"
        )

    assert result == 1


def _run_take_action(args):
    """Drive ``Run.take_action`` with the task backends and helpers mocked."""
    cmd, parsed_args = parse_args(validate.Run, args)

    with patch("osism.tasks.ansible.run") as mock_ansible, patch(
        "osism.tasks.ceph.run"
    ) as mock_ceph, patch("osism.tasks.kolla.run") as mock_kolla, patch(
        "osism.commands.validate.utils.check_task_lock_and_exit"
    ) as mock_check, patch.object(
        validate.Run, "_handle_task", return_value=0
    ) as mock_handle:
        result = cmd.take_action(parsed_args)

    return SimpleNamespace(
        result=result,
        ansible=mock_ansible,
        ceph=mock_ceph,
        kolla=mock_kolla,
        check=mock_check,
        handle=mock_handle,
    )


def test_take_action_kolla_validator_appends_config_validate_action():
    mocks = _run_take_action(["keystone-config", "-e", "foo=1"])

    mocks.kolla.delay.assert_called_once_with(
        "kolla", "keystone", ["-e", "foo=1", "-e kolla_action=config_validate"]
    )
    mocks.ansible.delay.assert_not_called()
    mocks.ceph.delay.assert_not_called()
    mocks.handle.assert_called_once_with(
        mocks.kolla.delay.return_value, True, "log", 300, "keystone"
    )
    assert mocks.result == 0


@pytest.mark.parametrize(
    ("args", "backend", "expected"),
    [
        (
            ["--environment", "custom", "keystone-config"],
            "kolla",
            ("custom", "keystone", ["-e kolla_action=config_validate"]),
        ),
        (
            ["--environment", "custom", "ceph-config"],
            "ceph",
            ("custom", "validate", []),
        ),
    ],
)
def test_take_action_honors_environment_for_ceph_and_kolla(args, backend, expected):
    mocks = _run_take_action(args)

    getattr(mocks, backend).delay.assert_called_once_with(*expected)


def test_take_action_ceph_validator_rewrites_playbook():
    mocks = _run_take_action(["ceph-config"])

    mocks.ceph.delay.assert_called_once_with("ceph", "validate", [])
    mocks.handle.assert_called_once_with(
        mocks.ceph.delay.return_value, True, "log", 300, "validate"
    )
    assert mocks.result == 0


def test_take_action_osism_validator_derives_playbook_name():
    mocks = _run_take_action(["ntp"])

    mocks.ansible.delay.assert_called_once_with("generic", "validate-ntp", [])
    mocks.handle.assert_called_once_with(
        mocks.ansible.delay.return_value, True, "log", 300, "validate-ntp"
    )
    assert mocks.result == 0


def test_take_action_checks_task_lock_before_scheduling():
    cmd, parsed_args = parse_args(validate.Run, ["ntp"])

    with patch("osism.tasks.ansible.run") as mock_ansible, patch(
        "osism.commands.validate.utils.check_task_lock_and_exit"
    ) as mock_check, patch.object(validate.Run, "_handle_task", return_value=0):
        mock_check.side_effect = assert_not_called_before_lock_check(mock_ansible.delay)
        cmd.take_action(parsed_args)

    mock_check.assert_called_once()


def test_handle_task_passes_through_rc_when_waiting():
    cmd = validate.Run(MagicMock(), MagicMock())
    task = MagicMock()

    with patch(
        "osism.commands.validate.utils.fetch_task_output", return_value=3
    ) as mock_fetch:
        result = cmd._handle_task(
            task, wait=True, format="log", timeout=5, playbook="validate-x"
        )

    mock_fetch.assert_called_once_with(task.id, timeout=5)
    assert result == 3


def test_handle_task_no_wait_log_format_logs_and_returns_zero(loguru_logs):
    cmd = validate.Run(MagicMock(), MagicMock())
    task = MagicMock()
    task.task_id = "taskid1"

    result = cmd._handle_task(
        task, wait=False, format="log", timeout=5, playbook="validate-ntp"
    )

    assert result == 0
    assert any(
        record["level"] == "INFO"
        and "Task taskid1 (validate validate-ntp) is running in background"
        in record["message"]
        for record in loguru_logs
    )


def test_handle_task_no_wait_script_format_prints_task_id(capsys):
    cmd = validate.Run(MagicMock(), MagicMock())
    task = MagicMock()
    task.task_id = "taskid1"

    result = cmd._handle_task(
        task, wait=False, format="script", timeout=5, playbook="validate-ntp"
    )

    assert result == 0
    assert capsys.readouterr().out == "taskid1\n"


def _run_scs(args, *, setup=("secret", ["/tmp/f1"], "/orig", True), run=None):
    """Drive ``Scs.take_action`` with the cloud setup and subprocess mocked."""
    cmd, parsed_args = parse_args(validate.Scs, args)

    if run is None:
        run = {"return_value": MagicMock(returncode=0)}

    with patch(
        "osism.tasks.openstack.setup_cloud_environment", return_value=setup
    ) as mock_setup, patch(
        "osism.tasks.openstack.cleanup_cloud_environment"
    ) as mock_cleanup, patch(
        "osism.commands.validate.subprocess.run", **run
    ) as mock_run:
        result = cmd.take_action(parsed_args)

    return SimpleNamespace(
        result=result, setup=mock_setup, cleanup=mock_cleanup, run=mock_run
    )


def _contains_slice(command, expected):
    """Whether ``expected`` occurs in ``command`` as a contiguous slice."""
    width = len(expected)
    return any(
        command[i : i + width] == expected for i in range(len(command) - width + 1)
    )


def test_scs_returns_one_when_cloud_setup_fails():
    mocks = _run_scs([], setup=(None, [], "/orig", False))

    assert mocks.result == 1
    mocks.run.assert_not_called()
    mocks.cleanup.assert_not_called()


def test_scs_builds_command_and_passes_returncode_through():
    mocks = _run_scs(
        ["--cloud", "mycloud", "--version", "v9.9"],
        run={"return_value": MagicMock(returncode=7)},
    )

    mocks.setup.assert_called_once_with("mycloud")

    args, kwargs = mocks.run.call_args
    command = args[0]
    assert command[:2] == ["python3", "/scs-tests/scs-compliance-check.py"]
    assert _contains_slice(command, ["-s", "mycloud"])
    assert _contains_slice(command, ["-a", "os_cloud=mycloud"])
    assert _contains_slice(command, ["-V", "v9.9"])
    assert command[-1] == "scs-compatible-iaas.yaml"
    assert kwargs["cwd"] == "/scs-tests/"
    assert kwargs["check"] is False
    assert kwargs["env"]["OS_CLIENT_CONFIG_FILE"] == "/tmp/clouds.yaml"

    mocks.cleanup.assert_called_once_with(["/tmp/f1"], "/orig")
    assert mocks.result == 7


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--verbose"], ["-v"]),
        (["--debug"], ["--debug"]),
        (["--tests", "scs-0100|scs-0103"], ["-t", "scs-0100|scs-0103"]),
        (["--output", "report.yaml"], ["-o", "report.yaml"]),
        (["--sections", "standard,iaas"], ["-S", "standard,iaas"]),
    ],
)
def test_scs_optional_arguments_extend_command(args, expected):
    mocks = _run_scs(args)

    command = mocks.run.call_args[0][0]
    assert _contains_slice(command, expected)


def test_scs_returns_one_when_check_tool_is_missing(loguru_logs):
    mocks = _run_scs([], run={"side_effect": FileNotFoundError})

    assert mocks.result == 1
    assert any(
        "SCS compliance check tool not found" in record["message"]
        for record in loguru_logs
    )
    mocks.cleanup.assert_called_once_with(["/tmp/f1"], "/orig")


def test_scs_returns_one_on_unexpected_subprocess_error():
    mocks = _run_scs([], run={"side_effect": RuntimeError("boom")})

    assert mocks.result == 1
    mocks.cleanup.assert_called_once_with(["/tmp/f1"], "/orig")
