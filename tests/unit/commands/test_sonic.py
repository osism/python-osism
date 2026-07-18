# SPDX-License-Identifier: Apache-2.0

"""Tests for the SONiC command base helpers and command orchestration.

The SSH-key handling of ``_create_ssh_connection`` and the
``--refresh-host-key`` wiring are covered in ``test_sonic_ssh.py``; this
module covers the remaining ``SonicCommandBase`` helpers and the
``take_action`` control flow of the SSH-driven commands.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

import paramiko
import pytest

from osism.commands import sonic


class _ConcreteSonicCommand(sonic.SonicCommandBase):
    """Concrete subclass so we can instantiate the abstract base in tests."""

    def take_action(self, parsed_args):  # pragma: no cover - not exercised
        return 0


def _make_base():
    return _ConcreteSonicCommand(MagicMock(), MagicMock())


def _make_exec_result(exit_status=0, stdout=b"", stderr=b""):
    out, err = MagicMock(), MagicMock()
    out.channel.recv_exit_status.return_value = exit_status
    out.read.return_value = stdout
    err.read.return_value = stderr
    return (MagicMock(), out, err)


def make_ssh(exit_status=0, stdout=b"", stderr=b""):
    ssh = MagicMock()
    ssh.exec_command.return_value = _make_exec_result(exit_status, stdout, stderr)
    return ssh


# --- SonicCommandBase._get_device_from_netbox ---


def test_get_device_from_netbox_by_name():
    device = MagicMock()
    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = device

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert _make_base()._get_device_from_netbox("sw1") is device

    fake_nb.dcim.devices.get.assert_called_once_with(name="sw1")
    fake_nb.dcim.devices.filter.assert_not_called()


def test_get_device_from_netbox_by_inventory_hostname(loguru_logs):
    first, second = MagicMock(), MagicMock()
    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None
    fake_nb.dcim.devices.filter.return_value = [first, second]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert _make_base()._get_device_from_netbox("sw1") is first

    fake_nb.dcim.devices.filter.assert_called_once_with(cf_inventory_hostname="sw1")
    assert any(
        "found by inventory_hostname" in record["message"] for record in loguru_logs
    )


def test_get_device_from_netbox_not_found(loguru_logs):
    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None
    fake_nb.dcim.devices.filter.return_value = []

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert _make_base()._get_device_from_netbox("sw1") is None

    assert any(
        "not found in NetBox" in record["message"] and record["level"] == "ERROR"
        for record in loguru_logs
    )


# --- SonicCommandBase._get_config_context ---


def test_get_config_context_without_attribute():
    device = SimpleNamespace()
    assert _make_base()._get_config_context(device, "sw1") is None


@pytest.mark.parametrize("context", [None, {}], ids=["none", "empty"])
def test_get_config_context_empty(context):
    device = SimpleNamespace(local_context_data=context)
    assert _make_base()._get_config_context(device, "sw1") is None


def test_get_config_context_filters_underscore_keys():
    device = SimpleNamespace(
        local_context_data={"_meta": 1, "management": {"ip": "10.0.0.1"}}
    )
    result = _make_base()._get_config_context(device, "sw1")
    assert result == {"management": {"ip": "10.0.0.1"}}


# --- SonicCommandBase._save_config_context ---


def test_save_config_context_writes_json():
    base = _make_base()
    m_open = mock_open()

    with patch("builtins.open", m_open), patch(
        "osism.commands.sonic.json.dump"
    ) as mock_dump:
        result = base._save_config_context({"a": 1}, "sw1", "20260718")

    assert result == "/tmp/config_db_sw1_20260718.json"
    m_open.assert_called_once_with("/tmp/config_db_sw1_20260718.json", "w")
    assert mock_dump.call_args[0][0] == {"a": 1}
    assert mock_dump.call_args[1] == {"indent": 2}


def test_save_config_context_returns_none_on_error(loguru_logs):
    base = _make_base()

    with patch("builtins.open", side_effect=OSError("denied")):
        result = base._save_config_context({"a": 1}, "sw1", "20260718")

    assert result is None
    assert any(
        "Failed to save config context" in record["message"] for record in loguru_logs
    )


# --- SonicCommandBase._get_ssh_connection_details ---


def test_ssh_details_from_config_context():
    config_context = {"management": {"ip": "10.0.0.5", "username": "ops"}}

    with patch("osism.tasks.conductor.netbox.get_device_oob_ip") as mock_oob:
        host, username = _make_base()._get_ssh_connection_details(
            config_context, MagicMock(), "sw1"
        )

    assert (host, username) == ("10.0.0.5", "ops")
    mock_oob.assert_not_called()


def test_ssh_details_fall_back_to_oob_ip():
    config_context = {"management": {"username": "ops"}}
    device = MagicMock()

    with patch(
        "osism.tasks.conductor.netbox.get_device_oob_ip",
        return_value=("10.0.0.9", "eth0"),
    ) as mock_oob:
        host, username = _make_base()._get_ssh_connection_details(
            config_context, device, "sw1"
        )

    assert (host, username) == ("10.0.0.9", "ops")
    mock_oob.assert_called_once_with(device)


def test_ssh_details_none_when_no_host(loguru_logs):
    with patch("osism.tasks.conductor.netbox.get_device_oob_ip", return_value=None):
        result = _make_base()._get_ssh_connection_details({}, MagicMock(), "sw1")

    assert result == (None, None)
    assert any("No SSH host found" in record["message"] for record in loguru_logs)


def test_ssh_details_default_username():
    config_context = {"management": {"ip": "10.0.0.5"}}

    with patch("osism.tasks.conductor.netbox.get_device_oob_ip") as mock_oob:
        host, username = _make_base()._get_ssh_connection_details(
            config_context, MagicMock(), "sw1"
        )

    assert (host, username) == ("10.0.0.5", "admin")
    mock_oob.assert_not_called()


# --- SonicCommandBase._generate_backup_filename ---


def test_generate_backup_filename_first_free_slot():
    ssh = MagicMock()
    ssh.exec_command.return_value = _make_exec_result(stdout=b"")

    result = _make_base()._generate_backup_filename(ssh, "sw1", "20260718")

    assert result == "/home/admin/config_db_sw1_20260718_1.json"
    ssh.exec_command.assert_called_once_with(
        "ls /home/admin/config_db_sw1_20260718_1.json 2>/dev/null"
    )


def test_generate_backup_filename_skips_existing_files():
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(stdout=b"/home/admin/config_db_sw1_20260718_1.json\n"),
        _make_exec_result(stdout=b"/home/admin/config_db_sw1_20260718_2.json\n"),
        _make_exec_result(stdout=b""),
    ]

    result = _make_base()._generate_backup_filename(ssh, "sw1", "20260718")

    assert result == "/home/admin/config_db_sw1_20260718_3.json"
    assert ssh.exec_command.call_count == 3
    assert ssh.exec_command.call_args == call(
        "ls /home/admin/config_db_sw1_20260718_3.json 2>/dev/null"
    )


# --- exec-command helpers ---

_EXEC_HELPER_CASES = [
    (
        "_backup_current_config",
        ("/home/admin/backup.json",),
        "sudo cp /etc/sonic/config_db.json /home/admin/backup.json",
    ),
    ("_load_configuration", ("/tmp/cfg.json",), "sudo config load -y /tmp/cfg.json"),
    ("_reload_configuration", (), "sudo config reload -y"),
    ("_save_configuration", (), "sudo config save -y"),
    ("_enable_ztp", (), "sudo config ztp enable"),
    ("_disable_ztp", (), "sudo config ztp disable"),
]


@pytest.mark.parametrize(
    "method,args,expected_cmd",
    _EXEC_HELPER_CASES,
    ids=[c[0] for c in _EXEC_HELPER_CASES],
)
def test_exec_helper_success(method, args, expected_cmd):
    ssh = make_ssh(exit_status=0)

    assert getattr(_make_base(), method)(ssh, *args) is True
    ssh.exec_command.assert_called_once_with(expected_cmd)


@pytest.mark.parametrize(
    "method,args,expected_cmd",
    _EXEC_HELPER_CASES,
    ids=[c[0] for c in _EXEC_HELPER_CASES],
)
def test_exec_helper_failure_logs_stderr(method, args, expected_cmd, loguru_logs):
    ssh = make_ssh(exit_status=1, stderr=b"boom happened")

    assert getattr(_make_base(), method)(ssh, *args) is False
    assert any(
        "boom happened" in record["message"] and record["level"] == "ERROR"
        for record in loguru_logs
    )


# --- SonicCommandBase._cleanup_temp_file / _get_ztp_status ---


def test_cleanup_temp_file_success(loguru_logs):
    ssh = make_ssh(exit_status=0)

    assert _make_base()._cleanup_temp_file(ssh, "/tmp/x.json") is None
    ssh.exec_command.assert_called_once_with("rm /tmp/x.json")
    assert not any(record["level"] == "WARNING" for record in loguru_logs)


def test_cleanup_temp_file_warns_on_failure(loguru_logs):
    ssh = make_ssh(exit_status=1, stderr=b"nope")

    assert _make_base()._cleanup_temp_file(ssh, "/tmp/x.json") is None
    assert any(
        "nope" in record["message"] and record["level"] == "WARNING"
        for record in loguru_logs
    )


def test_get_ztp_status_returns_stripped_output():
    ssh = make_ssh(exit_status=0, stdout=b"  ZTP Admin Mode : True\n")

    assert _make_base()._get_ztp_status(ssh) == "ZTP Admin Mode : True"
    ssh.exec_command.assert_called_once_with("show ztp status")


def test_get_ztp_status_none_on_failure():
    ssh = make_ssh(exit_status=1, stderr=b"err")

    assert _make_base()._get_ztp_status(ssh) is None


# --- Load.take_action ---

_LOAD_SSH_STEPS = [
    "_generate_backup_filename",
    "_backup_current_config",
    "_upload_config_context",
    "_load_configuration",
    "_save_configuration",
    "_cleanup_temp_file",
]


def _stub_pre_ssh_helpers(cmd, ssh):
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"management": {"ip": "10.0.0.1"}})
    cmd._save_config_context = MagicMock(return_value="/tmp/cfg.json")
    cmd._get_ssh_connection_details = MagicMock(return_value=("10.0.0.1", "admin"))
    cmd._create_ssh_connection = MagicMock(return_value=ssh)


def _make_load(ssh):
    cmd = sonic.Load(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    cmd._generate_backup_filename = MagicMock(return_value="/home/admin/backup_1.json")
    cmd._backup_current_config = MagicMock(return_value=True)
    cmd._upload_config_context = MagicMock(
        return_value="/tmp/config_db_sw1_current.json"
    )
    cmd._load_configuration = MagicMock(return_value=True)
    cmd._save_configuration = MagicMock(return_value=True)
    cmd._cleanup_temp_file = MagicMock()
    return cmd


def test_load_happy_path_runs_steps_in_order():
    ssh = MagicMock()
    cmd = _make_load(ssh)
    manager = MagicMock()
    for name in _LOAD_SSH_STEPS:
        manager.attach_mock(getattr(cmd, name), name)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0

    assert [name for name, _, _ in manager.mock_calls] == _LOAD_SSH_STEPS
    ssh.close.assert_called_once_with()


@pytest.mark.parametrize(
    "failing",
    [
        "_get_device_from_netbox",
        "_get_config_context",
        "_save_config_context",
        "_create_ssh_connection",
        "_backup_current_config",
        "_upload_config_context",
        "_load_configuration",
        "_save_configuration",
    ],
)
def test_load_returns_one_when_step_fails(failing):
    ssh = MagicMock()
    cmd = _make_load(ssh)
    getattr(cmd, failing).return_value = None
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1

    if failing in {
        "_backup_current_config",
        "_upload_config_context",
        "_load_configuration",
        "_save_configuration",
    }:
        ssh.close.assert_called_once_with()


def test_load_returns_one_when_no_ssh_host():
    cmd = _make_load(MagicMock())
    cmd._get_ssh_connection_details.return_value = (None, None)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1
    cmd._create_ssh_connection.assert_not_called()


@pytest.mark.parametrize(
    "exc",
    [
        paramiko.AuthenticationException(),
        paramiko.SSHException("broken"),
        Exception("boom"),
    ],
    ids=["auth", "ssh", "generic"],
)
def test_load_returns_one_on_ssh_exception(exc):
    ssh = MagicMock()
    cmd = _make_load(ssh)
    cmd._backup_current_config.side_effect = exc
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1
    ssh.close.assert_called_once_with()


# --- Backup.take_action ---


def _make_backup(ssh):
    cmd = sonic.Backup(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    cmd._generate_backup_filename = MagicMock(return_value="/home/admin/backup_1.json")
    cmd._backup_current_config = MagicMock(return_value=True)
    return cmd


def test_backup_happy_path():
    ssh = MagicMock()
    cmd = _make_backup(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0

    cmd._backup_current_config.assert_called_once_with(ssh, "/home/admin/backup_1.json")
    ssh.close.assert_called_once_with()


def test_backup_returns_one_when_backup_fails():
    ssh = MagicMock()
    cmd = _make_backup(ssh)
    cmd._backup_current_config.return_value = False
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1
    ssh.close.assert_called_once_with()


# --- Ztp.take_action ---


def _make_ztp(ssh):
    cmd = sonic.Ztp(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    cmd._enable_ztp = MagicMock(return_value=True)
    cmd._disable_ztp = MagicMock(return_value=True)
    cmd._get_ztp_status = MagicMock(return_value="ZTP Admin Mode : True")
    return cmd


@pytest.mark.parametrize(
    "action,helper,other_helpers",
    [
        ("enable", "_enable_ztp", ["_disable_ztp", "_get_ztp_status"]),
        ("disable", "_disable_ztp", ["_enable_ztp", "_get_ztp_status"]),
    ],
)
def test_ztp_enable_disable(action, helper, other_helpers):
    ssh = MagicMock()
    cmd = _make_ztp(ssh)
    parsed_args = cmd.get_parser("test").parse_args([action, "sw1"])

    assert cmd.take_action(parsed_args) == 0

    getattr(cmd, helper).assert_called_once_with(ssh)
    for name in other_helpers:
        getattr(cmd, name).assert_not_called()
    ssh.close.assert_called_once_with()


@pytest.mark.parametrize(
    "action,helper", [("enable", "_enable_ztp"), ("disable", "_disable_ztp")]
)
def test_ztp_enable_disable_failure(action, helper):
    cmd = _make_ztp(MagicMock())
    getattr(cmd, helper).return_value = False
    parsed_args = cmd.get_parser("test").parse_args([action, "sw1"])

    assert cmd.take_action(parsed_args) == 1


def test_ztp_status_success():
    cmd = _make_ztp(MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["status", "sw1"])

    assert cmd.take_action(parsed_args) == 0
    cmd._get_ztp_status.assert_called_once()


def test_ztp_status_failure():
    cmd = _make_ztp(MagicMock())
    cmd._get_ztp_status.return_value = None
    parsed_args = cmd.get_parser("test").parse_args(["status", "sw1"])

    assert cmd.take_action(parsed_args) == 1


# --- Reload.take_action ---


def _make_reload(ssh):
    cmd = sonic.Reload(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    cmd._generate_backup_filename = MagicMock(return_value="/home/admin/backup_1.json")
    cmd._backup_current_config = MagicMock(return_value=True)
    cmd._upload_config_context = MagicMock(
        return_value="/tmp/config_db_sw1_current.json"
    )
    cmd._load_configuration = MagicMock(return_value=True)
    cmd._reload_configuration = MagicMock(return_value=True)
    cmd._save_configuration = MagicMock(return_value=True)
    cmd._cleanup_temp_file = MagicMock()
    return cmd


def test_reload_happy_path():
    ssh = MagicMock()
    cmd = _make_reload(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0
    cmd._save_configuration.assert_called_once_with(ssh)
    ssh.close.assert_called_once_with()


def test_reload_skips_save_when_reload_fails(loguru_logs):
    cmd = _make_reload(MagicMock())
    cmd._reload_configuration.return_value = False
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1

    cmd._save_configuration.assert_not_called()
    assert any(
        "Skipping config save due to reload failure" in record["message"]
        for record in loguru_logs
    )


def test_reload_returns_one_when_save_fails():
    cmd = _make_reload(MagicMock())
    cmd._save_configuration.return_value = False
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1


# --- Reboot.take_action ---


def test_reboot_happy_path():
    exec_result = _make_exec_result()
    ssh = MagicMock()
    ssh.exec_command.return_value = exec_result
    cmd = sonic.Reboot(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0

    ssh.exec_command.assert_called_once_with("sudo reboot")
    # The exit status is deliberately not checked: the reboot kills the
    # connection before a status could be received.
    exec_result[1].channel.recv_exit_status.assert_not_called()
    ssh.close.assert_called_once_with()


# --- Reset.take_action ---


def _make_reset(ssh):
    cmd = sonic.Reset(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    return cmd


def test_reset_cancelled_by_prompt():
    cmd = _make_reset(MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.commands.sonic.prompt", return_value="no"
    ):
        assert cmd.take_action(parsed_args) == 0

    cmd._get_device_from_netbox.assert_not_called()


@pytest.mark.parametrize("answer", ["yes", "y", "YES", "Y"])
def test_reset_proceeds_on_confirmation(answer):
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(),
        _make_exec_result(),
        _make_exec_result(),
    ]
    cmd = _make_reset(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.commands.sonic.prompt", return_value=answer
    ), patch(
        "osism.commands.sonic.cleanup_ssh_known_hosts_for_node", return_value=True
    ), patch(
        "osism.tasks.netbox.set_provision_state"
    ):
        assert cmd.take_action(parsed_args) == 0

    cmd._get_device_from_netbox.assert_called_once_with("sw1")


def test_reset_force_skips_prompt():
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(),
        _make_exec_result(),
        _make_exec_result(),
    ]
    cmd = _make_reset(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "--force"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.commands.sonic.prompt"
    ) as mock_prompt, patch(
        "osism.commands.sonic.cleanup_ssh_known_hosts_for_node", return_value=True
    ), patch(
        "osism.tasks.netbox.set_provision_state"
    ):
        assert cmd.take_action(parsed_args) == 0

    mock_prompt.assert_not_called()


def test_reset_returns_one_when_first_grub_command_fails():
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(exit_status=1, stderr=b"grub err")
    ]
    cmd = _make_reset(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "--force"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.netbox.set_provision_state"
    ) as mock_state:
        assert cmd.take_action(parsed_args) == 1

    mock_state.delay.assert_not_called()
    ssh.close.assert_called_once_with()


def test_reset_returns_one_when_second_grub_command_fails():
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(),
        _make_exec_result(exit_status=1, stderr=b"grub err"),
    ]
    cmd = _make_reset(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "--force"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.netbox.set_provision_state"
    ) as mock_state:
        assert cmd.take_action(parsed_args) == 1

    mock_state.delay.assert_not_called()


@pytest.mark.parametrize("cleanup_result", [True, False])
def test_reset_happy_path(cleanup_result):
    ssh = MagicMock()
    ssh.exec_command.side_effect = [
        _make_exec_result(),
        _make_exec_result(),
        _make_exec_result(),
    ]
    cmd = _make_reset(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "--force"])

    with patch("osism.commands.sonic.utils.check_task_lock_and_exit"), patch(
        "osism.commands.sonic.cleanup_ssh_known_hosts_for_node",
        return_value=cleanup_result,
    ) as mock_cleanup, patch("osism.tasks.netbox.set_provision_state") as mock_state:
        assert cmd.take_action(parsed_args) == 0

    assert ssh.exec_command.call_args_list == [
        call("sudo grub-editenv /host/grub/grubenv set onie_mode=uninstall"),
        call("sudo grub-editenv /host/grub/grubenv set next_entry=ONIE"),
        call("sudo reboot"),
    ]
    mock_cleanup.assert_called_once_with("sw1")
    mock_state.delay.assert_called_once_with("sw1", "ztp")
    ssh.close.assert_called_once_with()


# --- Show.take_action ---


def _make_show(ssh):
    cmd = sonic.Show(MagicMock(), MagicMock())
    _stub_pre_ssh_helpers(cmd, ssh)
    return cmd


def test_show_builds_command_from_parts(capsys):
    ssh = make_ssh(exit_status=0, stdout=b"route table\n")
    cmd = _make_show(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "ip", "route"])

    assert cmd.take_action(parsed_args) == 0

    ssh.exec_command.assert_called_once_with("show ip route")
    assert "route table" in capsys.readouterr().out
    ssh.close.assert_called_once_with()


def test_show_bare_command_without_parts():
    ssh = make_ssh(exit_status=0, stdout=b"help\n")
    cmd = _make_show(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0
    ssh.exec_command.assert_called_once_with("show")


def test_show_empty_output_logs_info(capsys, loguru_logs):
    ssh = make_ssh(exit_status=0, stdout=b"")
    cmd = _make_show(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "version"])

    assert cmd.take_action(parsed_args) == 0

    assert capsys.readouterr().out == ""
    assert any("no output" in record["message"] for record in loguru_logs)


def test_show_returns_one_on_failure(loguru_logs):
    ssh = make_ssh(exit_status=2, stderr=b"bad command")
    cmd = _make_show(ssh)
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "bogus"])

    assert cmd.take_action(parsed_args) == 1
    assert any(
        "bad command" in record["message"] and record["level"] == "ERROR"
        for record in loguru_logs
    )


# --- Console.take_action ---


def _make_console():
    cmd = sonic.Console(MagicMock(), MagicMock())
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"management": {"ip": "10.0.0.1"}})
    cmd._get_ssh_connection_details = MagicMock(return_value=("10.0.0.1", "admin"))
    return cmd


def test_console_returns_one_when_key_missing():
    cmd = _make_console()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    with patch("osism.commands.sonic.os.path.exists", return_value=False):
        assert cmd.take_action(parsed_args) == 1


def test_console_builds_ssh_command():
    cmd = _make_console()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    with patch("osism.commands.sonic.os.path.exists", return_value=True), patch(
        "osism.commands.sonic.ensure_known_hosts_file", return_value=True
    ), patch("osism.commands.sonic.os.system", return_value=0) as mock_system:
        assert cmd.take_action(parsed_args) == 0

    ssh_command = mock_system.call_args[0][0]
    assert "-i /ansible/secrets/id_rsa.operator" in ssh_command
    assert "UserKnownHostsFile=" in ssh_command
    assert "admin@10.0.0.1" in ssh_command


def test_console_returns_one_on_nonzero_exit():
    cmd = _make_console()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    with patch("osism.commands.sonic.os.path.exists", return_value=True), patch(
        "osism.commands.sonic.ensure_known_hosts_file", return_value=True
    ), patch("osism.commands.sonic.os.system", return_value=256):
        assert cmd.take_action(parsed_args) == 1


# --- Dump.take_action ---


def test_dump_prints_config_context(capsys):
    cmd = sonic.Dump(MagicMock(), MagicMock())
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value={"management": {"ip": "10.0.0.1"}})
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 0

    out = capsys.readouterr().out
    assert json.loads(out) == {"management": {"ip": "10.0.0.1"}}
    assert out.startswith("{\n  ")


def test_dump_returns_one_without_device():
    cmd = sonic.Dump(MagicMock(), MagicMock())
    cmd._get_device_from_netbox = MagicMock(return_value=None)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1


def test_dump_returns_one_without_config_context():
    cmd = sonic.Dump(MagicMock(), MagicMock())
    cmd._get_device_from_netbox = MagicMock(return_value=MagicMock())
    cmd._get_config_context = MagicMock(return_value=None)
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    assert cmd.take_action(parsed_args) == 1
