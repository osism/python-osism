# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism report`` commands.

The first group of tests covers the exit-code contract when loading the
Ansible inventory: a command must return a non-zero exit status when the
inventory query itself cannot be run (a non-zero ansible-inventory return
code, or a timeout), but must keep returning success when the query runs fine
and simply yields no hosts.

The per-command tests then drive the SSH fan-out with mocked
``subprocess.run`` results: parsed rows must land in the printed table with
the documented defaults, while hosts whose output cannot be read or parsed
must end up in the failure summary instead of the table.
"""

import json
import subprocess
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import report

COMMANDS = [report.Memory, report.Lldp, report.Bgp, report.Status]

# Status requires a positional "type"; the others take no required args.
ARGS = {report.Status: ["bootstrap"]}


def _make(cls):
    cmd = cls(MagicMock(), MagicMock())
    return cmd, cmd.get_parser("test").parse_args(ARGS.get(cls, []))


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_nonzero_when_inventory_load_fails(cls):
    cmd, parsed_args = _make(cls)
    failed = MagicMock()
    failed.returncode = 1

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run", return_value=failed
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_nonzero_when_inventory_load_times_out(cls):
    cmd, parsed_args = _make(cls)

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run",
        side_effect=subprocess.TimeoutExpired("ansible-inventory", 30),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_success_when_inventory_is_empty(cls):
    cmd, parsed_args = _make(cls)
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{}"

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run", return_value=ok
    ), patch(
        "osism.commands.report.get_hosts_from_inventory", return_value=[]
    ):
        result = cmd.take_action(parsed_args)

    assert not result


# --- per-host SSH fan-out helpers ---


def _proc(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@contextmanager
def _ssh_env(hosts, ssh_results):
    """Patch the inventory pipeline so ``take_action`` iterates ``hosts``.

    ``subprocess.run`` first serves the ansible-inventory call, then hands out
    ``ssh_results`` in order; exception instances in the list are raised.
    """
    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.get_hosts_from_inventory", return_value=hosts
    ), patch(
        "osism.commands.report.resolve_host_with_fallback",
        side_effect=lambda host: host,
    ), patch(
        "osism.commands.report.subprocess.run",
        side_effect=[_proc(stdout="{}"), *ssh_results],
    ):
        yield


# --- Memory ---


def test_memory_sums_memory_over_hosts(capsys):
    cmd, parsed_args = _make(report.Memory)

    with _ssh_env(
        ["host-a", "host-b"],
        [
            _proc(stdout="64\n"),
            _proc(stdout="uuid-a\n"),
            _proc(stdout="128\n"),
            _proc(stdout="uuid-b\n"),
        ],
    ):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "uuid-a" in out
    assert "uuid-b" in out
    assert "Hosts: 2" in out
    assert "Memory: 192 GB" in out


def test_memory_reports_uuid_as_na_when_unreadable(capsys):
    cmd, parsed_args = _make(report.Memory)

    with _ssh_env(["host-a"], [_proc(stdout="64\n"), _proc(returncode=1)]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "n/a" in out
    assert "Hosts: 1" in out
    assert "Memory: 64 GB" in out


def test_memory_skips_host_when_memory_query_fails(capsys, loguru_logs):
    cmd, parsed_args = _make(report.Memory)

    with _ssh_env(
        ["host-a", "host-b"],
        [
            _proc(returncode=1, stderr="ssh: connection refused"),
            _proc(stdout="32\n"),
            _proc(stdout="uuid-b\n"),
        ],
    ):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "Hosts: 1" in out
    assert "Memory: 32 GB" in out
    messages = [record["message"] for record in loguru_logs]
    assert any("Failed to get memory info from host-a" in m for m in messages)
    assert any("Failed to query 1 host(s): host-a" in m for m in messages)


def test_memory_marks_host_failed_on_timeout(loguru_logs):
    cmd, parsed_args = _make(report.Memory)

    with _ssh_env(["host-a"], [subprocess.TimeoutExpired("ssh", 30)]):
        result = cmd.take_action(parsed_args)

    assert not result
    messages = [record["message"] for record in loguru_logs]
    assert any("Timeout connecting to host-a." in m for m in messages)
    assert any("Failed to query 1 host(s): host-a" in m for m in messages)


def test_memory_marks_host_failed_on_unparsable_output(loguru_logs):
    cmd, parsed_args = _make(report.Memory)

    with _ssh_env(["host-a"], [_proc(stdout="lots\n"), _proc(stdout="uuid-a\n")]):
        result = cmd.take_action(parsed_args)

    assert not result
    messages = [record["message"] for record in loguru_logs]
    assert any("Could not parse memory info from host-a." in m for m in messages)
    assert any("Failed to query 1 host(s): host-a" in m for m in messages)


# --- Lldp ---

IFACE_ETH0 = {
    "chassis": {"switch-1": {"id": {"value": "aa:bb:cc"}}},
    "port": {"id": {"value": "Ethernet10"}, "descr": "downlink"},
    "age": "12 days",
}

IFACE_ETH1 = {
    "chassis": {"switch-2": {"id": {"value": "dd:ee:ff"}}},
    "port": {"id": {"value": "Ethernet20"}, "descr": "uplink"},
    "age": "3 days",
}


def _lldp_json(interface):
    return json.dumps({"lldp": {"interface": interface}})


def test_lldp_normalizes_single_interface_dict(capsys):
    cmd, parsed_args = _make(report.Lldp)

    with _ssh_env(["host-a"], [_proc(stdout=_lldp_json({"eth0": IFACE_ETH0}))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "eth0" in out
    assert "switch-1" in out
    assert "Ethernet10" in out
    assert "Neighbors: 1" in out


def test_lldp_handles_interface_list(capsys):
    cmd, parsed_args = _make(report.Lldp)
    interfaces = [{"eth0": IFACE_ETH0}, {"eth1": IFACE_ETH1}]

    with _ssh_env(["host-a"], [_proc(stdout=_lldp_json(interfaces))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "eth0" in out
    assert "eth1" in out
    assert "switch-2" in out
    assert "Ethernet20" in out
    assert "Neighbors: 2" in out


def test_lldp_defaults_missing_neighbor_details(capsys):
    cmd, parsed_args = _make(report.Lldp)

    with _ssh_env(["host-a"], [_proc(stdout=_lldp_json({"eth0": {}}))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "Neighbors: 1" in out
    # Remote switch, remote port and age all fall back to "n/a".
    assert out.count("n/a") >= 3


def test_lldp_marks_host_failed_on_invalid_json(loguru_logs):
    cmd, parsed_args = _make(report.Lldp)

    with _ssh_env(["host-a"], [_proc(stdout="not json")]):
        result = cmd.take_action(parsed_args)

    assert not result
    messages = [record["message"] for record in loguru_logs]
    assert any("Could not parse LLDP info from host-a." in m for m in messages)
    assert any("Failed to query 1 host(s): host-a" in m for m in messages)


# --- Bgp ---


def test_bgp_afi_filter_matches_case_insensitively(capsys):
    cmd = report.Bgp(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--afi", "ipv4Unicast"])
    bgp_data = {
        # Deliberately differs in case from the parsed choice "ipv4Unicast".
        "IPv4Unicast": {
            "peers": {"10.0.0.1": {"hostname": "spine-1", "state": "Established"}}
        },
        "l2VpnEvpn": {
            "peers": {"10.0.0.2": {"hostname": "spine-2", "state": "Established"}}
        },
    }

    with _ssh_env(["host-a"], [_proc(stdout=json.dumps(bgp_data))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "spine-1" in out
    assert "spine-2" not in out
    assert "Sessions: 1" in out


def test_bgp_defaults_missing_peer_fields(capsys):
    cmd, parsed_args = _make(report.Bgp)
    bgp_data = {"ipv4Unicast": {"peers": {"10.0.0.1": {}}}}

    with _ssh_env(["host-a"], [_proc(stdout=json.dumps(bgp_data))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "10.0.0.1" in out
    assert "n/a" in out
    assert "Sessions: 1" in out
    assert "Established: 0/1" in out


def test_bgp_counts_established_sessions(capsys):
    cmd, parsed_args = _make(report.Bgp)
    bgp_data = {
        "ipv4Unicast": {
            "peers": {
                "10.0.0.1": {"state": "Established"},
                "10.0.0.2": {"state": "Active"},
            }
        }
    }

    with _ssh_env(["host-a"], [_proc(stdout=json.dumps(bgp_data))]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "Sessions: 2" in out
    assert "Established: 1/2" in out


# --- Status ---


def test_status_parses_bootstrap_facts(capsys):
    cmd, parsed_args = _make(report.Status)
    fact = "[bootstrap]\nstatus = True\ntimestamp = 2026-01-01T00:00:00Z\n"

    with _ssh_env(["host-a"], [_proc(stdout=fact)]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "host-a" in out
    assert "True" in out
    assert "2026-01-01T00:00:00Z" in out
    assert "Hosts: 1" in out


def test_status_falls_back_when_section_missing(capsys):
    cmd, parsed_args = _make(report.Status)

    with _ssh_env(["host-a"], [_proc(stdout="[other]\nstatus = True\n")]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "False" in out
    assert "n/a" in out
    assert "Hosts: 1" in out


def test_status_reports_unreachable_host_as_false(capsys, loguru_logs):
    cmd, parsed_args = _make(report.Status)

    with _ssh_env(["host-a"], [_proc(returncode=1)]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "host-a" in out
    assert "False" in out
    assert "n/a" in out
    assert "Hosts: 1" in out
    # An unreachable host is reported in the table, not as a query failure.
    assert not any("Failed to query" in record["message"] for record in loguru_logs)


def test_status_filter_drops_non_matching_rows(capsys):
    cmd = report.Status(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["bootstrap", "--status", "True"])
    fact_a = "[bootstrap]\nstatus = True\ntimestamp = t1\n"
    fact_b = "[bootstrap]\nstatus = False\ntimestamp = t2\n"

    with _ssh_env(["host-a", "host-b"], [_proc(stdout=fact_a), _proc(stdout=fact_b)]):
        result = cmd.take_action(parsed_args)

    assert not result
    out = capsys.readouterr().out
    assert "host-a" in out
    assert "host-b" not in out
    assert "Hosts: 1" in out


def test_status_marks_host_failed_on_unparsable_facts(loguru_logs):
    cmd, parsed_args = _make(report.Status)

    with _ssh_env(["host-a"], [_proc(stdout="status True without a section header\n")]):
        result = cmd.take_action(parsed_args)

    assert not result
    messages = [record["message"] for record in loguru_logs]
    assert any("Could not parse bootstrap info from host-a." in m for m in messages)
    assert any("Failed to query 1 host(s): host-a" in m for m in messages)
