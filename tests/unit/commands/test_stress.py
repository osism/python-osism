# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import stress

STRESS_TOOL = "/openstack-simple-stress/openstack_simple_stress/main.py"

BOOLEAN_FLAGS = [
    "--no-cleanup",
    "--debug",
    "--no-delete",
    "--no-volume",
    "--no-boot-volume",
    "--no-wait",
    "--clean",
]


def _run(args, run_mock=None, setup_success=True):
    """Drive OpenStackStress.take_action with mocked cloud helpers."""
    cmd = stress.OpenStackStress(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)

    setup = MagicMock(return_value=("pw", ["tempfile"], "/cwd", setup_success))
    cleanup = MagicMock()
    if run_mock is None:
        run_mock = MagicMock(return_value=MagicMock(returncode=0))
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, MagicMock(), cleanup),
    ), patch("osism.commands.stress.subprocess.run", run_mock):
        result = cmd.take_action(parsed_args)
    return result, run_mock, cleanup


def _flag_value(command, flag):
    return command[command.index(flag) + 1]


def test_defaults_build_expected_command():
    result, run_mock, _ = _run([])

    command = run_mock.call_args[0][0]
    assert command[:2] == ["python3", STRESS_TOOL]
    for flag in BOOLEAN_FLAGS:
        assert flag not in command

    expected = {
        "--interval": "10",
        "--number": "1",
        "--parallel": "1",
        "--timeout": "600",
        "--volume-number": "1",
        "--volume-size": "1",
        "--boot-volume-size": "20",
        "--cloud": "simple-stress",
        "--flavor": "SCS-1V-2",
        "--image": "Ubuntu 24.04",
        "--subnet-cidr": "10.100.0.0/16",
        "--prefix": "simple-stress",
        "--compute-zone": "nova",
        "--storage-zone": "nova",
        "--affinity": "soft-anti-affinity",
        "--volume-type": "__DEFAULT__",
        "--mode": "rolling",
    }
    for flag, value in expected.items():
        assert _flag_value(command, flag) == value

    assert result == 0


@pytest.mark.parametrize("flag", BOOLEAN_FLAGS)
def test_boolean_flag_appended(flag):
    _, run_mock, _ = _run([flag])
    assert flag in run_mock.call_args[0][0]


def test_custom_values_propagated():
    _, run_mock, _ = _run(["--number", "5", "--flavor", "X", "--volume-size", "10"])

    command = run_mock.call_args[0][0]
    assert _flag_value(command, "--number") == "5"
    assert _flag_value(command, "--flavor") == "X"
    assert _flag_value(command, "--volume-size") == "10"


@pytest.mark.parametrize("returncode", [0, 3])
def test_returncode_passed_through(returncode):
    run_mock = MagicMock(return_value=MagicMock(returncode=returncode))
    result, _, cleanup = _run([], run_mock=run_mock)

    assert result == returncode
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_tool_not_found_returns_1(loguru_logs):
    run_mock = MagicMock(side_effect=FileNotFoundError())
    result, _, cleanup = _run([], run_mock=run_mock)

    assert result == 1
    assert any(
        record["level"] == "ERROR" and STRESS_TOOL in record["message"]
        for record in loguru_logs
    )
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_generic_exception_returns_1():
    run_mock = MagicMock(side_effect=RuntimeError("boom"))
    result, _, cleanup = _run([], run_mock=run_mock)

    assert result == 1
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_setup_failure_returns_1():
    result, run_mock, _ = _run([], setup_success=False)

    assert result == 1
    run_mock.assert_not_called()
