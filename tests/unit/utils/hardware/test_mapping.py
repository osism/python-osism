# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.mapping``."""

from pathlib import Path
from unittest.mock import MagicMock

import pynetbox
import pytest
from pynetbox.models.dcim import Interfaces

from osism.tasks.conductor.sonic import interface as sonic_interface
from osism.tasks.conductor.sonic.cache import clear_interface_cache
from osism.utils.hardware.mapping import (
    Endpoint,
    Match,
    NetboxInterface,
    fetch_devices,
    fetch_interfaces,
    find_devices,
    interface_from_netbox,
    map_node_ports,
    map_switch_ports,
    neighbour_is_endpoint,
    neighbour_port_names,
    physical_interfaces,
    same_system,
    sonic_alias_index,
    sonic_name_index,
)
from osism.utils.hardware.parse_lldp import neighbour

REPO_ROOT = Path(__file__).resolve().parents[4]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_interface(interface_id, name, device_id=1, device="leaf-1a", **extra):
    """Interface as the NetBox API returns it in a list response."""
    data = {
        "id": interface_id,
        "url": f"http://netbox.invalid/api/dcim/interfaces/{interface_id}/",
        "name": name,
        "label": "",
        "type": {"value": "25gbase-x-sfp28", "label": "SFP28 (25GE)"},
        "device": {
            "id": device_id,
            "url": f"http://netbox.invalid/api/dcim/devices/{device_id}/",
            "name": device,
        },
        "mgmt_only": False,
        "mac_address": None,
        "cable": None,
        "connected_endpoints": None,
        "connected_endpoints_type": None,
        "connected_endpoints_reachable": None,
    }
    data.update(extra)
    return data


def _peer(interface_id, name, device_id, device):
    return {
        "id": interface_id,
        "url": f"http://netbox.invalid/api/dcim/interfaces/{interface_id}/",
        "name": name,
        "device": {
            "id": device_id,
            "url": f"http://netbox.invalid/api/dcim/devices/{device_id}/",
            "name": device,
        },
    }


def _cabled(interface_id, name, peers, **extra):
    return _api_interface(
        interface_id,
        name,
        cable={
            "id": 900 + interface_id,
            "url": "http://netbox.invalid/api/dcim/cables/1/",
        },
        connected_endpoints=peers,
        connected_endpoints_type="dcim.interface",
        connected_endpoints_reachable=True,
        **extra,
    )


def _iface(interface_id, name, **kwargs):
    kwargs.setdefault("device_id", 1)
    kwargs.setdefault("device", "dev")
    return NetboxInterface(id=interface_id, name=name, **kwargs)


def _port(name, **kwargs):
    port = {"name": name, "kind": "physical", "altnames": []}
    port.update(kwargs)
    return port


def _methods(matches):
    return {
        name: (match.interface.name if match.interface else None, match.method)
        for name, match in matches.items()
    }


# ---------------------------------------------------------------------------
# Conversion of NetBox data
# ---------------------------------------------------------------------------


def test_interface_without_cable():
    interface = interface_from_netbox(_api_interface(5, "Eth1/1", label="port 1"))

    assert interface == NetboxInterface(
        id=5,
        device_id=1,
        device="leaf-1a",
        name="Eth1/1",
        label="port 1",
        type="25gbase-x-sfp28",
    )
    assert interface.has_cable is False
    assert interface.path_incomplete is False
    assert interface.is_virtual is False


def test_interface_with_a_reachable_peer():
    interface = interface_from_netbox(
        _cabled(5, "Eth1/1", [_peer(77, "ens1f0", 10, "compute-041")])
    )

    assert interface.has_cable is True
    assert interface.endpoints == [
        Endpoint(
            device="compute-041", interface="ens1f0", device_id=10, interface_id=77
        )
    ]
    assert interface.path_incomplete is False


def test_breakout_cable_has_several_endpoints():
    interface = interface_from_netbox(
        _cabled(
            5,
            "Eth1/49",
            [
                _peer(77, "ens1f0", 10, "compute-041"),
                _peer(78, "ens1f0", 11, "compute-042"),
            ],
        )
    )

    assert [(e.device, e.interface) for e in interface.endpoints] == [
        ("compute-041", "ens1f0"),
        ("compute-042", "ens1f0"),
    ]


@pytest.mark.parametrize(
    "overrides",
    [
        # The path ends at a patch panel port
        {"connected_endpoints": None},
        # The path ends at a circuit termination
        {
            "connected_endpoints": [{"id": 3, "url": "http://netbox.invalid/x/3/"}],
            "connected_endpoints_type": "circuits.circuittermination",
        },
        # A cable of the path is marked as not connected
        {"connected_endpoints_reachable": False},
    ],
)
def test_cable_path_that_does_not_end_at_an_interface_is_incomplete(overrides):
    data = _cabled(5, "Eth1/1", [_peer(77, "ens1f0", 10, "compute-041")])
    data.update(overrides)

    interface = interface_from_netbox(data)

    assert interface.endpoints == []
    assert interface.path_incomplete is True


def test_mac_addresses_of_old_and_new_netbox_are_merged():
    interface = interface_from_netbox(
        _api_interface(
            5,
            "ens1f0",
            mac_address="AA:BB:CC:00:00:01",
            primary_mac_address={"id": 1, "mac_address": "AA:BB:CC:00:00:01"},
            mac_addresses=[
                {"id": 1, "mac_address": "AA:BB:CC:00:00:01"},
                {"id": 2, "mac_address": "AA:BB:CC:00:00:02"},
            ],
        )
    )

    assert interface.macs == ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02"]


def test_virtual_and_management_interfaces_can_be_dropped():
    interfaces = [
        _iface(1, "Eth1/1"),
        _iface(2, "PortChannel1", type="lag"),
        _iface(3, "Vlan100", type="virtual"),
        _iface(4, "br0", type="bridge"),
        _iface(5, "eth0", mgmt_only=True),
    ]

    assert [i.name for i in physical_interfaces(interfaces)] == ["Eth1/1", "eth0"]
    assert [i.name for i in physical_interfaces(interfaces, include_mgmt=False)] == [
        "Eth1/1"
    ]


def test_fetch_interfaces_queries_in_chunks():
    nb = MagicMock()
    nb.dcim.interfaces.filter.side_effect = [
        [
            _api_interface(1, "Eth1/1", device_id=1),
            _api_interface(2, "Eth1/1", device_id=2),
        ],
        [_api_interface(3, "Eth1/1", device_id=3)],
    ]

    interfaces = fetch_interfaces(nb, [3, 1, 2, 1, 4], chunk_size=2)

    assert [c.kwargs for c in nb.dcim.interfaces.filter.call_args_list] == [
        {"device_id": [1, 2]},
        {"device_id": [3, 4]},
    ]
    assert {
        device_id: [i.id for i in found] for device_id, found in interfaces.items()
    } == {
        1: [1],
        2: [2],
        3: [3],
        4: [],
    }


def test_fetch_interfaces_reads_pynetbox_records_without_further_requests():
    """A list response on NetBox before 4.2 has no ``mac_addresses``.

    Reading a missing attribute from a pynetbox record fetches the record
    again. The API object points at a host that does not exist, so any such
    request would make this test fail.
    """
    api = pynetbox.api("http://netbox.invalid", token="unused")
    record = Interfaces(
        _cabled(
            5,
            "Eth1/1",
            [_peer(77, "ens1f0", 10, "compute-041")],
            mac_address="AA:BB:CC:00:00:01",
        ),
        api,
        None,
    )
    nb = MagicMock()
    nb.dcim.interfaces.filter.return_value = [record]

    (interface,) = fetch_interfaces(nb, [1])[1]

    assert interface.name == "Eth1/1"
    assert interface.macs == ["aa:bb:cc:00:00:01"]
    assert interface.endpoints == [
        Endpoint(
            device="compute-041", interface="ens1f0", device_id=10, interface_id=77
        )
    ]
    assert record.has_details is False


# ---------------------------------------------------------------------------
# SONiC name index
# ---------------------------------------------------------------------------


@pytest.fixture
def port_config(monkeypatch, mocker):
    """Use the port config files of the repository and forbid NetBox access."""
    monkeypatch.setattr(
        sonic_interface, "PORT_CONFIG_PATH", str(REPO_ROOT / "files/sonic/port_config")
    )
    sonic_interface.clear_port_config_cache()
    nb = MagicMock()
    mocker.patch("osism.utils.nb", new=nb, create=True)
    yield nb
    sonic_interface.clear_port_config_cache()
    clear_interface_cache()


def test_sonic_name_index_translates_through_the_port_config(port_config):
    interfaces = [
        _iface(1, "Eth1/1"),
        _iface(2, "Eth1/12"),
        _iface(3, "Ethernet52"),
        _iface(4, "PortChannel1", type="lag"),
        _iface(5, "eth0", mgmt_only=True),
    ]

    index = sonic_name_index(1, "leaf-1a", "Accton-AS7326-56X", interfaces)

    assert {name: i.name for name, i in index.items()} == {
        "Ethernet0": "Eth1/1",
        "Ethernet11": "Eth1/12",
    }
    # The interfaces were handed to the cache instead of being fetched again
    port_config.dcim.interfaces.filter.assert_not_called()


def test_sonic_name_index_needs_hwsku_and_port_config(port_config, loguru_logs):
    interfaces = [_iface(1, "Eth1/1")]

    assert sonic_name_index(1, "leaf-1a", None, interfaces) == {}
    assert sonic_name_index(None, "leaf-1a", "Accton-AS7326-56X", interfaces) == {}
    assert sonic_name_index(1, "leaf-1a", "No-Such-HWSKU", interfaces) == {}
    # No per-interface warning for a switch that cannot be translated
    assert not any("No HWSKU found" in r["message"] for r in loguru_logs)


def test_sonic_alias_index_maps_vendor_aliases_to_port_names(port_config):
    index = sonic_alias_index("Accton-AS7326-56X")

    assert index["twentyFiveGigE1"] == "Ethernet0"
    assert index["twentyFiveGigE12"] == "Ethernet11"
    assert sonic_alias_index(None) == {}
    assert sonic_alias_index("No-Such-HWSKU") == {}


# ---------------------------------------------------------------------------
# NetBox devices
# ---------------------------------------------------------------------------


def test_fetch_devices_queries_by_id_in_chunks():
    nb = MagicMock()
    nb.dcim.devices.filter.side_effect = [
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        [{"id": 3, "name": "c"}],
    ]

    devices = fetch_devices(nb, [3, 1, 2, 1], chunk_size=2)

    assert [c.kwargs for c in nb.dcim.devices.filter.call_args_list] == [
        {"id": [1, 2]},
        {"id": [3]},
    ]
    assert [device["name"] for device in devices] == ["a", "b", "c"]
    assert fetch_devices(nb, []) == []


def test_find_devices_ignores_case_and_tries_the_short_name():
    nb = MagicMock()
    nb.dcim.devices.filter.return_value = [
        {"id": 1, "name": "leaf-1c"},
        {"id": 1, "name": "leaf-1c"},
        {"id": 2, "name": "tor-9"},
    ]

    devices = find_devices(nb, ["Leaf-1C.example.com", "tor-9", "tor-9"])

    nb.dcim.devices.filter.assert_called_once_with(
        name__ie=["Leaf-1C.example.com", "Leaf-1C", "tor-9"]
    )
    assert [device["id"] for device in devices] == [1, 2]
    assert find_devices(MagicMock(), []) == []


# ---------------------------------------------------------------------------
# Switch mapping
# ---------------------------------------------------------------------------


def test_switch_ports_match_by_port_config_alias_and_name():
    interfaces = [
        _iface(1, "Eth1/1"),
        _iface(2, "Eth1/2"),
        _iface(3, "Ethernet8"),
        _iface(4, "Eth1/9"),
    ]
    ports = [
        _port("Ethernet0", alias="twentyFiveGigE1"),
        _port("Ethernet4", alias="Eth1/2"),
        _port("Ethernet8", alias="twentyFiveGigE3"),
        _port("Ethernet12", alias="twentyFiveGigE4"),
    ]

    matches, unmatched = map_switch_ports(
        ports, interfaces, {"Ethernet0": interfaces[0]}
    )

    assert _methods(matches) == {
        "Ethernet0": ("Eth1/1", "port-config"),
        "Ethernet4": ("Eth1/2", "alias"),
        "Ethernet8": ("Ethernet8", "name"),
        "Ethernet12": (None, "none"),
    }
    assert [i.name for i in unmatched] == ["Eth1/9"]


def test_port_config_wins_over_a_conflicting_alias():
    interfaces = [_iface(1, "Eth1/1"), _iface(2, "Eth1/2")]
    ports = [_port("Ethernet0", alias="Eth1/2"), _port("Ethernet4", alias="Eth1/2")]

    matches, unmatched = map_switch_ports(
        ports, interfaces, {"Ethernet0": interfaces[0]}
    )

    assert _methods(matches) == {
        "Ethernet0": ("Eth1/1", "port-config"),
        "Ethernet4": ("Eth1/2", "alias"),
    }
    assert unmatched == []


def test_an_interface_is_matched_to_one_port_only():
    interfaces = [_iface(1, "Eth1/1")]
    ports = [_port("Ethernet0", alias="Eth1/1"), _port("Ethernet4", alias="Eth1/1")]

    matches, _ = map_switch_ports(ports, interfaces)

    assert _methods(matches) == {
        "Ethernet0": ("Eth1/1", "alias"),
        "Ethernet4": (None, "none"),
    }


def test_port_config_index_only_counts_for_the_given_interfaces():
    hidden = _iface(9, "Eth1/1")

    matches, _ = map_switch_ports([_port("Ethernet0")], [], {"Ethernet0": hidden})

    assert matches == {"Ethernet0": Match()}


@pytest.mark.parametrize(
    "mgmt_interfaces,expected",
    [
        (
            [
                _iface(7, "mgmt0", mgmt_only=True, macs=["aa:aa:aa:00:00:01"]),
                _iface(8, "eth0", mgmt_only=True),
            ],
            ("mgmt0", "mac"),
        ),
        (
            [_iface(7, "mgmt0", mgmt_only=True), _iface(8, "eth0", mgmt_only=True)],
            ("eth0", "name"),
        ),
        ([_iface(7, "Management1", mgmt_only=True)], ("Management1", "mgmt-only")),
        (
            [_iface(7, "mgmt0", mgmt_only=True), _iface(8, "mgmt1", mgmt_only=True)],
            (None, "none"),
        ),
        ([], (None, "none")),
    ],
)
def test_management_port_matches_management_interfaces(mgmt_interfaces, expected):
    interfaces = [_iface(1, "Eth1/1"), *mgmt_interfaces]
    ports = [
        _port("Ethernet0", alias="Eth1/1"),
        _port(
            "eth0",
            kind="mgmt",
            mac="aa:aa:aa:00:00:01",
            permanent_mac="aa:aa:aa:00:00:01",
        ),
    ]

    matches, _ = map_switch_ports(ports, interfaces)

    assert _methods(matches)["eth0"] == expected
    assert _methods(matches)["Ethernet0"] == ("Eth1/1", "alias")


def test_front_panel_port_never_matches_a_management_interface():
    interfaces = [_iface(7, "Ethernet0", mgmt_only=True)]

    matches, unmatched = map_switch_ports([_port("Ethernet0")], interfaces)

    assert matches == {"Ethernet0": Match()}
    assert unmatched == interfaces


# ---------------------------------------------------------------------------
# Node mapping
# ---------------------------------------------------------------------------


def test_node_ports_match_by_mac_name_and_label():
    interfaces = [
        _iface(1, "nic1-port1", macs=["b8:ce:f6:aa:00:10"]),
        _iface(2, "enp59s0f1np1"),
        _iface(3, "Port 3", label="eno1"),
        _iface(4, "eno9"),
    ]
    ports = [
        _port("ens1f0np0", permanent_mac="b8:ce:f6:aa:00:10"),
        _port(
            "ens1f1np1", permanent_mac="b8:ce:f6:aa:00:11", altnames=["enp59s0f1np1"]
        ),
        _port("eno1", permanent_mac="3c:ec:ef:10:20:30"),
        _port("eno2", permanent_mac="3c:ec:ef:10:20:31"),
    ]

    matches, unmatched = map_node_ports(ports, interfaces)

    assert _methods(matches) == {
        "ens1f0np0": ("nic1-port1", "mac"),
        "ens1f1np1": ("enp59s0f1np1", "name"),
        "eno1": ("Port 3", "label"),
        "eno2": (None, "none"),
    }
    assert [i.name for i in unmatched] == ["eno9"]


def test_bond_members_match_by_permanent_mac_not_by_bond_mac():
    interfaces = [
        _iface(1, "p1", macs=["b8:ce:f6:aa:00:10"]),
        _iface(2, "p2", macs=["b8:ce:f6:aa:00:11"]),
    ]
    ports = [
        _port("ens1f1np1", mac="b8:ce:f6:aa:00:10", permanent_mac="b8:ce:f6:aa:00:11"),
        _port("ens1f0np0", mac="b8:ce:f6:aa:00:10", permanent_mac="b8:ce:f6:aa:00:10"),
    ]

    matches, _ = map_node_ports(ports, interfaces)

    assert _methods(matches) == {
        "ens1f1np1": ("p2", "mac"),
        "ens1f0np0": ("p1", "mac"),
    }


def test_mac_match_wins_over_a_name_match():
    interfaces = [_iface(1, "eth0"), _iface(2, "eth1", macs=["aa:aa:aa:00:00:01"])]
    ports = [_port("eth0", permanent_mac="aa:aa:aa:00:00:01")]

    matches, _ = map_node_ports(ports, interfaces)

    assert _methods(matches) == {"eth0": ("eth1", "mac")}


def test_node_port_matches_by_lldp_neighbour_when_it_is_unambiguous():
    interfaces = [
        _iface(1, "nic-a", endpoints=[Endpoint("leaf-1a", "Eth1/12")]),
        _iface(2, "nic-b", endpoints=[Endpoint("leaf-1b", "Eth1/12")]),
    ]
    ports = [_port("ens1f0"), _port("ens1f1"), _port("ens1f2")]
    neighbours = {
        "ens1f0": [neighbour(system_name="LEAF-1A.example.com", port_id="Eth1/12")],
        "ens1f1": [
            neighbour(
                system_name="leaf-1b", port_id="Ethernet11", port_description="Eth1/12"
            )
        ],
        "ens1f2": [neighbour(system_name="leaf-1c", port_id="Eth1/12")],
    }

    matches, unmatched = map_node_ports(ports, interfaces, neighbours)

    assert _methods(matches) == {
        "ens1f0": ("nic-a", "lldp"),
        "ens1f1": ("nic-b", "lldp"),
        "ens1f2": (None, "none"),
    }
    assert unmatched == []


def test_ambiguous_lldp_neighbour_does_not_match():
    interfaces = [
        _iface(1, "nic-a", endpoints=[Endpoint("leaf-1a", "Eth1/12")]),
        _iface(2, "nic-b", endpoints=[Endpoint("leaf-1a", "Eth1/12")]),
    ]
    neighbours = {"ens1f0": [neighbour(system_name="leaf-1a", port_id="Eth1/12")]}

    matches, unmatched = map_node_ports([_port("ens1f0")], interfaces, neighbours)

    assert matches == {"ens1f0": Match()}
    assert len(unmatched) == 2


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("leaf-1a", "LEAF-1A", True),
        ("leaf-1a.example.com", "leaf-1a", True),
        ("leaf-1a", "leaf-1a.other.net", True),
        ("leaf-1a", "leaf-1b", False),
        (None, "leaf-1a", False),
        ("leaf-1a", "", False),
    ],
)
def test_same_system(left, right, expected):
    assert same_system(left, right) is expected


def test_neighbour_is_endpoint_compares_port_id_and_description():
    endpoint = Endpoint("leaf-1a", "Eth1/12")

    assert neighbour_is_endpoint(
        neighbour(system_name="leaf-1a", port_id="Eth1/12"), endpoint
    )
    assert neighbour_is_endpoint(
        neighbour(system_name="leaf-1a", port_id="x", port_description="Eth1/12"),
        endpoint,
    )
    assert not neighbour_is_endpoint(
        neighbour(system_name="leaf-1a", port_id="Eth1/13"), endpoint
    )
    assert not neighbour_is_endpoint(
        neighbour(system_name="leaf-1b", port_id="Eth1/12"), endpoint
    )


@pytest.mark.parametrize(
    "record,expected",
    [
        # A SONiC switch: alias as port ID, SONiC name as description
        (
            neighbour(
                port_id="Eth1/1/1", port_id_type="local", port_description="Ethernet0"
            ),
            ["Eth1/1/1", "Ethernet0"],
        ),
        # lldpd on a node: MAC address as port ID, port name as description
        (
            neighbour(
                port_id="02:00:00:00:00:01",
                port_id_type="mac",
                port_description="ens4f0np0",
            ),
            ["02:00:00:00:00:01", "ens4f0np0"],
        ),
        # RouterOS: a bridge port, without description
        (
            neighbour(port_id="bridge/ether9", port_id_type="ifname"),
            ["bridge/ether9", "ether9"],
        ),
        (neighbour(port_id="ether9", port_id_type="ifname"), ["ether9"]),
        (neighbour(port_id="bridge/", port_id_type="ifname"), ["bridge/"]),
        (neighbour(port_id="Ethernet1/12", port_id_type="ifname"), ["Ethernet1/12"]),
        # Only an interface name is cut at the slash
        (neighbour(port_id="Eth1/12", port_id_type="local"), ["Eth1/12"]),
        (neighbour(port_id="Eth1/12"), ["Eth1/12"]),
        (neighbour(port_description="uplink"), ["uplink"]),
        (neighbour(), []),
    ],
)
def test_neighbour_port_names(record, expected):
    assert neighbour_port_names(record) == expected


def test_neighbour_is_endpoint_knows_the_bridge_ports_of_routeros():
    seen = neighbour(
        system_name="oob-1", port_id="bridge/ether9", port_id_type="ifname"
    )

    assert neighbour_is_endpoint(seen, Endpoint("oob-1", "ether9"))
    assert not neighbour_is_endpoint(seen, Endpoint("oob-1", "ether10"))
