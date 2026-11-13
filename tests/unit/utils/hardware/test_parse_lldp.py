# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_lldp``."""

import json

import pytest

from osism.utils.hardware.parse_lldp import (
    LldpError,
    entry_port,
    linux_neighbours,
    neighbour,
    parse_lldp_entry_table,
    parse_lldpctl,
    sonic_neighbours,
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


# ---------------------------------------------------------------------------
# SONiC
# ---------------------------------------------------------------------------

ENTRY_ETH11 = {
    "lldp_rem_chassis_id": "b8:ce:f6:aa:00:10",
    "lldp_rem_chassis_id_subtype": "4",
    "lldp_rem_port_id": "b8:ce:f6:aa:00:10",
    "lldp_rem_port_id_subtype": "3",
    "lldp_rem_port_desc": "ens1f0np0",
    "lldp_rem_sys_name": "compute-042",
    "lldp_rem_sys_desc": "Ubuntu 24.04",
    "lldp_rem_man_addr": "10.10.1.42,fe80::1",
    "lldp_rem_time_mark": "1234",
    "lldp_rem_index": "1",
}


def _sonic(entries=None, lldpctl=None, errors=None):
    document = {"db": {}, "errors": errors or {}}
    if entries is not None:
        document["db"]["APPL_DB"] = {
            "LLDP_ENTRY_TABLE": {
                f"LLDP_ENTRY_TABLE:{name}": {"type": "hash", "value": fields}
                for name, fields in entries.items()
            }
        }
    if lldpctl is not None:
        document["lldpctl"] = lldpctl
    return document


def test_lldp_entry_table_is_normalised():
    neighbours = parse_lldp_entry_table({"Ethernet11": ENTRY_ETH11})

    assert neighbours == {
        "Ethernet11": [
            neighbour(
                system_name="compute-042",
                chassis_id="b8:ce:f6:aa:00:10",
                chassis_id_type="mac",
                port_id="b8:ce:f6:aa:00:10",
                port_id_type="mac",
                port_description="ens1f0np0",
                management_addresses=["10.10.1.42", "fe80::1"],
                # lldp_rem_time_mark is not an age on every release
                age=None,
            )
        ]
    }


def test_lldp_entry_table_with_sparse_and_unknown_fields():
    neighbours = parse_lldp_entry_table(
        {
            "Ethernet0": {
                "lldp_rem_port_id": "Eth1/1",
                "lldp_rem_port_id_subtype": "7",
            },
            "eth0": {"lldp_rem_port_id_subtype": "99"},
        }
    )

    assert neighbours["Ethernet0"][0]["port_id_type"] == "local"
    assert neighbours["Ethernet0"][0]["age"] is None
    assert neighbours["eth0"] == [neighbour()]
    assert parse_lldp_entry_table({}) == {}


@pytest.mark.parametrize(
    "key,port",
    [
        ("Ethernet0", "Ethernet0"),
        ("eth0", "eth0"),
        # Enterprise SONiC 4.5 appends the source MAC of the neighbour
        ("Ethernet0:02:00:00:00:00:01", "Ethernet0"),
        ("Ethernet124:02:00:00:00:00:09", "Ethernet124"),
        ("eth0:02:00:00:00:00:17", "eth0"),
        ("Ethernet0:AA:BB:CC:DD:EE:FF", "Ethernet0"),
        # Not a MAC address: part of the name
        ("Ethernet0:1", "Ethernet0:1"),
    ],
)
def test_entry_port(key, port):
    assert entry_port(key) == port


def test_lldp_entry_table_keeps_several_neighbours_of_a_port():
    """A NIC with an LLDP agent of its own answers next to the host."""
    firmware = dict(ENTRY_ETH11, lldp_rem_sys_name="NIC firmware")
    neighbours = parse_lldp_entry_table(
        {
            "Ethernet11:b8:ce:f6:aa:00:10": ENTRY_ETH11,
            "Ethernet11:b8:ce:f6:aa:00:12": firmware,
        }
    )

    assert sorted(neighbours) == ["Ethernet11"]
    assert [found["system_name"] for found in neighbours["Ethernet11"]] == [
        "compute-042",
        "NIC firmware",
    ]


def test_sonic_neighbours_of_enterprise_sonic_4_5(load_fixture):
    """The keys of LLDP_ENTRY_TABLE carry the MAC address of the neighbour."""
    neighbours = sonic_neighbours(load_fixture("sonic-enterprise.json"))

    assert sorted(neighbours) == [
        "Ethernet0",
        "Ethernet1",
        "Ethernet12",
        "Ethernet120",
        "Ethernet124",
        "Ethernet13",
        "Ethernet22",
        "Ethernet6",
        "Ethernet9",
        "eth0",
    ]
    assert all(len(found) == 1 for found in neighbours.values())

    # lldpd on a node advertises the MAC address of the port as port ID
    # and the name of the port as description
    node = neighbours["Ethernet0"][0]
    assert node == neighbour(
        system_name="node-1",
        chassis_id="02:00:00:00:00:19",
        chassis_id_type="mac",
        port_id="02:00:00:00:00:01",
        port_id_type="mac",
        port_description="ens4f0np0",
        management_addresses=["192.0.2.4", "2001:db8::1"],
    )

    # The other leaf: alias as port ID, SONiC name as description
    leaf = neighbours["Ethernet120"][0]
    assert leaf["system_name"] == "leaf-2"
    assert (leaf["port_id"], leaf["port_id_type"]) == ("Eth1/31", "local")
    assert leaf["port_description"] == "Ethernet120"

    # The management port is part of the table
    oob = neighbours["eth0"][0]
    assert oob["system_name"] == "oob-1"
    assert (oob["port_id"], oob["port_id_type"]) == ("bridge/ether9", "ifname")
    assert oob["port_description"] is None


def test_what_a_node_announces_is_not_always_its_name_in_netbox(load_fixture):
    neighbours = sonic_neighbours(load_fixture("sonic-enterprise.json"))

    # A host name that differs from the device name
    assert neighbours["Ethernet6"][0]["system_name"] == "deploy-1"
    # The LLDP agent of a NIC, answering instead of the host: no host name, no
    # management address, but the MAC address of the port
    agent = neighbours["Ethernet9"][0]
    assert agent["system_name"].startswith("Broadcom P225p NetXtreme-E")
    assert agent["management_addresses"] == []
    assert agent["port_id_type"] == "mac"
    # Two nodes with the same chassis ID, the MAC address of the USB host
    # interface of their BMC, and with the address of docker0
    first, second = neighbours["Ethernet12"][0], neighbours["Ethernet13"][0]
    assert first["system_name"] != second["system_name"]
    assert first["chassis_id"] == second["chassis_id"] == "02:00:00:00:00:1f"
    assert first["port_id"] != second["port_id"]
    assert "172.17.0.1" in first["management_addresses"]
    assert "172.17.0.1" in second["management_addresses"]


def test_sonic_neighbours_of_enterprise_sonic_4_4(load_fixture):
    """The keys of LLDP_ENTRY_TABLE are the port names."""
    document = load_fixture("sonic-enterprise-4.4.json")
    neighbours = sonic_neighbours(document)

    assert "lldpctl" not in document
    assert sorted(neighbours) == [
        "Ethernet0",
        "Ethernet120",
        "Ethernet124",
        "Ethernet22",
        "Ethernet6",
        "eth0",
    ]
    assert neighbours["Ethernet0"][0]["system_name"] == "node-1"
    assert neighbours["Ethernet0"][0]["port_description"] == "ens4f1np1"
    assert neighbours["Ethernet120"][0]["system_name"] == "leaf-1"
    assert neighbours["Ethernet120"][0]["port_id"] == "Eth1/31"
    assert neighbours["eth0"][0]["port_id"] == "bridge/ether8"
    assert neighbours["Ethernet0"][0]["age"] is None


def test_both_ends_of_a_cable_name_each_other(load_fixture):
    """node-1 and leaf-1 were captured at both ends of the same cable."""
    node = linux_neighbours(load_fixture("linux-connectx4.json"))
    switch = sonic_neighbours(load_fixture("sonic-enterprise.json"))

    seen_by_node = node["ens4f0np0"][0]
    seen_by_switch = switch["Ethernet0"][0]
    assert seen_by_node["system_name"] == "leaf-1"
    assert seen_by_node["port_description"] == "Ethernet0"
    assert seen_by_switch["system_name"] == "node-1"
    assert seen_by_switch["port_description"] == "ens4f0np0"


def test_sonic_neighbours_from_the_table():
    neighbours = sonic_neighbours(_sonic({"Ethernet11": ENTRY_ETH11}))

    assert sorted(neighbours) == ["Ethernet11"]
    assert neighbours["Ethernet11"][0]["system_name"] == "compute-042"


def test_sonic_neighbours_of_an_empty_table_are_empty():
    assert sonic_neighbours(_sonic({})) == {}


def test_lldpctl_fills_in_ports_the_table_does_not_list():
    """The management port, in case the table only has front-panel ports."""
    lldpctl = {
        "rc": 0,
        "out": _lldp([{"eth0": IFACE_ETH0}, {"Ethernet11": IFACE_ETH1}]),
        "err": "",
    }

    neighbours = sonic_neighbours(_sonic({"Ethernet11": ENTRY_ETH11}, lldpctl))

    assert sorted(neighbours) == ["Ethernet11", "eth0"]
    assert neighbours["eth0"][0]["system_name"] == "switch-1"
    # The table stays the source for the ports it lists
    assert neighbours["Ethernet11"][0]["system_name"] == "compute-042"


def test_sonic_neighbours_fall_back_to_lldpctl_without_the_table():
    lldpctl = {"rc": 0, "out": _lldp({"Ethernet0": IFACE_ETH0}), "err": ""}

    neighbours = sonic_neighbours(_sonic(lldpctl=lldpctl))

    assert neighbours["Ethernet0"][0]["port_id"] == "Ethernet10"


def test_failing_lldpctl_is_ignored_when_the_table_was_read():
    lldpctl = {"rc": 1, "out": "", "err": "Error: No such container: lldp"}
    garbage = {"rc": 0, "out": "not json", "err": ""}

    assert sorted(sonic_neighbours(_sonic({"Ethernet11": ENTRY_ETH11}, lldpctl))) == [
        "Ethernet11"
    ]
    assert sorted(sonic_neighbours(_sonic({"Ethernet11": ENTRY_ETH11}, garbage))) == [
        "Ethernet11"
    ]


@pytest.mark.parametrize(
    "document,message",
    [
        (
            _sonic(
                lldpctl={"rc": 1, "out": "", "err": "x\nError: No such container: lldp"}
            ),
            "LLDP neighbours not readable: Error: No such container: lldp",
        ),
        (
            _sonic(errors={"APPL_DB LLDP_ENTRY_TABLE": "permission denied"}),
            "LLDP neighbours not readable: permission denied",
        ),
        (_sonic(), "LLDP neighbours not readable: no LLDP data"),
        (
            _sonic(lldpctl={"rc": 0, "out": "not json", "err": ""}),
            "unparsable lldpctl output",
        ),
    ],
)
def test_sonic_neighbours_failures_have_a_clear_message(document, message):
    with pytest.raises(LldpError) as excinfo:
        sonic_neighbours(document)

    assert str(excinfo.value) == message
