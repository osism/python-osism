# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import stress

STRESS_TOOL = "/openstack-simple-stress/openstack_simple_stress/main.py"


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
    return result, run_mock, setup, cleanup


def test_defaults_pass_only_the_cloud():
    result, run_mock, setup, _ = _run([])

    assert run_mock.call_args[0][0] == [
        "python3",
        STRESS_TOOL,
        "--cloud",
        "simple-stress",
    ]
    setup.assert_called_once_with("simple-stress")
    assert result == 0


def test_tool_options_are_forwarded_unchanged():
    args = [
        "--number",
        "5",
        "--profile",
        "acceptance",
        "--no-network",
        "--clean",
        "--yes",
    ]
    _, run_mock, _, _ = _run(args)

    assert run_mock.call_args[0][0][4:] == args


def test_cloud_is_used_for_setup_and_forwarded():
    _, run_mock, setup, _ = _run(["--cloud", "admin", "--number", "2"])

    setup.assert_called_once_with("admin")
    assert run_mock.call_args[0][0][2:] == ["--cloud", "admin", "--number", "2"]


def test_separator_is_removed():
    _, run_mock, _, _ = _run(["--number", "3", "--", "--debug", "--help"])

    assert run_mock.call_args[0][0][4:] == ["--number", "3", "--debug", "--help"]


def test_cloud_after_separator_is_rejected():
    cmd = stress.OpenStackStress(MagicMock(), MagicMock())
    with pytest.raises(SystemExit) as exc:
        cmd.get_parser("test").parse_args(["--", "--cloud", "admin"])
    assert exc.value.code == 2


def test_cloud_equals_after_separator_is_rejected():
    cmd = stress.OpenStackStress(MagicMock(), MagicMock())
    with pytest.raises(SystemExit) as exc:
        cmd.get_parser("test").parse_args(["--number", "2", "--", "--cloud=admin"])
    assert exc.value.code == 2


def test_no_interval_is_imposed():
    _, run_mock, _, _ = _run([])

    assert "--interval" not in run_mock.call_args[0][0]


@pytest.mark.parametrize("returncode", [0, 1, 2, 130])
def test_returncode_passed_through(returncode):
    run_mock = MagicMock(return_value=MagicMock(returncode=returncode))
    result, _, _, cleanup = _run([], run_mock=run_mock)

    assert result == returncode
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_tool_not_found_returns_1(loguru_logs):
    run_mock = MagicMock(side_effect=FileNotFoundError())
    result, _, _, cleanup = _run([], run_mock=run_mock)

    assert result == 1
    assert any(
        record["level"] == "ERROR" and STRESS_TOOL in record["message"]
        for record in loguru_logs
    )
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_generic_exception_returns_1():
    run_mock = MagicMock(side_effect=RuntimeError("boom"))
    result, _, _, cleanup = _run([], run_mock=run_mock)

    assert result == 1
    cleanup.assert_called_once_with(["tempfile"], "/cwd")


def test_setup_failure_returns_1():
    result, run_mock, _, _ = _run([], setup_success=False)

    assert result == 1
    run_mock.assert_not_called()
