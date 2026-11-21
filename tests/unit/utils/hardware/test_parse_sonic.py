# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_sonic``."""

from osism.utils.hardware.parse_sonic import (
    device_metadata,
    parse_mgmt_port,
    parse_ports,
    table,
)


def test_table_strips_the_prefix_and_unwraps_the_value(load_fixture):
    document = load_fixture("sonic-enterprise.json")

    config = table(document, "CONFIG_DB", "PORT")
    assert config["Ethernet0"]["alias"] == "Eth1/1/1"

    state = table(document, "APPL_DB", "PORT_TABLE")
    assert state["Ethernet0"]["oper_status"] == "up"
    assert "PortInitDone" in state


def test_table_accepts_entries_without_a_value_wrapper():
    document = {"db": {"CONFIG_DB": {"PORT": {"PORT|Ethernet0": {"alias": "Eth1/1"}}}}}

    assert table(document, "CONFIG_DB", "PORT") == {"Ethernet0": {"alias": "Eth1/1"}}


def test_table_that_was_not_collected_is_empty():
    assert table({}, "STATE_DB", "TRANSCEIVER_INFO") == {}
    assert table({"db": {"CONFIG_DB": {}}}, "CONFIG_DB", "PORT") == {}


def test_device_metadata(load_fixture):
    metadata = device_metadata(load_fixture("sonic-enterprise.json"))

    assert metadata["hwsku"] == "Accton-AS7726-32X"
    assert metadata["hostname"] == "leaf-1"
    assert device_metadata({}) == {}


def test_parse_ports_of_a_switch(load_fixture):
    ports = parse_ports(load_fixture("sonic-enterprise.json"))

    assert [port["name"] for port in ports] == [
        "Ethernet0",
        "Ethernet1",
        "Ethernet4",
        "Ethernet6",
        "Ethernet9",
        "Ethernet12",
        "Ethernet13",
        "Ethernet22",
        "Ethernet24",
        "Ethernet120",
        "Ethernet124",
        "Ethernet125",
    ]
    by_name = {port["name"]: port for port in ports}

    # First lane of a QSFP28 cage that is broken out into 4x25G
    first = by_name["Ethernet0"]
    assert first["alias"] == "Eth1/1/1"
    assert first["admin_status"] == "up"
    assert first["oper_status"] == "up"
    assert first["speed"] == 25000
    assert first["mtu"] == 9100
    assert first["lanes"] == "1"
    assert first["index"] == 1
    # Enterprise SONiC keeps neither of them in PORT unless configured
    assert first["fec"] is None
    assert first["description"] is None

    assert by_name["Ethernet1"]["alias"] == "Eth1/1/2"
    assert by_name["Ethernet1"]["index"] == 1
    assert by_name["Ethernet4"]["admin_status"] == "down"
    assert by_name["Ethernet4"]["oper_status"] == "down"
    assert by_name["Ethernet12"]["speed"] == 10000
    assert by_name["Ethernet120"]["alias"] == "Eth1/31"
    assert by_name["Ethernet120"]["speed"] == 100000
    assert by_name["Ethernet120"]["lanes"] == "121,122,123,124"


def test_parse_ports_reads_speed_fec_and_description_from_either_table():
    document = {
        "db": {
            "CONFIG_DB": {
                "PORT": {
                    "PORT|Ethernet0": {
                        "value": {
                            "speed": "25000",
                            "fec": "rs",
                            "description": "compute-042",
                        }
                    },
                    "PORT|Ethernet4": {"value": {"speed": "25000"}},
                }
            },
            "APPL_DB": {
                "PORT_TABLE": {
                    "PORT_TABLE:Ethernet0": {
                        "value": {"speed": "10000", "description": "ignored"}
                    },
                    "PORT_TABLE:Ethernet4": {
                        "value": {"fec": "fc", "description": "uplink"}
                    },
                }
            },
        }
    }

    first, second = parse_ports(document)

    # The operational speed wins over the configured one
    assert first["speed"] == 10000
    assert first["fec"] == "rs"
    assert first["description"] == "compute-042"
    assert second["speed"] == 25000
    assert second["fec"] == "fc"
    assert second["description"] == "uplink"


def test_parse_ports_without_operational_state():
    document = {
        "db": {
            "CONFIG_DB": {
                "PORT": {
                    "PORT|Ethernet4": {"value": {"alias": "Eth1/2", "speed": "25000"}},
                    "PORT|Loopback0": {"value": {}},
                }
            }
        }
    }

    (port,) = parse_ports(document)

    assert port["name"] == "Ethernet4"
    assert port["admin_status"] == "down"
    assert port["oper_status"] is None
    assert port["speed"] == 25000


def test_parse_mgmt_port(load_fixture):
    port = parse_mgmt_port(load_fixture("sonic-enterprise.json"))

    assert port["name"] == "eth0"
    assert port["kind"] == "mgmt"
    assert port["oper_status"] == "up"
    assert port["mac"] == "02:00:00:00:00:1d"
    assert port["permanent_mac"] == "02:00:00:00:00:1d"
    assert port["speed"] == 1000


def test_parse_mgmt_port_uses_carrier_for_unknown_operstate():
    document = {
        "mgmt": {"eth0": {"operstate": "unknown", "carrier": "0", "speed": "-1"}}
    }

    port = parse_mgmt_port(document)

    assert port["oper_status"] == "down"
    assert port["speed"] is None
    assert port["mac"] is None


def test_parse_mgmt_port_is_none_when_it_was_not_seen():
    assert parse_mgmt_port({}) is None
    assert parse_mgmt_port({"mgmt": {}}) is None
