# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.bgp import (
    calculate_local_asn_from_ipv4,
    calculate_minimum_as_for_group,
    find_interconnected_spine_groups,
)
from osism.tasks.conductor.sonic.constants import DEFAULT_LOCAL_AS_PREFIX

# ---------------------------------------------------------------------------
# calculate_local_asn_from_ipv4
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip,prefix,expected",
    [
        # docstring example
        ("192.168.45.123", None, 4200045123),
        # CIDR suffix is stripped before parsing
        ("192.168.45.123/32", None, 4200045123),
        # third/fourth octet are zero-padded into the lower 6 digits
        ("10.20.5.7", None, 4200005007),
        # boundary octets
        ("0.0.0.0", None, 4200000000),
        ("255.255.255.255", None, 4200255255),
        # custom prefix replaces DEFAULT_LOCAL_AS_PREFIX
        ("10.0.1.2", 4201, 4201001002),
        # custom prefix combined with CIDR
        ("10.0.1.2/24", 4201, 4201001002),
    ],
)
def test_calculate_local_asn_from_ipv4_valid_inputs(ip, prefix, expected):
    if prefix is None:
        assert calculate_local_asn_from_ipv4(ip) == expected
    else:
        assert calculate_local_asn_from_ipv4(ip, prefix=prefix) == expected


def test_calculate_local_asn_from_ipv4_returns_int():
    result = calculate_local_asn_from_ipv4("192.168.45.123")

    assert isinstance(result, int)


def test_calculate_local_asn_from_ipv4_uses_default_prefix():
    assert calculate_local_asn_from_ipv4(
        "192.168.45.123"
    ) == calculate_local_asn_from_ipv4("192.168.45.123", prefix=DEFAULT_LOCAL_AS_PREFIX)


def test_calculate_local_asn_from_ipv4_only_third_and_fourth_octets_matter():
    # First two octets are not part of the AS number — only the lower two are.
    assert calculate_local_asn_from_ipv4("1.2.45.123") == calculate_local_asn_from_ipv4(
        "99.99.45.123"
    )


@pytest.mark.parametrize(
    "invalid_input,expected_match",
    [
        ("192.168.45", "Invalid IPv4 address format"),
        ("not-an-ip", "Invalid IPv4 address format"),
        ("192.168.45.999", "Invalid octet values"),
        ("192.168.999.45", "Invalid octet values"),
        ("", "Invalid IPv4 address format"),
        ("192.168.45.123.1", "Invalid IPv4 address format"),
        ("192.168.45.abc", "invalid literal for int"),
    ],
)
def test_calculate_local_asn_from_ipv4_invalid_inputs(invalid_input, expected_match):
    with pytest.raises(ValueError, match=expected_match):
        calculate_local_asn_from_ipv4(invalid_input)


def test_calculate_local_asn_from_ipv4_error_message_includes_input():
    with pytest.raises(ValueError, match="192.168.45.999"):
        calculate_local_asn_from_ipv4("192.168.45.999")


# ---------------------------------------------------------------------------
# calculate_minimum_as_for_group
# ---------------------------------------------------------------------------


def _device(name, primary_ip4):
    return SimpleNamespace(name=name, primary_ip4=primary_ip4)


def test_calculate_minimum_as_for_group_three_devices():
    devices = [
        _device("sw1", "192.168.45.123/32"),
        _device("sw2", "192.168.45.50/32"),
        _device("sw3", "192.168.45.200/32"),
    ]

    result = calculate_minimum_as_for_group(devices)

    assert result == 4200045050


def test_calculate_minimum_as_for_group_skips_invalid_ip(mocker):
    debug = mocker.patch("osism.tasks.conductor.sonic.bgp.logger.debug")
    devices = [
        _device("sw1", "not-an-ip"),
        _device("sw2", "192.168.45.50/32"),
        _device("sw3", "192.168.45.200/32"),
    ]

    result = calculate_minimum_as_for_group(devices)

    assert result == 4200045050
    debug.assert_called_once()
    assert "sw1" in debug.call_args.args[0]


def test_calculate_minimum_as_for_group_all_invalid_returns_none(mocker):
    debug = mocker.patch("osism.tasks.conductor.sonic.bgp.logger.debug")
    devices = [
        _device("sw1", "not-an-ip"),
        _device("sw2", "also-bad"),
    ]

    assert calculate_minimum_as_for_group(devices) is None
    assert debug.call_count == 2


def test_calculate_minimum_as_for_group_empty_returns_none():
    assert calculate_minimum_as_for_group([]) is None


def test_calculate_minimum_as_for_group_skips_none_primary_ip4(mocker):
    debug = mocker.patch("osism.tasks.conductor.sonic.bgp.logger.debug")
    devices = [
        _device("sw1", None),
        _device("sw2", "192.168.45.50/32"),
    ]

    result = calculate_minimum_as_for_group(devices)

    assert result == 4200045050
    # None falls through the truthiness check, so logger.debug must NOT be called
    # for the skipped device.
    debug.assert_not_called()


def test_calculate_minimum_as_for_group_skips_empty_string_primary_ip4(mocker):
    debug = mocker.patch("osism.tasks.conductor.sonic.bgp.logger.debug")
    devices = [
        _device("sw1", ""),
        _device("sw2", "192.168.45.50/32"),
    ]

    result = calculate_minimum_as_for_group(devices)

    assert result == 4200045050
    debug.assert_not_called()


def test_calculate_minimum_as_for_group_all_none_returns_none():
    devices = [
        _device("sw1", None),
        _device("sw2", None),
    ]

    assert calculate_minimum_as_for_group(devices) is None


def test_calculate_minimum_as_for_group_single_device():
    devices = [_device("sw1", "192.168.45.123/32")]

    assert calculate_minimum_as_for_group(devices) == 4200045123


def test_calculate_minimum_as_for_group_custom_prefix():
    devices = [
        _device("sw1", "10.0.1.2/32"),
        _device("sw2", "10.0.5.10/32"),
    ]

    assert calculate_minimum_as_for_group(devices, prefix=4201) == 4201001002


def test_calculate_minimum_as_for_group_stringifies_primary_ip4(mocker):
    # primary_ip4 may be a non-str object (e.g. NetBox IPAddress) — the function
    # passes it through str() before parsing.
    class _IP:
        def __str__(self):
            return "192.168.45.123/32"

    devices = [_device("sw1", _IP())]

    assert calculate_minimum_as_for_group(devices) == 4200045123


# ---------------------------------------------------------------------------
# find_interconnected_spine_groups (deprecated wrapper)
# ---------------------------------------------------------------------------


def test_find_interconnected_spine_groups_delegates_with_default_roles(mocker):
    mock_fn = mocker.patch(
        "osism.tasks.conductor.sonic.connections.find_interconnected_devices",
        return_value=[["device-a", "device-b"]],
    )
    devices = ["device-a", "device-b", "device-c"]

    result = find_interconnected_spine_groups(devices)

    mock_fn.assert_called_once_with(devices, ["spine", "superspine"])
    assert result == [["device-a", "device-b"]]


def test_find_interconnected_spine_groups_passes_custom_target_roles(mocker):
    mock_fn = mocker.patch(
        "osism.tasks.conductor.sonic.connections.find_interconnected_devices",
        return_value=[],
    )
    devices = ["device-a"]
    custom_roles = ["leaf", "accessleaf"]

    result = find_interconnected_spine_groups(devices, target_roles=custom_roles)

    mock_fn.assert_called_once_with(devices, custom_roles)
    assert result == []


def test_find_interconnected_spine_groups_returns_value_unchanged(mocker):
    sentinel = object()
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.find_interconnected_devices",
        return_value=sentinel,
    )

    assert find_interconnected_spine_groups([]) is sentinel
