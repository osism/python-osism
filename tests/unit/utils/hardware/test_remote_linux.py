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
