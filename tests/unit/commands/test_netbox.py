# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism netbox`` commands.

These focus on the exit-code contract: a command must return a non-zero exit
status when it gives up waiting for a task (a timeout is an operational
failure), rather than falling through to an implicit success.
"""

from unittest.mock import MagicMock, patch

from osism.commands import netbox


def test_ironic_returns_nonzero_on_task_timeout():
    cmd = netbox.Ironic(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_ironic.delay", return_value=MagicMock()
    ), patch(
        "osism.commands.netbox.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_sync_returns_nonzero_on_task_timeout():
    cmd = netbox.Sync(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_netbox.delay", return_value=MagicMock()
    ), patch(
        "osism.commands.netbox.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_dump_returns_nonzero_when_netbox_not_configured():
    cmd = netbox.Dump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["somehost"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_dump_returns_nonzero_when_device_not_found():
    cmd = netbox.Dump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["somehost"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = []

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_console_returns_nonzero_when_netbox_not_configured():
    cmd = netbox.Console(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["info"])

    with patch("osism.commands.netbox.os.path.exists", return_value=False), patch(
        "osism.commands.netbox.os.mkdir"
    ), patch("osism.commands.netbox.os.environ.get", return_value=None), patch(
        "builtins.open", side_effect=FileNotFoundError
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
