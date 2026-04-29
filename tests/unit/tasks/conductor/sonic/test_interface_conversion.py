# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the conversion / port-config helpers in
``osism.tasks.conductor.sonic.interface``.

The two ``detect_*`` functions in the same module are tracked separately
(see #2199) and intentionally not covered here.
"""

from types import SimpleNamespace
from unittest.mock import mock_open

import pytest

from osism.tasks.conductor.sonic.interface import (
    _convert_using_port_config,
    _convert_using_speed_calculation,
    _extract_port_number_from_alias,
    _find_base_port_for_breakout,
    _find_sonic_name_by_alias_mapping,
    _handle_breakout_interface,
    _handle_standard_interface,
    _map_interface_name_to_sonic,
    clear_port_config_cache,
    convert_netbox_interface_to_sonic,
    convert_sonic_interface_to_alias,
    get_connected_interfaces,
    get_port_config,
    get_speed_from_port_type,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_port_config_cache():
    """Each test starts and ends with an empty module-level port-config cache.

    The cache is keyed by HWSKU; without isolation, a prior test that cached
    a fake port_config would silently feed it into later tests.
    """
    clear_port_config_cache()
    yield
    clear_port_config_cache()


def _make_device(hwsku="Accton-AS7326-56X", device_id=1, name="sw-1"):
    """Build a minimal NetBox-shaped device with sonic_parameters."""
    custom_fields = (
        {"sonic_parameters": {"hwsku": hwsku}}
        if hwsku is not None
        else {"sonic_parameters": {}}
    )
    return SimpleNamespace(id=device_id, name=name, custom_fields=custom_fields)


def _make_iface(name):
    return SimpleNamespace(name=name)


# ---------------------------------------------------------------------------
# get_speed_from_port_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port_type,expected",
    [
        ("10gbase-x-sfpp", 10000),
        ("100gbase-x-qsfp28", 100000),
        # Mixed case: implementation lower-cases before lookup.
        ("100GBase-X-QSFP28", 100000),
        ("400gbase-x-qsfpdd", 400000),
    ],
)
def test_get_speed_from_port_type_known(port_type, expected):
    assert get_speed_from_port_type(port_type) == expected


@pytest.mark.parametrize("falsy", [None, ""])
def test_get_speed_from_port_type_returns_none_for_falsy_input(falsy):
    assert get_speed_from_port_type(falsy) is None


def test_get_speed_from_port_type_unknown_returns_none():
    assert get_speed_from_port_type("banana") is None


def test_get_speed_from_port_type_numeric_input_coerced():
    # Defensive: integer-like input is str()-coerced; not in the map → None.
    assert get_speed_from_port_type(1234) is None


# ---------------------------------------------------------------------------
# convert_netbox_interface_to_sonic
# ---------------------------------------------------------------------------


def test_convert_netbox_interface_already_sonic_returns_unchanged():
    device = _make_device()
    iface = _make_iface("Ethernet4")

    assert convert_netbox_interface_to_sonic(iface, device) == "Ethernet4"


def test_convert_netbox_interface_string_without_device_returns_input():
    assert convert_netbox_interface_to_sonic("Eth1/1", device=None) == "Eth1/1"


def test_convert_netbox_interface_object_without_device_returns_name():
    iface = _make_iface("Eth1/1")

    assert convert_netbox_interface_to_sonic(iface, device=None) == "Eth1/1"


def test_convert_netbox_interface_device_without_hwsku_returns_input():
    device = _make_device(hwsku=None)  # sonic_parameters dict, no "hwsku" key
    iface = _make_iface("Eth1/1")

    assert convert_netbox_interface_to_sonic(iface, device) == "Eth1/1"


def test_convert_netbox_interface_cache_failure_returns_input(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
        side_effect=RuntimeError("netbox down"),
    )
    device = _make_device()
    iface = _make_iface("Eth1/1")

    assert convert_netbox_interface_to_sonic(iface, device) == "Eth1/1"


def test_convert_netbox_interface_empty_port_config_returns_input(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
        return_value=[_make_iface("Eth1/1")],
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_port_config",
        return_value={},
    )
    device = _make_device()

    assert convert_netbox_interface_to_sonic(_make_iface("Eth1/1"), device) == "Eth1/1"


def test_convert_netbox_interface_port_config_raises_returns_input(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
        return_value=[_make_iface("Eth1/1")],
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_port_config",
        side_effect=RuntimeError("disk error"),
    )
    device = _make_device()

    assert convert_netbox_interface_to_sonic(_make_iface("Eth1/1"), device) == "Eth1/1"


def test_convert_netbox_interface_standard_form_resolves_via_alias(mocker):
    iface = _make_iface("Eth1/1")
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
        return_value=[iface],
    )
    port_config = {
        "Ethernet0": {
            "lanes": "1",
            "alias": "tenGigE1",
            "index": "1",
            "speed": "10000",
        },
    }
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_port_config",
        return_value=port_config,
    )
    device = _make_device()

    assert convert_netbox_interface_to_sonic(iface, device) == "Ethernet0"


def test_convert_netbox_interface_breakout_form_resolves(mocker):
    # Build an interface list that looks like a 4-lane breakout group on
    # physical port 49 — _handle_breakout_interface should drive the result.
    breakout_ifaces = [_make_iface(f"Eth1/49/{i}") for i in range(1, 5)]
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
        return_value=breakout_ifaces,
    )
    port_config = {
        "Ethernet48": {
            "lanes": "53,54,55,56",
            "alias": "hundredGigE49",
            "index": "13",
            "speed": "100000",
        },
    }
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.get_port_config",
        return_value=port_config,
    )
    device = _make_device()

    assert convert_netbox_interface_to_sonic(breakout_ifaces[0], device) == "Ethernet48"
    assert convert_netbox_interface_to_sonic(breakout_ifaces[3], device) == "Ethernet51"


# ---------------------------------------------------------------------------
# _map_interface_name_to_sonic
# ---------------------------------------------------------------------------


def test_map_interface_name_routes_breakout_form(mocker):
    spy = mocker.patch(
        "osism.tasks.conductor.sonic.interface._handle_breakout_interface",
        return_value="Ethernet48",
    )
    port_config = {"Ethernet48": {"alias": "hundredGigE49"}}

    result = _map_interface_name_to_sonic(
        "Eth1/49/1", ["Eth1/49/1"], port_config, "hwsku"
    )

    spy.assert_called_once()
    assert result == "Ethernet48"


def test_map_interface_name_routes_standard_form(mocker):
    spy = mocker.patch(
        "osism.tasks.conductor.sonic.interface._handle_standard_interface",
        return_value="Ethernet0",
    )
    port_config = {"Ethernet0": {"alias": "tenGigE1"}}

    result = _map_interface_name_to_sonic("Eth1/1", ["Eth1/1"], port_config, "hwsku")

    spy.assert_called_once()
    assert result == "Ethernet0"


def test_map_interface_name_finds_match_via_alias_scan():
    # The "any other format" branch: interface name matches an alias verbatim.
    port_config = {"Ethernet0": {"alias": "Eth1(Port1)"}}

    assert (
        _map_interface_name_to_sonic("Eth1(Port1)", [], port_config, "hwsku")
        == "Ethernet0"
    )


def test_map_interface_name_unknown_format_returns_input():
    port_config = {"Ethernet0": {"alias": "tenGigE1"}}

    assert (
        _map_interface_name_to_sonic("strange-name", [], port_config, "hwsku")
        == "strange-name"
    )


# ---------------------------------------------------------------------------
# _handle_breakout_interface
# ---------------------------------------------------------------------------


def test_handle_breakout_single_subport_falls_through_to_alias_mapping():
    # Only one Eth1/1/1 in the list → not a breakout group → fall through.
    port_config = {
        "Ethernet0": {
            "lanes": "1",
            "alias": "tenGigE1",
            "index": "1",
            "speed": "10000",
        },
    }

    assert (
        _handle_breakout_interface("Eth1/1/1", ["Eth1/1/1"], port_config, "hwsku")
        == "Ethernet0"
    )


def test_handle_breakout_4_lane_group_maps_subports_sequentially():
    interface_names = [f"Eth1/49/{i}" for i in range(1, 5)]
    port_config = {
        "Ethernet48": {
            "lanes": "53,54,55,56",
            "alias": "hundredGigE49",
            "index": "13",
            "speed": "25000",
        },
    }

    expected = ["Ethernet48", "Ethernet49", "Ethernet50", "Ethernet51"]
    for name, want in zip(interface_names, expected):
        assert (
            _handle_breakout_interface(name, interface_names, port_config, "hwsku")
            == want
        )


def test_handle_breakout_8_lane_master_uses_offset_multiplier_2():
    interface_names = [f"Eth1/1/{i}" for i in range(1, 5)]
    port_config = {
        "Ethernet0": {
            "lanes": "73,74,75,76,77,78,79,80",
            "alias": "fourHundredGigE1",
            "index": "1",
            "speed": "100000",
        },
    }

    expected = ["Ethernet0", "Ethernet2", "Ethernet4", "Ethernet6"]
    for name, want in zip(interface_names, expected):
        assert (
            _handle_breakout_interface(name, interface_names, port_config, "hwsku")
            == want
        )


def test_handle_breakout_sorts_subports_before_mapping():
    # Out-of-order list must not affect subport→Ethernet mapping; the
    # implementation re-sorts breakout_group by subport number.
    interface_names = ["Eth1/49/3", "Eth1/49/1", "Eth1/49/4", "Eth1/49/2"]
    port_config = {
        "Ethernet48": {
            "lanes": "53,54,55,56",
            "alias": "hundredGigE49",
            "index": "13",
            "speed": "25000",
        },
    }

    assert (
        _handle_breakout_interface("Eth1/49/2", interface_names, port_config, "hwsku")
        == "Ethernet49"
    )


def test_handle_breakout_master_alias_not_found_returns_input():
    # Group has >1 subport, but no alias in port_config maps Eth1/1/1, so
    # base_sonic_name doesn't begin with "Ethernet" and we fall through to
    # a final alias scan that also fails — input is returned.
    interface_names = ["Eth1/1/1", "Eth1/1/2"]
    port_config = {}  # no aliases at all

    assert (
        _handle_breakout_interface("Eth1/1/1", interface_names, port_config, "hwsku")
        == "Eth1/1/1"
    )


def test_handle_breakout_regex_no_match_returns_input():
    # Calling _handle_breakout_interface directly with a non-breakout name
    # should hit the early-return guard and echo the input back.
    assert (
        _handle_breakout_interface(
            "Eth1/1", [], {"Ethernet0": {"alias": "x1"}}, "hwsku"
        )
        == "Eth1/1"
    )


# ---------------------------------------------------------------------------
# _handle_standard_interface
# ---------------------------------------------------------------------------


def test_handle_standard_delegates_to_alias_mapping(mocker):
    spy = mocker.patch(
        "osism.tasks.conductor.sonic.interface._find_sonic_name_by_alias_mapping",
        return_value="Ethernet0",
    )
    port_config = {"Ethernet0": {"alias": "tenGigE1"}}

    result = _handle_standard_interface("Eth1/1", port_config, "hwsku")

    spy.assert_called_once_with("Eth1/1", port_config)
    assert result == "Ethernet0"


# ---------------------------------------------------------------------------
# _find_sonic_name_by_alias_mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "interface_name,expected",
    [
        ("Eth1(Port1)", "Ethernet0"),
        ("Eth48(Port48)", "Ethernet47"),
    ],
)
def test_find_sonic_name_paren_form_uses_one_based_offset(interface_name, expected):
    # The Eth(Port) format short-circuits the alias scan and uses the
    # 1-based-to-0-based conversion directly.
    assert _find_sonic_name_by_alias_mapping(interface_name, {}) == expected


def test_find_sonic_name_standard_form_resolves_via_alias():
    port_config = {
        "Ethernet0": {"alias": "tenGigE1"},
        "Ethernet1": {"alias": "tenGigE2"},
    }

    assert _find_sonic_name_by_alias_mapping("Eth1/1", port_config) == "Ethernet0"


def test_find_sonic_name_breakout_first_subport_resolves_via_alias():
    port_config = {
        "Ethernet48": {"alias": "hundredGigE49"},
    }

    assert _find_sonic_name_by_alias_mapping("Eth1/49/1", port_config) == "Ethernet48"


def test_find_sonic_name_skips_entries_with_empty_alias():
    # Empty-alias entries must be skipped silently — only the populated entry
    # is considered.
    port_config = {
        "Ethernet0": {"alias": ""},
        "Ethernet1": {"alias": "tenGigE1"},
    }

    assert _find_sonic_name_by_alias_mapping("Eth1/1", port_config) == "Ethernet1"


def test_find_sonic_name_skips_alias_without_trailing_number():
    # An alias that yields no port number from either regex must be skipped.
    port_config = {
        "Ethernet0": {"alias": "no-digits-here"},
    }

    assert _find_sonic_name_by_alias_mapping("Eth1/1", port_config) == "Eth1/1"


def test_find_sonic_name_no_match_returns_input():
    # Alias_num is 99, expected names are Eth1/99 / Eth1/99/1 — neither
    # matches the input — return input unchanged.
    port_config = {
        "Ethernet0": {"alias": "tenGigE99"},
    }

    assert _find_sonic_name_by_alias_mapping("Eth1/1", port_config) == "Eth1/1"


# ---------------------------------------------------------------------------
# convert_sonic_interface_to_alias
# ---------------------------------------------------------------------------


def test_convert_sonic_to_alias_non_ethernet_returned_unchanged():
    assert convert_sonic_interface_to_alias("PortChannel1") == "PortChannel1"


def test_convert_sonic_to_alias_regular_with_port_config():
    port_config = {
        "Ethernet0": {"alias": "twentyFiveGigE1"},
    }

    assert (
        convert_sonic_interface_to_alias("Ethernet0", port_config=port_config)
        == "Eth1/1"
    )


def test_convert_sonic_to_alias_breakout_with_port_config():
    # Ethernet2 isn't in port_config — _find_base_port_for_breakout walks
    # backwards to Ethernet0 (alias twentyFiveGigE1, port 1). Subport is
    # (2 - 0) + 1 = 3 → Eth1/1/3.
    port_config = {
        "Ethernet0": {"alias": "twentyFiveGigE1"},
    }

    assert (
        convert_sonic_interface_to_alias(
            "Ethernet2", is_breakout=True, port_config=port_config
        )
        == "Eth1/1/3"
    )


def test_convert_sonic_to_alias_regular_high_speed_no_port_config():
    # 100G is in HIGH_SPEED_PORTS → multiplier 4 → Ethernet4 -> Eth1/2.
    assert (
        convert_sonic_interface_to_alias("Ethernet4", interface_speed=100000)
        == "Eth1/2"
    )


def test_convert_sonic_to_alias_regular_low_speed_no_port_config():
    # 25G falls outside HIGH_SPEED_PORTS → multiplier 1 → Ethernet4 -> Eth1/5.
    assert (
        convert_sonic_interface_to_alias("Ethernet4", interface_speed=25000) == "Eth1/5"
    )


def test_convert_sonic_to_alias_breakout_no_port_config_legacy_calc():
    # Legacy speed-based fallback: Ethernet5 → base_port=4, subport=2,
    # physical_port=2 → Eth1/2/2.
    assert convert_sonic_interface_to_alias("Ethernet5", is_breakout=True) == "Eth1/2/2"


# ---------------------------------------------------------------------------
# _convert_using_port_config
# ---------------------------------------------------------------------------


def test_convert_using_port_config_breakout_no_base_port_falls_back():
    # is_breakout=True with empty port_config → no base port → legacy calc.
    # Ethernet5 → Eth1/2/2 via _convert_using_speed_calculation.
    assert _convert_using_port_config("Ethernet5", 5, True, {}) == "Eth1/2/2"


def test_convert_using_port_config_regular_missing_alias_falls_back():
    # Regular path with port present but alias unparseable → legacy calc.
    # Ethernet4 with speed=None falls to multiplier 1 → Eth1/5.
    port_config = {"Ethernet4": {"alias": "no-digits"}}

    assert _convert_using_port_config("Ethernet4", 4, False, port_config) == "Eth1/5"


# ---------------------------------------------------------------------------
# _find_base_port_for_breakout
# ---------------------------------------------------------------------------


def test_find_base_port_exact_match():
    port_config = {"Ethernet0": {}, "Ethernet4": {}}

    assert _find_base_port_for_breakout(4, port_config) == "Ethernet4"


def test_find_base_port_walks_back_to_smaller_port():
    port_config = {"Ethernet0": {}}

    assert _find_base_port_for_breakout(3, port_config) == "Ethernet0"


def test_find_base_port_returns_none_when_no_smaller_port_exists():
    assert _find_base_port_for_breakout(0, {}) is None


# ---------------------------------------------------------------------------
# _extract_port_number_from_alias
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("twentyFiveGigE1", 1),
        ("hundredGigE49", 49),
        # The Eth(Port) regex wins over the trailing-digit fallback.
        ("Eth54(Port54)", 54),
        # Trailing-digit fallback: any alias that ends with digits.
        ("someAlias5", 5),
    ],
)
def test_extract_port_number_known_aliases(alias, expected):
    assert _extract_port_number_from_alias(alias) == expected


@pytest.mark.parametrize("falsy", [None, ""])
def test_extract_port_number_falsy_input_returns_none(falsy):
    assert _extract_port_number_from_alias(falsy) is None


def test_extract_port_number_no_digits_returns_none():
    assert _extract_port_number_from_alias("foo") is None


def test_extract_port_number_paren_alias_without_leading_digit():
    # "Eth(Port5)" has no digit immediately after "Eth", so the primary
    # Eth\d+(Port\d+) regex does not match.  The explicit \(Port(\d+)\)
    # pattern handles it next and returns 5.
    assert _extract_port_number_from_alias("Eth(Port5)") == 5


def test_extract_port_number_alias_with_prefix_digits_uses_trailing():
    # "QSFP28-49": the \(Port(\d+)\) pattern does not match, and the
    # trailing-number fallback correctly returns 49 rather than 28.
    assert _extract_port_number_from_alias("QSFP28-49") == 49


# ---------------------------------------------------------------------------
# _convert_using_speed_calculation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ethernet_num,speed,is_breakout,expected",
    [
        # Breakout cases.
        (5, None, True, "Eth1/2/2"),
        (0, None, True, "Eth1/1/1"),
        # Regular cases.
        (4, 100000, False, "Eth1/2"),  # high-speed: multiplier 4
        (4, 25000, False, "Eth1/5"),  # low-speed: multiplier 1
        (4, None, False, "Eth1/5"),  # no speed: defaults to multiplier 1
    ],
)
def test_convert_using_speed_calculation(ethernet_num, speed, is_breakout, expected):
    assert (
        _convert_using_speed_calculation(ethernet_num, speed, is_breakout) == expected
    )


# ---------------------------------------------------------------------------
# get_port_config
# ---------------------------------------------------------------------------


def test_get_port_config_missing_file_returns_empty_and_caches(mocker):
    exists = mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=False
    )

    assert get_port_config("missing-hwsku") == {}

    # Even if the file appears later with valid content, the empty result
    # remains cached — the cache is keyed by HWSKU regardless of file state.
    exists.return_value = True
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data="Ethernet0 1 tenGigE1 1 10000\n"),
        create=True,
    )

    assert get_port_config("missing-hwsku") == {}


def test_get_port_config_parses_5_column_lines(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    content = "# header line\nEthernet0 1,2,3,4 twentyFiveGigE1 1 100000\n"
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data=content),
        create=True,
    )

    assert get_port_config("hwsku-A") == {
        "Ethernet0": {
            "lanes": "1,2,3,4",
            "alias": "twentyFiveGigE1",
            "index": "1",
            "speed": "100000",
        },
    }


def test_get_port_config_parses_optional_valid_speeds_column(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    content = "Ethernet0 2 tenGigE1 1 10000 10000,25000\n"
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data=content),
        create=True,
    )

    assert get_port_config("hwsku-A")["Ethernet0"]["valid_speeds"] == "10000,25000"


@pytest.mark.parametrize("autoneg_value", ["on", "off"])
def test_get_port_config_skips_non_numeric_sixth_column(mocker, autoneg_value):
    # The 6th column may carry an autoneg flag — non-digit values must NOT
    # be stored as valid_speeds.
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    content = f"Ethernet0 2 tenGigE1 1 10000 {autoneg_value}\n"
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data=content),
        create=True,
    )

    assert "valid_speeds" not in get_port_config("hwsku-A")["Ethernet0"]


def test_get_port_config_skips_comments_and_blank_lines(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    content = (
        "# name lanes alias index speed\n"
        "\n"
        "Ethernet0 1 tenGigE1 1 10000\n"
        "   \n"
        "# trailing comment\n"
        "Ethernet1 2 tenGigE2 2 10000\n"
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data=content),
        create=True,
    )

    result = get_port_config("hwsku-A")
    assert set(result.keys()) == {"Ethernet0", "Ethernet1"}


def test_get_port_config_isolates_callers_from_each_other(mocker):
    # Behavioral contract: callers can mutate their result without affecting
    # the cache or other callers' results. The implementation happens to use
    # deep-copy, but the test only asserts the visible isolation guarantee.
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    content = "Ethernet0 1 tenGigE1 1 10000\n"
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        mock_open(read_data=content),
        create=True,
    )

    first = get_port_config("hwsku-A")
    second = get_port_config("hwsku-A")
    assert (
        first
        == second
        == {
            "Ethernet0": {
                "lanes": "1",
                "alias": "tenGigE1",
                "index": "1",
                "speed": "10000",
            },
        }
    )

    first["Ethernet0"]["alias"] = "MUTATED"

    # Mutation of one caller's result must not leak into the other caller's
    # result nor into a future call.
    assert second["Ethernet0"]["alias"] == "tenGigE1"
    assert get_port_config("hwsku-A")["Ethernet0"]["alias"] == "tenGigE1"


def test_get_port_config_open_failure_returns_empty_and_caches(mocker):
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    open_patch = mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        side_effect=OSError("boom"),
        create=True,
    )

    assert get_port_config("hwsku-A") == {}

    # Even if a subsequent open() would now succeed, the cached empty result
    # is returned — the failure is sticky until the cache is cleared.
    open_patch.side_effect = mock_open(read_data="Ethernet0 1 tenGigE1 1 10000\n")

    assert get_port_config("hwsku-A") == {}


# ---------------------------------------------------------------------------
# clear_port_config_cache
# ---------------------------------------------------------------------------


def test_clear_port_config_cache_forces_re_read(mocker):
    # Behavioral check: while the cache is populated, changing the underlying
    # file has no effect. After clear_port_config_cache(), a follow-up call
    # observes the new content — proving the cache was actually invalidated.
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.os.path.exists", return_value=True
    )
    contents = iter(
        [
            "Ethernet0 1 tenGigE1 1 10000\n",
            "Ethernet99 1 newAlias 1 10000\n",
        ]
    )

    def fake_open(*args, **kwargs):
        return mock_open(read_data=next(contents))(*args, **kwargs)

    mocker.patch(
        "osism.tasks.conductor.sonic.interface.open",
        side_effect=fake_open,
        create=True,
    )

    first = get_port_config("hwsku-A")
    assert set(first.keys()) == {"Ethernet0"}

    # Cached: the file source has effectively changed but the cached value wins.
    cached = get_port_config("hwsku-A")
    assert set(cached.keys()) == {"Ethernet0"}

    clear_port_config_cache()
    fresh = get_port_config("hwsku-A")
    assert set(fresh.keys()) == {"Ethernet99"}


# ---------------------------------------------------------------------------
# get_connected_interfaces (deprecated shim)
# ---------------------------------------------------------------------------


def test_get_connected_interfaces_delegates_to_connections_module(mocker):
    spy = mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_connected_interfaces",
        return_value=({"Ethernet0"}, set()),
    )
    device = SimpleNamespace(id=1)
    portchannel_info = {"PortChannel1": {"members": []}}

    result = get_connected_interfaces(device, portchannel_info)

    spy.assert_called_once_with(device, portchannel_info)
    assert result == ({"Ethernet0"}, set())
