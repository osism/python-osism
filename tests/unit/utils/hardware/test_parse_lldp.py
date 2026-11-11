# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_lldp``."""

import json

import pytest

from osism.utils.hardware.parse_lldp import (
    LldpError,
    linux_neighbours,
    neighbour,
    parse_lldpctl,
)

IFACE_ETH0 = {
    "chassis": {"switch-1": {"id": {"type": "mac", "value": "aa:bb:cc:00:00:01"}}},
    "port": {"id": {"type": "ifname", "value": "Ethernet10"}, "descr": "downlink"},
    "age": "12 days",
}
IFACE_ETH1 = {
    "chassis": {"switch-2": {}},
    "port": {"id": {"value": "Ethernet20"}, "descr": "uplink"},
    "age": "3 days",
}


def _lldp(interface):
    return json.dumps({"lldp": {"interface": interface}})


def test_single_interface_dict_is_normalised():
    neighbours = parse_lldpctl(_lldp({"eth0": IFACE_ETH0}))

    assert neighbours == {
        "eth0": [
            neighbour(
                system_name="switch-1",
                chassis_id="aa:bb:cc:00:00:01",
                chassis_id_type="mac",
                port_id="Ethernet10",
                port_id_type="ifname",
                port_description="downlink",
                age="12 days",
            )
        ]
    }


def test_interface_list_is_handled():
    neighbours = parse_lldpctl(_lldp([{"eth0": IFACE_ETH0}, {"eth1": IFACE_ETH1}]))

    assert sorted(neighbours) == ["eth0", "eth1"]
    assert neighbours["eth1"][0]["system_name"] == "switch-2"
    assert neighbours["eth1"][0]["port_id"] == "Ethernet20"
    assert neighbours["eth1"][0]["chassis_id"] is None


def test_several_neighbours_on_one_port_are_all_kept():
    neighbours = parse_lldpctl(_lldp([{"eth0": IFACE_ETH0}, {"eth0": IFACE_ETH1}]))

    assert [n["system_name"] for n in neighbours["eth0"]] == ["switch-1", "switch-2"]


def test_missing_neighbour_details_become_none():
    neighbours = parse_lldpctl(_lldp({"eth0": {}}))

    assert neighbours == {"eth0": [neighbour()]}
    assert neighbours["eth0"][0]["management_addresses"] == []


def test_chassis_without_a_system_name():
    entry = {
        "chassis": {
            "id": {"type": "mac", "value": "aa:bb:cc:00:00:09"},
            "mgmt-ip": "10.0.0.9",
        },
        "port": {"id": {"type": "mac", "value": "aa:bb:cc:00:00:0a"}},
    }

    (found,) = parse_lldpctl(_lldp({"eth0": entry}))["eth0"]

    assert found["system_name"] is None
    assert found["chassis_id"] == "aa:bb:cc:00:00:09"
    assert found["port_id_type"] == "mac"
    assert found["management_addresses"] == ["10.0.0.9"]


def test_management_addresses_can_be_a_list():
    entry = {"chassis": {"sw": {"mgmt-ip": ["10.0.0.1", "fe80::1"]}}}

    (found,) = parse_lldpctl(_lldp({"eth0": entry}))["eth0"]

    assert found["management_addresses"] == ["10.0.0.1", "fe80::1"]


@pytest.mark.parametrize(
    "text", ["", "{}", '{"lldp": {}}', '{"lldp": {"interface": []}}']
)
def test_no_neighbours(text):
    assert parse_lldpctl(text) == {}


def test_invalid_json_raises_value_error():
    with pytest.raises(ValueError):
        parse_lldpctl("not json")
    with pytest.raises(ValueError):
        parse_lldpctl("[1, 2]")


def test_linux_neighbours_from_a_collector_document(load_fixture):
    neighbours = linux_neighbours(load_fixture("linux-mellanox.json"))

    assert sorted(neighbours) == ["eno1", "ens1f0np0", "ens1f1np1"]
    (found,) = neighbours["ens1f0np0"]
    assert found["system_name"] == "leaf-1a"
    assert found["port_id"] == "Eth1/12"
    assert found["port_id_type"] == "local"
    assert found["port_description"] == "Ethernet11"
    assert found["chassis_id"] == "0c:29:ef:d1:a0:00"
    assert found["management_addresses"] == ["10.10.0.11"]
    assert found["age"] == "3 days, 04:12:55"


def test_linux_neighbours_of_a_captured_node(load_fixture):
    neighbours = linux_neighbours(load_fixture("linux-connectx4.json"))

    assert sorted(neighbours) == ["enp4s0f0", "ens4f0np0", "ens4f1np1"]

    # A SONiC switch configured by OSISM advertises the alias of the port as
    # a locally assigned port ID and the SONiC name as the description. The
    # port is the first lane of a cage that is broken out.
    (leaf,) = neighbours["ens4f0np0"]
    assert leaf["system_name"] == "leaf-1"
    assert leaf["chassis_id"] == "02:00:00:00:00:1d"
    assert leaf["chassis_id_type"] == "mac"
    assert leaf["port_id"] == "Eth1/1/1"
    assert leaf["port_id_type"] == "local"
    assert leaf["port_description"] == "Ethernet0"
    assert leaf["management_addresses"] == ["192.0.2.2"]
    assert neighbours["ens4f1np1"][0]["system_name"] == "leaf-2"

    # RouterOS names a bridge port after the bridge and sends no description
    (oob,) = neighbours["enp4s0f0"]
    assert oob["system_name"] == "oob-1"
    assert oob["port_id"] == "bridge/ether14"
    assert oob["port_id_type"] == "ifname"
    assert oob["port_description"] is None


@pytest.mark.parametrize(
    "result,message",
    [
        (None, "LLDP data was not collected"),
        ({"rc": 127, "out": "", "err": "No such file"}, "lldpctl not found"),
        (
            {
                "rc": 1,
                "out": "",
                "err": "warning\nunable to connect to socket /run/lldpd.socket",
            },
            "lldpctl failed: unable to connect to socket /run/lldpd.socket",
        ),
        ({"rc": 1, "out": "", "err": ""}, "lldpctl failed: exit code 1"),
        ({"rc": 0, "out": "not json", "err": ""}, "unparsable lldpctl output"),
    ],
)
def test_linux_neighbours_failures_have_a_clear_message(result, message):
    document = {} if result is None else {"lldpctl": result}

    with pytest.raises(LldpError) as excinfo:
        linux_neighbours(document)

    assert str(excinfo.value) == message
