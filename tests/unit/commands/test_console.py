# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism console`` command and its resolution helpers.

The module-level helpers resolve a target host step by step: DNS first
(``resolve_hostname_to_ip``), then the Netbox primary IPv4 address
(``get_primary_ipv4_from_netbox``), falling back to the original hostname
(``resolve_host_with_fallback``). ``get_hosts_from_group`` expands an
inventory group into a sorted host list and swallows any resolution error,
and ``select_host_from_list`` runs the interactive host picker.

``Run.take_action`` routes on the host syntax (``host/`` container prompt,
``host/container`` container console, ``.host`` ansible console, ``:group``
clush) and otherwise opens an SSH session, expanding inventory groups and
resolving the host first. The tests pin the constructed command lines,
including shell quoting and the ``UserKnownHostsFile`` SSH option.
"""

import json
import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from osism import settings
from osism.commands import console
from osism.commands.console import KNOWN_HOSTS_PATH

from ._helpers import parse_args

# --- resolve_hostname_to_ip ---


def test_resolve_hostname_to_ip_returns_ip_on_success():
    with patch("osism.commands.console.socket.gethostbyname", return_value="192.0.2.1"):
        assert console.resolve_hostname_to_ip("testhost") == "192.0.2.1"


def test_resolve_hostname_to_ip_returns_none_on_dns_failure():
    with patch(
        "osism.commands.console.socket.gethostbyname",
        side_effect=socket.gaierror("Name or service not known"),
    ):
        assert console.resolve_hostname_to_ip("testhost") is None


# --- get_primary_ipv4_from_netbox ---


def test_get_primary_ipv4_returns_none_without_netbox_connection():
    with patch("osism.commands.console.utils.nb", None):
        assert console.get_primary_ipv4_from_netbox("testhost") is None


def test_get_primary_ipv4_strips_prefix_from_netbox_address():
    device = MagicMock()
    device.primary_ip4.address = "10.0.0.1/24"
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    with patch("osism.commands.console.utils.nb", nb):
        assert console.get_primary_ipv4_from_netbox("testhost") == "10.0.0.1"

    nb.dcim.devices.get.assert_called_once_with(name="testhost")


def test_get_primary_ipv4_returns_none_when_device_missing():
    nb = MagicMock()
    nb.dcim.devices.get.return_value = None

    with patch("osism.commands.console.utils.nb", nb):
        assert console.get_primary_ipv4_from_netbox("testhost") is None


def test_get_primary_ipv4_returns_none_without_primary_ip():
    device = MagicMock()
    device.primary_ip4 = None
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    with patch("osism.commands.console.utils.nb", nb):
        assert console.get_primary_ipv4_from_netbox("testhost") is None


def test_get_primary_ipv4_warns_and_returns_none_on_netbox_error(loguru_logs):
    nb = MagicMock()
    nb.dcim.devices.get.side_effect = RuntimeError("connection refused")

    with patch("osism.commands.console.utils.nb", nb):
        assert console.get_primary_ipv4_from_netbox("testhost") is None

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("Error querying Netbox for testhost" in m for m in warnings)


# --- resolve_host_with_fallback ---


def test_resolve_host_with_fallback_prefers_dns_result():
    with patch(
        "osism.commands.console.resolve_hostname_to_ip", return_value="192.0.2.1"
    ), patch("osism.commands.console.get_primary_ipv4_from_netbox") as mock_netbox:
        assert console.resolve_host_with_fallback("testhost") == "192.0.2.1"

    mock_netbox.assert_not_called()


def test_resolve_host_with_fallback_uses_netbox_when_dns_fails():
    with patch(
        "osism.commands.console.resolve_hostname_to_ip", return_value=None
    ), patch(
        "osism.commands.console.get_primary_ipv4_from_netbox", return_value="10.0.0.1"
    ):
        assert console.resolve_host_with_fallback("testhost") == "10.0.0.1"


def test_resolve_host_with_fallback_returns_hostname_when_all_fail(loguru_logs):
    with patch(
        "osism.commands.console.resolve_hostname_to_ip", return_value=None
    ), patch("osism.commands.console.get_primary_ipv4_from_netbox", return_value=None):
        assert console.resolve_host_with_fallback("testhost") == "testhost"

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("Could not resolve testhost via DNS or Netbox" in m for m in warnings)


# --- get_hosts_from_group ---


def test_get_hosts_from_group_returns_sorted_hosts():
    inventory = {"_meta": {"hostvars": {}}}

    with patch(
        "osism.commands.console.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.console.subprocess.check_output",
        return_value=json.dumps(inventory).encode(),
    ) as mock_check_output, patch(
        "osism.commands.console.get_hosts_from_inventory",
        return_value=["ctl002", "ctl001"],
    ):
        assert console.get_hosts_from_group("ctl") == ["ctl001", "ctl002"]

    mock_check_output.assert_called_once_with(
        [
            "ansible-inventory",
            "-i",
            "/ansible/inventory/hosts.yml",
            "--list",
            "--limit",
            "ctl",
        ],
        stderr=subprocess.DEVNULL,
    )


def test_get_hosts_from_group_returns_empty_list_on_error():
    with patch(
        "osism.commands.console.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.console.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ansible-inventory"),
    ):
        assert console.get_hosts_from_group("ctl") == []


# --- select_host_from_list ---


def test_select_host_from_list_returns_chosen_host(capsys):
    with patch("osism.commands.console.prompt", side_effect=["2"]):
        assert console.select_host_from_list(["host1", "host2"]) == "host2"

    captured = capsys.readouterr()
    assert "Group contains 2 hosts" in captured.out
    assert "1) host1" in captured.out


@pytest.mark.parametrize("answer", ["q", "quit", "exit"])
def test_select_host_from_list_returns_none_on_cancel(answer):
    with patch("osism.commands.console.prompt", side_effect=[answer]):
        assert console.select_host_from_list(["host1", "host2"]) is None


def test_select_host_from_list_retries_on_non_numeric_input(capsys):
    with patch(
        "osism.commands.console.prompt", side_effect=["abc", "1"]
    ) as mock_prompt:
        assert console.select_host_from_list(["host1", "host2"]) == "host1"

    assert mock_prompt.call_count == 2
    assert "Please enter a number between 1 and 2" in capsys.readouterr().out


def test_select_host_from_list_retries_on_out_of_range_input():
    with patch(
        "osism.commands.console.prompt", side_effect=["0", "3", "2"]
    ) as mock_prompt:
        assert console.select_host_from_list(["host1", "host2"]) == "host2"

    assert mock_prompt.call_count == 3


# --- Run.take_action ---


def _invoke_run(
    args,
    *,
    known_hosts=True,
    group_hosts=None,
    selected=None,
    resolved=None,
    prompts=None,
):
    cmd, parsed_args = parse_args(console.Run, args)
    resolved_map = resolved or {}

    with patch(
        "osism.commands.console.subprocess.call", return_value=0
    ) as mock_call, patch(
        "osism.commands.console.ensure_known_hosts_file", return_value=known_hosts
    ), patch(
        "osism.commands.console.get_hosts_from_group", return_value=group_hosts or []
    ), patch(
        "osism.commands.console.resolve_host_with_fallback",
        side_effect=lambda host: resolved_map.get(host, host),
    ) as mock_resolve, patch(
        "osism.commands.console.select_host_from_list", return_value=selected
    ) as mock_select, patch(
        "osism.commands.console.prompt", side_effect=prompts or ["exit"]
    ) as mock_prompt:
        result = cmd.take_action(parsed_args)

    return result, {
        "call": mock_call,
        "resolve": mock_resolve,
        "select": mock_select,
        "prompt": mock_prompt,
    }


def test_run_trailing_slash_routes_to_container_prompt():
    _, mocks = _invoke_run(["ctl001/"], prompts=["ps -a", "exit"])

    mocks["prompt"].assert_called_with("ctl001>>> ")
    mocks["resolve"].assert_called_once_with("ctl001")
    mocks["call"].assert_called_once()
    call_args = mocks["call"].call_args[0][0]
    assert call_args[-1] == "docker 'ps -a'"
    assert f"{settings.OPERATOR_USER}@ctl001" in call_args


def test_run_container_prompt_exit_immediately_makes_no_ssh_call():
    _, mocks = _invoke_run(["ctl001/"], prompts=["exit"])

    mocks["call"].assert_not_called()


def test_run_slash_routes_to_container_console():
    _, mocks = _invoke_run(["ctl001/rabbitmq"])

    mocks["prompt"].assert_not_called()
    mocks["resolve"].assert_called_once_with("ctl001")
    call_args = mocks["call"].call_args[0][0]
    assert call_args[-1] == "docker exec -it rabbitmq bash"
    assert "RequestTTY=force" in call_args
    assert f"UserKnownHostsFile={KNOWN_HOSTS_PATH}" in call_args
    assert f"{settings.OPERATOR_USER}@ctl001" in call_args


def test_run_container_console_shell_quotes_container_name():
    _, mocks = _invoke_run(["ctl001/rabbit mq"])

    call_args = mocks["call"].call_args[0][0]
    assert call_args[-1] == "docker exec -it 'rabbit mq' bash"


def test_run_leading_dot_routes_to_ansible_console():
    _, mocks = _invoke_run([".ctl001"])

    mocks["call"].assert_called_once_with(["/run-ansible-console.sh", "ctl001"])


def test_run_leading_colon_routes_to_clush():
    _, mocks = _invoke_run([":ctl"])

    mocks["call"].assert_called_once_with(
        ["/usr/local/bin/clush", "-l", settings.OPERATOR_USER, "-g", "ctl"]
    )


def test_run_ssh_uses_single_host_from_group():
    _, mocks = _invoke_run(["ctl"], group_hosts=["ctl001"])

    mocks["select"].assert_not_called()
    mocks["resolve"].assert_called_once_with("ctl001")
    assert mocks["call"].call_args[0][0][-1] == f"{settings.OPERATOR_USER}@ctl001"


def test_run_ssh_prompts_selection_for_multi_host_group():
    _, mocks = _invoke_run(["ctl"], group_hosts=["ctl001", "ctl002"], selected="ctl002")

    mocks["select"].assert_called_once_with(["ctl001", "ctl002"])
    mocks["resolve"].assert_called_once_with("ctl002")
    assert mocks["call"].call_args[0][0][-1] == f"{settings.OPERATOR_USER}@ctl002"


def test_run_ssh_cancelled_selection_skips_ssh_call():
    result, mocks = _invoke_run(
        ["ctl"], group_hosts=["ctl001", "ctl002"], selected=None
    )

    assert result is None
    mocks["resolve"].assert_not_called()
    mocks["call"].assert_not_called()


def test_run_ssh_call_uses_resolved_host_and_known_hosts_file():
    _, mocks = _invoke_run(["testhost"], resolved={"testhost": "192.0.2.1"})

    mocks["call"].assert_called_once_with(
        [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            f"{settings.OPERATOR_USER}@192.0.2.1",
        ]
    )


def test_run_warns_but_continues_when_known_hosts_init_fails(loguru_logs):
    _, mocks = _invoke_run(["testhost"], known_hosts=False)

    mocks["call"].assert_called_once()
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any(f"Could not initialize {KNOWN_HOSTS_PATH}" in m for m in warnings)
