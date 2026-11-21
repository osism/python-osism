# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.cabling``.

The comparison is a pure function over plain data, so the tests describe a
small rack twice: once as NetBox documents it (``Lab.cable``) and once as
the devices see it (``Lab.live``). Unless a test says otherwise, a live port
carries the name of its NetBox interface, and a neighbour announces itself
with its NetBox device name and interface name.
"""

import itertools

import pytest

from osism.utils.hardware.cabling import (
    RESULTS,
    Directory,
    LiveDevice,
    NetboxDevice,
    compare,
    find_live_port,
    neighbour_listing,
    netbox_device,
    summary,
)
from osism.utils.hardware import parse_linux, parse_sonic
from osism.utils.hardware.mapping import (
    Endpoint,
    Match,
    NetboxInterface,
    interface_from_netbox,
    map_node_ports,
    map_switch_ports,
)
from osism.utils.hardware.parse_lldp import (
    linux_neighbours,
    neighbour,
    sonic_neighbours,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seen(text):
    """Neighbour record for ``device:interface``."""
    device, _, interface = text.partition(":")
    return neighbour(system_name=device, port_id=interface)


class Lab:
    """The documented and the live side of a small topology."""

    def __init__(self, *devices):
        self.ids = {}
        self.kinds = {}
        self.netbox = {}
        self._interface_ids = itertools.count(100)
        for device in devices:
            self.add(device)

    def add(self, name, kind=None):
        self.ids[name] = len(self.ids) + 1
        self.kinds[name] = kind or (
            "switch" if name.startswith(("leaf", "mgmt")) else "node"
        )
        self.netbox[self.ids[name]] = {}
        return self

    def interface(self, device, name, **kwargs):
        if device not in self.ids:
            self.add(device)
        interfaces = self.netbox[self.ids[device]]
        if name not in interfaces:
            interfaces[name] = NetboxInterface(
                id=next(self._interface_ids),
                device_id=self.ids[device],
                device=device,
                name=name,
                **kwargs,
            )
        return interfaces[name]

    def cable(self, left, right):
        """Document a cable between ``device:interface`` and another one."""
        (left_device, left_name), (right_device, right_name) = (
            left.split(":"),
            right.split(":"),
        )
        a = self.interface(left_device, left_name)
        b = self.interface(right_device, right_name)
        a.has_cable = b.has_cable = True
        a.endpoints.append(
            Endpoint(right_device, right_name, self.ids[right_device], b.id)
        )
        b.endpoints.append(
            Endpoint(left_device, left_name, self.ids[left_device], a.id)
        )
        return self

    def live(self, device, ports):
        """Live view of a device.

        Args:
            ports: ``{port name: (link state, [seen "device:interface"])}``
        """
        documented = self.netbox[self.ids[device]]
        return LiveDevice(
            name=device,
            kind=self.kinds[device],
            device_id=self.ids[device],
            ports=[
                {"name": name, "kind": "physical", "oper_status": link, "altnames": []}
                for name, (link, _) in ports.items()
            ],
            neighbours={
                name: [_seen(item) for item in seen]
                for name, (_, seen) in ports.items()
                if seen
            },
            matches={
                name: Match(documented[name], "name") if name in documented else Match()
                for name in ports
            },
            unmatched=[
                interface for name, interface in documented.items() if name not in ports
            ],
        )

    def directory(self, live=(), **kwargs):
        return Directory(
            [NetboxDevice(device_id, name) for name, device_id in self.ids.items()],
            {
                device_id: list(found.values())
                for device_id, found in self.netbox.items()
            },
            live,
            **kwargs,
        )

    def check(self, *live, **kwargs):
        """Compare and return ``{(device, interface): (result, hint)}``."""
        rows = compare(list(live), self.directory(live), **kwargs)
        return {
            (row["device"], row["interface"]): (row["result"], row["hint"])
            for row in rows
        }


@pytest.fixture
def rack():
    """Two compute nodes, each with one port on each of two leaf switches."""
    return (
        Lab("leaf-1a", "leaf-1b", "compute-041", "compute-042")
        .cable("compute-041:ens1f0", "leaf-1a:Eth1/11")
        .cable("compute-041:ens1f1", "leaf-1b:Eth1/11")
        .cable("compute-042:ens1f0", "leaf-1a:Eth1/12")
        .cable("compute-042:ens1f1", "leaf-1b:Eth1/12")
    )


# ---------------------------------------------------------------------------
# One port against its documentation
# ---------------------------------------------------------------------------


def test_documented_neighbour_is_ok(rack):
    live = rack.live(
        "compute-041",
        {"ens1f0": ("up", ["leaf-1a:Eth1/11"]), "ens1f1": ("up", ["leaf-1b:Eth1/11"])},
    )

    assert rack.check(live) == {
        ("compute-041", "ens1f0"): ("ok", ""),
        ("compute-041", "ens1f1"): ("ok", ""),
    }


def test_removed_cable_is_missing(rack):
    live = rack.live(
        "compute-041", {"ens1f0": ("down", []), "ens1f1": ("up", ["leaf-1b:Eth1/11"])}
    )

    assert rack.check(live)[("compute-041", "ens1f0")] == ("missing", "link down")


@pytest.mark.parametrize("link", ["up", None])
def test_silent_peer_is_no_lldp(rack, link):
    live = rack.live("compute-041", {"ens1f0": (link, [])})

    assert rack.check(live)[("compute-041", "ens1f0")] == (
        "no-lldp",
        "link up, no neighbour",
    )


def test_cable_in_another_port_of_the_expected_device_is_wrong_port(rack):
    rack.cable("compute-044:ens1f0", "leaf-1a:Eth1/14")
    rack.interface("leaf-1a", "Eth1/20")

    documented = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/14"])})
    uncabled = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/20"])})
    unknown = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/99"])})

    assert rack.check(documented)[("compute-041", "ens1f0")] == (
        "wrong-port",
        "documented at compute-044:ens1f0",
    )
    assert rack.check(uncabled)[("compute-041", "ens1f0")] == (
        "wrong-port",
        "seen port has no cable in NetBox",
    )
    assert rack.check(unknown)[("compute-041", "ens1f0")] == (
        "wrong-port",
        "neighbour port not found in NetBox",
    )


def test_cable_to_another_device_is_wrong_device(rack):
    rack.cable("compute-044:ens1f0", "leaf-1c:Eth1/11")

    other = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1c:Eth1/11"])})
    stranger = rack.live("compute-041", {"ens1f0": ("up", ["tor-9:xe-0/0/1"])})

    assert rack.check(other)[("compute-041", "ens1f0")] == (
        "wrong-device",
        "documented at compute-044:ens1f0",
    )
    assert rack.check(stranger)[("compute-041", "ens1f0")] == (
        "wrong-device",
        "neighbour unknown to NetBox",
    )


def test_undocumented_cable_is_unexpected(rack):
    rack.interface("compute-041", "ens2f0")
    rack.interface("compute-041", "ens2f1")

    live = rack.live(
        "compute-041",
        {"ens2f0": ("up", ["leaf-1a:Eth1/20"]), "ens2f1": ("up", [])},
    )

    assert rack.check(live) == {
        ("compute-041", "ens2f0"): ("unexpected", "no cable in NetBox"),
        ("compute-041", "ens2f1"): (
            "unexpected",
            "link up, no neighbour, no cable in NetBox",
        ),
        # The documented ports were not seen on the node at all
        ("compute-041", "ens1f0"): (
            "unmapped",
            "no live port for this NetBox interface",
        ),
        ("compute-041", "ens1f1"): (
            "unmapped",
            "no live port for this NetBox interface",
        ),
    }


def test_incomplete_cable_path_gives_no_expectation(rack):
    rack.interface("compute-041", "ens2f0", has_cable=True)
    rack.interface("compute-041", "ens2f1", has_cable=True)

    live = rack.live(
        "compute-041",
        {
            "ens1f0": ("up", ["leaf-1a:Eth1/11"]),
            "ens1f1": ("up", ["leaf-1b:Eth1/11"]),
            "ens2f0": ("up", ["leaf-1a:Eth1/20"]),
            "ens2f1": ("up", []),
        },
    )
    results = rack.check(live, include_idle=True)

    assert results[("compute-041", "ens2f0")] == (
        "unexpected",
        "incomplete cable path in NetBox",
    )
    # Nothing to compare with and nothing seen: only shown on request
    assert results[("compute-041", "ens2f1")] == ("", "incomplete cable path in NetBox")
    assert ("compute-041", "ens2f1") not in rack.check(live)


def test_port_with_nothing_documented_and_nothing_seen_is_not_listed(rack):
    rack.interface("compute-041", "ens2f0")
    live = rack.live(
        "compute-041",
        {
            "ens1f0": ("up", ["leaf-1a:Eth1/11"]),
            "ens1f1": ("up", ["leaf-1b:Eth1/11"]),
            "ens2f0": ("down", []),
            "usb0": ("up", []),
        },
    )

    assert sorted(rack.check(live)) == [
        ("compute-041", "ens1f0"),
        ("compute-041", "ens1f1"),
    ]

    with_idle = rack.check(live, include_idle=True)
    assert with_idle[("compute-041", "ens2f0")] == ("", "")
    # Unknown to NetBox and silent: says nothing about the cabling
    assert with_idle[("compute-041", "usb0")] == ("", "port not found in NetBox")


def test_port_that_cannot_be_matched_is_unmapped(rack):
    live = rack.live(
        "compute-041",
        {
            "ens1f0": ("up", ["leaf-1a:Eth1/11"]),
            "enp9s0": ("up", ["leaf-1b:Eth1/11"]),
        },
    )

    assert rack.check(live) == {
        ("compute-041", "ens1f0"): ("ok", ""),
        ("compute-041", "enp9s0"): ("unmapped", "port not found in NetBox"),
        ("compute-041", "ens1f1"): (
            "unmapped",
            "no live port for this NetBox interface",
        ),
    }


def test_documented_interface_without_cable_and_live_port_is_not_listed(rack):
    rack.interface("compute-041", "ens9f0")
    live = rack.live(
        "compute-041",
        {"ens1f0": ("up", ["leaf-1a:Eth1/11"]), "ens1f1": ("up", ["leaf-1b:Eth1/11"])},
    )

    assert ("compute-041", "ens9f0") not in rack.check(live, include_idle=True)


@pytest.mark.parametrize("seen", ["leaf-1a:Eth1/11", "leaf-1b:Eth1/40"])
def test_neighbour_on_a_port_without_link_is_stale(rack, seen):
    live = rack.live("compute-041", {"ens1f0": ("down", [seen])})

    assert rack.check(live)[("compute-041", "ens1f0")] == (
        "stale",
        "link down, neighbour not aged out",
    )


def test_one_of_several_neighbours_is_enough(rack):
    live = rack.live(
        "compute-041",
        {"ens1f0": ("up", ["hypervisor-bridge:vnet3", "leaf-1a:Eth1/11"])},
    )

    assert rack.check(live)[("compute-041", "ens1f0")] == ("ok", "")


def test_every_endpoint_of_a_breakout_cable_is_accepted():
    lab = (
        Lab("leaf-1a", "compute-041", "compute-042")
        .cable("leaf-1a:Eth1/49", "compute-041:ens1f0")
        .cable("leaf-1a:Eth1/49", "compute-042:ens1f0")
    )

    first = lab.live("leaf-1a", {"Eth1/49": ("up", ["compute-041:ens1f0"])})
    second = lab.live("leaf-1a", {"Eth1/49": ("up", ["compute-042:ens1f0"])})
    wrong = lab.live("leaf-1a", {"Eth1/49": ("up", ["compute-042:ens1f1"])})

    assert lab.check(first)[("leaf-1a", "Eth1/49")] == ("ok", "")
    assert lab.check(second)[("leaf-1a", "Eth1/49")] == ("ok", "")
    assert lab.check(wrong)[("leaf-1a", "Eth1/49")][0] == "wrong-port"


def test_cable_through_a_patch_panel_is_compared_with_the_far_end():
    """NetBox reports the panel as link peer and the switch as endpoint."""
    interface = interface_from_netbox(
        {
            "id": 100,
            "name": "ens1f0",
            "device": {"id": 1, "name": "compute-041"},
            "type": {"value": "25gbase-x-sfp28"},
            "cable": {"id": 7},
            "link_peers": [
                {"id": 500, "name": "1", "device": {"id": 9, "name": "panel-a"}}
            ],
            "link_peers_type": "dcim.frontport",
            "connected_endpoints": [
                {"id": 200, "name": "Eth1/11", "device": {"id": 2, "name": "leaf-1a"}}
            ],
            "connected_endpoints_type": "dcim.interface",
            "connected_endpoints_reachable": True,
        }
    )
    directory = Directory(
        [
            NetboxDevice(1, "compute-041"),
            NetboxDevice(2, "leaf-1a"),
            NetboxDevice(9, "panel-a"),
        ],
        {
            1: [interface],
            2: [NetboxInterface(id=200, device_id=2, device="leaf-1a", name="Eth1/11")],
        },
    )

    def result(seen):
        live = LiveDevice(
            name="compute-041",
            kind="node",
            device_id=1,
            ports=[{"name": "ens1f0", "oper_status": "up"}],
            neighbours={"ens1f0": [_seen(seen)]},
            matches={"ens1f0": Match(interface, "mac")},
        )
        (row,) = compare([live], directory)
        return row

    row = result("leaf-1a:Eth1/11")
    assert row["result"] == "ok"
    assert row["expected"] == [{"device": "leaf-1a", "interface": "Eth1/11"}]
    assert result("panel-a:1")["result"] == "wrong-device"


# ---------------------------------------------------------------------------
# Exchanged cables
# ---------------------------------------------------------------------------


def test_two_cables_swapped_on_one_node(rack):
    live = rack.live(
        "compute-042",
        {"ens1f0": ("up", ["leaf-1b:Eth1/12"]), "ens1f1": ("up", ["leaf-1a:Eth1/12"])},
    )

    assert rack.check(live) == {
        ("compute-042", "ens1f0"): ("swapped", "swapped with ens1f1"),
        ("compute-042", "ens1f1"): ("swapped", "swapped with ens1f0"),
    }


def test_cables_of_two_nodes_swapped_on_the_switch(rack):
    first = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])})
    second = rack.live("compute-042", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})

    results = rack.check(first, second)

    assert results[("compute-041", "ens1f0")] == (
        "swapped",
        "swapped with compute-042:ens1f0",
    )
    assert results[("compute-042", "ens1f0")] == (
        "swapped",
        "swapped with compute-041:ens1f0",
    )


def test_swap_is_found_from_the_switch_side_as_well(rack):
    switch = rack.live(
        "leaf-1a",
        {
            "Eth1/11": ("up", ["compute-042:ens1f0"]),
            "Eth1/12": ("up", ["compute-041:ens1f0"]),
        },
    )

    assert rack.check(switch) == {
        ("leaf-1a", "Eth1/11"): ("swapped", "swapped with Eth1/12"),
        ("leaf-1a", "Eth1/12"): ("swapped", "swapped with Eth1/11"),
    }


def test_swap_with_a_port_that_was_not_queried_stays_a_mismatch(rack):
    first = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])})

    assert rack.check(first)[("compute-041", "ens1f0")] == (
        "wrong-port",
        "documented at compute-042:ens1f0",
    )


def test_mismatch_whose_partner_is_fine_is_not_a_swap(rack):
    first = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])})
    second = rack.live("compute-042", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])})

    results = rack.check(first, second)

    assert results[("compute-041", "ens1f0")][0] == "wrong-port"
    assert results[("compute-042", "ens1f0")] == ("ok", "")


def test_rotation_of_three_cables():
    lab = (
        Lab("leaf-1a", "compute-041", "compute-042", "compute-043")
        .cable("compute-041:ens1f0", "leaf-1a:Eth1/11")
        .cable("compute-042:ens1f0", "leaf-1a:Eth1/12")
        .cable("compute-043:ens1f0", "leaf-1a:Eth1/13")
    )
    live = [
        lab.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])}),
        lab.live("compute-042", {"ens1f0": ("up", ["leaf-1a:Eth1/13"])}),
        lab.live("compute-043", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])}),
    ]

    assert lab.check(*live) == {
        ("compute-041", "ens1f0"): (
            "swapped",
            "swapped with compute-042:ens1f0, compute-043:ens1f0",
        ),
        ("compute-042", "ens1f0"): (
            "swapped",
            "swapped with compute-043:ens1f0, compute-041:ens1f0",
        ),
        ("compute-043", "ens1f0"): (
            "swapped",
            "swapped with compute-041:ens1f0, compute-042:ens1f0",
        ),
    }


def test_chain_that_does_not_close_is_not_a_swap():
    lab = (
        Lab("leaf-1a", "compute-041", "compute-042", "compute-043")
        .cable("compute-041:ens1f0", "leaf-1a:Eth1/11")
        .cable("compute-042:ens1f0", "leaf-1a:Eth1/12")
        .cable("compute-043:ens1f0", "leaf-1a:Eth1/13")
    )
    lab.interface("leaf-1a", "Eth1/20")
    live = [
        lab.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/12"])}),
        lab.live("compute-042", {"ens1f0": ("up", ["leaf-1a:Eth1/13"])}),
        lab.live("compute-043", {"ens1f0": ("up", ["leaf-1a:Eth1/20"])}),
    ]

    results = lab.check(*live)

    assert {result for result, _ in results.values()} == {"wrong-port"}
    assert results[("compute-041", "ens1f0")][1] == "documented at compute-042:ens1f0"


# ---------------------------------------------------------------------------
# Both ends queried
# ---------------------------------------------------------------------------


def test_peer_that_sees_this_side_keeps_ok(rack):
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})
    switch = rack.live("leaf-1a", {"Eth1/11": ("up", ["compute-041:ens1f0"])})

    results = rack.check(node, switch)

    assert results[("compute-041", "ens1f0")] == ("ok", "")
    assert results[("leaf-1a", "Eth1/11")] == ("ok", "")


@pytest.mark.parametrize("seen_by_switch", [[], ["compute-041:ens1f1"], ["tor-9:x"]])
def test_peer_that_does_not_see_this_side_makes_it_one_sided(rack, seen_by_switch):
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})
    switch = rack.live("leaf-1a", {"Eth1/11": ("up", seen_by_switch)})

    results = rack.check(node, switch)

    assert results[("compute-041", "ens1f0")] == (
        "one-sided",
        "leaf-1a:Eth1/11 does not see this port",
    )


def test_peer_that_sees_the_node_on_an_unidentified_port_does_not_disagree(rack):
    """The switch sees the node, but not under a port name NetBox knows."""
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})
    switch = rack.live("leaf-1a", {"Eth1/11": ("up", ["compute-041:bond0-slave"])})

    assert rack.check(node, switch)[("compute-041", "ens1f0")] == ("ok", "")


def test_peer_that_was_not_queried_cannot_disagree(rack):
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})

    assert rack.check(node)[("compute-041", "ens1f0")] == ("ok", "")


def test_peer_port_that_is_not_live_cannot_disagree(rack):
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Eth1/11"])})
    switch = rack.live("leaf-1a", {"Eth1/12": ("up", ["compute-042:ens1f0"])})

    assert rack.check(node, switch)[("compute-041", "ens1f0")] == ("ok", "")


# ---------------------------------------------------------------------------
# Management interfaces
# ---------------------------------------------------------------------------


def test_bmc_port_of_a_node_produces_no_finding_on_the_node():
    lab = Lab("mgmt-1", "compute-041").cable("compute-041:bmc", "mgmt-1:Eth1/5")
    lab.netbox[lab.ids["compute-041"]]["bmc"].mgmt_only = True
    node = lab.live("compute-041", {})

    assert lab.check(node, include_idle=True) == {}


def test_bmc_cable_is_checked_from_the_oob_switch():
    lab = Lab("mgmt-1", "compute-041").cable("compute-041:bmc", "mgmt-1:Eth1/5")
    bmc = lab.netbox[lab.ids["compute-041"]]["bmc"]
    bmc.mgmt_only = True
    bmc.macs = ["3c:ec:ef:00:00:99"]

    def check(port_id):
        switch = lab.live("mgmt-1", {"Eth1/5": ("up", [])})
        # A BMC announces its MAC address, not an interface name
        switch.neighbours["Eth1/5"] = [
            neighbour(system_name="compute-041", port_id=port_id, port_id_type="mac")
        ]
        return lab.check(switch)[("mgmt-1", "Eth1/5")][0]

    assert check("3c:ec:ef:00:00:99") == "ok"
    assert check("3c:ec:ef:00:00:11") == "wrong-port"


def test_management_port_of_a_switch_is_checked():
    lab = Lab("mgmt-1", "leaf-1a").cable("leaf-1a:eth0", "mgmt-1:Eth1/1")
    lab.netbox[lab.ids["leaf-1a"]]["eth0"].mgmt_only = True

    def check(link, seen):
        switch = lab.live("leaf-1a", {"eth0": (link, seen)})
        switch.ports[0]["kind"] = "mgmt"
        return lab.check(switch)[("leaf-1a", "eth0")][0]

    assert check("up", ["mgmt-1:Eth1/1"]) == "ok"
    assert check("down", []) == "missing"
    assert check("up", ["mgmt-1:Eth1/2"]) == "wrong-port"


# ---------------------------------------------------------------------------
# Resolving LLDP identities
# ---------------------------------------------------------------------------


@pytest.fixture
def directory():
    interfaces = {
        1: [
            NetboxInterface(
                id=11, device_id=1, device="leaf-1a", name="Eth1/11", label="port 11"
            ),
            NetboxInterface(id=12, device_id=1, device="leaf-1a", name="Eth1/12"),
        ],
        2: [
            NetboxInterface(
                id=21,
                device_id=2,
                device="sto-1",
                name="nic1",
                macs=["aa:aa:aa:00:00:21"],
            ),
            NetboxInterface(id=22, device_id=2, device="sto-1", name="nic2"),
        ],
    }
    live = LiveDevice(
        name="sto-1",
        kind="node",
        device_id=2,
        ports=[
            {
                "name": "ens1f0",
                "altnames": ["enp59s0f0"],
                "permanent_mac": "aa:aa:aa:00:00:21",
            },
            {
                "name": "ens1f1",
                "altnames": [],
                "permanent_mac": "aa:aa:aa:00:00:22",
                "alias": "uplink-b",
            },
        ],
        matches={
            "ens1f0": Match(interfaces[2][0], "mac"),
            "ens1f1": Match(interfaces[2][1], "name"),
        },
    )
    return Directory(
        [
            NetboxDevice(1, "leaf-1a", addresses=["10.10.0.11"]),
            NetboxDevice(2, "sto-1", hostname="storage-001"),
        ],
        interfaces,
        [live],
        sonic_names={
            1: {"Ethernet10": interfaces[1][0], "Ethernet11": interfaces[1][1]}
        },
        sonic_aliases={1: {"twentyFiveGigE12": "Ethernet11"}},
    )


@pytest.mark.parametrize(
    "record,expected",
    [
        (neighbour(system_name="leaf-1a"), "leaf-1a"),
        (neighbour(system_name="LEAF-1A"), "leaf-1a"),
        (neighbour(system_name="leaf-1a.example.com"), "leaf-1a"),
        (neighbour(system_name="storage-001"), "sto-1"),
        (neighbour(system_name="Storage-001.example.com"), "sto-1"),
        (neighbour(system_name="x", management_addresses=["10.10.0.11"]), "leaf-1a"),
        (neighbour(chassis_id="AA:AA:AA:00:00:21", chassis_id_type="mac"), "sto-1"),
        # The port ID names one interface and wins over address and chassis
        (
            neighbour(
                system_name="x",
                port_id="aa:aa:aa:00:00:21",
                port_id_type="mac",
                management_addresses=["10.10.0.11"],
            ),
            "sto-1",
        ),
        (neighbour(system_name="x", port_id="de:ad:be:ef:00:02"), None),
        (neighbour(system_name="tor-9", chassis_id="de:ad:be:ef:00:01"), None),
        (neighbour(), None),
    ],
)
def test_neighbour_device_resolution(directory, record, expected):
    device = directory.resolve_device(record)

    assert (device.name if device else None) == expected


@pytest.mark.parametrize(
    "device,record,expected",
    [
        # 1. Name or label of a NetBox interface
        ("leaf-1a", neighbour(port_id="Eth1/12"), "Eth1/12"),
        ("leaf-1a", neighbour(port_id="x", port_description="Eth1/12"), "Eth1/12"),
        ("leaf-1a", neighbour(port_id="port 11"), "Eth1/11"),
        # 2. SONiC port name or vendor alias, through the port config
        ("leaf-1a", neighbour(port_id="Ethernet10"), "Eth1/11"),
        ("leaf-1a", neighbour(port_id="x", port_description="Ethernet11"), "Eth1/12"),
        ("leaf-1a", neighbour(port_id="twentyFiveGigE12"), "Eth1/12"),
        # 3. MAC address of a NetBox interface
        ("sto-1", neighbour(port_id="AA:AA:AA:00:00:21", port_id_type="mac"), "nic1"),
        # 4. Live interface of a queried device: name, altname, MAC, alias
        ("sto-1", neighbour(port_id="ens1f1"), "nic2"),
        ("sto-1", neighbour(port_id="enp59s0f0"), "nic1"),
        ("sto-1", neighbour(port_id="aa:aa:aa:00:00:22"), "nic2"),
        ("sto-1", neighbour(port_id="x", port_description="uplink-b"), "nic2"),
        # Nothing matches
        ("leaf-1a", neighbour(port_id="Ethernet99"), None),
        ("sto-1", neighbour(port_id="eth7"), None),
    ],
)
def test_neighbour_port_resolution(directory, device, record, expected):
    netbox = directory.resolve_device(neighbour(system_name=device))

    interface = directory.resolve_port(netbox, record)

    assert (interface.name if interface else None) == expected


@pytest.mark.parametrize(
    "system_name",
    [
        # A host name that is not the device name
        "deploy-1",
        # The default host name of an image
        "ubuntu",
        # The LLDP agent of a NIC, which answers instead of the host
        "Broadcom P225p NetXtreme-E Dual-port 10Gb/25Gb Ethernet PCIe Ada",
    ],
)
def test_port_id_identifies_a_neighbour_that_announces_another_name(
    directory, system_name
):
    seen = directory.resolve(
        neighbour(
            system_name=system_name,
            chassis_id="de:ad:be:ef:00:01",
            chassis_id_type="mac",
            port_id="aa:aa:aa:00:00:21",
            port_id_type="mac",
            port_description="data1",
            management_addresses=["172.17.0.1"],
        )
    )

    assert (seen.device, seen.interface, seen.device_id) == ("sto-1", "nic1", 2)


def test_mac_address_documented_on_several_devices_identifies_none():
    """The USB host interface of a BMC has the same address on every node.

    ``lldpd`` picks it as chassis ID on some of them.
    """
    shared = "02:00:00:00:00:1f"
    interfaces = {
        device_id: [
            NetboxInterface(
                id=device_id * 10,
                device_id=device_id,
                device=name,
                name="usb0",
                macs=[shared],
            ),
            NetboxInterface(
                id=device_id * 10 + 1,
                device_id=device_id,
                device=name,
                name="data2",
                macs=[mac],
            ),
        ]
        for device_id, name, mac in (
            (1, "node-2", "02:00:00:00:00:0a"),
            (2, "node-3", "02:00:00:00:00:0b"),
        )
    }
    directory = Directory(
        [NetboxDevice(1, "node-2"), NetboxDevice(2, "node-3")], interfaces
    )

    by_chassis = neighbour(system_name="ubuntu", chassis_id=shared)
    by_port = neighbour(
        system_name="ubuntu", chassis_id=shared, port_id="02:00:00:00:00:0b"
    )

    assert directory.resolve_device(by_chassis) is None
    assert directory.resolve_device(by_port).name == "node-3"
    assert directory.resolve(by_port).interface == "data2"


def test_bridge_port_of_routeros_is_compared_by_the_name_of_the_port():
    """RouterOS announces ``bridge/ether9`` for the port ``ether9``."""
    lab = Lab("leaf-1a", "mgmt-1").cable("leaf-1a:eth0", "mgmt-1:ether9")
    leaf = lab.live("leaf-1a", {"eth0": ("up", [])})
    leaf.neighbours["eth0"] = [
        neighbour(system_name="mgmt-1", port_id="bridge/ether9", port_id_type="ifname")
    ]

    assert lab.check(leaf) == {("leaf-1a", "eth0"): ("ok", "")}

    # In another port of the bridge it is still the wrong port
    leaf.neighbours["eth0"][0]["port_id"] = "bridge/ether10"
    assert lab.check(leaf)[("leaf-1a", "eth0")][0] == "wrong-port"


def test_port_name_wins_over_a_sonic_translation(directory):
    """``Ethernet10`` would translate, but an interface of that name exists."""
    directory.interfaces[1].append(
        NetboxInterface(id=13, device_id=1, device="leaf-1a", name="Ethernet10")
    )
    netbox = directory.resolve_device(neighbour(system_name="leaf-1a"))

    assert directory.resolve_port(netbox, neighbour(port_id="Ethernet10")).id == 13


def test_resolve_keeps_what_an_unknown_neighbour_announced(directory):
    stranger = directory.resolve(neighbour(system_name="tor-9", port_id="xe-0/0/1"))
    nameless = directory.resolve(neighbour(chassis_id="de:ad:be:ef:00:01"))
    half = directory.resolve(neighbour(system_name="leaf-1a", port_id="Ethernet99"))

    assert (stranger.device, stranger.interface, stranger.device_id) == (
        "tor-9",
        "xe-0/0/1",
        None,
    )
    assert (nameless.device, nameless.interface) == ("de:ad:be:ef:00:01", "?")
    assert (half.device, half.interface, half.device_id) == ("leaf-1a", "Ethernet99", 1)
    assert half.netbox_interface is None


def test_switch_that_advertises_sonic_names_is_compared_through_the_port_config(rack):
    """The node sees ``Ethernet10``; NetBox calls that port ``Eth1/11``."""
    node = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1a:Ethernet10"])})
    leaf = rack.netbox[rack.ids["leaf-1a"]]
    directory = rack.directory(
        [node], sonic_names={rack.ids["leaf-1a"]: {"Ethernet10": leaf["Eth1/11"]}}
    )

    (row,) = [r for r in compare([node], directory) if r["interface"] == "ens1f0"]

    assert row["result"] == "ok"
    assert row["seen"][0]["interface"] == "Eth1/11"
    assert row["seen"][0]["port_id"] == "Ethernet10"


def test_netbox_device_collects_names_and_addresses():
    device = netbox_device(
        {
            "id": 7,
            "name": "sto-1",
            "custom_fields": {"inventory_hostname": "storage-001"},
            "primary_ip4": {"address": "192.0.2.7/24"},
            "primary_ip6": None,
            "oob_ip": {"address": "198.51.100.7/24"},
        }
    )

    assert device == NetboxDevice(
        7, "sto-1", hostname="storage-001", addresses=["192.0.2.7", "198.51.100.7"]
    )
    assert netbox_device({"id": 8, "name": "x"}) == NetboxDevice(8, "x")


def test_find_live_port_without_a_match():
    device = LiveDevice(name="n", kind="node", ports=[{"name": "eth0", "altnames": []}])

    assert find_live_port(device, neighbour(port_id="eth9")) is None
    assert find_live_port(device, neighbour()) is None


# ---------------------------------------------------------------------------
# Captured devices
# ---------------------------------------------------------------------------


def _captured_node(lab, name, document):
    ports = parse_linux.parse_ports(document)
    matches, unmatched = map_node_ports(ports, list(lab.netbox[lab.ids[name]].values()))
    return LiveDevice(
        name=name,
        kind="node",
        device_id=lab.ids[name],
        ports=ports,
        neighbours=linux_neighbours(document),
        matches=matches,
        unmatched=unmatched,
    )


def _captured_switch(lab, name, document):
    ports = parse_sonic.parse_ports(document) + [parse_sonic.parse_mgmt_port(document)]
    matches, unmatched = map_switch_ports(
        ports, list(lab.netbox[lab.ids[name]].values())
    )
    return LiveDevice(
        name=name,
        kind="switch",
        device_id=lab.ids[name],
        ports=ports,
        neighbours=sonic_neighbours(document),
        matches=matches,
        unmatched=unmatched,
    )


def test_captured_cables_are_ok_from_both_ends(load_fixture):
    """A node and the two leaf switches it is cabled to, as captured.

    NetBox names the switch ports by their alias. The switches announce the
    alias, the node the MAC address and the name of its port, and the
    RouterOS switch of the management network a bridge port.
    """
    lab = Lab("leaf-1", "leaf-2", "node-1", "oob-1")
    lab.interface("leaf-1", "eth0", mgmt_only=True)
    lab.interface("leaf-2", "eth0", mgmt_only=True)
    lab.cable("node-1:ens4f0np0", "leaf-1:Eth1/1/1")
    lab.cable("node-1:ens4f1np1", "leaf-2:Eth1/1/1")
    lab.cable("node-1:enp4s0f0", "oob-1:ether14")
    lab.cable("leaf-1:eth0", "oob-1:ether9")
    lab.cable("leaf-2:eth0", "oob-1:ether8")
    lab.cable("leaf-1:Eth1/31", "leaf-2:Eth1/31")
    lab.cable("leaf-1:Eth1/32", "leaf-2:Eth1/32")

    node = _captured_node(lab, "node-1", load_fixture("linux-connectx4.json"))
    leaf_1 = _captured_switch(lab, "leaf-1", load_fixture("sonic-enterprise.json"))
    leaf_2 = _captured_switch(lab, "leaf-2", load_fixture("sonic-enterprise-4.4.json"))
    results = lab.check(node, leaf_1, leaf_2)

    for port in (
        ("node-1", "ens4f0np0"),
        ("node-1", "ens4f1np1"),
        ("node-1", "enp4s0f0"),
        ("leaf-1", "Ethernet0"),
        ("leaf-1", "Ethernet120"),
        ("leaf-1", "Ethernet124"),
        ("leaf-1", "eth0"),
        ("leaf-2", "Ethernet0"),
        ("leaf-2", "Ethernet120"),
        ("leaf-2", "Ethernet124"),
        ("leaf-2", "eth0"),
    ):
        assert results[port] == ("ok", ""), port
    # The unused onboard port of the node has nothing to report
    assert ("node-1", "enp4s0f1") not in results


def test_captured_neighbours_with_another_name_are_found_by_their_port(load_fixture):
    """Ethernet6 sees a host name that is not a device name, Ethernet9 the
    LLDP agent of a NIC. NetBox documents the MAC addresses of the ports."""
    lab = Lab("leaf-1", "node-17", "node-20")
    lab.cable("leaf-1:Eth1/2/3", "node-17:data1")
    lab.cable("leaf-1:Eth1/3/2", "node-20:data1")
    lab.interface("node-17", "data1").macs.append("02:00:00:00:00:03")
    lab.interface("node-20", "data1").macs.append("02:00:00:00:00:16")

    leaf = _captured_switch(lab, "leaf-1", load_fixture("sonic-enterprise.json"))
    results = lab.check(leaf)

    assert results[("leaf-1", "Ethernet6")] == ("ok", "")
    assert results[("leaf-1", "Ethernet9")] == ("ok", "")


def test_captured_cable_in_the_wrong_cage_is_found(load_fixture):
    """NetBox documents node-1 in the cage next to the one it is plugged in."""
    lab = Lab("leaf-1", "node-1").cable("node-1:ens4f0np0", "leaf-1:Eth1/2/1")

    node = _captured_node(lab, "node-1", load_fixture("linux-connectx4.json"))
    leaf = _captured_switch(lab, "leaf-1", load_fixture("sonic-enterprise.json"))
    results = lab.check(node, leaf)

    assert results[("node-1", "ens4f0np0")][0] == "wrong-port"
    # Ethernet4 is the documented port: no link, no neighbour
    assert results[("leaf-1", "Ethernet4")] == ("missing", "link down")
    # Ethernet0 is where the node is: NetBox does not know that port
    assert results[("leaf-1", "Ethernet0")] == ("unmapped", "port not found in NetBox")


# ---------------------------------------------------------------------------
# Rows, listing without NetBox, summary
# ---------------------------------------------------------------------------


def test_rows_carry_expected_and_seen_without_working_data(rack):
    live = rack.live("compute-041", {"ens1f0": ("up", ["leaf-1b:Eth1/11"])})

    rows = compare([live], rack.directory([live]))
    (row,) = [r for r in rows if r["interface"] == "ens1f0"]

    assert row == {
        "device": "compute-041",
        "kind": "node",
        "interface": "ens1f0",
        "netbox_name": "ens1f0",
        "mapping": "name",
        "oper_status": "up",
        "expected": [{"device": "leaf-1a", "interface": "Eth1/11"}],
        "seen": [
            dict(
                {"device": "leaf-1b", "interface": "Eth1/11"},
                **_seen("leaf-1b:Eth1/11"),
            )
        ],
        "result": "wrong-device",
        "hint": "documented at compute-041:ens1f1",
    }


def _plain(name, ports, kind="node", hostname=""):
    return LiveDevice(
        name=name,
        kind=kind,
        hostname=hostname,
        ports=[
            {"name": port, "oper_status": link, "altnames": [], "alias": alias}
            for port, (link, alias, _) in ports.items()
        ],
        neighbours={port: seen for port, (_, _, seen) in ports.items() if seen},
    )


def test_listing_has_one_row_per_neighbour():
    node = _plain(
        "compute-041",
        {
            "ens1f0": ("up", None, [_seen("leaf-1a:Eth1/11"), _seen("bridge:vnet0")]),
            "ens1f1": ("down", None, []),
        },
    )
    node.neighbours["br0"] = [_seen("leaf-1b:Eth1/11")]

    rows = neighbour_listing([node])

    assert [
        (r["interface"], r["seen"][0]["system_name"], r["result"]) for r in rows
    ] == [
        ("ens1f0", "leaf-1a", ""),
        ("ens1f0", "bridge", ""),
        ("br0", "leaf-1b", ""),
    ]
    assert rows[0]["expected"] == []
    assert rows[0]["netbox_name"] is None


def test_listing_flags_a_port_with_link_but_without_neighbour():
    node = _plain(
        "compute-041", {"ens1f0": ("up", None, []), "ens1f1": (None, None, [])}
    )

    (row,) = neighbour_listing([node])

    assert (row["interface"], row["result"], row["hint"]) == (
        "ens1f0",
        "no-lldp",
        "link up, no neighbour",
    )
    assert row["seen"] == []


def test_listing_flags_a_queried_neighbour_that_does_not_see_this_port():
    node = _plain(
        "sto-1",
        {
            "ens1f0": ("up", None, [_seen("leaf-1a:Eth1/11")]),
            "ens1f1": ("down", None, []),
        },
        hostname="storage-001",
    )
    agrees = _plain(
        "leaf-1a",
        {"Ethernet10": ("up", "Eth1/11", [_seen("storage-001.example.com:ens1f0")])},
        kind="switch",
    )
    silent = _plain("leaf-1a", {"Ethernet10": ("up", "Eth1/11", [])}, kind="switch")
    elsewhere = _plain(
        "leaf-1a",
        {"Ethernet10": ("up", "Eth1/11", [_seen("storage-001:ens1f1")])},
        kind="switch",
    )

    def result(switch):
        rows = neighbour_listing([node, switch])
        return [(r["result"], r["hint"]) for r in rows if r["device"] == "sto-1"]

    assert result(agrees) == [("", "")]
    assert result(silent) == [
        ("one-sided", "leaf-1a:Ethernet10 does not see this port")
    ]
    assert result(elsewhere) == [
        ("one-sided", "leaf-1a:Ethernet10 does not see this port")
    ]


def test_listing_accepts_a_neighbour_that_sees_this_device_on_an_unknown_port():
    node = _plain("sto-1", {"ens1f0": ("up", None, [_seen("leaf-1a:Eth1/11")])})
    switch = _plain(
        "leaf-1a",
        {"Ethernet10": ("up", "Eth1/11", [_seen("sto-1:aa:bb:cc:00:00:01")])},
        kind="switch",
    )

    rows = neighbour_listing([node, switch])

    assert [r["result"] for r in rows if r["device"] == "sto-1"] == [""]


def test_listing_does_not_judge_neighbours_that_were_not_queried():
    node = _plain("compute-041", {"ens1f0": ("up", None, [_seen("leaf-1a:Eth1/11")])})
    other = _plain("leaf-1b", {"Ethernet10": ("up", "Eth1/11", [])}, kind="switch")

    rows = neighbour_listing([node, other])

    assert [r["result"] for r in rows if r["device"] == "compute-041"] == [""]


def test_summary_counts_results_in_a_fixed_order():
    rows = [
        {"result": "swapped"},
        {"result": "ok"},
        {"result": ""},
        {"result": "swapped"},
        {"result": "missing"},
    ]

    assert list(summary(rows).items()) == [("ok", 1), ("missing", 1), ("swapped", 2)]
    assert summary([]) == {}
    assert RESULTS == [
        "ok",
        "missing",
        "no-lldp",
        "wrong-port",
        "wrong-device",
        "swapped",
        "unexpected",
        "one-sided",
        "unmapped",
        "stale",
    ]
