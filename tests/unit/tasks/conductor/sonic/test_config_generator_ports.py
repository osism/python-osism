# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the port/interface/portchannel/breakout helpers in
``osism.tasks.conductor.sonic.config_generator``.

Each helper mutates a ``config`` dict in place. The tests build a minimal
scaffold via the ``config`` fixture and assert against the post-call state.
"""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import (
    _add_interface_configurations,
    _add_missing_breakout_ports,
    _add_port_configurations,
    _add_portchannel_configuration,
    _add_tagged_vlans_to_ports,
    _calculate_breakout_port_lane,
    _get_breakout_port_valid_speeds,
    _get_transfer_role_ipv4_addresses,
    _has_direct_ipv4_address,
    _has_transfer_role_ipv4,
    _is_untagged_vlan_member,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    """Minimal SONiC config scaffold the targeted helpers index into."""
    return {
        "PORT": {},
        "INTERFACE": {},
        "PORTCHANNEL": {},
        "PORTCHANNEL_INTERFACE": {},
        "PORTCHANNEL_MEMBER": {},
        "BREAKOUT_CFG": {},
        "BREAKOUT_PORTS": {},
    }


@pytest.fixture
def device():
    return SimpleNamespace(id=1, name="leaf-1")


@pytest.fixture
def patch_post_loop_hooks(mocker):
    """Patch the two helpers ``_add_port_configurations`` calls after its
    main loop, so individual tests can focus on the port-config branches.
    """
    return SimpleNamespace(
        missing=mocker.patch.object(config_generator, "_add_missing_breakout_ports"),
        tagged=mocker.patch.object(config_generator, "_add_tagged_vlans_to_ports"),
    )


def _port_info(*, index="1", lanes="1,2,3,4", speed="100000", **extra):
    """Shape used by ``port_config[port]``."""
    info = {"index": index, "lanes": lanes, "speed": speed}
    info.update(extra)
    return info


def _nb_iface(
    *, speed=None, speed_explicit=False, netbox_name=None, tags=None, type_=None
):
    """Shape used by ``netbox_interfaces[sonic_name]``."""
    return {
        "speed": speed,
        "speed_explicit": speed_explicit,
        "tags": tags or [],
        "type": type_,
        "netbox_name": netbox_name,
    }


# ---------------------------------------------------------------------------
# _add_port_configurations
# ---------------------------------------------------------------------------


class TestAddPortConfigurations:
    def test_ports_processed_in_natural_sort_order(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        port_config = {
            "Ethernet120": _port_info(index="120", lanes="121,122,123,124"),
            "Ethernet0": _port_info(index="1", lanes="1,2,3,4"),
            "Ethernet4": _port_info(index="4", lanes="5,6,7,8"),
        }
        alias = mocker.patch.object(
            config_generator,
            "convert_sonic_interface_to_alias",
            side_effect=lambda port, *_args, **_kw: f"alias-{port}",
        )

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        seen = [call.args[0] for call in alias.call_args_list]
        assert seen == ["Ethernet0", "Ethernet4", "Ethernet120"]

    def test_master_port_with_breakout_cfg_is_skipped(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator,
            "convert_sonic_interface_to_alias",
            return_value="alias",
        )
        port_config = {"Ethernet0": _port_info()}

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={
                "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
                "breakout_ports": {},
            },
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert "Ethernet0" not in config["PORT"]

    def test_admin_status_up_when_port_connected(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(),
            "Ethernet4": _port_info(index="4", lanes="5,6,7,8"),
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet0"]["admin_status"] == "up"
        assert config["PORT"]["Ethernet4"]["admin_status"] == "down"

    def test_admin_status_up_when_port_is_portchannel_member(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {"Ethernet0": _port_info()}

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={
                "portchannels": {},
                "member_mapping": {"Ethernet0": "PortChannel1"},
            },
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet0"]["admin_status"] == "up"

    def test_explicit_netbox_speed_overrides_port_config(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {"Ethernet0": _port_info(speed="40000")}
        netbox_interfaces = {
            "Ethernet0": _nb_iface(speed=100000, speed_explicit=True),
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces=netbox_interfaces,
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet0"]["speed"] == "100"

    def test_derived_netbox_speed_only_used_when_port_speed_empty(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(speed="40000"),
            "Ethernet4": _port_info(index="4", lanes="5,6,7,8", speed="0"),
            "Ethernet8": _port_info(index="8", lanes="9,10,11,12", speed=""),
        }
        netbox_interfaces = {
            "Ethernet0": _nb_iface(speed=25000, speed_explicit=False),
            "Ethernet4": _nb_iface(speed=25000, speed_explicit=False),
            "Ethernet8": _nb_iface(speed=25000, speed_explicit=False),
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces=netbox_interfaces,
            vlan_info={"vlan_members": {}},
            device=device,
        )

        # Existing speed is kept when explicit=False
        assert config["PORT"]["Ethernet0"]["speed"] == "40000"
        # speed "0" / "" → derived NetBox speed is applied (kbps → Mbps)
        assert config["PORT"]["Ethernet4"]["speed"] == "25"
        assert config["PORT"]["Ethernet8"]["speed"] == "25"

    def test_breakout_port_speed_from_netbox(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(speed="100000"),
            "Ethernet1": _port_info(index="1", lanes="2", speed="0"),
        }
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }
        netbox_interfaces = {
            "Ethernet1": _nb_iface(speed=25000, speed_explicit=True),
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info=breakout_info,
            netbox_interfaces=netbox_interfaces,
            vlan_info={"vlan_members": {}},
            device=device,
        )

        # 25000 kbps → 25 Mbps for breakout port
        assert config["PORT"]["Ethernet1"]["speed"] == "25"

    @pytest.mark.parametrize(
        "brkout_mode, expected_speed",
        [
            ("4x10G", "10000"),
            ("4x25G", "25000"),
            ("4x50G", "50000"),
            ("4x100G", "100000"),
            ("4x200G", "200000"),
        ],
    )
    def test_breakout_port_speed_derived_from_brkout_mode(
        self,
        config,
        device,
        mocker,
        patch_post_loop_hooks,
        brkout_mode,
        expected_speed,
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(speed="100000"),
            "Ethernet1": _port_info(index="1", lanes="2", speed="100000"),
        }
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": brkout_mode}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info=breakout_info,
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet1"]["speed"] == expected_speed

    def test_breakout_port_index_copied_from_master(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(index="42", lanes="1,2,3,4"),
            "Ethernet1": _port_info(index="999", lanes="2"),
        }
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info=breakout_info,
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet1"]["index"] == "42"

    def test_default_port_data_keys(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator,
            "convert_sonic_interface_to_alias",
            return_value="Eth1/1",
        )
        port_config = {"Ethernet0": _port_info(speed="100000")}

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        port = config["PORT"]["Ethernet0"]
        assert port == {
            "admin_status": "up",
            "alias": "Eth1/1",
            "index": "1",
            "lanes": "1,2,3,4",
            "speed": "100000",
            "mtu": "9100",
            "adv_speeds": "all",
            "autoneg": "off",
            "link_training": "off",
            "unreliable_los": "auto",
            "valid_speeds": "100000",
        }

    def test_valid_speeds_propagated_from_port_info(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(speed="100000", valid_speeds="100000,40000"),
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet0"]["valid_speeds"] == "100000,40000"

    def test_valid_speeds_falls_back_to_port_speed(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {"Ethernet0": _port_info(speed="40000")}

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info={"breakout_cfgs": {}, "breakout_ports": {}},
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet0"]["valid_speeds"] == "40000"

    def test_breakout_port_valid_speeds_overridden(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        port_config = {
            "Ethernet0": _port_info(speed="100000", valid_speeds="100000"),
            "Ethernet1": _port_info(
                index="1", lanes="2", speed="100000", valid_speeds="100000"
            ),
        }
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }

        _add_port_configurations(
            config,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            breakout_info=breakout_info,
            netbox_interfaces={},
            vlan_info={"vlan_members": {}},
            device=device,
        )

        assert config["PORT"]["Ethernet1"]["valid_speeds"] == "25000,10000,1000"

    def test_post_loop_hooks_invoked(
        self, config, device, mocker, patch_post_loop_hooks
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        portchannel_info = {"portchannels": {}, "member_mapping": {}}
        breakout_info = {"breakout_cfgs": {}, "breakout_ports": {}}
        netbox_interfaces = {}
        vlan_info = {"vlan_members": {}}

        _add_port_configurations(
            config,
            {"Ethernet0": _port_info()},
            connected_interfaces=set(),
            portchannel_info=portchannel_info,
            breakout_info=breakout_info,
            netbox_interfaces=netbox_interfaces,
            vlan_info=vlan_info,
            device=device,
        )

        patch_post_loop_hooks.missing.assert_called_once_with(
            config,
            breakout_info,
            {"Ethernet0": _port_info()},
            set(),
            portchannel_info,
            netbox_interfaces,
        )
        patch_post_loop_hooks.tagged.assert_called_once_with(
            config, vlan_info, netbox_interfaces, device
        )


# ---------------------------------------------------------------------------
# _get_breakout_port_valid_speeds
# ---------------------------------------------------------------------------


class TestGetBreakoutPortValidSpeeds:
    @pytest.mark.parametrize(
        "port_speed, expected",
        [
            ("10000", "10000,1000"),
            ("25000", "25000,10000,1000"),
            ("50000", "50000,25000,10000,1000"),
            ("100000", "100000,50000,25000,10000,1000"),
            ("200000", "200000,100000,50000,25000,10000,1000"),
            ("40000", "40000,10000,1000"),
        ],
    )
    def test_known_speeds(self, port_speed, expected):
        assert _get_breakout_port_valid_speeds(port_speed) == expected

    @pytest.mark.parametrize("falsy", [None, ""])
    def test_falsy_speed_returns_none(self, falsy):
        assert _get_breakout_port_valid_speeds(falsy) is None

    def test_unsupported_numeric_speed_appends_common_lower_speeds(self):
        # Numeric but non-standard speeds fall through to the generic branch
        # which appends 10000,1000 to whatever was passed in.
        assert _get_breakout_port_valid_speeds("12345") == "12345,10000,1000"

    def test_non_numeric_speed_raises(self):
        # The function casts via int() before branching, so non-numeric input
        # propagates a ValueError to the caller.
        with pytest.raises(ValueError):
            _get_breakout_port_valid_speeds("abc")


# ---------------------------------------------------------------------------
# _calculate_breakout_port_lane
# ---------------------------------------------------------------------------


class TestCalculateBreakoutPortLane:
    def test_standard_4_lane_breakout(self):
        port_config = {"Ethernet0": _port_info(lanes="1,2,3,4")}
        assert (
            _calculate_breakout_port_lane("Ethernet2", "Ethernet0", port_config) == "3"
        )

    def test_400g_8_lane_breakout(self):
        port_config = {
            "Ethernet0": _port_info(lanes="73,74,75,76,77,78,79,80"),
        }
        assert (
            _calculate_breakout_port_lane("Ethernet2", "Ethernet0", port_config)
            == "75,76"
        )
        assert (
            _calculate_breakout_port_lane("Ethernet6", "Ethernet0", port_config)
            == "79,80"
        )

    def test_range_syntax(self):
        port_config = {"Ethernet0": _port_info(lanes="1-4")}
        assert (
            _calculate_breakout_port_lane("Ethernet1", "Ethernet0", port_config) == "2"
        )

    def test_single_lane_master(self):
        port_config = {"Ethernet0": _port_info(lanes="5")}
        # total_lanes=1 → unexpected branch, lanes_per_port=1, returns single lane
        assert (
            _calculate_breakout_port_lane("Ethernet0", "Ethernet0", port_config) == "5"
        )

    def test_unexpected_lane_count(self):
        port_config = {"Ethernet0": _port_info(lanes="1,2,3,4,5,6")}
        # 6 lanes is unexpected → defaults to lanes_per_port=1, picks single lane
        assert (
            _calculate_breakout_port_lane("Ethernet2", "Ethernet0", port_config) == "3"
        )

    def test_calculated_range_out_of_bounds(self):
        port_config = {"Ethernet0": _port_info(lanes="1,2,3,4")}
        # offset 8 with lanes_per_port=1 → subport_index 8 → range out of bounds
        assert (
            _calculate_breakout_port_lane("Ethernet8", "Ethernet0", port_config) == "1"
        )

    def test_master_port_not_in_port_config(self):
        assert _calculate_breakout_port_lane("Ethernet1", "Ethernet0", {}) == "1"

    def test_port_name_regex_no_match(self):
        port_config = {"Ethernet0": _port_info(lanes="1,2,3,4")}
        assert (
            _calculate_breakout_port_lane("PortChannel1", "Ethernet0", port_config)
            == "1"
        )


# ---------------------------------------------------------------------------
# _add_missing_breakout_ports
# ---------------------------------------------------------------------------


class TestAddMissingBreakoutPorts:
    def test_existing_port_skipped(self, config, mocker):
        alias = mocker.patch.object(
            config_generator,
            "convert_sonic_interface_to_alias",
            return_value="alias",
        )
        config["PORT"]["Ethernet1"] = {"sentinel": True}
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }
        port_config = {"Ethernet0": _port_info(speed="100000", valid_speeds="100000")}

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        assert config["PORT"]["Ethernet1"] == {"sentinel": True}
        alias.assert_not_called()

    def test_speed_from_netbox_converts_kbps_to_mbps(self, config, mocker):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x100G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }
        # NetBox stores speed in kbps; 25 G = 25_000_000 kbps -> 25_000 Mbps
        netbox_interfaces = {"Ethernet1": _nb_iface(speed=25_000_000)}

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config={"Ethernet0": _port_info()},
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces=netbox_interfaces,
        )

        assert config["PORT"]["Ethernet1"]["speed"] == "25000"

    @pytest.mark.parametrize(
        "brkout_mode, expected_speed",
        [
            ("4x25G", "25000"),
            ("4x50G", "50000"),
            ("4x100G", "100000"),
            ("4x200G", "200000"),
            ("unknown", "25000"),  # default fallback
        ],
    )
    def test_speed_fallback_via_brkout_mode(
        self, config, mocker, brkout_mode, expected_speed
    ):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": brkout_mode}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config={"Ethernet0": _port_info()},
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        assert config["PORT"]["Ethernet1"]["speed"] == expected_speed

    def test_speed_default_when_master_not_in_breakout_cfgs(self, config, mocker):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config={},
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        assert config["PORT"]["Ethernet1"]["speed"] == "25000"

    def test_admin_status_follows_connection_state(self, config, mocker):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {
                "Ethernet1": {"master": "Ethernet0"},
                "Ethernet2": {"master": "Ethernet0"},
                "Ethernet3": {"master": "Ethernet0"},
            },
        }

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config={"Ethernet0": _port_info()},
            connected_interfaces={"Ethernet1"},
            portchannel_info={
                "portchannels": {},
                "member_mapping": {"Ethernet2": "PortChannel1"},
            },
            netbox_interfaces={},
        )

        assert config["PORT"]["Ethernet1"]["admin_status"] == "up"
        assert config["PORT"]["Ethernet2"]["admin_status"] == "up"
        assert config["PORT"]["Ethernet3"]["admin_status"] == "down"

    def test_port_index_default_and_master_copy(self, config, mocker):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {
                "Ethernet0": {"brkout_mode": "4x25G"},
                "Ethernet8": {"brkout_mode": "4x25G"},
            },
            "breakout_ports": {
                "Ethernet1": {"master": "Ethernet0"},  # master in port_config
                "Ethernet9": {"master": "Ethernet8"},  # master not in port_config
            },
        }
        port_config = {"Ethernet0": _port_info(index="42")}

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        assert config["PORT"]["Ethernet1"]["index"] == "42"
        assert config["PORT"]["Ethernet9"]["index"] == "1"

    def test_valid_speeds_overridden_after_master_default(self, config, mocker):
        mocker.patch.object(
            config_generator, "convert_sonic_interface_to_alias", return_value="a"
        )
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }
        port_config = {
            "Ethernet0": _port_info(speed="100000", valid_speeds="100000,40000"),
        }

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        # First master's "100000,40000" is set, then overridden by helper
        assert config["PORT"]["Ethernet1"]["valid_speeds"] == "25000,10000,1000"

    def test_alias_called_with_breakout_flag(self, config, mocker):
        alias = mocker.patch.object(
            config_generator,
            "convert_sonic_interface_to_alias",
            return_value="Eth1/1/2",
        )
        breakout_info = {
            "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
            "breakout_ports": {"Ethernet1": {"master": "Ethernet0"}},
        }
        port_config = {"Ethernet0": _port_info()}

        _add_missing_breakout_ports(
            config,
            breakout_info,
            port_config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            netbox_interfaces={},
        )

        alias.assert_called_once_with(
            "Ethernet1", 25000, is_breakout=True, port_config=port_config
        )


# ---------------------------------------------------------------------------
# _add_tagged_vlans_to_ports
# ---------------------------------------------------------------------------


class TestAddTaggedVlansToPorts:
    def test_multiple_tagged_vlans_sorted_numerically(self, config, device):
        config["PORT"]["Ethernet0"] = {"speed": "100000"}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {
            "vlan_members": {
                100: {"Eth1/1": "tagged"},
                10: {"Eth1/1": "tagged"},
                20: {"Eth1/1": "tagged"},
            },
        }

        _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device)

        assert config["PORT"]["Ethernet0"]["tagged_vlans"] == ["10", "20", "100"]

    def test_untagged_members_not_added(self, config, device):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {
            "vlan_members": {
                10: {"Eth1/1": "untagged"},
            },
        }

        _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device)

        assert "tagged_vlans" not in config["PORT"]["Ethernet0"]

    def test_unknown_netbox_interface_skipped(self, config, device, loguru_logs):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {
            "vlan_members": {
                10: {"Eth9/9": "tagged"},
            },
        }

        _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device)

        assert "tagged_vlans" not in config["PORT"]["Ethernet0"]
        assert any(
            r["level"] == "WARNING" and "Eth9/9" in r["message"] for r in loguru_logs
        )

    def test_port_in_mapping_but_absent_from_config(self, config, device):
        # Ethernet0 maps to Eth1/1 in netbox, but config["PORT"] is empty
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {
            "vlan_members": {
                10: {"Eth1/1": "tagged"},
            },
        }

        _add_tagged_vlans_to_ports(config, vlan_info, netbox_interfaces, device)

        assert config["PORT"] == {}


# ---------------------------------------------------------------------------
# _add_interface_configurations
# ---------------------------------------------------------------------------


class TestAddInterfaceConfigurations:
    def test_connected_with_ipv4(self, config, device):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        interface_ips = {"Eth1/1": "10.0.0.1/31"}

        _add_interface_configurations(
            config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            interface_ips=interface_ips,
            netbox_interfaces=netbox_interfaces,
            device=device,
        )

        assert config["INTERFACE"]["Ethernet0"] == {}
        assert config["INTERFACE"]["Ethernet0|10.0.0.1/31"] == {}

    def test_connected_without_ipv4(self, config, device):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}

        _add_interface_configurations(
            config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            interface_ips={},
            netbox_interfaces=netbox_interfaces,
            device=device,
        )

        assert config["INTERFACE"]["Ethernet0"] == {
            "ipv6_use_link_local_only": "enable"
        }

    def test_portchannel_member_skipped(self, config, device):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}

        _add_interface_configurations(
            config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={
                "portchannels": {},
                "member_mapping": {"Ethernet0": "PortChannel1"},
            },
            interface_ips={"Eth1/1": "10.0.0.1/31"},
            netbox_interfaces=netbox_interfaces,
            device=device,
        )

        assert "Ethernet0" not in config["INTERFACE"]

    def test_disconnected_skipped(self, config, device):
        config["PORT"]["Ethernet0"] = {}
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}

        _add_interface_configurations(
            config,
            connected_interfaces=set(),
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            interface_ips={"Eth1/1": "10.0.0.1/31"},
            netbox_interfaces=netbox_interfaces,
            device=device,
        )

        assert "Ethernet0" not in config["INTERFACE"]

    def test_connected_but_not_in_netbox_interfaces(self, config, device):
        config["PORT"]["Ethernet0"] = {}

        _add_interface_configurations(
            config,
            connected_interfaces={"Ethernet0"},
            portchannel_info={"portchannels": {}, "member_mapping": {}},
            interface_ips={},
            netbox_interfaces={},
            device=device,
        )

        # Falls into the no-IPv4 branch
        assert config["INTERFACE"]["Ethernet0"] == {
            "ipv6_use_link_local_only": "enable"
        }


# ---------------------------------------------------------------------------
# _get_transfer_role_ipv4_addresses
# ---------------------------------------------------------------------------


def _make_iface(iface_id, name, *, mgmt_only=False, type_value=None):
    type_attr = SimpleNamespace(value=type_value) if type_value is not None else None
    return SimpleNamespace(
        id=iface_id,
        name=name,
        mgmt_only=mgmt_only,
        type=type_attr,
    )


def _make_ip_addr(address, *, assigned_object_id):
    return SimpleNamespace(address=address, assigned_object_id=assigned_object_id)


class TestGetTransferRoleIpv4Addresses:
    def test_happy_path(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.10/24", assigned_object_id=1),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        result = _get_transfer_role_ipv4_addresses(device)

        assert result == {"Eth1/1": "10.5.0.10/24"}

    def test_first_ip_per_interface_wins(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.10/24", assigned_object_id=1),
            _make_ip_addr("10.5.0.11/24", assigned_object_id=1),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        result = _get_transfer_role_ipv4_addresses(device)

        assert result == {"Eth1/1": "10.5.0.10/24"}

    def test_ipv6_ignored(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("fd00::10/64", assigned_object_id=1),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        assert _get_transfer_role_ipv4_addresses(device) == {}

    def test_mgmt_and_virtual_interfaces_skipped(self, mocker, device):
        mgmt = _make_iface(1, "mgmt0", mgmt_only=True)
        virt = _make_iface(2, "vlan10", type_value="virtual")
        physical = _make_iface(3, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[mgmt, virt, physical],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.1/24", assigned_object_id=1),
            _make_ip_addr("10.5.0.2/24", assigned_object_id=2),
            _make_ip_addr("10.5.0.3/24", assigned_object_id=3),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        result = _get_transfer_role_ipv4_addresses(device)

        assert result == {"Eth1/1": "10.5.0.3/24"}

    def test_invalid_prefix_string_caught(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.10/24", assigned_object_id=1),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="not-a-prefix"),
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        result = _get_transfer_role_ipv4_addresses(device)

        assert result == {"Eth1/1": "10.5.0.10/24"}

    def test_invalid_ip_address_caught(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        iface2 = _make_iface(2, "Eth1/2")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface, iface2],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("not-an-ip", assigned_object_id=1),
            _make_ip_addr("10.5.0.20/24", assigned_object_id=2),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        result = _get_transfer_role_ipv4_addresses(device)

        assert result == {"Eth1/2": "10.5.0.20/24"}

    def test_ip_without_assigned_object_id_skipped(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.10/24", assigned_object_id=None),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        assert _get_transfer_role_ipv4_addresses(device) == {}

    def test_assigned_object_id_not_in_interface_map(self, mocker, device):
        iface = _make_iface(1, "Eth1/1")
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            return_value=[iface],
        )
        nb = mocker.patch.object(config_generator, "utils", create=True).nb
        nb.ipam.ip_addresses.filter.return_value = [
            _make_ip_addr("10.5.0.10/24", assigned_object_id=999),
        ]
        nb.ipam.prefixes.filter.return_value = [
            SimpleNamespace(prefix="10.5.0.0/24"),
        ]

        assert _get_transfer_role_ipv4_addresses(device) == {}

    def test_top_level_exception_returns_empty_dict(self, mocker, device):
        mocker.patch.object(
            config_generator,
            "get_cached_device_interfaces",
            side_effect=RuntimeError("netbox down"),
        )

        assert _get_transfer_role_ipv4_addresses(device) == {}


# ---------------------------------------------------------------------------
# _has_direct_ipv4_address
# ---------------------------------------------------------------------------


class TestHasDirectIpv4Address:
    def test_mapped_with_ipv4(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        interface_ips = {"Eth1/1": "10.0.0.1/31"}
        assert _has_direct_ipv4_address("Ethernet0", interface_ips, netbox_interfaces)

    def test_mapped_without_ipv4(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        assert not _has_direct_ipv4_address(
            "Ethernet0", {"Eth9/9": "ip"}, netbox_interfaces
        )

    def test_port_not_in_netbox_interfaces(self):
        assert not _has_direct_ipv4_address("Ethernet0", {"Eth1/1": "ip"}, {})

    def test_empty_interface_ips(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        assert not _has_direct_ipv4_address("Ethernet0", {}, netbox_interfaces)
        assert not _has_direct_ipv4_address("Ethernet0", None, netbox_interfaces)

    def test_empty_netbox_interfaces(self):
        assert not _has_direct_ipv4_address("Ethernet0", {"Eth1/1": "ip"}, None)


# ---------------------------------------------------------------------------
# _has_transfer_role_ipv4
# ---------------------------------------------------------------------------


class TestHasTransferRoleIpv4:
    def test_mapped_with_transfer_ip(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        transfer_ips = {"Eth1/1": "10.5.0.1/24"}
        assert _has_transfer_role_ipv4("Ethernet0", transfer_ips, netbox_interfaces)

    def test_empty_inputs(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        assert not _has_transfer_role_ipv4("Ethernet0", {}, netbox_interfaces)
        assert not _has_transfer_role_ipv4("Ethernet0", None, netbox_interfaces)
        assert not _has_transfer_role_ipv4("Ethernet0", {"Eth1/1": "ip"}, None)


# ---------------------------------------------------------------------------
# _is_untagged_vlan_member
# ---------------------------------------------------------------------------


class TestIsUntaggedVlanMember:
    def test_untagged_member_returns_true(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {"vlan_members": {10: {"Eth1/1": "untagged"}}}
        assert _is_untagged_vlan_member("Ethernet0", vlan_info, netbox_interfaces)

    def test_only_tagged_returns_false(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        vlan_info = {"vlan_members": {10: {"Eth1/1": "tagged"}}}
        assert not _is_untagged_vlan_member("Ethernet0", vlan_info, netbox_interfaces)

    def test_port_not_in_netbox_interfaces(self):
        vlan_info = {"vlan_members": {10: {"Eth1/1": "untagged"}}}
        assert not _is_untagged_vlan_member("Ethernet0", vlan_info, {})

    def test_empty_inputs(self):
        netbox_interfaces = {"Ethernet0": _nb_iface(netbox_name="Eth1/1")}
        assert not _is_untagged_vlan_member("Ethernet0", {}, netbox_interfaces)
        assert not _is_untagged_vlan_member("Ethernet0", None, netbox_interfaces)


# ---------------------------------------------------------------------------
# _add_portchannel_configuration
# ---------------------------------------------------------------------------


class TestAddPortchannelConfiguration:
    def test_portchannel_with_no_members(self, config):
        # PORTCHANNEL and PORTCHANNEL_INTERFACE are still created for a
        # member-less port-channel, but PORTCHANNEL_MEMBER stays empty.
        portchannel_info = {
            "portchannels": {
                "PortChannel1": {
                    "admin_status": "up",
                    "fast_rate": "false",
                    "min_links": "1",
                    "mtu": "9100",
                    "members": [],
                },
            },
            "member_mapping": {},
        }

        _add_portchannel_configuration(config, portchannel_info)

        assert config["PORTCHANNEL"]["PortChannel1"] == {
            "admin_status": "up",
            "fast_rate": "false",
            "min_links": "1",
            "mtu": "9100",
        }
        assert config["PORTCHANNEL_INTERFACE"]["PortChannel1"] == {
            "ipv6_use_link_local_only": "enable"
        }
        assert config["PORTCHANNEL_MEMBER"] == {}

    def test_one_portchannel_with_two_members(self, config):
        portchannel_info = {
            "portchannels": {
                "PortChannel1": {
                    "admin_status": "up",
                    "fast_rate": "false",
                    "min_links": "1",
                    "mtu": "9100",
                    "members": ["Ethernet0", "Ethernet4"],
                },
            },
            "member_mapping": {
                "Ethernet0": "PortChannel1",
                "Ethernet4": "PortChannel1",
            },
        }

        _add_portchannel_configuration(config, portchannel_info)

        assert config["PORTCHANNEL"]["PortChannel1"] == {
            "admin_status": "up",
            "fast_rate": "false",
            "min_links": "1",
            "mtu": "9100",
        }
        assert config["PORTCHANNEL_INTERFACE"]["PortChannel1"] == {
            "ipv6_use_link_local_only": "enable"
        }
        assert "PortChannel1|Ethernet0" in config["PORTCHANNEL_MEMBER"]
        assert "PortChannel1|Ethernet4" in config["PORTCHANNEL_MEMBER"]
        assert config["PORTCHANNEL_MEMBER"]["PortChannel1|Ethernet0"] == {}

    def test_empty_portchannels_no_op(self, config):
        _add_portchannel_configuration(
            config, {"portchannels": {}, "member_mapping": {}}
        )

        assert config["PORTCHANNEL"] == {}
        assert config["PORTCHANNEL_INTERFACE"] == {}
        assert config["PORTCHANNEL_MEMBER"] == {}
