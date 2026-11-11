# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.parse_linux``."""

import json

import pytest

from osism.utils.hardware.parse_linux import (
    command_output,
    oper_status,
    parse_devlink,
    parse_ethtool,
    parse_ethtool_driver,
    parse_ethtool_fec,
    parse_infiniband,
    parse_inventory,
    parse_ip_link,
    parse_key_values,
    parse_lspci,
    parse_module,
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


# ---------------------------------------------------------------------------
# Hardware view: link settings, driver, module, NIC
# ---------------------------------------------------------------------------


def _inventory(load_fixture, name, dom=False):
    system, interfaces = parse_inventory(load_fixture(name), dom)
    return system, {interface["name"]: interface for interface in interfaces}


def test_parse_key_values_splits_at_the_first_colon_and_joins_continuations():
    text = (
        "Settings for eth0:\n"
        "\tSupported link modes:   1000baseT/Full\n"
        "\t                        10000baseT/Full\n"
        "\tVendor OUI                : 00:90:65\n"
        "\n"
        "\tTransceiver type          : 10G Ethernet: 10G Base-SR\n"
    )

    assert parse_key_values(text) == [
        ("Settings for eth0", ""),
        ("Supported link modes", "1000baseT/Full 10000baseT/Full"),
        ("Vendor OUI", "00:90:65"),
        ("Transceiver type", "10G Ethernet: 10G Base-SR"),
    ]
    assert parse_key_values(None) == []


def test_parse_ethtool_link_settings():
    up = _ok(
        "Settings for eth0:\n\tSpeed: 25000Mb/s\n\tDuplex: Full\n"
        "\tAuto-negotiation: on\n\tPort: Direct Attach Copper\n\tLink detected: yes\n"
    )
    down = _ok(
        "Settings for eth0:\n\tSpeed: Unknown!\n\tDuplex: Unknown! (255)\n"
        "\tAuto-negotiation: off\n\tPort: FIBRE\n\tLink detected: no\n"
    )

    assert parse_ethtool(up) == {
        "speed": 25000,
        "duplex": "full",
        "autoneg": True,
        "port_type": "Direct Attach Copper",
        "link_detected": True,
    }
    assert parse_ethtool(down) == {
        "speed": None,
        "duplex": None,
        "autoneg": False,
        "port_type": "FIBRE",
        "link_detected": False,
    }
    assert parse_ethtool(None)["speed"] is None


def test_parse_ethtool_driver():
    result = _ok(
        "driver: mlx5_core\nversion: 6.8.0-51-generic\n"
        "firmware-version: 16.35.2000 (MT_0000000080)\nexpansion-rom-version: \n"
        "bus-info: 0000:3b:00.0\n"
    )

    assert parse_ethtool_driver(result) == {
        "driver": "mlx5_core",
        "driver_version": "6.8.0-51-generic",
        "firmware_version": "16.35.2000 (MT_0000000080)",
        "pci_address": "0000:3b:00.0",
    }


def test_parse_ethtool_fec():
    text = "FEC parameters for eth0:\nConfigured FEC encodings: Auto RS\nActive FEC encoding: RS\n"

    assert parse_ethtool_fec(_ok(text)) == "rs"
    assert parse_ethtool_fec({"rc": 1, "out": "", "err": "not supported"}) is None


def test_module_of_a_passive_copper_cable(load_fixture):
    _, ports = _inventory(load_fixture, "linux-mellanox.json")

    module = ports["ens1f0np0"]["transceiver"]

    assert module["present"] is True
    assert module["form_factor"] == "SFP"
    assert module["connector"] == "Copper pigtail"
    assert module["vendor"] == "Mellanox"
    assert module["vendor_oui"] == "00:02:c9"
    assert module["part_number"] == "MCP2M00-A003E30L"
    assert module["serial"] == "MT2114VS01234"
    assert module["revision"] == "A3"
    assert module["date_code"] == "2021-04-08"
    assert module["cable_length"] == "3m"
    assert module["wavelength"] is None
    assert "Extended: 25G Base-CR CA-N" in module["compliance"]
    # SFF-8472 modules have a vendor revision but no firmware field
    assert module["firmware_active"] is None
    assert "dom" not in module


def test_module_of_an_optic_with_diagnostics(load_fixture):
    _, ports = _inventory(load_fixture, "linux-mellanox.json", dom=True)

    module = ports["ens1f1np1"]["transceiver"]

    assert module["form_factor"] == "SFP"
    assert module["connector"] == "LC"
    assert module["part_number"] == "SFP28-25GSR-85"
    assert module["cable_length"] == "70m"
    assert module["wavelength"] == "850nm"
    # Readings, not the alarm thresholds printed with the same names
    assert module["dom"] == {
        "temperature": 33.45,
        "voltage": 3.2934,
        "lanes": [{"rx_power": -3.47, "tx_power": -2.35, "tx_bias": 6.212}],
    }


def test_module_with_several_lanes(load_fixture):
    _, ports = _inventory(load_fixture, "linux-intel.json", dom=True)

    module = ports["enp65s0f0"]["transceiver"]

    assert module["form_factor"] == "QSFP28"
    assert module["connector"] == "MPO Parallel Optic"
    assert module["vendor"] == "Intel Corp"
    assert module["dom"]["temperature"] == 31.0
    assert module["dom"]["lanes"] == [
        {"rx_power": -0.86, "tx_power": -0.22, "tx_bias": 6.75},
        {"rx_power": -0.97, "tx_power": -0.32, "tx_bias": 6.812},
        {"rx_power": -1.02, "tx_power": -0.13, "tx_bias": 6.7},
        {"rx_power": -0.92, "tx_power": -0.41, "tx_bias": 6.79},
    ]


def test_cmis_module_exposes_its_firmware(load_fixture):
    _, ports = _inventory(load_fixture, "linux-intel.json")

    module = ports["enp66s0"]["transceiver"]

    assert module["form_factor"] == "QSFP-DD"
    assert module["connector"] == "MPO 1x16"
    assert module["firmware_active"] == "2.9"
    assert module["firmware_inactive"] == "2.8"
    assert module["cable_length"] == "100m"


@pytest.mark.parametrize(
    "result",
    [
        {"rc": 75, "out": "", "err": "netlink error: Operation not supported"},
        {"rc": 1, "out": "", "err": "Cannot get module EEPROM information"},
        {"rc": 0, "out": "", "err": ""},
        None,
    ],
)
def test_port_without_a_module_is_not_present(result):
    module = parse_module(result, dom=True)

    assert module["present"] is False
    assert module["vendor"] is None
    assert module["form_factor"] is None


def test_ports_without_a_module_are_reported_not_failed(load_fixture):
    _, mellanox = _inventory(load_fixture, "linux-mellanox.json")
    _, intel = _inventory(load_fixture, "linux-intel.json")

    # RJ45 port without a cage, and an empty QSFP28 cage
    assert mellanox["eno1"]["transceiver"]["present"] is False
    assert intel["enp65s0f1"]["transceiver"]["present"] is False
    assert intel["enp65s0f1"]["oper_status"] == "down"
    assert intel["enp65s0f1"]["nic"]["model"] == "Ethernet Controller E810-C for QSFP"


def test_parse_lspci_splits_names_and_ids():
    result = _ok(
        "Slot:\t0000:3b:00.0\nClass:\tEthernet controller [0200]\n"
        "Vendor:\tMellanox Technologies [15b3]\n"
        "Device:\tMT27800 Family [ConnectX-5] [1017]\n"
        "SVendor:\tMellanox Technologies [15b3]\n"
        "SDevice:\tConnectX-5 EN network interface card [0080]\nRev:\t00\n"
    )

    assert parse_lspci(result) == {
        "vendor": "Mellanox Technologies",
        "vendor_id": "15b3",
        "model": "MT27800 Family [ConnectX-5]",
        "model_id": "1017",
        "subsystem_vendor": "Mellanox Technologies",
        "subsystem_model": "ConnectX-5 EN network interface card",
        "revision": "00",
    }
    assert parse_lspci({"rc": 127, "out": "", "err": ""})["vendor"] is None


def test_parse_devlink():
    info = {
        "info": {
            "pci/0000:41:00.0": {
                "driver": "ice",
                "serial_number": "00-01-00-ff-ff-00-00-00",
                "versions": {
                    "fixed": {"board.id": "K91258-006"},
                    "running": {"fw.mgmt": "7.4.13"},
                    "stored": {},
                },
            }
        }
    }

    assert parse_devlink(_ok(json.dumps(info))) == {
        "serial": "00-01-00-ff-ff-00-00-00",
        "board_id": "K91258-006",
        "firmware": {"running": {"fw.mgmt": "7.4.13"}},
    }
    # devlink prints an empty document next to its error for a USB NIC
    empty = {"serial": None, "board_id": None, "firmware": None}
    assert parse_devlink({"rc": 1, "out": '{"info":{}}', "err": "x"}) == empty
    assert parse_devlink(_ok("not json")) == empty
    assert parse_devlink(_ok('{"info": {}}')) == empty
    assert parse_devlink({"rc": 1, "out": "", "err": "not supported"}) == empty


def test_parse_devlink_prefers_the_serial_number_of_the_board():
    info = {
        "info": {
            "pci/0000:98:00.0": {
                "driver": "bnxt_en",
                "serial_number": "02-00-00-FF-FE-00-00-03",
                "board.serial_number": "SN00000009",
                "versions": {"fixed": {"board.id": "BCM957414A4142CC"}},
            }
        }
    }

    assert parse_devlink(_ok(json.dumps(info))) == {
        "serial": "SN00000009",
        "board_id": "BCM957414A4142CC",
        "firmware": None,
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"state": "4: ACTIVE", "rate": "100 Gb/sec (4X EDR)"}, ("up", 100000)),
        ({"state": "1: DOWN", "rate": "2.5 Gb/sec (1X SDR)"}, ("down", 2500)),
        ({"state": None, "rate": None}, (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_infiniband(raw, expected):
    link = parse_infiniband(raw)

    assert (link["oper_status"], link["speed"]) == expected


def test_inventory_of_a_mellanox_node(load_fixture):
    system, ports = _inventory(load_fixture, "linux-mellanox.json")

    assert system == {
        "system_vendor": "Supermicro",
        "system_model": "SYS-120C-TN10R",
        "serial": "S123456X0A01234",
    }
    port = ports["ens1f0np0"]
    assert port["speed"] == 25000
    assert port["duplex"] == "full"
    assert port["autoneg"] is True
    assert port["fec"] == "rs"
    assert port["port_type"] == "Direct Attach Copper"
    assert port["nic"] == {
        "pci_address": "0000:3b:00.0",
        "vendor": "Mellanox Technologies",
        "model": "MT27800 Family [ConnectX-5]",
        "subsystem_vendor": "Mellanox Technologies",
        "subsystem_model": "ConnectX-5 EN network interface card, 25GbE dual-port SFP28",
        "revision": "00",
        "serial": None,
        "board_id": "MT_0000000080",
        "driver": "mlx5_core",
        "driver_version": "6.8.0-51-generic",
        "firmware_version": "16.35.2000 (MT_0000000080)",
        "firmware": {
            "running": {"fw.version": "16.35.2000", "fw": "16.35.2000"},
            "stored": {"fw.version": "16.35.2000", "fw": "16.35.2000"},
        },
    }
    # The onboard port has no devlink support and no FEC
    assert ports["eno1"]["nic"]["driver"] == "igb"
    assert ports["eno1"]["nic"]["firmware"] is None
    assert ports["eno1"]["fec"] is None
    assert ports["eno2"]["speed"] is None


def test_inventory_of_an_intel_node(load_fixture):
    system, ports = _inventory(load_fixture, "linux-intel.json")

    assert system["system_model"] == "PowerEdge R750"
    nic = ports["enp65s0f0"]["nic"]
    assert nic["vendor"] == "Intel Corporation"
    assert nic["model"] == "Ethernet Controller E810-C for QSFP"
    assert nic["driver"] == "ice"
    assert nic["firmware_version"] == "4.40 0x8001c7d4 1.3534.0"
    assert nic["serial"] == "00-01-00-ff-ff-00-00-00"
    assert nic["board_id"] == "K91258-006"
    assert ports["enp65s0f0"]["speed"] == 100000
    assert ports["enp66s0"]["speed"] == 400000


def test_inventory_of_a_broadcom_node_without_optional_tools(load_fixture):
    """lspci and devlink are missing on this node. Their fields stay empty."""
    system, ports = _inventory(load_fixture, "linux-broadcom.json")

    assert system["system_vendor"] == "HPE"
    nic = ports["ens2f0np0"]["nic"]
    assert nic["driver"] == "bnxt_en"
    assert nic["firmware_version"] == "229.0.141.0/pkg 229.1.123.0"
    assert nic["pci_address"] == "0000:12:00.0"
    assert nic["vendor"] is None and nic["model"] is None
    assert nic["serial"] is None and nic["firmware"] is None
    assert ports["ens2f0np0"]["fec"] == "baser"
    assert ports["ens2f1np1"]["speed"] == 10000
    assert ports["ens2f1np1"]["transceiver"]["part_number"] == "SFP28-25GSR-85"


def test_inventory_marks_virtual_functions_and_infiniband_ports(load_fixture):
    _, ports = _inventory(load_fixture, "linux-mellanox-vf-ib.json")

    assert {name: port["kind"] for name, port in ports.items()} == {
        "ens3f0np0": "physical",
        "ens3f0v0": "vf",
        "ibp129s0": "infiniband",
    }

    vf = ports["ens3f0v0"]
    assert vf["parent"] == "ens3f0np0"
    assert vf["mac"] == "02:00:00:00:00:01"
    assert vf["nic"]["driver"] == "mlx5_core"
    # The module belongs to the physical function and is not repeated
    assert vf["transceiver"]["present"] is None
    assert vf["transceiver"]["vendor"] is None

    ib = ports["ibp129s0"]
    assert ib["oper_status"] == "up"
    assert ib["speed"] == 100000
    assert ib["transceiver"]["form_factor"] == "QSFP28"


# ---------------------------------------------------------------------------
# Captured nodes
# ---------------------------------------------------------------------------


def test_inventory_of_a_captured_connectx4_node(load_fixture):
    system, ports = _inventory(load_fixture, "linux-connectx4.json")

    assert system == {
        "system_vendor": "Supermicro",
        "system_model": "X10DRi",
        "serial": "SN00000003",
    }
    port = ports["ens4f0np0"]
    assert port["speed"] == 25000
    assert port["duplex"] == "full"
    assert port["autoneg"] is True
    assert port["port_type"] == "Direct Attach Copper"
    assert port["fec"] == "off"
    assert port["nic"] == {
        "pci_address": "0000:82:00.0",
        "vendor": "Mellanox Technologies",
        "model": "MT27710 Family [ConnectX-4 Lx]",
        "subsystem_vendor": "Mellanox Technologies",
        "subsystem_model": (
            "Stand-up ConnectX-4 Lx EN, 25GbE dual-port SFP28, PCIe3.0 x8,"
            " MCX4121A-ACAT"
        ),
        "revision": None,
        # mlx5_core reports no serial number for this card
        "serial": None,
        "board_id": "MT_2420110034",
        "driver": "mlx5_core",
        "driver_version": "6.8.0-136-generic",
        "firmware_version": "14.32.1010 (MT_2420110034)",
        "firmware": {
            "running": {"fw.version": "14.32.1010", "fw": "14.32.1010"},
            "stored": {"fw.version": "14.32.1010", "fw": "14.32.1010"},
        },
    }
    # One SFP28 end of a QSFP28 to 4x SFP28 breakout cable
    assert port["transceiver"] == {
        "present": True,
        "form_factor": "SFP",
        "connector": "Copper pigtail",
        "vendor": "FS",
        "vendor_oui": "64:9d:99",
        "part_number": "Q-4S28PC02",
        "serial": "SN00000004-1",
        "revision": "01",
        "date_code": "2022-09-07",
        "firmware_active": None,
        "firmware_inactive": None,
        "compliance": "Passive Cable; Extended: 25G Base-CR CA-S",
        "cable_length": "2m",
        "wavelength": None,
    }

    # An onboard RJ45 port: ethtool -m is not supported, devlink is silent
    onboard = ports["enp4s0f0"]
    assert onboard["port_type"] == "Twisted Pair"
    assert onboard["transceiver"]["present"] is False
    assert onboard["nic"]["driver"] == "igb"
    assert onboard["nic"]["model"] == "I350 Gigabit Network Connection"
    assert onboard["nic"]["firmware"] is None
    # A port without link reports "Unknown!" as speed and duplex
    assert ports["enp4s0f1"]["speed"] is None
    assert ports["enp4s0f1"]["duplex"] is None


def test_inventory_of_a_captured_broadcom_node(load_fixture):
    _, ports = _inventory(load_fixture, "linux-bcm57414.json")

    assert sorted(ports) == ["data1", "data2", "eno2np1", "enx02000000001f", "mgmt1"]
    nic = ports["data1"]["nic"]
    assert nic["vendor"] == "Broadcom Inc. and subsidiaries"
    assert nic["model"] == "BCM57414 NetXtreme-E 10Gb/25Gb RDMA Ethernet Controller"
    assert nic["driver"] == "bnxt_en"
    assert nic["firmware_version"] == "214.4.91.1/pkg 216.0.333.11"
    # The serial number of the board, not the one derived from the MAC
    assert nic["serial"] == "SN00000009"
    assert nic["board_id"] == "BCM957414A4142CC"
    assert nic["firmware"]["running"]["fw.mgmt"] == "214.4.91.1"
    assert ports["data1"]["transceiver"]["cable_length"] == "3m"
    assert ports["data1"]["altnames"] == ["enp152s0f0np0"]

    # 10GBASE-T ports of an Intel X710 on the same node
    assert ports["mgmt1"]["nic"]["driver"] == "i40e"
    assert ports["mgmt1"]["speed"] == 1000
    assert ports["mgmt1"]["transceiver"]["present"] is False
    assert ports["eno2np1"]["oper_status"] == "down"
    assert ports["eno2np1"]["port_type"] == "Other"


def test_usb_nic_of_a_bmc_is_a_port_without_pci_device(load_fixture):
    """The host interface of the BMC shows up as a USB network device."""
    _, ports = _inventory(load_fixture, "linux-bcm57414.json")

    port = ports["enx02000000001f"]
    assert port["kind"] == "physical"
    assert port["oper_status"] == "down"
    assert port["pci_address"] is None
    assert port["fec"] is None
    assert port["transceiver"]["present"] is False
    assert port["nic"] == {
        "pci_address": None,
        "vendor": None,
        "model": None,
        "subsystem_vendor": None,
        "subsystem_model": None,
        "revision": None,
        "serial": None,
        "board_id": None,
        "driver": "rndis_host",
        "driver_version": "7.0.0-31-generic",
        "firmware_version": "RNDIS device",
        "firmware": None,
    }


def test_inventory_of_a_captured_82599_node(load_fixture):
    system, ports = _inventory(load_fixture, "linux-82599.json")

    assert system["system_model"] == "SYS-530MT-H12TRF"
    port = ports["data2"]
    # A 10G port on a 25G capable cable; ixgbe does not report FEC
    assert port["speed"] == 10000
    assert port["autoneg"] is False
    assert port["fec"] is None
    assert port["nic"]["driver"] == "ixgbe"
    assert port["nic"]["model"] == "82599ES 10-Gigabit SFI/SFP+ Network Connection"
    assert port["nic"]["firmware_version"] == "0x800006da, 1.2527.0"
    assert port["nic"]["firmware"] == {
        "running": {"fw.undi": "1.2527.0", "fw.bundle_id": "0x800006da"}
    }
    assert port["transceiver"]["part_number"] == "QSFP-100G-4SPC02"
    assert port["transceiver"]["serial"] == "SN00000015-3"
