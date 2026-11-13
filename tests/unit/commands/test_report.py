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

The hardware reports (``report transceiver``) select devices through NetBox
and collect over SSH in parallel. Their tests replace selection, collection
and the NetBox interface fetch, and feed the collector documents that are
also used as parser fixtures.
"""

import csv
import io
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import report
from osism.utils.hardware.collect import Collection
from osism.utils.hardware.mapping import Endpoint, NetboxInterface
from osism.utils.hardware.selection import Target

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


# ---------------------------------------------------------------------------
# Hardware reports: shared helpers
# ---------------------------------------------------------------------------

HARDWARE_FIXTURES = Path(__file__).parents[1] / "utils" / "hardware" / "fixtures"


def _document(name):
    return json.loads((HARDWARE_FIXTURES / name).read_text())


def _target(name, kind, device_id=None, **device):
    return Target(
        name=name,
        hostname=name,
        kind=kind,
        address="192.0.2.1",
        user="admin" if kind == "switch" else "dragon",
        device_id=device_id,
        device=dict(device, id=device_id, name=name) if device_id else {},
    )


def _netbox_interface(interface_id, device, name, peer=None, **kwargs):
    endpoints = [Endpoint(device=peer[0], interface=peer[1])] if peer else []
    return NetboxInterface(
        id=interface_id,
        device_id=kwargs.pop("device_id", 1),
        device=device,
        name=name,
        has_cable=bool(peer),
        endpoints=endpoints,
        **kwargs,
    )


@contextmanager
def _hardware_env(targets, documents, failed=(), interfaces=None, netbox=True):
    """Replace selection, collection and NetBox for a hardware report.

    Yields the mocks, so that a test can look at what was requested.
    """
    collection = Collection(documents=dict(documents), failed=list(failed))
    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.select_targets", return_value=list(targets)
    ) as select, patch(
        "osism.commands.report.resolve_addresses"
    ) as resolve, patch(
        "osism.commands.report.collect", return_value=collection
    ) as collect, patch(
        "osism.commands.report.fetch_interfaces", return_value=interfaces or {}
    ) as fetch, patch(
        "osism.commands.report.sonic_name_index", return_value={}
    ), patch(
        "osism.utils.nb", new=MagicMock() if netbox else None, create=True
    ):
        yield SimpleNamespace(
            select=select, resolve=resolve, collect=collect, fetch=fetch
        )


def _run(cls, argv, *args, **kwargs):
    """Run a hardware report and return ``(exit code, mocks)``."""
    cmd = cls(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(argv)
    with _hardware_env(*args, **kwargs) as mocks:
        return cmd.take_action(parsed_args), mocks


def _logged(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


# ---------------------------------------------------------------------------
# report transceiver
# ---------------------------------------------------------------------------

NODE = _target("compute-042", "node", device_id=10, serial="NETBOX-SERIAL")
SWITCH = _target(
    "leaf-1a",
    "switch",
    device_id=1,
    site={"slug": "fra1"},
    rack={"name": "R12"},
    role={"slug": "leaf"},
)
DOCUMENTS = {
    "compute-042": _document("linux-mellanox.json"),
    "leaf-1a": _document("sonic-synthetic.json"),
}
INTERFACES = {
    10: [
        _netbox_interface(
            101,
            "compute-042",
            "nic1-port1",
            peer=("leaf-1a", "Eth1/12"),
            device_id=10,
            macs=["b8:ce:f6:aa:00:10"],
        ),
        _netbox_interface(102, "compute-042", "enp59s0f1np1", device_id=10),
        _netbox_interface(103, "compute-042", "bmc", device_id=10, mgmt_only=True),
        _netbox_interface(104, "compute-042", "bond0", device_id=10, type="lag"),
        _netbox_interface(105, "compute-042", "ens9f0", device_id=10),
    ],
    1: [
        _netbox_interface(1, "leaf-1a", "Eth1/1"),
        _netbox_interface(12, "leaf-1a", "Eth1/12", peer=("compute-042", "nic1-port1")),
        _netbox_interface(49, "leaf-1a", "Ethernet48"),
        _netbox_interface(99, "leaf-1a", "eth0", mgmt_only=True),
    ],
}


def _transceiver_json(argv=(), **kwargs):
    kwargs.setdefault("interfaces", INTERFACES)
    stdout = io.StringIO()
    with patch("sys.stdout", stdout):
        result, mocks = _run(
            report.Transceiver,
            ["--format", "json", *argv],
            kwargs.pop("targets", [NODE, SWITCH]),
            kwargs.pop("documents", DOCUMENTS),
            **kwargs,
        )
    return result, json.loads(stdout.getvalue()), mocks


def _by_name(document, device):
    (entry,) = [d for d in document["devices"] if d["name"] == device]
    return entry, {i["name"]: i for i in entry["interfaces"]}


def test_transceiver_reports_every_port_of_nodes_and_switches(capsys):
    result, _ = _run(
        report.Transceiver, [], [NODE, SWITCH], DOCUMENTS, interfaces=INTERFACES
    )

    assert not result
    out = capsys.readouterr().out
    for port in ("eno1", "eno2", "ens1f0np0", "ens1f1np1", "Ethernet0", "Ethernet52"):
        assert f"| {port} " in out
    assert "MCP2M00-A003E30L" in out
    assert "MT27800 Family [ConnectX-5]" in out
    assert "Devices: 2" in out
    assert "Ports: 11" in out
    assert "Modules present: 6" in out


def test_transceiver_collects_with_one_session_per_device():
    _, mocks = _run(report.Transceiver, [], [NODE, SWITCH], DOCUMENTS)

    targets, requests = mocks.collect.call_args.args
    assert [target.name for target in targets] == ["compute-042", "leaf-1a"]
    assert requests["node"].sections == [
        "ports",
        "lldp",
        "ethtool",
        "module",
        "nic",
        "system",
    ]
    assert requests["node"].sudo is True
    assert requests["node"].options == []
    assert requests["switch"].sections == ["ports", "transceiver", "system"]
    assert requests["switch"].sudo is False
    assert mocks.collect.call_args.kwargs == {"parallel": 10, "timeout": 60}
    mocks.resolve.assert_called_once()


def test_transceiver_options_reach_the_collectors():
    _, mocks = _run(
        report.Transceiver,
        [
            "--include-vf",
            "--include-infiniband",
            "--dom",
            "--parallel",
            "3",
            "--timeout",
            "5",
        ],
        [NODE, SWITCH],
        DOCUMENTS,
    )

    requests = mocks.collect.call_args.args[1]
    assert requests["node"].options == ["--include-vf", "--include-infiniband"]
    assert requests["switch"].sections == ["ports", "transceiver", "system", "dom"]
    assert mocks.collect.call_args.kwargs == {"parallel": 3, "timeout": 5.0}


def test_transceiver_node_rows_carry_port_module_and_nic():
    _, document, _ = _transceiver_json()

    device, ports = _by_name(document, "compute-042")
    assert device["kind"] == "node"
    assert device["system_vendor"] == "Supermicro"
    assert device["system_model"] == "SYS-120C-TN10R"
    # The serial read from the node wins over the one in NetBox
    assert device["serial"] == "S123456X0A01234"
    assert "hwsku" not in device

    port = ports["ens1f0np0"]
    assert (port["admin_status"], port["oper_status"], port["speed"]) == (
        "up",
        "up",
        25000,
    )
    assert port["kind"] == "physical"
    assert port["transceiver"]["vendor"] == "Mellanox"
    assert port["transceiver"]["part_number"] == "MCP2M00-A003E30L"
    assert port["transceiver"]["serial"] == "MT2114VS01234"
    assert port["transceiver"]["revision"] == "A3"
    assert port["nic"]["vendor"] == "Mellanox Technologies"
    assert port["nic"]["model"] == "MT27800 Family [ConnectX-5]"
    assert port["nic"]["driver"] == "mlx5_core"
    assert port["nic"]["firmware_version"] == "16.35.2000 (MT_0000000080)"
    assert port["lldp_neighbor"] == "leaf-1a"
    assert port["lldp_neighbor_port"] == "Eth1/12"


def test_transceiver_switch_rows_carry_platform_and_software():
    _, document, _ = _transceiver_json()

    device, ports = _by_name(document, "leaf-1a")
    assert device["kind"] == "switch"
    assert device["site"] == "fra1"
    assert device["rack"] == "R12"
    assert device["platform"] == "x86_64-accton_as7326_56x-r0"
    assert device["hwsku"] == "Accton-AS7326-56X"
    assert device["asic"] == "broadcom"
    assert device["os_version"] == "4.5.0-Enterprise_Base"
    assert device["firmware"]["bios"] == "v41.01.00"
    assert ports["Ethernet48"]["transceiver"]["part_number"] == "0W8H6T"
    assert ports["Ethernet48"]["nic"] is None
    assert "eth0" not in ports


def test_transceiver_ports_without_module_are_rows_not_failures():
    result, document, _ = _transceiver_json()

    _, node = _by_name(document, "compute-042")
    _, switch = _by_name(document, "leaf-1a")
    assert node["eno1"]["transceiver"]["present"] is False
    assert switch["Ethernet52"]["transceiver"]["present"] is False
    assert document["failed"] == []
    assert not result


def test_transceiver_shows_netbox_name_and_mapping_method():
    _, document, _ = _transceiver_json()

    node_device, node = _by_name(document, "compute-042")
    switch_device, switch = _by_name(document, "leaf-1a")

    assert (node["ens1f0np0"]["netbox_name"], node["ens1f0np0"]["mapping"]) == (
        "nic1-port1",
        "mac",
    )
    assert node["ens1f0np0"]["netbox_peer_device"] == "leaf-1a"
    assert node["ens1f0np0"]["netbox_peer_interface"] == "Eth1/12"
    assert (node["ens1f1np1"]["netbox_name"], node["ens1f1np1"]["mapping"]) == (
        "enp59s0f1np1",
        "name",
    )
    assert (node["eno1"]["netbox_name"], node["eno1"]["mapping"]) == (None, "none")

    assert (switch["Ethernet0"]["netbox_name"], switch["Ethernet0"]["mapping"]) == (
        "Eth1/1",
        "alias",
    )
    assert (switch["Ethernet48"]["netbox_name"], switch["Ethernet48"]["mapping"]) == (
        "Ethernet48",
        "name",
    )
    assert switch["Ethernet11"]["netbox_peer_device"] == "compute-042"

    # Documented interfaces without a live port. Management and LAG
    # interfaces have no cage and are not expected to show up.
    assert node_device["unmatched_netbox_interfaces"] == ["ens9f0"]
    assert switch_device["unmatched_netbox_interfaces"] == []


def test_transceiver_uses_the_port_config_translation():
    eth1_1 = INTERFACES[1][0]
    cmd = report.Transceiver(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--format", "json"])
    stdout = io.StringIO()

    with _hardware_env([SWITCH], DOCUMENTS, interfaces=INTERFACES), patch(
        "osism.commands.report.sonic_name_index", return_value={"Ethernet10": eth1_1}
    ) as index, patch("sys.stdout", stdout):
        cmd.take_action(parsed_args)

    _, ports = _by_name(json.loads(stdout.getvalue()), "leaf-1a")
    assert (ports["Ethernet10"]["netbox_name"], ports["Ethernet10"]["mapping"]) == (
        "Eth1/1",
        "port-config",
    )
    assert ports["Ethernet0"]["mapping"] == "none"
    # HWSKU read from the switch, since the NetBox device has none here
    assert index.call_args.args[:3] == (1, "leaf-1a", "Accton-AS7326-56X")


def test_transceiver_warns_about_unmatched_netbox_interfaces(capsys, loguru_logs):
    _run(report.Transceiver, [], [NODE, SWITCH], DOCUMENTS, interfaces=INTERFACES)

    assert _logged(
        loguru_logs,
        "WARNING",
        "compute-042: 1 NetBox interface(s) without a live port: ens9f0",
    )
    assert not _logged(loguru_logs, "WARNING", "leaf-1a: ")


def test_transceiver_failed_device_does_not_abort_the_report(capsys, loguru_logs):
    failed = [{"name": "compute-043", "error": "timeout"}]
    targets = [NODE, _target("compute-043", "node", device_id=11), SWITCH]

    result, _ = _run(report.Transceiver, [], targets, DOCUMENTS, failed=failed)

    assert not result
    out = capsys.readouterr().out
    assert "ens1f0np0" in out and "Ethernet0" in out
    assert "Devices: 2" in out
    assert _logged(
        loguru_logs, "WARNING", "Failed to query 1 device(s): compute-043 (timeout)"
    )


def test_transceiver_strict_turns_a_failed_device_into_exit_code_1():
    failed = [{"name": "compute-043", "error": "timeout"}]

    result, _ = _run(report.Transceiver, ["--strict"], [NODE], DOCUMENTS, failed=failed)
    assert result == 1

    result, _ = _run(report.Transceiver, ["--strict"], [NODE], DOCUMENTS)
    assert not result


def test_transceiver_lists_failed_devices_in_json():
    failed = [{"name": "compute-043", "error": "Permission denied (publickey)."}]

    _, document, _ = _transceiver_json(failed=failed)

    assert document["failed"] == failed
    assert [device["name"] for device in document["devices"]] == [
        "compute-042",
        "leaf-1a",
    ]
    assert document["generated_at"].endswith("Z")


def test_transceiver_unparsable_document_is_a_failed_device(loguru_logs):
    documents = dict(DOCUMENTS, **{"leaf-1a": {"db": "garbage"}})

    result, document, _ = _transceiver_json(documents=documents)

    assert not result
    assert document["failed"] == [{"name": "leaf-1a", "error": "unparsable output"}]
    assert [device["name"] for device in document["devices"]] == ["compute-042"]


def test_transceiver_json_on_stdout_is_one_document(capsys, loguru_logs):
    failed = [{"name": "compute-043", "error": "timeout"}]

    _run(
        report.Transceiver,
        ["--format", "json"],
        [NODE, SWITCH],
        DOCUMENTS,
        failed=failed,
        interfaces=INTERFACES,
    )

    # Warnings go to the log, stdout parses as a whole
    document = json.loads(capsys.readouterr().out)
    assert sorted(document) == ["devices", "failed", "generated_at"]
    assert _logged(loguru_logs, "WARNING", "Failed to query 1 device(s)")


def test_transceiver_csv_has_a_header_and_no_footer(capsys):
    _run(
        report.Transceiver,
        ["--format", "csv"],
        [NODE, SWITCH],
        DOCUMENTS,
        interfaces=INTERFACES,
    )

    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0][:5] == [
        "device_name",
        "interface_name",
        "interface_netbox_name",
        "interface_mapping",
        "interface_admin_status",
    ]
    assert len(rows) == 12
    assert all(len(row) == len(rows[0]) for row in rows)
    by_port = {(row[0], row[1]): row for row in rows[1:]}
    assert by_port[("leaf-1a", "Ethernet0")][2:4] == ["Eth1/1", "alias"]
    # Natural order: Ethernet2 before Ethernet10
    names = [row[1] for row in rows[1:] if row[0] == "leaf-1a"]
    assert names.index("Ethernet2") < names.index("Ethernet10")


def test_transceiver_column_and_long_select_the_columns(capsys):
    _run(
        report.Transceiver,
        ["--format", "csv", "--column", "Serial", "--column", "device_name"],
        [NODE],
        DOCUMENTS,
    )
    rows = list(csv.reader(io.StringIO(capsys.readouterr().out)))
    assert rows[0] == ["transceiver_serial", "device_name"]
    assert ["MT2114VS01234", "compute-042"] in rows

    _run(report.Transceiver, ["--format", "csv", "--long"], [NODE], DOCUMENTS)
    header = list(csv.reader(io.StringIO(capsys.readouterr().out)))[0]
    assert len(header) == len(report.TRANSCEIVER_COLUMNS)
    assert "nic_driver" in header and "transceiver_vendor_oui" in header


def test_transceiver_rejects_unknown_columns_before_connecting(loguru_logs):
    result, mocks = _run(report.Transceiver, ["--column", "bogus"], [NODE], DOCUMENTS)

    assert result == 1
    mocks.select.assert_not_called()
    mocks.collect.assert_not_called()
    assert _logged(loguru_logs, "ERROR", "No valid columns specified")


def test_transceiver_output_writes_a_file(tmp_path, capsys):
    path = tmp_path / "optics.csv"

    _run(
        report.Transceiver,
        ["--format", "csv", "--output", str(path)],
        [NODE],
        DOCUMENTS,
    )

    assert capsys.readouterr().out == ""
    assert path.read_text().splitlines()[0].startswith("device_name,interface_name")


def test_transceiver_dom_adds_the_readings():
    _, document, _ = _transceiver_json(["--dom"], targets=[NODE])

    _, ports = _by_name(document, "compute-042")
    assert ports["ens1f1np1"]["transceiver"]["dom"]["temperature"] == 33.45
    assert ports["ens1f0np0"]["transceiver"]["dom"] is None

    _, document, _ = _transceiver_json(targets=[NODE])
    _, ports = _by_name(document, "compute-042")
    assert "dom" not in ports["ens1f1np1"]["transceiver"]


def test_transceiver_marks_virtual_functions_and_infiniband_ports():
    target = _target("gpu-001", "node")
    documents = {"gpu-001": _document("linux-mellanox-vf-ib.json")}

    _, document, _ = _transceiver_json(
        ["--include-vf", "--include-infiniband"],
        targets=[target],
        documents=documents,
        interfaces={},
    )

    _, ports = _by_name(document, "gpu-001")
    assert {name: port["kind"] for name, port in ports.items()} == {
        "ens3f0np0": "physical",
        "ens3f0v0": "vf",
        "ibp129s0": "infiniband",
    }
    assert ports["ens3f0v0"]["parent"] == "ens3f0np0"


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["--present"], ["ens1f0np0", "ens1f1np1"]),
        (["--oper-status", "down"], ["eno2"]),
        (["--interface", "eno*"], ["eno1", "eno2"]),
        (["--interface", "nic1-*", "--interface", "eno2"], ["eno2", "ens1f0np0"]),
        (
            ["--interface", "ens*", "--present", "--oper-status", "up"],
            ["ens1f0np0", "ens1f1np1"],
        ),
    ],
)
def test_transceiver_row_filters(argv, expected):
    _, document, _ = _transceiver_json(argv, targets=[NODE])

    _, ports = _by_name(document, "compute-042")
    assert sorted(ports) == expected


def test_transceiver_without_netbox_reports_nodes_without_mapping():
    target = _target("compute-042", "node")

    _, document, mocks = _transceiver_json(
        targets=[target], interfaces={}, netbox=False
    )

    device, ports = _by_name(document, "compute-042")
    assert ports["ens1f0np0"]["mapping"] == "none"
    assert ports["ens1f0np0"]["netbox_name"] is None
    assert ports["ens1f0np0"]["transceiver"]["vendor"] == "Mellanox"
    assert device["unmatched_netbox_interfaces"] == []
    assert device["site"] is None
    mocks.fetch.assert_not_called()


def test_transceiver_without_netbox_rejects_netbox_filters(loguru_logs):
    cmd = report.Transceiver(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--site", "fra1"])

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch("osism.utils.nb", new=None, create=True), patch(
        "osism.commands.report.collect"
    ) as collect:
        result = cmd.take_action(parsed_args)

    assert result == 1
    collect.assert_not_called()
    assert _logged(loguru_logs, "ERROR", "NetBox is not configured")


def test_transceiver_netbox_failure_after_collection_keeps_the_report(loguru_logs):
    cmd = report.Transceiver(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--format", "json"])
    stdout = io.StringIO()

    with _hardware_env([NODE], DOCUMENTS), patch(
        "osism.commands.report.fetch_interfaces", side_effect=RuntimeError("503")
    ), patch("sys.stdout", stdout):
        result = cmd.take_action(parsed_args)

    assert not result
    _, ports = _by_name(json.loads(stdout.getvalue()), "compute-042")
    assert ports["ens1f0np0"]["mapping"] == "none"
    assert _logged(loguru_logs, "WARNING", "Could not load interfaces from NetBox: 503")


def test_transceiver_dump_raw_writes_the_collected_documents(tmp_path, loguru_logs):
    directory = tmp_path / "capture"

    _run(
        report.Transceiver,
        ["--dump-raw", str(directory)],
        [NODE, SWITCH],
        DOCUMENTS,
    )

    assert sorted(path.name for path in directory.iterdir()) == [
        "compute-042.json",
        "leaf-1a.json",
    ]
    assert json.loads((directory / "leaf-1a.json").read_text()) == DOCUMENTS["leaf-1a"]
    assert _logged(loguru_logs, "INFO", "Wrote 2 raw document(s)")


def test_transceiver_is_registered_as_a_command():
    import configparser

    config = configparser.ConfigParser()
    config.read(Path(__file__).parents[3] / "setup.cfg")

    assert (
        "report transceiver = osism.commands.report:Transceiver"
        in config["options.entry_points"]["osism.commands"]
    )
