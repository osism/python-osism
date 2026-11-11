# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Linux collector ``osism.utils.hardware.remote_linux``.

The collector runs on the node. Here it reads a fake ``/sys/class/net``
below ``tmp_path`` and gets its command output from a fake runner.
"""

import io
import json

import pytest

from osism.utils.hardware import remote_linux


def _netdev(sys_net, name, device=True, link_type="1", physfn=None, **attributes):
    base = sys_net / name
    base.mkdir(parents=True)
    (base / "type").write_text(f"{link_type}\n")
    for attribute, value in attributes.items():
        (base / attribute).write_text(f"{value}\n")
    if device:
        (base / "device").mkdir()
    if physfn:
        (base / "device" / "physfn" / "net" / physfn).mkdir(parents=True)
    return base


@pytest.fixture
def sys_net(tmp_path):
    root = tmp_path / "net"
    root.mkdir()
    _netdev(root, "lo", device=False, link_type="772")
    _netdev(root, "bond0", device=False)
    _netdev(root, "vlan100", device=False)
    _netdev(
        root,
        "ens1f0",
        address="aa:bb:cc:00:00:01",
        operstate="up",
        carrier="1",
        speed="25000",
        mtu="9000",
        phys_port_name="p0",
    )
    _netdev(root, "ens1f0v0", physfn="ens1f0", address="02:00:00:00:00:01")
    _netdev(root, "ens1f0r0", phys_port_name="pf0vf0")
    _netdev(root, "ib0", link_type="32")
    _netdev(root, "wwan0", link_type="65534")
    return str(root)


def _runner(calls=None):
    def run(argv, timeout=20):
        if calls is not None:
            calls.append(argv)
        return {"rc": 0, "out": "output of " + " ".join(argv), "err": ""}

    return run


def test_port_kind_classifies_network_devices(sys_net):
    kinds = {
        name: remote_linux.port_kind(name, sys_net)
        for name in [
            "lo",
            "bond0",
            "vlan100",
            "ens1f0",
            "ens1f0v0",
            "ens1f0r0",
            "ib0",
            "wwan0",
        ]
    }

    assert kinds == {
        "lo": None,
        "bond0": None,
        "vlan100": None,
        "ens1f0": "physical",
        "ens1f0v0": "vf",
        "ens1f0r0": None,
        "ib0": "infiniband",
        "wwan0": None,
    }


def test_list_ports_returns_only_the_requested_kinds(sys_net):
    assert remote_linux.list_ports(["physical"], sys_net) == {"ens1f0": "physical"}
    assert remote_linux.list_ports(["physical", "vf", "infiniband"], sys_net) == {
        "ens1f0": "physical",
        "ens1f0v0": "vf",
        "ib0": "infiniband",
    }


def test_list_ports_without_sysfs_is_empty(tmp_path):
    assert remote_linux.list_ports(["physical"], str(tmp_path / "missing")) == {}


def test_collect_gathers_identity_and_link_state(sys_net):
    calls = []

    document = remote_linux.collect(
        ["ports", "lldp"], ["physical", "vf"], sys_net, _runner(calls)
    )

    assert document["collector"] == "linux"
    assert document["sections"] == ["ports", "lldp"]
    assert sorted(document["ports"]) == ["ens1f0", "ens1f0v0"]

    port = document["ports"]["ens1f0"]
    assert port["kind"] == "physical"
    assert port["sysfs"]["address"] == "aa:bb:cc:00:00:01"
    assert port["sysfs"]["speed"] == "25000"
    assert port["sysfs"]["duplex"] is None
    assert port["ethtool_P"]["out"] == "output of ethtool -P ens1f0"
    assert "physfn" not in port
    assert document["ports"]["ens1f0v0"]["physfn"] == ["ens1f0"]

    assert document["ip_link"]["out"] == "output of ip -j -d link show"
    assert document["lldpctl"]["out"] == "output of lldpctl -f json"
    assert ["lldpctl", "-f", "json"] in calls


def test_collect_runs_only_the_requested_sections(sys_net):
    calls = []

    document = remote_linux.collect(["ports"], ["physical"], sys_net, _runner(calls))

    assert "lldpctl" not in document
    assert ["lldpctl", "-f", "json"] not in calls


def test_main_prints_one_json_document(sys_net):
    stream = io.StringIO()

    code = remote_linux.main(
        ["--sections", "ports,lldp", "--include-vf", "--include-infiniband"],
        sys_net=sys_net,
        runner=_runner(),
        stream=stream,
    )

    assert code == 0
    document = json.loads(stream.getvalue())
    assert sorted(document["ports"]) == ["ens1f0", "ens1f0v0", "ib0"]


def test_main_defaults_to_physical_ports(sys_net):
    stream = io.StringIO()

    remote_linux.main([], sys_net=sys_net, runner=_runner(), stream=stream)

    assert sorted(json.loads(stream.getvalue())["ports"]) == ["ens1f0"]


def test_main_rejects_unknown_sections(sys_net, capsys):
    code = remote_linux.main(["--sections", "ports,bogus"], sys_net=sys_net)

    assert code == 2
    assert "unknown section(s): bogus" in capsys.readouterr().err


def test_run_reports_missing_commands_and_output():
    missing = remote_linux.run(["/nonexistent/osism-test-binary"])
    assert missing["rc"] == 127
    assert missing["out"] == ""

    ok = remote_linux.run(["python3", "-c", "print('hello')"])
    assert ok == {"rc": 0, "out": "hello\n", "err": ""}


# ---------------------------------------------------------------------------
# Hardware sections
# ---------------------------------------------------------------------------


def test_hardware_sections_query_every_port(sys_net):
    calls = []

    document = remote_linux.collect(
        ["ports", "ethtool", "module", "nic"],
        ["physical", "vf"],
        sys_net,
        _runner(calls),
    )

    port = document["ports"]["ens1f0"]
    assert port["ethtool"]["out"] == "output of ethtool ens1f0"
    assert port["ethtool_i"]["out"] == "output of ethtool -i ens1f0"
    assert port["ethtool_fec"]["out"] == "output of ethtool --show-fec ens1f0"
    assert port["ethtool_m"]["out"] == "output of ethtool -m ens1f0"
    assert port["lspci"]["out"].startswith("output of lspci -D -vmm -nn -s ")
    assert port["devlink"]["out"].startswith("output of devlink -j dev info pci/")
    assert ["ethtool", "-m", "ens1f0v0"] in calls


def test_module_section_keeps_the_exit_code_of_a_port_without_module(sys_net):
    def runner(argv, timeout=20):
        if argv[:2] == ["ethtool", "-m"]:
            return {"rc": 75, "out": "", "err": "Operation not supported"}
        return {"rc": 0, "out": "", "err": ""}

    document = remote_linux.collect(["ports", "module"], ["physical"], sys_net, runner)

    assert document["ports"]["ens1f0"]["ethtool_m"] == {
        "rc": 75,
        "out": "",
        "err": "Operation not supported",
    }


def test_nic_section_queries_a_shared_pci_function_once(tmp_path):
    root = tmp_path / "net"
    function = tmp_path / "devices" / "0000:3b:00.0"
    function.mkdir(parents=True)
    for name in ("p0", "p1"):
        base = root / name
        base.mkdir(parents=True)
        (base / "type").write_text("1\n")
        (base / "device").symlink_to(function)
    calls = []

    document = remote_linux.collect(
        ["ports", "nic"], ["physical"], str(root), _runner(calls)
    )

    assert document["ports"]["p0"]["pci"] == "0000:3b:00.0"
    assert document["ports"]["p1"]["lspci"] == document["ports"]["p0"]["lspci"]
    assert calls.count(["lspci", "-D", "-vmm", "-nn", "-s", "0000:3b:00.0"]) == 1
    assert calls.count(["devlink", "-j", "dev", "info", "pci/0000:3b:00.0"]) == 1


def test_system_section_reads_dmi(sys_net, tmp_path, monkeypatch):
    dmi = tmp_path / "dmi"
    dmi.mkdir()
    (dmi / "sys_vendor").write_text("Supermicro\n")
    (dmi / "product_name").write_text("SYS-120C\n")
    monkeypatch.setattr(remote_linux, "SYS_DMI", str(dmi))

    document = remote_linux.collect(["system"], ["physical"], sys_net, _runner())

    assert document["dmi"] == {
        "sys_vendor": "Supermicro",
        "product_name": "SYS-120C",
        "product_serial": None,
    }


def test_infiniband_port_reports_state_and_rate(sys_net, tmp_path):
    port = tmp_path / "net" / "ib0" / "device" / "infiniband" / "mlx5_2" / "ports" / "2"
    port.mkdir(parents=True)
    (port / "state").write_text("4: ACTIVE\n")
    (port / "rate").write_text("100 Gb/sec (4X EDR)\n")
    (tmp_path / "net" / "ib0" / "dev_port").write_text("1\n")

    document = remote_linux.collect(["ports"], ["infiniband"], sys_net, _runner())

    assert document["ports"]["ib0"]["infiniband"] == {
        "device": "mlx5_2",
        "port": 2,
        "state": "4: ACTIVE",
        "rate": "100 Gb/sec (4X EDR)",
    }


def test_infiniband_port_without_ib_device(sys_net):
    document = remote_linux.collect(["ports"], ["infiniband"], sys_net, _runner())

    assert document["ports"]["ib0"]["infiniband"] == {}
