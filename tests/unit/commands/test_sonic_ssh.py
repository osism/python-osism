# SPDX-License-Identifier: Apache-2.0

"""Tests for the --refresh-host-key option on SONiC SSH-using commands."""

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import sonic

SSH_COMMAND_CLASSES = [
    sonic.Load,
    sonic.Backup,
    sonic.Ztp,
    sonic.Reload,
    sonic.Reboot,
    sonic.Reset,
    sonic.Show,
]


def _build_parser_for(cmd_cls):
    """Instantiate a cliff Command and return its argparse parser."""
    cmd = cmd_cls(MagicMock(), MagicMock())
    return cmd.get_parser("test")


# --- Parser wiring ---


@pytest.mark.parametrize("cmd_cls", SSH_COMMAND_CLASSES, ids=lambda c: c.__name__)
def test_parser_registers_refresh_host_key_option(cmd_cls):
    parser = _build_parser_for(cmd_cls)
    actions = {a.dest: a for a in parser._actions}
    assert "refresh_host_key" in actions
    action = actions["refresh_host_key"]
    assert "--refresh-host-key" in action.option_strings
    assert action.default is False
    # store_true: nargs=0, const=True
    assert action.const is True
    assert action.nargs == 0


@pytest.mark.parametrize("cmd_cls", SSH_COMMAND_CLASSES, ids=lambda c: c.__name__)
def test_parser_default_is_false(cmd_cls):
    parser = _build_parser_for(cmd_cls)
    # All these commands take a hostname positional, plus Show takes nargs="*",
    # plus Ztp takes a leading action. Build a minimal valid argv per command.
    if cmd_cls is sonic.Ztp:
        argv = ["status", "switch1"]
    else:
        argv = ["switch1"]
    args = parser.parse_args(argv)
    assert args.refresh_host_key is False


@pytest.mark.parametrize("cmd_cls", SSH_COMMAND_CLASSES, ids=lambda c: c.__name__)
def test_parser_sets_true_when_flag_passed(cmd_cls):
    parser = _build_parser_for(cmd_cls)
    if cmd_cls is sonic.Ztp:
        argv = ["status", "switch1", "--refresh-host-key"]
    else:
        argv = ["switch1", "--refresh-host-key"]
    args = parser.parse_args(argv)
    assert args.refresh_host_key is True


# --- _create_ssh_connection behavior ---


class _ConcreteSonicCommand(sonic.SonicCommandBase):
    """Concrete subclass so we can instantiate the abstract base in tests."""

    def take_action(self, parsed_args):  # pragma: no cover - not exercised
        return 0


def _make_base():
    return _ConcreteSonicCommand(MagicMock(), MagicMock())


@patch("osism.commands.sonic.paramiko")
@patch("osism.commands.sonic.remove_known_hosts_entries")
@patch("osism.commands.sonic.ensure_known_hosts_file", return_value=True)
@patch("osism.commands.sonic.os.path.exists", return_value=True)
def test_create_ssh_connection_calls_remove_when_refresh_true(
    _exists, _ensure, mock_remove, _paramiko
):
    base = _make_base()
    result = base._create_ssh_connection("10.0.0.1", "admin", refresh_host_key=True)
    assert result is not None
    mock_remove.assert_called_once_with("10.0.0.1", sonic.KNOWN_HOSTS_PATH)


@patch("osism.commands.sonic.paramiko")
@patch("osism.commands.sonic.remove_known_hosts_entries")
@patch("osism.commands.sonic.ensure_known_hosts_file", return_value=True)
@patch("osism.commands.sonic.os.path.exists", return_value=True)
def test_create_ssh_connection_skips_remove_when_refresh_false(
    _exists, _ensure, mock_remove, _paramiko
):
    base = _make_base()
    base._create_ssh_connection("10.0.0.1", "admin", refresh_host_key=False)
    mock_remove.assert_not_called()


@patch("osism.commands.sonic.paramiko")
@patch("osism.commands.sonic.remove_known_hosts_entries")
@patch("osism.commands.sonic.ensure_known_hosts_file", return_value=True)
@patch("osism.commands.sonic.os.path.exists", return_value=True)
def test_create_ssh_connection_default_does_not_refresh(
    _exists, _ensure, mock_remove, _paramiko
):
    """Default value preserves prior (non-refreshing) behavior."""
    base = _make_base()
    base._create_ssh_connection("10.0.0.1", "admin")
    mock_remove.assert_not_called()


@patch("osism.commands.sonic.paramiko")
@patch("osism.commands.sonic.remove_known_hosts_entries")
@patch("osism.commands.sonic.ensure_known_hosts_file", return_value=True)
@patch("osism.commands.sonic.os.path.exists", return_value=False)
def test_create_ssh_connection_returns_none_when_key_missing(
    _exists, _ensure, mock_remove, _paramiko
):
    """Missing private key short-circuits before any host-key handling."""
    base = _make_base()
    result = base._create_ssh_connection("10.0.0.1", "admin", refresh_host_key=True)
    assert result is None
    mock_remove.assert_not_called()


@patch("osism.commands.sonic.paramiko")
@patch(
    "osism.commands.sonic.remove_known_hosts_entries",
    side_effect=PermissionError("denied"),
)
@patch("osism.commands.sonic.ensure_known_hosts_file", return_value=True)
@patch("osism.commands.sonic.os.path.exists", return_value=True)
def test_create_ssh_connection_continues_when_refresh_fails(
    _exists, _ensure, _mock_remove, mock_paramiko
):
    """If the host-key refresh raises, we log and proceed with the connection."""
    base = _make_base()
    result = base._create_ssh_connection("10.0.0.1", "admin", refresh_host_key=True)
    assert result is not None
    mock_paramiko.SSHClient.return_value.connect.assert_called_once()


# --- take_action forwards refresh_host_key to _create_ssh_connection ---


def _build_parsed_args(cmd_cls, refresh_host_key):
    """Build a minimal parsed_args mock for each command's take_action."""
    parsed_args = MagicMock()
    parsed_args.hostname = "switch1"
    parsed_args.refresh_host_key = refresh_host_key
    if cmd_cls is sonic.Ztp:
        parsed_args.action = "status"
    if cmd_cls is sonic.Reset:
        # Skip the interactive confirmation prompt.
        parsed_args.force = True
    if cmd_cls is sonic.Show:
        parsed_args.command = []
    return parsed_args


@pytest.mark.parametrize("cmd_cls", SSH_COMMAND_CLASSES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("refresh", [True, False], ids=["refresh", "no_refresh"])
@patch("osism.commands.sonic.utils")
def test_take_action_forwards_refresh_host_key(mock_utils, cmd_cls, refresh):
    """Each SSH-using command must forward parsed_args.refresh_host_key."""
    cmd = cmd_cls(MagicMock(), MagicMock())

    # Stub the helpers take_action calls before _create_ssh_connection.
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"management": {}})
    cmd._save_config_context = MagicMock(return_value="/tmp/cfg.json")
    cmd._get_ssh_connection_details = MagicMock(return_value=("10.0.0.1", "admin"))
    # Returning None short-circuits take_action right after _create_ssh_connection.
    cmd._create_ssh_connection = MagicMock(return_value=None)

    parsed_args = _build_parsed_args(cmd_cls, refresh)
    cmd.take_action(parsed_args)

    cmd._create_ssh_connection.assert_called_once()
    args, kwargs = cmd._create_ssh_connection.call_args
    # refresh_host_key may be passed positionally (3rd arg) or as a keyword.
    if "refresh_host_key" in kwargs:
        assert kwargs["refresh_host_key"] is refresh
    else:
        assert args[2] is refresh
