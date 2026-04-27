# SPDX-License-Identifier: Apache-2.0

import pytest

from osism.tasks.conductor.sonic.constants import (
    BGP_AF_L2VPN_EVPN_TAG,
    DEFAULT_LOCAL_AS_PREFIX,
    DEFAULT_SONIC_ROLES,
    DEFAULT_SONIC_VERSION,
    HIGH_SPEED_PORTS,
    PORT_CONFIG_PATH,
    PORT_TYPE_TO_SPEED_MAP,
    SUPPORTED_HWSKUS,
)

# ---------------------------------------------------------------------------
# Simple constant values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "constant,expected",
    [
        (BGP_AF_L2VPN_EVPN_TAG, "bgp-af-l2vpn-evpn"),
        (DEFAULT_LOCAL_AS_PREFIX, 4200),
        (PORT_CONFIG_PATH, "/etc/sonic/port_config"),
    ],
)
def test_simple_constant_values(constant, expected):
    assert constant == expected


def test_default_local_as_prefix_is_int():
    assert isinstance(DEFAULT_LOCAL_AS_PREFIX, int)


# ---------------------------------------------------------------------------
# DEFAULT_SONIC_ROLES
# ---------------------------------------------------------------------------


def test_default_sonic_roles_contains_expected_roles():
    expected = {"spine", "superspine", "leaf", "accessleaf"}

    assert expected.issubset(set(DEFAULT_SONIC_ROLES))


def test_default_sonic_roles_is_sorted():
    assert DEFAULT_SONIC_ROLES == sorted(DEFAULT_SONIC_ROLES)


def test_default_sonic_roles_has_no_duplicates():
    assert len(DEFAULT_SONIC_ROLES) == len(set(DEFAULT_SONIC_ROLES))


def test_default_sonic_roles_entries_are_non_empty_strings():
    for role in DEFAULT_SONIC_ROLES:
        assert isinstance(role, str)
        assert role


# ---------------------------------------------------------------------------
# DEFAULT_SONIC_VERSION
# ---------------------------------------------------------------------------


def test_default_sonic_version_is_non_empty_string():
    assert isinstance(DEFAULT_SONIC_VERSION, str)
    assert DEFAULT_SONIC_VERSION


# ---------------------------------------------------------------------------
# PORT_TYPE_TO_SPEED_MAP
# ---------------------------------------------------------------------------


def test_port_type_to_speed_map_values_are_non_negative_ints():
    for key, value in PORT_TYPE_TO_SPEED_MAP.items():
        assert isinstance(value, int), key
        assert value >= 0, key


def test_port_type_to_speed_map_keys_are_non_empty_strings():
    for key in PORT_TYPE_TO_SPEED_MAP:
        assert isinstance(key, str)
        assert key


@pytest.mark.parametrize(
    "port_type,expected_speed",
    [
        ("virtual", 0),
        ("10gbase-t", 10000),
        ("100gbase-x-qsfp28", 100000),
        ("400gbase-x-qsfpdd", 400000),
    ],
)
def test_port_type_to_speed_map_specific_values(port_type, expected_speed):
    assert PORT_TYPE_TO_SPEED_MAP[port_type] == expected_speed


# ---------------------------------------------------------------------------
# HIGH_SPEED_PORTS
# ---------------------------------------------------------------------------


def test_high_speed_ports_value():
    assert HIGH_SPEED_PORTS == {100000, 200000, 400000, 800000}


def test_high_speed_ports_is_set():
    assert isinstance(HIGH_SPEED_PORTS, set)


def test_high_speed_ports_values_positive():
    for value in HIGH_SPEED_PORTS:
        assert isinstance(value, int)
        assert value > 0


def test_high_speed_ports_consistent_with_port_type_map():
    # All high-speed ports must be representable by at least one port type,
    # except 800000 which is reserved for future 800G ports and has no entry
    # in PORT_TYPE_TO_SPEED_MAP yet. Asserting on the exact gap (rather than
    # skipping 800000) makes the test fail once an 800000 port type is added,
    # forcing the maintainer to remove this carve-out.
    speeds_in_map = set(PORT_TYPE_TO_SPEED_MAP.values())
    unrepresented = HIGH_SPEED_PORTS - speeds_in_map

    assert unrepresented == {800000}


# ---------------------------------------------------------------------------
# SUPPORTED_HWSKUS
# ---------------------------------------------------------------------------


def test_supported_hwskus_is_non_empty():
    assert SUPPORTED_HWSKUS


def test_supported_hwskus_no_duplicates():
    assert len(SUPPORTED_HWSKUS) == len(set(SUPPORTED_HWSKUS))


@pytest.mark.parametrize("hwsku", SUPPORTED_HWSKUS)
def test_supported_hwskus_entry_invariants(hwsku):
    assert isinstance(hwsku, str)
    assert hwsku
    assert hwsku.startswith("Accton-")
