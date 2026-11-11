# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_linux``."""

import json

import pytest

from osism.utils.hardware.parse_linux import (
    command_output,
    oper_status,
    parse_ip_link,
    parse_permanent_address,
    parse_ports,
    pci_address,
)


def _ok(text):
    return {"rc": 0, "out": text, "err": ""}


def test_command_output_is_none_for_failed_or_missing_commands():
    assert command_output(_ok("x")) == "x"
    assert command_output({"rc": 1, "out": "x", "err": "boom"}) is None
    assert command_output(None) is None


def test_parse_ip_link_indexes_by_name_and_tolerates_garbage():
    links = parse_ip_link(_ok(json.dumps([{"ifname": "eth0", "mtu": 1500}, {"x": 1}])))

    assert links == {"eth0": {"ifname": "eth0", "mtu": 1500}}
    assert parse_ip_link(_ok("not json")) == {}
    assert parse_ip_link(_ok("{}")) == {}
    assert parse_ip_link({"rc": 127, "out": "", "err": "not found"}) == {}


def test_parse_permanent_address():
    assert (
        parse_permanent_address(_ok("Permanent address: B8:CE:F6:AA:00:11\n"))
        == "b8:ce:f6:aa:00:11"
    )
    assert parse_permanent_address(_ok("Permanent address: 00:00:00:00:00:00")) is None
    assert parse_permanent_address({"rc": 1, "out": "", "err": "x"}) is None


@pytest.mark.parametrize(
    "operstate,carrier,expected",
    [
        ("UP", None, "up"),
        ("up", "0", "up"),
        ("DOWN", "1", "down"),
        ("LOWERLAYERDOWN", None, "down"),
        ("UNKNOWN", "1", "up"),
        ("unknown", "0", "down"),
        (None, None, None),
    ],
)
def test_oper_status(operstate, carrier, expected):
    assert oper_status(operstate, carrier) == expected


def test_parse_ports_of_a_node(load_fixture):
    ports = parse_ports(load_fixture("linux-mellanox.json"))

    assert [port["name"] for port in ports] == [
        "eno1",
        "eno2",
        "ens1f0np0",
        "ens1f1np1",
    ]
    by_name = {port["name"]: port for port in ports}

    eno1 = by_name["eno1"]
    assert eno1["kind"] == "physical"
    assert eno1["admin_status"] == "up"
    assert eno1["oper_status"] == "up"
    assert eno1["speed"] == 1000
    assert eno1["mtu"] == 1500
    assert eno1["altnames"] == ["enp3s0f0"]
    assert eno1["bond"] is None
    assert eno1["pci_address"] == "0000:03:00.0"

    eno2 = by_name["eno2"]
    assert eno2["admin_status"] == "down"
    assert eno2["oper_status"] == "down"
    assert eno2["speed"] is None


def test_parse_ports_of_a_captured_node(load_fixture):
    ports = parse_ports(load_fixture("linux-connectx4.json"))

    assert [port["name"] for port in ports] == [
        "enp4s0f0",
        "enp4s0f1",
        "ens4f0np0",
        "ens4f1np1",
    ]
    by_name = {port["name"]: port for port in ports}

    first = by_name["ens4f0np0"]
    assert first["kind"] == "physical"
    assert first["admin_status"] == "up"
    assert first["oper_status"] == "up"
    assert first["speed"] == 25000
    assert first["duplex"] == "full"
    assert first["mtu"] == 9100
    assert first["altnames"] == ["enp130s0f0np0"]
    assert first["mac"] == "02:00:00:00:00:01"
    assert first["permanent_mac"] == "02:00:00:00:00:01"
    assert first["bond"] is None
    assert first["pci_address"] == "0000:82:00.0"

    # A port that is administratively down has no readable carrier, speed
    # or duplex in sysfs
    unused = by_name["enp4s0f1"]
    assert unused["admin_status"] == "down"
    assert unused["oper_status"] == "down"
    assert unused["speed"] is None
    assert unused["duplex"] is None


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0000:82:00.0", "0000:82:00.0"),
        ("0000:65:00.1", "0000:65:00.1"),
        ("10000:01:00.0", "10000:01:00.0"),
        # USB path of the host interface of a BMC
        ("1-7.2:2.0", None),
        ("", None),
        (None, None),
    ],
)
def test_pci_address_is_none_for_other_buses(value, expected):
    assert pci_address(value) == expected


def test_port_on_a_usb_device_has_no_pci_address():
    document = {"ports": {"enx0200000000ff": {"kind": "physical", "pci": "1-7.2:2.0"}}}

    (port,) = parse_ports(document)

    assert port["pci_address"] is None


def test_bond_member_keeps_its_permanent_mac(load_fixture):
    ports = {p["name"]: p for p in parse_ports(load_fixture("linux-mellanox.json"))}

    second = ports["ens1f1np1"]
    # Both members report the MAC of the bond as their address
    assert second["mac"] == "b8:ce:f6:aa:00:10"
    assert second["permanent_mac"] == "b8:ce:f6:aa:00:11"
    assert second["bond"] == "bond0"
    assert ports["ens1f0np0"]["permanent_mac"] == "b8:ce:f6:aa:00:10"


def test_permanent_mac_falls_back_to_permaddr_then_address():
    links = [
        {
            "ifname": "a",
            "address": "aa:aa:aa:00:00:01",
            "permaddr": "aa:aa:aa:00:00:02",
        },
        {"ifname": "b", "address": "aa:aa:aa:00:00:03"},
    ]
    document = {
        "ports": {
            "a": {"kind": "physical", "ethtool_P": {"rc": 127, "out": "", "err": ""}},
            "b": {"kind": "physical"},
        },
        "ip_link": _ok(json.dumps(links)),
    }

    ports = {port["name"]: port for port in parse_ports(document)}

    assert ports["a"]["permanent_mac"] == "aa:aa:aa:00:00:02"
    assert ports["b"]["permanent_mac"] == "aa:aa:aa:00:00:03"


def test_parse_ports_without_ip_link_uses_sysfs():
    document = {
        "ports": {
            "eth1": {
                "kind": "vf",
                "physfn": ["eth0"],
                "sysfs": {
                    "address": "02:00:00:00:00:01",
                    "operstate": "up",
                    "speed": "-1",
                    "mtu": "1500",
                },
            }
        },
        "ip_link": {"rc": 127, "out": "", "err": "not found"},
    }

    (port,) = parse_ports(document)

    assert port["kind"] == "vf"
    assert port["parent"] == "eth0"
    assert port["admin_status"] is None
    assert port["oper_status"] == "up"
    assert port["speed"] is None
    assert port["mac"] == "02:00:00:00:00:01"
    assert port["altnames"] == []


def test_parse_ports_of_an_empty_document():
    assert parse_ports({}) == []
