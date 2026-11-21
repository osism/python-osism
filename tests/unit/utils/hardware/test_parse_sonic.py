# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_sonic``."""

import pytest

from osism.utils.hardware.parse_linux import parse_inventory as parse_linux_inventory
from osism.utils.hardware.parse_sonic import (
    device_metadata,
    parse_dom,
    parse_firmware_status,
    parse_inventory,
    parse_mgmt_port,
    parse_ports,
    parse_show_version,
    parse_syseeprom,
    parse_system,
    parse_transceivers,
    parse_version_file,
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


# ---------------------------------------------------------------------------
# Hardware view: transceivers, diagnostics, platform
# ---------------------------------------------------------------------------


def _inventory(load_fixture, name, dom=False):
    system, interfaces = parse_inventory(load_fixture(name), dom)
    return system, {interface["name"]: interface for interface in interfaces}


def test_transceivers_of_an_enterprise_switch(load_fixture):
    transceivers = parse_transceivers(load_fixture("sonic-enterprise.json"))

    # The table also holds the marker XcvrInitDone, which is not a port
    assert sorted(transceivers) == [
        "Ethernet0",
        "Ethernet1",
        "Ethernet12",
        "Ethernet120",
        "Ethernet124",
        "Ethernet13",
        "Ethernet22",
        "Ethernet4",
        "Ethernet6",
        "Ethernet9",
    ]
    # A passive breakout cable: all four ports of the cage report its
    # QSFP28 end
    assert transceivers["Ethernet0"] == {
        "present": True,
        "form_factor": "QSFP28",
        "connector": "No separable connector",
        "vendor": "FS",
        "vendor_oui": "64:9d:99",
        "part_number": "Q-4S28PC02",
        "serial": "SN00000004",
        "revision": "A",
        "date_code": "2022-09-07",
        "firmware_active": None,
        "firmware_inactive": None,
        "compliance": "100GBASE-CR4",
        "cable_length": "2m",
        "wavelength": None,
    }
    assert transceivers["Ethernet1"] == transceivers["Ethernet0"]
    assert transceivers["Ethernet4"]["cable_length"] == "3m"

    optic = transceivers["Ethernet120"]
    assert optic["connector"] == "MPOx12"
    assert optic["part_number"] == "QSFP28-SR4-100G"
    assert optic["compliance"] == "100GBASE-SR4; 1000BASE-SX; SAS 3.0G"
    assert optic["wavelength"] == "850nm"
    # "0.0" is the cable length of a module without a cable
    assert optic["cable_length"] is None


def test_both_ends_of_a_breakout_cable_read_alike(load_fixture):
    """node-1 is cabled to Ethernet0 of leaf-1 in the captures."""
    switch = parse_transceivers(load_fixture("sonic-enterprise.json"))["Ethernet0"]
    _, ports = parse_linux_inventory(load_fixture("linux-connectx4.json"))
    node = {port["name"]: port for port in ports}["ens4f0np0"]["transceiver"]

    for field in ("vendor", "vendor_oui", "part_number", "date_code", "cable_length"):
        assert node[field] == switch[field], field
    # The SFP28 ends carry the serial number of the cable plus their number
    assert node["serial"] == switch["serial"] + "-1"


def _transceiver(**fields):
    document = {
        "db": {
            "STATE_DB": {
                "TRANSCEIVER_INFO": {"TRANSCEIVER_INFO|Ethernet0": {"value": fields}}
            }
        }
    }
    return parse_transceivers(document)["Ethernet0"]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("{'10/40G Ethernet Compliance Code': '100GBASE-CR4'}", "100GBASE-CR4"),
        (
            "{'a': '100GBASE-SR4', 'b': 'N/A', 'c': '1000BASE-SX'}",
            "100GBASE-SR4; 1000BASE-SX",
        ),
        ("{'a': 'N/A'}", None),
        ("{}", None),
        ("25GBASE-CR CA-N", "25GBASE-CR CA-N"),
        ("sm_media_interface", "sm_media_interface"),
        ("{not a dict", "{not a dict"),
        ("{'a', 'b'}", "{'a', 'b'}"),
    ],
)
def test_compliance_is_reduced_to_its_codes(value, expected):
    assert _transceiver(specification_compliance=value)["compliance"] == expected


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"cable_length": "2.0"}, "2m"),
        ({"cable_length": "0.5", "cable_type": "Length Cable Assembly(m)"}, "0.5m"),
        ({"cable_length": "0.0", "cable_type": "Length OM3(2m)"}, None),
        # The unit of the EEPROM field is not the metre: keep it visible
        (
            {"cable_length": "35.0", "cable_type": "Length OM3(2m)"},
            "35.0 (Length OM3(2m))",
        ),
        ({"cable_length": "N/A"}, None),
        ({"cable_length": "short"}, "short"),
    ],
)
def test_cable_length_is_written_with_its_unit(fields, expected):
    assert _transceiver(vendor_name="X", **fields)["cable_length"] == expected


def test_oui_date_and_wavelength_are_written_like_ethtool_does():
    module = _transceiver(
        vendor_oui="3C-18-A0",
        vendor_date="2021-03-14T00:00:00+00:00",
        wavelength="1310.00000000",
    )

    assert module["vendor_oui"] == "3c:18:a0"
    assert module["date_code"] == "2021-03-14"
    assert module["wavelength"] == "1310nm"
    assert _transceiver(vendor_oui="unknown-oui")["vendor_oui"] == "unknown-oui"


def test_transceivers_with_community_field_names(load_fixture):
    transceivers = parse_transceivers(load_fixture("sonic-community.json"))

    module = transceivers["Ethernet0"]
    assert module["form_factor"] == "QSFP28"
    assert module["vendor"] == "Mellanox"
    assert module["part_number"] == "MFA1A00-C010"
    assert module["serial"] == "MT2030FT01234"
    assert module["revision"] == "A2"
    assert module["date_code"] == "2020-07-24"
    assert module["cable_length"] == "10m"
    assert module["vendor_oui"] == "00:02:c9"
    assert module["compliance"] == "Extended"
    assert module["firmware_active"] is None


def test_cmis_firmware_comes_from_the_firmware_table(load_fixture):
    transceivers = parse_transceivers(load_fixture("sonic-community.json"))

    assert transceivers["Ethernet4"]["form_factor"] == "QSFP-DD"
    assert transceivers["Ethernet4"]["firmware_active"] == "1.3.0"
    assert transceivers["Ethernet4"]["firmware_inactive"] == "1.2.9"


def test_firmware_in_the_info_table_wins_over_the_firmware_table():
    document = {
        "db": {
            "STATE_DB": {
                "TRANSCEIVER_INFO": {
                    "TRANSCEIVER_INFO|Ethernet0": {
                        "value": {"manufacturer": "X", "active_firmware": "2.0"}
                    }
                },
                "TRANSCEIVER_FIRMWARE_INFO": {
                    "TRANSCEIVER_FIRMWARE_INFO|Ethernet0": {
                        "value": {"active_firmware": "1.0", "inactive_firmware": "0.9"}
                    }
                },
            }
        }
    }

    module = parse_transceivers(document)["Ethernet0"]

    assert module["firmware_active"] == "2.0"
    assert module["firmware_inactive"] == "0.9"


def test_dom_readings(load_fixture):
    readings = parse_dom(load_fixture("sonic-community.json"))

    assert readings["Ethernet0"]["temperature"] == 34.5
    assert readings["Ethernet0"]["voltage"] == 3.281
    assert len(readings["Ethernet0"]["lanes"]) == 4
    assert readings["Ethernet0"]["lanes"][0] == {
        "rx_power": -1.02,
        "tx_power": -0.22,
        "tx_bias": 6.75,
    }
    assert readings["Ethernet4"]["lanes"] == [
        {"rx_power": -2.5, "tx_power": 0.8, "tx_bias": 55.0}
    ]
    assert parse_dom({}) == {}


def test_dom_readings_of_an_enterprise_switch(load_fixture):
    readings = parse_dom(load_fixture("sonic-enterprise.json"))

    # A passive copper cable has an entry with "N/A" for every value
    assert sorted(readings) == ["Ethernet120", "Ethernet124"]
    optic = readings["Ethernet120"]
    assert optic["temperature"] == 39.5703
    assert optic["voltage"] == 3.317
    assert len(optic["lanes"]) == 4
    assert optic["lanes"][0] == {
        "rx_power": 0.599,
        "tx_power": 0.1708,
        "tx_bias": 6.588,
    }


def test_parse_version_file():
    text = "---\nbuild_version: '4.5.0-Enterprise_Base'\nasic_type: broadcom\nbuild_date: Fri Mar 14 09:12:44 UTC 2025\n"

    values = parse_version_file(text)

    assert values["build_version"] == "4.5.0-Enterprise_Base"
    assert values["asic_type"] == "broadcom"
    assert values["build_date"] == "Fri Mar 14 09:12:44 UTC 2025"
    assert parse_version_file(None) == {}


def test_parse_show_version():
    text = "SONiC Software Version: SONiC.202311.1-0a1b2c3d4\nPlatform: x86_64-mlnx_msn3700c-r0\nHwSKU: Mellanox-SN3700C\nASIC: mellanox\nSerial Number: MT2012X04321\n"

    assert parse_show_version(text) == {
        "os_version": "202311.1-0a1b2c3d4",
        "asic": "mellanox",
        "platform": "x86_64-mlnx_msn3700c-r0",
        "hwsku": "Mellanox-SN3700C",
        "serial": "MT2012X04321",
    }
    assert parse_show_version(None)["os_version"] is None
    enterprise = "SONiC Software Version: SONiC-OS-4.5.2-Enterprise_Base\n"
    assert parse_show_version(enterprise)["os_version"] == "4.5.2-Enterprise_Base"


def test_syseeprom_from_state_db(load_fixture):
    assert parse_syseeprom(load_fixture("sonic-enterprise.json")) == {
        # The EEPROM names Accton as manufacturer and Edgecore as vendor
        "system_vendor": "Accton",
        "system_model": "7726-32X-O-AC-B",
        "part_number": "FP3ZZ7632076A",
        "serial": "SN00000001",
        "onie": "2017.11.00.05",
    }


def test_syseeprom_falls_back_to_the_show_command(load_fixture):
    assert parse_syseeprom(load_fixture("sonic-community.json")) == {
        "system_vendor": "Mellanox",
        "system_model": "MSN3700C",
        "part_number": "MSN3700-CS2FO",
        "serial": "MT2012X04321",
        "onie": "2019.11-5.2.0020-9600",
    }


def test_parse_firmware_status_cuts_cells_at_the_column_positions():
    text = (
        "Chassis    Module    Component    Version    Description\n"
        "---------  --------  -----------  ---------  ----------------------------\n"
        "7326-56X   N/A       BIOS         v41.01.00  BIOS - Basic Input/Output System\n"
        "                     CPLD1        0x12       CPLD - Complex Programmable Logic\n"
        "                     FPGA         N/A        FPGA\n"
    )

    assert parse_firmware_status(text) == {"BIOS": "v41.01.00", "CPLD1": "0x12"}


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Error: Platform API is not available",
        "Name  Value\n----  -----\nx     y\n",
    ],
)
def test_parse_firmware_status_without_a_usable_table(text):
    assert parse_firmware_status(text) == {}


def test_system_of_an_enterprise_switch(load_fixture):
    assert parse_system(load_fixture("sonic-enterprise.json")) == {
        "hwsku": "Accton-AS7726-32X",
        "platform": "x86_64-accton_as7726_32x-r0",
        "asic": "broadcom",
        "os_version": "4.5.2-Enterprise_Base",
        "firmware": {
            "bios": "v40.01.01.01",
            "cpld": "CPLD1 14, CPLD2 142, CPLD3 142",
            # Not a component of the firmware status, taken from the EEPROM
            "onie": "2017.11.00.05",
        },
        "system_vendor": "Accton",
        "system_model": "7726-32X-O-AC-B",
        "part_number": "FP3ZZ7632076A",
        "serial": "SN00000001",
        "base_mac": "02:00:00:00:00:20",
    }


def test_system_names_a_single_cpld_and_the_onie_component():
    document = {
        "commands": {
            "show platform firmware status": {
                "rc": 0,
                "err": "",
                "out": (
                    "Chassis    Module    Component    Version    Description\n"
                    "---------  --------  -----------  ---------  -----------\n"
                    "7326-56X   N/A       BIOS         v41.01.00  BIOS\n"
                    "                     ONIE         2018.05    ONIE\n"
                    "                     CPLD1        0x12       CPLD\n"
                ),
            }
        }
    }

    assert parse_system(document)["firmware"] == {
        "bios": "v41.01.00",
        "cpld": "0x12",
        "onie": "2018.05",
    }


def test_system_of_a_community_switch_uses_the_fallbacks(load_fixture):
    """No version file, no EEPROM table and no firmware status on this one."""
    system = parse_system(load_fixture("sonic-community.json"))

    assert system["os_version"] == "202311.1-0a1b2c3d4"
    assert system["asic"] == "mellanox"
    assert system["hwsku"] == "Mellanox-SN3700C"
    assert system["system_model"] == "MSN3700C"
    assert system["serial"] == "MT2012X04321"
    assert system["firmware"] == {
        "bios": None,
        "cpld": None,
        "onie": "2019.11-5.2.0020-9600",
    }


def test_inventory_of_a_switch(load_fixture):
    system, ports = _inventory(load_fixture, "sonic-enterprise.json")

    assert system["hwsku"] == "Accton-AS7726-32X"
    assert sorted(ports, key=lambda name: int(name[8:])) == [
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
    assert "eth0" not in ports
    assert ports["Ethernet120"]["transceiver"]["form_factor"] == "QSFP28"
    assert ports["Ethernet120"]["nic"] is None
    # No entry in TRANSCEIVER_INFO means no module, not a failure
    assert ports["Ethernet24"]["transceiver"]["present"] is False
    assert ports["Ethernet125"]["transceiver"]["present"] is False
    # A module stays visible in a port that is administratively down
    assert ports["Ethernet4"]["admin_status"] == "down"
    assert ports["Ethernet4"]["transceiver"]["present"] is True
    assert "dom" not in ports["Ethernet0"]["transceiver"]


def test_inventory_of_a_switch_with_diagnostics(load_fixture):
    _, ports = _inventory(load_fixture, "sonic-enterprise.json", dom=True)

    assert ports["Ethernet120"]["transceiver"]["dom"]["temperature"] == 39.5703
    # A passive copper cable has no diagnostics, an empty cage no module
    assert ports["Ethernet0"]["transceiver"]["dom"] is None
    assert ports["Ethernet24"]["transceiver"]["dom"] is None


def test_inventory_with_diagnostics(load_fixture):
    _, ports = _inventory(load_fixture, "sonic-community.json", dom=True)

    assert ports["Ethernet0"]["transceiver"]["dom"]["temperature"] == 34.5
    assert ports["Ethernet8"]["transceiver"]["present"] is False
    assert ports["Ethernet8"]["transceiver"]["dom"] is None
