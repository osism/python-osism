# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the BGP / VLAN / Loopback / VRF helpers in
``osism.tasks.conductor.sonic.config_generator``.

Each helper mutates a ``config`` dict in place. Tests build a minimal
scaffold, call the helper, and assert against the post-call state. Where
the only observable effect of a branch is a log line, the shared
``loguru_logs`` fixture (see ``tests/conftest.py``) is used.
"""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import (
    _add_bgp_configurations,
    _add_loopback_configuration,
    _add_vlan_configuration,
    _add_vrf_configuration,
    _determine_peer_type,
    _get_connected_device_for_interface,
    _get_vrf_info,
)
from osism.tasks.conductor.sonic.constants import BGP_AF_L2VPN_EVPN_TAG

# ---------------------------------------------------------------------------
# Builders / fixtures
# ---------------------------------------------------------------------------


def _nbif(netbox_name, tags=None):
    """Shape used by ``netbox_interfaces[sonic_name]``."""
    return {"netbox_name": netbox_name, "tags": tags or []}


def _l2vpn_tag():
    return SimpleNamespace(slug=BGP_AF_L2VPN_EVPN_TAG)


def _switch_device(name="spine-1", role_slug="spine"):
    return SimpleNamespace(id=99, name=name, role=SimpleNamespace(slug=role_slug))


def _server_device(name="server-1", role_slug="server"):
    return SimpleNamespace(id=98, name=name, role=SimpleNamespace(slug=role_slug))


@pytest.fixture
def device():
    return SimpleNamespace(id=1, name="leaf-1")


@pytest.fixture
def bgp_config():
    """Minimal scaffold the BGP helper indexes into."""
    return {"PORT": {}, "BGP_NEIGHBOR": {}, "BGP_NEIGHBOR_AF": {}}


@pytest.fixture
def patch_bgp(mocker):
    """Patch the two connection helpers ``_add_bgp_configurations`` calls.

    ``connected_device`` returns ``None`` and ``peer_ipv4`` returns ``None``
    by default; tests override ``.return_value`` / ``.side_effect``.
    """
    return SimpleNamespace(
        connected_device=mocker.patch.object(
            config_generator,
            "get_connected_device_for_sonic_interface",
            return_value=None,
        ),
        peer_ipv4=mocker.patch.object(
            config_generator,
            "get_connected_interface_ipv4_address",
            return_value=None,
        ),
    )


def _call_bgp(config, **kw):
    defaults = dict(
        connected_interfaces=set(),
        connected_portchannels=set(),
        portchannel_info={"member_mapping": {}},
        device=SimpleNamespace(id=1, name="leaf-1"),
    )
    defaults.update(kw)
    _add_bgp_configurations(config, **defaults)


# ---------------------------------------------------------------------------
# _add_bgp_configurations: BGP_NEIGHBOR_AF for connected interfaces
# ---------------------------------------------------------------------------


class TestBgpNeighborAfInterfaces:
    def _base(self, bgp_config, **kw):
        bgp_config["PORT"] = {"Ethernet0": {}}
        _call_bgp(
            bgp_config,
            connected_interfaces={"Ethernet0"},
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            **kw,
        )

    def test_untagged_vlan_member_excluded(self, bgp_config, patch_bgp):
        self._base(bgp_config, vlan_info={"vlan_members": {100: {"eth0": "untagged"}}})
        assert bgp_config["BGP_NEIGHBOR_AF"] == {}
        assert bgp_config["BGP_NEIGHBOR"] == {}

    def test_direct_ipv4_excluded_and_logged(self, bgp_config, patch_bgp, loguru_logs):
        self._base(
            bgp_config,
            interface_ips={"eth0": "10.0.0.1/31"},
            transfer_ips={},
        )
        assert bgp_config["BGP_NEIGHBOR_AF"] == {}
        assert any(
            "Excluding interface Ethernet0 from BGP detection" in r["message"]
            for r in loguru_logs
        )

    def test_no_direct_ipv4_adds_ipv4_and_ipv6(self, bgp_config, patch_bgp):
        self._base(bgp_config, interface_ips={}, transfer_ips={})
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert af["default|Ethernet0|ipv4_unicast"] == {"admin_status": "true"}
        assert af["default|Ethernet0|ipv6_unicast"] == {"admin_status": "true"}
        assert "default|Ethernet0|l2vpn_evpn" not in af

    def test_transfer_role_ipv4_adds_ipv4_only(self, bgp_config, patch_bgp):
        self._base(bgp_config, transfer_ips={"eth0": "10.0.0.1/31"})
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert af["default|Ethernet0|ipv4_unicast"] == {"admin_status": "true"}
        assert "default|Ethernet0|ipv6_unicast" not in af

    def test_switch_to_switch_adds_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _switch_device()
        self._base(bgp_config)
        assert bgp_config["BGP_NEIGHBOR_AF"]["default|Ethernet0|l2vpn_evpn"] == {
            "admin_status": "true"
        }

    def test_non_switch_with_l2vpn_tag_adds_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _server_device()
        bgp_config["PORT"] = {"Ethernet0": {}}
        _call_bgp(
            bgp_config,
            connected_interfaces={"Ethernet0"},
            netbox_interfaces={"Ethernet0": _nbif("eth0", tags=[_l2vpn_tag()])},
        )
        assert "default|Ethernet0|l2vpn_evpn" in bgp_config["BGP_NEIGHBOR_AF"]

    def test_non_switch_no_tag_skips_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _server_device()
        self._base(bgp_config)
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert "default|Ethernet0|ipv4_unicast" in af
        assert "default|Ethernet0|l2vpn_evpn" not in af

    def test_non_default_vrf_never_adds_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _switch_device()
        self._base(
            bgp_config,
            vrf_info={"interface_vrf_mapping": {"Ethernet0": "Vrf42"}},
        )
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert "Vrf42|Ethernet0|ipv4_unicast" in af
        assert "Vrf42|Ethernet0|l2vpn_evpn" not in af
        assert "default|Ethernet0|l2vpn_evpn" not in af

    def test_port_channel_member_skipped(self, bgp_config, patch_bgp):
        bgp_config["PORT"] = {"Ethernet0": {}}
        _call_bgp(
            bgp_config,
            connected_interfaces={"Ethernet0"},
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            portchannel_info={"member_mapping": {"Ethernet0": "PortChannel1"}},
        )
        assert bgp_config["BGP_NEIGHBOR_AF"] == {}
        assert bgp_config["BGP_NEIGHBOR"] == {}


# ---------------------------------------------------------------------------
# _add_bgp_configurations: BGP_NEIGHBOR_AF for port channels
# ---------------------------------------------------------------------------


class TestBgpNeighborAfPortChannels:
    def test_adds_ipv4_and_ipv6(self, bgp_config, patch_bgp):
        _call_bgp(bgp_config, connected_portchannels={"PortChannel1"})
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert af["default|PortChannel1|ipv4_unicast"] == {"admin_status": "true"}
        assert af["default|PortChannel1|ipv6_unicast"] == {"admin_status": "true"}

    def test_switch_connection_adds_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _switch_device()
        _call_bgp(bgp_config, connected_portchannels={"PortChannel1"})
        assert "default|PortChannel1|l2vpn_evpn" in bgp_config["BGP_NEIGHBOR_AF"]

    def test_non_switch_skips_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _server_device()
        _call_bgp(bgp_config, connected_portchannels={"PortChannel1"})
        assert "default|PortChannel1|l2vpn_evpn" not in bgp_config["BGP_NEIGHBOR_AF"]

    def test_non_default_vrf_never_adds_l2vpn(self, bgp_config, patch_bgp):
        patch_bgp.connected_device.return_value = _switch_device()
        _call_bgp(
            bgp_config,
            connected_portchannels={"PortChannel1"},
            vrf_info={"interface_vrf_mapping": {"PortChannel1": "Vrf42"}},
        )
        af = bgp_config["BGP_NEIGHBOR_AF"]
        assert "Vrf42|PortChannel1|ipv4_unicast" in af
        assert "Vrf42|PortChannel1|l2vpn_evpn" not in af


# ---------------------------------------------------------------------------
# _add_bgp_configurations: BGP_NEIGHBOR for connected interfaces
# ---------------------------------------------------------------------------


class TestBgpNeighborInterfaces:
    def _base(self, bgp_config, **kw):
        bgp_config["PORT"] = {"Ethernet0": {}}
        _call_bgp(
            bgp_config,
            connected_interfaces={"Ethernet0"},
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            **kw,
        )

    def test_direct_ipv4_only_not_added(self, bgp_config, patch_bgp):
        self._base(bgp_config, interface_ips={"eth0": "10.0.0.1/31"})
        assert bgp_config["BGP_NEIGHBOR"] == {}

    def test_untagged_vlan_member_skipped(self, bgp_config, patch_bgp):
        self._base(bgp_config, vlan_info={"vlan_members": {100: {"eth0": "untagged"}}})
        assert bgp_config["BGP_NEIGHBOR"] == {}

    def test_no_direct_no_peer_ip_uses_interface_name(self, bgp_config, patch_bgp):
        self._base(bgp_config)
        assert bgp_config["BGP_NEIGHBOR"]["default|Ethernet0"] == {
            "peer_type": "external",
            "v6only": "true",
        }

    def test_peer_ip_key_and_local_addr_from_interface_ips(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.5"
        self._base(
            bgp_config,
            netbox=object(),
            interface_ips={"eth0": "10.1.1.1/31"},
            transfer_ips={"eth0": "10.2.2.2/31"},
        )
        entry = bgp_config["BGP_NEIGHBOR"]["default|192.0.2.5"]
        assert entry["local_addr"] == "10.1.1.1"

    def test_peer_ip_local_addr_from_transfer_ips(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.5"
        self._base(
            bgp_config,
            netbox=object(),
            transfer_ips={"eth0": "10.2.2.2/31"},
        )
        entry = bgp_config["BGP_NEIGHBOR"]["default|192.0.2.5"]
        assert entry["local_addr"] == "10.2.2.2"
        assert entry["v6only"] == "false"

    def test_transfer_role_ipv4_v6only_false(self, bgp_config, patch_bgp):
        self._base(bgp_config, transfer_ips={"eth0": "10.2.2.2/31"})
        assert bgp_config["BGP_NEIGHBOR"]["default|Ethernet0"]["v6only"] == "false"

    def test_non_default_vrf_no_v6only(self, bgp_config, patch_bgp):
        self._base(
            bgp_config,
            vrf_info={"interface_vrf_mapping": {"Ethernet0": "Vrf42"}},
        )
        entry = bgp_config["BGP_NEIGHBOR"]["Vrf42|Ethernet0"]
        assert "v6only" not in entry

    def test_internal_peer_type_propagated(self, bgp_config, patch_bgp, mocker):
        patch_bgp.connected_device.return_value = _switch_device()
        mocker.patch.object(
            config_generator, "_determine_peer_type", return_value="internal"
        )
        self._base(bgp_config)
        assert bgp_config["BGP_NEIGHBOR"]["default|Ethernet0"]["peer_type"] == (
            "internal"
        )


# ---------------------------------------------------------------------------
# _add_bgp_configurations: BGP_NEIGHBOR for port channels
# ---------------------------------------------------------------------------


class TestBgpNeighborPortChannels:
    def test_default_vrf_no_peer_ip(self, bgp_config, patch_bgp):
        _call_bgp(bgp_config, connected_portchannels={"PortChannel1"})
        assert bgp_config["BGP_NEIGHBOR"]["default|PortChannel1"] == {
            "peer_type": "external",
            "v6only": "true",
        }

    def test_default_vrf_peer_ip_no_local_addr(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.9"
        _call_bgp(
            bgp_config,
            connected_portchannels={"PortChannel1"},
            netbox=object(),
        )
        entry = bgp_config["BGP_NEIGHBOR"]["default|192.0.2.9"]
        assert "local_addr" not in entry

    def test_non_default_vrf_no_v6only(self, bgp_config, patch_bgp):
        _call_bgp(
            bgp_config,
            connected_portchannels={"PortChannel1"},
            vrf_info={"interface_vrf_mapping": {"PortChannel1": "Vrf42"}},
        )
        assert "v6only" not in bgp_config["BGP_NEIGHBOR"]["Vrf42|PortChannel1"]

    def test_switch_connection_peer_type_evaluated(self, bgp_config, patch_bgp, mocker):
        patch_bgp.connected_device.return_value = _switch_device()
        mocker.patch.object(
            config_generator, "_determine_peer_type", return_value="internal"
        )
        _call_bgp(bgp_config, connected_portchannels={"PortChannel1"})
        assert bgp_config["BGP_NEIGHBOR"]["default|PortChannel1"]["peer_type"] == (
            "internal"
        )


# ---------------------------------------------------------------------------
# _add_bgp_configurations: VLAN-interface BGP
# ---------------------------------------------------------------------------


class TestBgpVlanInterfaces:
    def _vlan_info(self, members, addresses=None):
        return {
            "vlan_interfaces": {100: {"addresses": addresses or ["10.0.0.1/24"]}},
            "vlan_members": {100: members},
        }

    def test_untagged_member_with_peer_ip(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.20"
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            vlan_info=self._vlan_info({"eth0": "untagged"}),
        )
        assert bgp_config["BGP_NEIGHBOR"]["default|192.0.2.20"] == {
            "peer_type": "external",
            "v6only": "false",
        }
        assert bgp_config["BGP_NEIGHBOR_AF"]["default|192.0.2.20|ipv4_unicast"] == {
            "admin_status": "true"
        }

    def test_duplicate_peer_ip_deduped(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.20"
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={
                "Ethernet0": _nbif("eth0"),
                "Ethernet1": _nbif("eth1"),
            },
            vlan_info=self._vlan_info({"eth0": "untagged", "eth1": "untagged"}),
        )
        assert list(bgp_config["BGP_NEIGHBOR"]) == ["default|192.0.2.20"]

    @pytest.mark.parametrize(
        "vlan_info",
        [
            {"vlan_interfaces": {100: {}}, "vlan_members": {100: {}}},
            {
                "vlan_interfaces": {100: {"addresses": []}},
                "vlan_members": {100: {}},
            },
            {
                "vlan_interfaces": {100: {"addresses": ["10.0.0.1/24"]}},
                "vlan_members": {100: {"eth0": "tagged"}},
            },
            {
                "vlan_interfaces": {100: {"addresses": ["10.0.0.1/24"]}},
                "vlan_members": {},
            },
        ],
    )
    def test_skipped_cases(self, bgp_config, patch_bgp, vlan_info):
        patch_bgp.peer_ipv4.return_value = "192.0.2.20"
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            vlan_info=vlan_info,
        )
        assert bgp_config["BGP_NEIGHBOR"] == {}

    def test_no_peer_ip_warns(self, bgp_config, patch_bgp, loguru_logs):
        patch_bgp.peer_ipv4.return_value = None
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            vlan_info=self._vlan_info({"eth0": "untagged"}),
        )
        assert bgp_config["BGP_NEIGHBOR"] == {}
        assert any(
            "No peer IP addresses found for any untagged member of VLAN 100"
            in r["message"]
            for r in loguru_logs
        )

    def test_vlan_interface_name_used_for_vrf_lookup(self, bgp_config, patch_bgp):
        patch_bgp.peer_ipv4.return_value = "192.0.2.20"
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            vlan_info=self._vlan_info({"eth0": "untagged"}),
            vrf_info={"interface_vrf_mapping": {"Vlan100": "Vrf42"}},
        )
        entry = bgp_config["BGP_NEIGHBOR"]["Vrf42|192.0.2.20"]
        assert "v6only" not in entry
        assert "Vrf42|192.0.2.20|ipv4_unicast" in bgp_config["BGP_NEIGHBOR_AF"]

    def test_member_not_in_netbox_interfaces_skipped(
        self, bgp_config, patch_bgp, loguru_logs
    ):
        patch_bgp.peer_ipv4.return_value = "192.0.2.20"
        _call_bgp(
            bgp_config,
            netbox=object(),
            netbox_interfaces={"Ethernet0": _nbif("eth0")},
            vlan_info=self._vlan_info({"ethX": "untagged"}),
        )
        assert bgp_config["BGP_NEIGHBOR"] == {}
        assert any(
            "Could not find SONiC name for NetBox interface ethX" in r["message"]
            for r in loguru_logs
        )


# ---------------------------------------------------------------------------
# _get_connected_device_for_interface
# ---------------------------------------------------------------------------


def test_get_connected_device_for_interface_delegates(device, mocker):
    sentinel = object()
    patched = mocker.patch.object(
        config_generator,
        "get_connected_device_for_sonic_interface",
        return_value=sentinel,
    )
    result = _get_connected_device_for_interface(device, "Ethernet0")
    assert result is sentinel
    patched.assert_called_once_with(device, "Ethernet0")


# ---------------------------------------------------------------------------
# _determine_peer_type
# ---------------------------------------------------------------------------


def _peer_dev(did, name, ip=None):
    ip4 = SimpleNamespace(address=ip) if ip else None
    return SimpleNamespace(id=did, name=name, primary_ip4=ip4)


class TestDeterminePeerType:
    @pytest.fixture
    def calc(self, mocker):
        return mocker.patch.object(config_generator, "calculate_local_asn_from_ipv4")

    def test_both_in_mapping_same_as_internal(self, calc):
        local = _peer_dev(1, "leaf-1")
        remote = _peer_dev(2, "leaf-2")
        result = _determine_peer_type(local, remote, {1: 65000, 2: 65000})
        assert result == "internal"
        calc.assert_not_called()

    def test_both_in_mapping_different_as_external(self, calc):
        local = _peer_dev(1, "leaf-1")
        remote = _peer_dev(2, "leaf-2")
        result = _determine_peer_type(local, remote, {1: 65000, 2: 65001})
        assert result == "external"

    def test_local_not_in_mapping_computed_from_ip(self, calc):
        calc.return_value = 65000
        local = _peer_dev(1, "leaf-1", ip="10.0.0.1/32")
        remote = _peer_dev(2, "leaf-2")
        result = _determine_peer_type(local, remote, {2: 65000})
        assert result == "internal"
        calc.assert_called_once_with("10.0.0.1/32")

    def test_connected_not_in_mapping_computed_from_ip(self, calc):
        calc.return_value = 65000
        local = _peer_dev(1, "leaf-1")
        remote = _peer_dev(2, "leaf-2", ip="10.0.0.2/32")
        result = _determine_peer_type(local, remote, {1: 65000})
        assert result == "internal"
        calc.assert_called_once_with("10.0.0.2/32")

    def test_no_primary_ip_and_not_in_mapping_external(self, calc):
        local = _peer_dev(1, "leaf-1")  # no primary_ip4
        remote = _peer_dev(2, "leaf-2")
        result = _determine_peer_type(local, remote, {2: 65000})
        assert result == "external"

    def test_calculate_raises_returns_external(self, calc):
        calc.side_effect = RuntimeError("boom")
        local = _peer_dev(1, "leaf-1", ip="10.0.0.1/32")
        remote = _peer_dev(2, "leaf-2")
        result = _determine_peer_type(local, remote, {2: 65000})
        assert result == "external"


# ---------------------------------------------------------------------------
# _add_vlan_configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def vlan_config():
    return {"VLAN": {}, "VLAN_MEMBER": {}, "VLAN_INTERFACE": {}}


class TestAddVlanConfiguration:
    def test_members_and_vlan_member_entries(self, vlan_config):
        vlan_info = {
            "vlans": {100: {}},
            "vlan_members": {100: {"eth1": "tagged", "eth0": "untagged"}},
            "vlan_interfaces": {},
        }
        netbox_interfaces = {
            "Ethernet1": {"netbox_name": "eth1"},
            "Ethernet0": {"netbox_name": "eth0"},
        }
        _add_vlan_configuration(
            vlan_config, vlan_info, netbox_interfaces, SimpleNamespace()
        )
        vlan = vlan_config["VLAN"]["Vlan100"]
        assert vlan["admin_status"] == "up"
        assert vlan["vlanid"] == "100"
        assert sorted(vlan["members"]) == ["Ethernet0", "Ethernet1"]
        assert vlan_config["VLAN_MEMBER"]["Vlan100|Ethernet1"] == {
            "tagging_mode": "tagged"
        }
        assert vlan_config["VLAN_MEMBER"]["Vlan100|Ethernet0"] == {
            "tagging_mode": "untagged"
        }

    def test_unmapped_member_warns_and_skipped(self, vlan_config, loguru_logs):
        vlan_info = {
            "vlans": {100: {}},
            "vlan_members": {100: {"ethZ": "untagged"}},
            "vlan_interfaces": {},
        }
        _add_vlan_configuration(vlan_config, vlan_info, {}, SimpleNamespace())
        assert vlan_config["VLAN"]["Vlan100"]["members"] == []
        assert vlan_config["VLAN_MEMBER"] == {}
        assert any(
            "Interface ethZ not found in mapping" in r["message"] for r in loguru_logs
        )

    def test_svi_with_addresses(self, vlan_config):
        vlan_info = {
            "vlans": {},
            "vlan_members": {},
            "vlan_interfaces": {100: {"addresses": ["10.0.0.1/24", "fe80::1/64"]}},
        }
        _add_vlan_configuration(vlan_config, vlan_info, {}, SimpleNamespace())
        vi = vlan_config["VLAN_INTERFACE"]
        assert vi["Vlan100"] == {"admin_status": "up"}
        assert vi["Vlan100|10.0.0.1/24"] == {}
        assert vi["Vlan100|fe80::1/64"] == {}

    @pytest.mark.parametrize("iface_data", [{}, {"addresses": []}])
    def test_svi_without_addresses_no_entry(self, vlan_config, iface_data):
        vlan_info = {
            "vlans": {},
            "vlan_members": {},
            "vlan_interfaces": {100: iface_data},
        }
        _add_vlan_configuration(vlan_config, vlan_info, {}, SimpleNamespace())
        assert "Vlan100" not in vlan_config["VLAN_INTERFACE"]


# ---------------------------------------------------------------------------
# _add_loopback_configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def loopback_config():
    return {
        "LOOPBACK": {},
        "LOOPBACK_INTERFACE": {},
        "BGP_GLOBALS_AF_NETWORK": {},
    }


class TestAddLoopbackConfiguration:
    def test_non_loopback0_ipv4(self, loopback_config):
        _add_loopback_configuration(
            loopback_config,
            {"loopbacks": {"Loopback1": {"addresses": ["10.0.0.1/32"]}}},
        )
        assert loopback_config["LOOPBACK"]["Loopback1"] == {"admin_status": "up"}
        assert loopback_config["LOOPBACK_INTERFACE"]["Loopback1"] == {}
        assert loopback_config["LOOPBACK_INTERFACE"]["Loopback1|10.0.0.1/32"] == {}
        assert loopback_config["BGP_GLOBALS_AF_NETWORK"] == {}

    def test_loopback0_ipv4_adds_af_network(self, loopback_config):
        _add_loopback_configuration(
            loopback_config,
            {"loopbacks": {"Loopback0": {"addresses": ["10.0.0.1/32"]}}},
        )
        assert (
            loopback_config["BGP_GLOBALS_AF_NETWORK"][
                "default|ipv4_unicast|10.0.0.1/32"
            ]
            == {}
        )

    def test_loopback0_ipv6_adds_af_network(self, loopback_config):
        _add_loopback_configuration(
            loopback_config,
            {"loopbacks": {"Loopback0": {"addresses": ["2001:db8::1/128"]}}},
        )
        assert (
            loopback_config["BGP_GLOBALS_AF_NETWORK"][
                "default|ipv6_unicast|2001:db8::1/128"
            ]
            == {}
        )

    def test_invalid_ip_warns_and_skipped(self, loopback_config, loguru_logs):
        _add_loopback_configuration(
            loopback_config,
            {"loopbacks": {"Loopback0": {"addresses": ["not-an-ip"]}}},
        )
        assert loopback_config["BGP_GLOBALS_AF_NETWORK"] == {}
        assert loopback_config["LOOPBACK_INTERFACE"]["Loopback0|not-an-ip"] == {}
        assert any(
            "Invalid IP address format: not-an-ip" in r["message"] for r in loguru_logs
        )


# ---------------------------------------------------------------------------
# _get_vrf_info
# ---------------------------------------------------------------------------


def _vrf_iface(name, vrf_name=None, rd=None):
    vrf = SimpleNamespace(name=vrf_name, rd=rd) if vrf_name is not None else None
    return SimpleNamespace(name=name, vrf=vrf)


class TestGetVrfInfo:
    @pytest.fixture
    def patch_vrf(self, mocker):
        return SimpleNamespace(
            cached=mocker.patch.object(
                config_generator, "get_cached_device_interfaces"
            ),
            convert=mocker.patch.object(
                config_generator, "convert_netbox_interface_to_sonic"
            ),
        )

    @pytest.fixture
    def dev(self):
        return SimpleNamespace(id=1, name="leaf-1")

    def test_interface_without_vrf_skipped(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [_vrf_iface("eth0")]
        result = _get_vrf_info(dev)
        assert result == {"vrfs": {}, "interface_vrf_mapping": {}}

    def test_name_vrf42_no_rd_table_id(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [_vrf_iface("eth0", "vrf42", None)]
        patch_vrf.convert.return_value = "Ethernet0"
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {"Vrf42": {"table_id": 42}}
        assert result["interface_vrf_mapping"] == {"Ethernet0": "Vrf42"}

    def test_name_with_numeric_rd_uses_vni(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [_vrf_iface("eth0", "vrfStorage", "2001")]
        patch_vrf.convert.return_value = "Ethernet0"
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {"vrfStorage": {"vni": 2001}}

    def test_vrf_number_name_with_text_rd(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [_vrf_iface("eth0", "vrf2001", "vrfStorage")]
        patch_vrf.convert.return_value = "Ethernet0"
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {"vrfStorage": {"vni": 2001}}
        assert result["interface_vrf_mapping"] == {"Ethernet0": "vrfStorage"}

    def test_no_name_match_text_rd_uses_rd(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [_vrf_iface("eth0", "customvrf", "myrd")]
        patch_vrf.convert.return_value = "Ethernet0"
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {"myrd": {}}
        assert result["interface_vrf_mapping"] == {"Ethernet0": "myrd"}

    def test_no_name_match_no_rd_warns_skipped(self, patch_vrf, dev, loguru_logs):
        patch_vrf.cached.return_value = [_vrf_iface("eth0", "customvrf", None)]
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {}
        assert any("doesn't match pattern" in r["message"] for r in loguru_logs)

    def test_multiple_interfaces_same_vrf(self, patch_vrf, dev):
        patch_vrf.cached.return_value = [
            _vrf_iface("eth0", "vrf42", None),
            _vrf_iface("eth4", "vrf42", None),
        ]
        patch_vrf.convert.side_effect = ["Ethernet0", "Ethernet4"]
        result = _get_vrf_info(dev)
        assert result["vrfs"] == {"Vrf42": {"table_id": 42}}
        assert result["interface_vrf_mapping"] == {
            "Ethernet0": "Vrf42",
            "Ethernet4": "Vrf42",
        }

    def test_per_interface_exception_continues(self, patch_vrf, dev, loguru_logs):
        patch_vrf.cached.return_value = [
            _vrf_iface("eth0", "vrf42", None),
            _vrf_iface("eth4", "vrf42", None),
        ]
        patch_vrf.convert.side_effect = [RuntimeError("boom"), "Ethernet4"]
        result = _get_vrf_info(dev)
        assert result["interface_vrf_mapping"] == {"Ethernet4": "Vrf42"}
        assert any(
            "Error processing VRF for interface" in r["message"] for r in loguru_logs
        )

    def test_top_level_exception_returns_empty(self, patch_vrf, dev, loguru_logs):
        patch_vrf.cached.side_effect = RuntimeError("netbox down")
        result = _get_vrf_info(dev)
        assert result == {"vrfs": {}, "interface_vrf_mapping": {}}
        assert any("Could not get VRF information" in r["message"] for r in loguru_logs)


# ---------------------------------------------------------------------------
# _add_vrf_configuration
# ---------------------------------------------------------------------------


@pytest.fixture
def vrf_config():
    return {
        "VRF": {},
        "VLAN": {},
        "VLAN_INTERFACE": {},
        "BGP_GLOBALS_AF": {},
        "BGP_GLOBALS_ROUTE_ADVERTISE": {},
        "BGP_GLOBALS": {},
        "VXLAN_TUNNEL": {},
        "VXLAN_EVPN_NVO": {},
        "VXLAN_TUNNEL_MAP": {},
        "INTERFACE": {},
        "PORTCHANNEL_INTERFACE": {},
        "ROUTE_REDISTRIBUTE": {},
    }


class TestAddVrfConfiguration:
    def test_vrf_with_vni_full_config(self, vrf_config):
        vrf_info = {
            "vrfs": {"vrfStorage": {"vni": 2001}},
            "interface_vrf_mapping": {},
        }
        _add_vrf_configuration(vrf_config, vrf_info, {})
        assert vrf_config["VRF"]["vrfStorage"] == {
            "fallback": "false",
            "vni": "2001",
        }
        assert vrf_config["VLAN"]["Vlan2001"]["vlanid"] == "2001"
        assert vrf_config["VLAN_INTERFACE"]["Vlan2001"] == {"vrf_name": "vrfStorage"}
        assert "vrfStorage|ipv4_unicast" in vrf_config["BGP_GLOBALS_AF"]
        l2vpn = vrf_config["BGP_GLOBALS_AF"]["vrfStorage|l2vpn_evpn"]
        assert l2vpn["import-rts"] == ["2001:1"]
        assert l2vpn["export-rts"] == ["2001:1"]
        assert l2vpn["route-distinguisher"] == "2001:1"
        assert (
            "vrfStorage|L2VPN_EVPN|IPV4_UNICAST"
            in vrf_config["BGP_GLOBALS_ROUTE_ADVERTISE"]
        )
        assert (
            "vrfStorage|L2VPN_EVPN|IPV6_UNICAST"
            in vrf_config["BGP_GLOBALS_ROUTE_ADVERTISE"]
        )
        assert "vrfStorage|connected|bgp|ipv4" in vrf_config["ROUTE_REDISTRIBUTE"]

    def test_route_redistribute_created_when_absent(self, vrf_config):
        del vrf_config["ROUTE_REDISTRIBUTE"]
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {"vrfStorage": {"vni": 2001}}, "interface_vrf_mapping": {}},
            {},
        )
        assert "vrfStorage|connected|bgp|ipv4" in vrf_config["ROUTE_REDISTRIBUTE"]

    def test_vrf_with_table_id_only(self, vrf_config):
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {"Vrf42": {"table_id": 42}}, "interface_vrf_mapping": {}},
            {},
        )
        assert vrf_config["VRF"]["Vrf42"] == {"vrf_table_id": 42}

    def test_vrf_with_neither(self, vrf_config):
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {"Vrf42": {}}, "interface_vrf_mapping": {}},
            {},
        )
        assert vrf_config["VRF"]["Vrf42"] == {}

    def test_bgp_globals_default_deep_copied(self, vrf_config):
        vrf_config["BGP_GLOBALS"]["default"] = {
            "router_id": "10.0.0.1",
            "local_asn": "65000",
        }
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {"Vrf42": {}}, "interface_vrf_mapping": {}},
            {},
        )
        assert vrf_config["BGP_GLOBALS"]["Vrf42"] == {
            "router_id": "10.0.0.1",
            "local_asn": "65000",
        }
        vrf_config["BGP_GLOBALS"]["Vrf42"]["router_id"] = "changed"
        assert vrf_config["BGP_GLOBALS"]["default"]["router_id"] == "10.0.0.1"

    def test_multiple_vrfs_with_vni_create_vxlan(self, vrf_config):
        vrf_config["BGP_GLOBALS"]["default"] = {"router_id": "10.0.0.1"}
        vrf_info = {
            "vrfs": {"vrfA": {"vni": 1001}, "vrfB": {"vni": 1002}},
            "interface_vrf_mapping": {},
        }
        _add_vrf_configuration(vrf_config, vrf_info, {})
        vtep = config_generator.VXLAN_VTEP_NAME
        assert vrf_config["VXLAN_TUNNEL"][vtep]["src_ip"] == "10.0.0.1"
        assert vrf_config["VXLAN_EVPN_NVO"]["nvo1"] == {"source_vtep": vtep}
        assert len(vrf_config["VXLAN_TUNNEL_MAP"]) == 2

    def test_no_vni_no_vxlan(self, vrf_config):
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {"Vrf42": {"table_id": 42}}, "interface_vrf_mapping": {}},
            {},
        )
        assert vrf_config["VXLAN_TUNNEL"] == {}
        assert vrf_config["VXLAN_EVPN_NVO"] == {}
        assert vrf_config["VXLAN_TUNNEL_MAP"] == {}

    def test_interface_vrf_assignment(self, vrf_config):
        vrf_config["INTERFACE"]["Ethernet0"] = {}
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {}, "interface_vrf_mapping": {"Ethernet0": "Vrf42"}},
            {},
        )
        assert vrf_config["INTERFACE"]["Ethernet0"]["vrf_name"] == "Vrf42"

    def test_portchannel_vrf_assignment(self, vrf_config):
        vrf_config["PORTCHANNEL_INTERFACE"]["PortChannel1"] = {}
        _add_vrf_configuration(
            vrf_config,
            {
                "vrfs": {},
                "interface_vrf_mapping": {"PortChannel1": "Vrf42"},
            },
            {},
        )
        assert (
            vrf_config["PORTCHANNEL_INTERFACE"]["PortChannel1"]["vrf_name"] == "Vrf42"
        )

    def test_interface_in_mapping_but_neither_section(self, vrf_config, loguru_logs):
        _add_vrf_configuration(
            vrf_config,
            {"vrfs": {}, "interface_vrf_mapping": {"Ethernet9": "Vrf42"}},
            {},
        )
        assert "Ethernet9" not in vrf_config["INTERFACE"]
        assert any(
            "has VRF assignment but is not in" in r["message"] for r in loguru_logs
        )
