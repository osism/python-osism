# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism netbox`` commands.

Covers the exit-code contract (a command must return non-zero when it gives
up waiting for a task or cannot reach NetBox), the pure decision logic in
``Sync`` (error classification, table building), the argument assembly in
``Ironic``/``Manage``, and the device lookup and report formatting in
``Dump``.
"""

import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

import pytest
import requests

from osism.commands import netbox


class _FakeSession:
    """Minimal stand-in for a requests session with a timeout attribute."""

    def __init__(self, timeout=5):
        self.timeout = timeout


class _BareNb:
    """NetBox API stand-in without an http_session attribute."""

    def __init__(self, exc=None):
        self._exc = exc

    def status(self):
        if self._exc:
            raise self._exc
        return {"netbox-version": "4.0"}


class _FakeDevice:
    """NetBox device record stand-in; absent attributes stay absent."""

    def __init__(self, name, **attrs):
        self.name = name
        for key, value in attrs.items():
            setattr(self, key, value)


def _make_sync():
    return netbox.Sync(MagicMock(), MagicMock())


def _make_dump():
    return netbox.Dump(MagicMock(), MagicMock())


# --- Ironic.take_action ---


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


def test_ironic_forwards_arguments_and_returns_fetch_result():
    cmd = netbox.Ironic(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(
        [
            "node1",
            "--adopt",
            "--skip-kernel-param",
            "a",
            "--extra-kernel-param",
            "b=1",
            "--task-timeout",
            "60",
        ]
    )

    task = MagicMock()
    task.id = "task-id"
    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_ironic.delay", return_value=task
    ) as mock_delay, patch(
        "osism.commands.netbox.utils.fetch_task_output", return_value=0
    ) as mock_fetch:
        result = cmd.take_action(parsed_args)

    assert result == 0
    mock_delay.assert_called_once_with(
        node_name="node1",
        adopt=True,
        force=False,
        dry_run=False,
        skip_kernel_params=["a"],
        extra_kernel_params=["b=1"],
    )
    mock_fetch.assert_called_once_with("task-id", timeout=60)


def test_ironic_no_wait_returns_none_without_fetch():
    cmd = netbox.Ironic(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--no-wait"])

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_ironic.delay", return_value=MagicMock()
    ), patch("osism.commands.netbox.utils.fetch_task_output") as mock_fetch:
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_fetch.assert_not_called()


# --- Sync._check_netbox_instance ---


def test_check_netbox_instance_not_configured():
    assert _make_sync()._check_netbox_instance(None) == "Error: Not configured"


def test_check_netbox_instance_success_sets_and_restores_timeout():
    cmd = _make_sync()
    nb = MagicMock()
    nb.http_session = _FakeSession(timeout=5)
    seen = {}
    nb.status.side_effect = lambda: seen.setdefault("timeout", nb.http_session.timeout)

    assert cmd._check_netbox_instance(nb, timeout=42) == "Success"
    assert seen["timeout"] == 42
    assert nb.http_session.timeout == 5


@pytest.mark.parametrize(
    "message,expected",
    [
        ("connection timed out", "Error: Timeout"),
        ("401 Client Error", "Error: Auth failed"),
        ("Unauthorized", "Error: Auth failed"),
        ("connection refused", "Error: Connection refused"),
        ("certificate verify failed", "Error: SSL error"),
        ("SSL handshake failed", "Error: SSL error"),
        (
            "HTTPSConnectionPool(host='nb', port=443): "
            "Max retries exceeded (Caused by SSLError(...))",
            "Error: SSL error",
        ),
    ],
)
def test_check_netbox_instance_error_classification(message, expected):
    cmd = _make_sync()
    nb = MagicMock()
    nb.http_session = _FakeSession()
    nb.status.side_effect = Exception(message)

    assert cmd._check_netbox_instance(nb) == expected


def test_check_netbox_instance_truncates_long_error_message():
    cmd = _make_sync()
    nb = MagicMock()
    nb.http_session = _FakeSession()
    nb.status.side_effect = Exception("x" * 60)

    assert cmd._check_netbox_instance(nb) == f"Error: {'x' * 50}"


def test_check_netbox_instance_without_http_session_success():
    assert _make_sync()._check_netbox_instance(_BareNb()) == "Success"


def test_check_netbox_instance_without_http_session_classifies_error():
    result = _make_sync()._check_netbox_instance(_BareNb(Exception("boom")))
    assert result == "Error: boom"


# --- Sync._check_netbox_connectivity ---


def test_check_netbox_connectivity_not_configured():
    cmd = _make_sync()
    with patch("osism.commands.netbox.requests.get") as mock_get:
        result = cmd._check_netbox_connectivity(None, "url", "token", False)

    assert result == "Error: Not configured"
    mock_get.assert_not_called()


@pytest.mark.parametrize(
    "exc,expected",
    [
        (requests.exceptions.Timeout(), "Error: Timeout"),
        (requests.exceptions.ConnectionError(), "Error: Connection refused"),
        (requests.exceptions.SSLError(), "Error: SSL error"),
    ],
    ids=["timeout", "connection", "ssl"],
)
def test_check_netbox_connectivity_stage1_errors(exc, expected):
    cmd = _make_sync()
    nb = MagicMock()
    nb.base_url = "https://netbox.example/api"

    with patch("osism.commands.netbox.requests.get", side_effect=exc):
        result = cmd._check_netbox_connectivity(nb, "url", "token", False)

    assert result == expected
    nb.status.assert_not_called()


def test_check_netbox_connectivity_stage1_generic_error_truncated():
    cmd = _make_sync()
    nb = MagicMock()
    nb.base_url = "https://netbox.example/api"

    with patch("osism.commands.netbox.requests.get", side_effect=Exception("y" * 70)):
        result = cmd._check_netbox_connectivity(nb, "url", "token", False)

    assert result == f"Error: {'y' * 50}"
    nb.status.assert_not_called()


@pytest.mark.parametrize("ignore_ssl_errors", [True, False])
def test_check_netbox_connectivity_success_passes_verify(ignore_ssl_errors):
    cmd = _make_sync()
    nb = MagicMock()
    nb.base_url = "https://netbox.example/api"
    nb.http_session = _FakeSession()

    with patch("osism.commands.netbox.requests.get") as mock_get:
        result = cmd._check_netbox_connectivity(
            nb, "url", "token", ignore_ssl_errors, timeout=7
        )

    assert result == "Success"
    mock_get.assert_called_once_with(
        "https://netbox.example/api", timeout=7, verify=not ignore_ssl_errors
    )


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Request timed out", "Error: Timeout"),
        ("401 Unauthorized", "Error: Auth failed"),
    ],
)
def test_check_netbox_connectivity_stage2_classification(message, expected):
    cmd = _make_sync()
    nb = MagicMock()
    nb.base_url = "https://netbox.example/api"
    nb.http_session = _FakeSession()
    nb.status.side_effect = Exception(message)

    with patch("osism.commands.netbox.requests.get"):
        result = cmd._check_netbox_connectivity(nb, "url", "token", False)

    assert result == expected


# --- Sync._build_netbox_table ---


def test_build_netbox_table_empty(monkeypatch):
    cmd = _make_sync()
    monkeypatch.setattr(netbox.settings, "NETBOX_URL", None)

    with patch.dict("osism.utils.__dict__", {"secondary_nb_list": []}):
        table, headers = cmd._build_netbox_table()

    assert table == []
    assert headers == ["Name", "URL", "Site"]


def test_build_netbox_table_primary_row_first(monkeypatch):
    cmd = _make_sync()
    monkeypatch.setattr(netbox.settings, "NETBOX_URL", "https://primary.example")
    secondary = SimpleNamespace(
        base_url="https://sec.example", netbox_name="sec1", netbox_site="site1"
    )

    with patch.dict("osism.utils.__dict__", {"secondary_nb_list": [secondary]}):
        table, headers = cmd._build_netbox_table()

    assert headers == ["Name", "URL", "Site"]
    assert table[0] == ["primary", "https://primary.example", "N/A"]
    assert table[1] == ["sec1", "https://sec.example", "site1"]


def test_build_netbox_table_secondary_without_name_and_site(monkeypatch):
    cmd = _make_sync()
    monkeypatch.setattr(netbox.settings, "NETBOX_URL", None)

    class _UrlOnly:
        base_url = "https://sec.example"

    with patch.dict("osism.utils.__dict__", {"secondary_nb_list": [_UrlOnly()]}):
        table, _ = cmd._build_netbox_table()

    assert table == [["N/A", "https://sec.example", "N/A"]]


def test_build_netbox_table_check_connectivity(monkeypatch):
    cmd = _make_sync()
    monkeypatch.setattr(netbox.settings, "NETBOX_URL", "https://primary.example")
    monkeypatch.setattr(netbox.settings, "NETBOX_TOKEN", "token123")
    monkeypatch.setattr(netbox.settings, "IGNORE_SSL_ERRORS", True)
    cmd._check_netbox_connectivity = MagicMock(return_value="Success")
    cmd._check_netbox_instance = MagicMock(return_value="Error: Timeout")

    fake_nb = MagicMock()
    secondary = SimpleNamespace(
        base_url="https://sec.example", netbox_name="sec1", netbox_site="site1"
    )

    with patch.dict(
        "osism.utils.__dict__", {"nb": fake_nb, "secondary_nb_list": [secondary]}
    ):
        table, headers = cmd._build_netbox_table(check_connectivity=True, timeout=9)

    assert headers == ["Name", "URL", "Site", "Status"]
    cmd._check_netbox_connectivity.assert_called_once_with(
        fake_nb, "https://primary.example", "token123", True, 9
    )
    cmd._check_netbox_instance.assert_called_once_with(secondary, 9)
    assert table[0][-1] == "Success"
    assert table[1][-1] == "Error: Timeout"


# --- Sync.take_action ---


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


def test_sync_list_prints_table_without_scheduling(capsys):
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["--list"])
    cmd._build_netbox_table = MagicMock(
        return_value=([["primary", "https://x", "N/A"]], ["Name", "URL", "Site"])
    )

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_netbox.delay"
    ) as mock_delay:
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_delay.assert_not_called()
    cmd._build_netbox_table.assert_called_once_with(check_connectivity=False)
    out = capsys.readouterr().out
    assert "primary" in out
    assert "https://x" in out


def test_sync_list_empty_warns_and_prints_nothing(capsys, loguru_logs):
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["--list"])
    cmd._build_netbox_table = MagicMock(return_value=([], ["Name", "URL", "Site"]))

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"):
        result = cmd.take_action(parsed_args)

    assert result is None
    assert capsys.readouterr().out == ""
    assert any(
        "No NetBox instances configured" in record["message"] for record in loguru_logs
    )


def test_sync_check_uses_connectivity_table(capsys):
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["--check"])
    cmd._build_netbox_table = MagicMock(
        return_value=(
            [["primary", "https://x", "N/A", "Success"]],
            ["Name", "URL", "Site", "Status"],
        )
    )

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"):
        result = cmd.take_action(parsed_args)

    assert result is None
    cmd._build_netbox_table.assert_called_once_with(check_connectivity=True, timeout=20)
    assert "Success" in capsys.readouterr().out


def test_sync_no_wait_schedules_without_fetch():
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["--no-wait"])

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_netbox.delay", return_value=MagicMock()
    ) as mock_delay, patch(
        "osism.commands.netbox.utils.fetch_task_output"
    ) as mock_fetch:
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_delay.assert_called_once_with(node_name=None, netbox_filter=None)
    mock_fetch.assert_not_called()


def test_sync_forwards_filter():
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["--filter", "foo", "--no-wait"])

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_netbox.delay", return_value=MagicMock()
    ) as mock_delay:
        cmd.take_action(parsed_args)

    mock_delay.assert_called_once_with(node_name=None, netbox_filter="foo")


def test_sync_wait_returns_fetch_result():
    cmd = _make_sync()
    parsed_args = cmd.get_parser("test").parse_args(["node1", "--task-timeout", "60"])

    task = MagicMock()
    task.id = "task-id"
    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.conductor.sync_netbox.delay", return_value=task
    ) as mock_delay, patch(
        "osism.commands.netbox.utils.fetch_task_output", return_value=0
    ) as mock_fetch:
        result = cmd.take_action(parsed_args)

    assert result == 0
    mock_delay.assert_called_once_with(node_name="node1", netbox_filter=None)
    mock_fetch.assert_called_once_with("task-id", timeout=60)


# --- Manage.take_action ---


def _run_manage(argv):
    cmd = netbox.Manage(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(argv)

    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.netbox.manage"
    ) as mock_manage, patch(
        "osism.tasks.handle_task", return_value=0
    ) as mock_handle_task:
        result = cmd.take_action(parsed_args)

    return result, mock_manage, mock_handle_task


def test_manage_default_arguments():
    result, mock_manage, mock_handle_task = _run_manage([])

    mock_manage.si.assert_called_once_with(
        "run", "--wait", "--no-skipdtl", "--no-skipmtl", "--no-skipres"
    )
    task = mock_manage.si.return_value.apply_async.return_value
    mock_handle_task.assert_called_once_with(task, True, format="script", timeout=3600)
    assert result == 0


def test_manage_no_netbox_wait():
    _, mock_manage, _ = _run_manage(["--no-netbox-wait"])

    mock_manage.si.assert_called_once_with(
        "run", "--no-wait", "--no-skipdtl", "--no-skipmtl", "--no-skipres"
    )


def test_manage_parallel_and_limit():
    _, mock_manage, _ = _run_manage(["--parallel", "4", "--limit", "foo"])

    mock_manage.si.assert_called_once_with(
        "run",
        "--wait",
        "--parallel",
        "4",
        "--limit",
        "foo",
        "--no-skipdtl",
        "--no-skipmtl",
        "--no-skipres",
    )


def test_manage_skip_flags():
    _, mock_manage, _ = _run_manage(["--skipdtl", "--skipmtl", "--skipres"])

    mock_manage.si.assert_called_once_with(
        "run", "--wait", "--skipdtl", "--skipmtl", "--skipres"
    )


def test_manage_no_wait_passed_to_handle_task():
    _, mock_manage, mock_handle_task = _run_manage(["--no-wait"])

    task = mock_manage.si.return_value.apply_async.return_value
    mock_handle_task.assert_called_once_with(task, False, format="script", timeout=3600)


# --- Versions.take_action ---


def test_versions_prints_task_result(capsys):
    cmd = netbox.Versions(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    task = MagicMock()
    task.get.return_value = "netbox 4.1"
    with patch("osism.commands.netbox.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.netbox.ping"
    ) as mock_ping:
        mock_ping.delay.return_value = task
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_ping.delay.assert_called_once_with()
    task.wait.assert_called_once_with(timeout=None, interval=0.5)
    assert "netbox 4.1" in capsys.readouterr().out


# --- Console.take_action ---


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


def test_console_existing_config_runs_nbcli_directly():
    cmd = netbox.Console(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["info", "device"])

    with patch("osism.commands.netbox.os.path.exists", return_value=True), patch(
        "osism.commands.netbox.os.path.expanduser", return_value="/fakehome"
    ), patch("osism.commands.netbox.os.remove") as mock_remove, patch(
        "osism.commands.netbox.subprocess.call"
    ) as mock_call:
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_remove.assert_not_called()
    mock_call.assert_called_once_with("/usr/local/bin/nbcli info device", shell=True)


def test_console_initializes_config_when_missing():
    cmd = netbox.Console(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["shell"])

    m_open = mock_open(read_data="secrettoken\n")
    with patch("osism.commands.netbox.os.path.exists", return_value=False), patch(
        "osism.commands.netbox.os.path.expanduser", return_value="/fakehome"
    ), patch("osism.commands.netbox.os.mkdir") as mock_mkdir, patch(
        "osism.commands.netbox.os.environ.get", return_value="https://netbox.example"
    ), patch(
        "builtins.open", m_open
    ), patch(
        "osism.commands.netbox.os.remove"
    ) as mock_remove, patch(
        "osism.commands.netbox.subprocess.call"
    ) as mock_call, patch(
        "osism.commands.netbox.yaml.dump"
    ) as mock_yaml_dump:
        result = cmd.take_action(parsed_args)

    assert result is None
    mock_mkdir.assert_called_once_with("/fakehome/.nbcli")
    assert m_open.call_args_list[0] == call("/run/secrets/NETBOX_TOKEN", "r")
    assert mock_call.call_args_list[0] == call(
        ["/usr/local/bin/nbcli", "init"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    mock_remove.assert_called_once_with("/fakehome/.nbcli/user_config.yml")
    assert m_open.call_args_list[1] == call("/fakehome/.nbcli/user_config.yml", "w")
    config = mock_yaml_dump.call_args[0][0]
    assert config["pynetbox"] == {
        "url": "https://netbox.example",
        "token": "secrettoken",
    }
    assert config["requests"] == {"verify": False}
    assert config["nbcli"] == {"filter_limit": 50}
    assert mock_call.call_args_list[-1] == call(
        "/usr/local/bin/nbcli shell ", shell=True
    )


def test_console_quotes_arguments_with_spaces():
    cmd = netbox.Console(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["filter", "name foo", "bar"])

    with patch("osism.commands.netbox.os.path.exists", return_value=True), patch(
        "osism.commands.netbox.os.path.expanduser", return_value="/fakehome"
    ), patch("osism.commands.netbox.subprocess.call") as mock_call:
        cmd.take_action(parsed_args)

    mock_call.assert_called_once_with(
        "/usr/local/bin/nbcli filter 'name foo' bar", shell=True
    )


# --- Dump.take_action ---


def _filter_dispatch(mapping):
    """Route ``devices.filter(...)`` calls by the filter keyword used."""

    def _filter(**kwargs):
        for key, value in mapping.items():
            if key in kwargs:
                return value
        return []

    return _filter


def test_dump_returns_nonzero_when_netbox_not_configured():
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["somehost"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_dump_returns_nonzero_when_device_not_found():
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["somehost"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = []

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_dump_selects_exact_name_match(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [
        _FakeDevice("sw1-old"),
        _FakeDevice("sw1"),
    ]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result is None
    fake_nb.dcim.devices.filter.assert_called_once_with(name="sw1")
    assert "sw1" in capsys.readouterr().out


def test_dump_falls_back_through_custom_field_lookups(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["ext-host"])

    # The alternative_name stage returns a device whose custom field does not
    # match exactly, so the lookup must continue to inventory_hostname.
    wrong = _FakeDevice("other", custom_fields={"alternative_name": "different"})
    right = _FakeDevice("sw2", custom_fields={"inventory_hostname": "ext-host"})
    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.side_effect = _filter_dispatch(
        {
            "name": [],
            "cf_alternative_name": [wrong],
            "cf_inventory_hostname": [right],
        }
    )

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result is None
    assert fake_nb.dcim.devices.filter.call_count == 3
    out = capsys.readouterr().out
    assert "sw2" in out
    assert "Inventory Hostname" in out
    assert "ext-host" in out


def test_dump_prints_device_details(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    device = _FakeDevice(
        "sw1",
        device_type="Accton AS7326",
        role="leaf",
        site="site1",
        status="Active",
        oob_ip=SimpleNamespace(address="192.0.2.1/24"),
        primary_ip4=SimpleNamespace(address="192.0.2.2/24"),
        primary_ip6=SimpleNamespace(address="2001:db8::1/64"),
    )
    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [device]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    for value in [
        "Accton AS7326",
        "leaf",
        "site1",
        "Active",
        "192.0.2.1/24",
        "192.0.2.2/24",
        "2001:db8::1/64",
    ]:
        assert value in out


def test_dump_prints_na_for_missing_details(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [_FakeDevice("sw1")]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    # Device Type, Device Role, Site, Status, OOB IP, Primary IPv4, Primary IPv6
    assert out.count("N/A") == 7


def test_dump_formats_yaml_custom_fields(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    device = _FakeDevice(
        "sw1",
        custom_fields={
            "sonic_parameters": "hwsku: Accton-AS7326-56X",
            "netplan_parameters": {"dummy0": {"addresses": ["192.0.2.1/32"]}},
            "frr_parameters": "a: [1, 2",
        },
    )
    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [device]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result is None
    out = capsys.readouterr().out
    # String value parsed and re-dumped as YAML
    assert "hwsku: Accton-AS7326-56X" in out
    # Dict value dumped directly
    assert "dummy0:" in out
    assert "- 192.0.2.1/32" in out
    # Invalid YAML falls back to the raw string representation
    assert "a: [1, 2" in out


def test_dump_appends_hostname_custom_fields(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1"])

    device = _FakeDevice(
        "sw1",
        custom_fields={
            "alternative_name": "alt1",
            "inventory_hostname": "inv1",
            "external_hostname": "ext1",
        },
    )
    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [device]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert "Alternative Name" in out
    assert "alt1" in out
    assert "Inventory Hostname" in out
    assert "inv1" in out
    assert "External Hostname" in out
    assert "ext1" in out


def test_dump_field_filter_matches_case_insensitive(capsys):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "IP"])

    device = _FakeDevice(
        "sw1",
        site="site1",
        oob_ip=SimpleNamespace(address="192.0.2.1/24"),
    )
    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [device]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result is None
    out = capsys.readouterr().out
    assert "Out-of-band IP" in out
    assert "Primary IPv4" in out
    assert "Primary IPv6" in out
    assert "Site" not in out
    assert "Device Type" not in out


def test_dump_field_filter_without_match_warns(capsys, loguru_logs):
    cmd = _make_dump()
    parsed_args = cmd.get_parser("test").parse_args(["sw1", "zzz"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.filter.return_value = [_FakeDevice("sw1")]

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        result = cmd.take_action(parsed_args)

    assert result is None
    assert capsys.readouterr().out == ""
    assert any(
        "No fields matching 'zzz' found" in record["message"] for record in loguru_logs
    )
