# SPDX-License-Identifier: Apache-2.0

"""Tests for ``detect_port_channels``.

Lives in ``osism.tasks.conductor.sonic.interface`` and is one of the two large
topology-detection helpers driving the rest of the SONiC config pipeline. It is
exercised here against in-memory NetBox stubs; the IO-bound helpers
(``get_cached_device_interfaces``, ``convert_netbox_interface_to_sonic``) are
patched on the ``interface`` module.
"""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.interface import detect_port_channels

from ._detection_helpers import _make_iface, _make_lag

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_pc_helpers(mocker):
    """Patch helpers consumed by ``detect_port_channels``.

    ``sonic_name_lookup`` maps NetBox ``interface.name`` → SONiC name; when an
    interface name is absent from the lookup, the conversion is identity, which
    matches the common case where members are already named ``Ethernet*``.
    """

    def _patch(*, interfaces=None, sonic_name_lookup=None, cache_side_effect=None):
        sonic_name_lookup = sonic_name_lookup or {}
        if cache_side_effect is not None:
            cache = mocker.patch(
                "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
                side_effect=cache_side_effect,
            )
        else:
            cache = mocker.patch(
                "osism.tasks.conductor.sonic.interface.get_cached_device_interfaces",
                return_value=interfaces or [],
            )
        convert = mocker.patch(
            "osism.tasks.conductor.sonic.interface.convert_netbox_interface_to_sonic",
            side_effect=lambda iface, _device: sonic_name_lookup.get(
                iface.name, iface.name
            ),
        )
        return SimpleNamespace(cache=cache, convert=convert)

    return _patch


# ---------------------------------------------------------------------------
# detect_port_channels — early exits and basic behaviour
# ---------------------------------------------------------------------------


def test_detect_port_channels_cache_raises_returns_empty(patch_pc_helpers, mocker):
    device = SimpleNamespace(id=1, name="sw1")
    patch_pc_helpers(cache_side_effect=RuntimeError("netbox down"))
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    assert detect_port_channels(device) == {
        "portchannels": {},
        "member_mapping": {},
    }
    warning.assert_called_once()
    assert "sw1" in warning.call_args.args[0]
    assert "netbox down" in warning.call_args.args[0]


def test_detect_port_channels_no_lag_interfaces_returns_empty(patch_pc_helpers):
    device = SimpleNamespace(id=1, name="sw1")
    interfaces = [_make_iface("Ethernet0", speed=10000, type_value="10gbase-x-sfpp")]
    patch_pc_helpers(interfaces=interfaces)

    assert detect_port_channels(device) == {
        "portchannels": {},
        "member_mapping": {},
    }


def test_detect_port_channels_lag_with_no_members_returns_empty(patch_pc_helpers):
    # The LAG parent itself is in the interface list but no member references
    # it via ``.lag``, so no PortChannel is produced.
    device = SimpleNamespace(id=1, name="sw1")
    interfaces = [_make_lag("PortChannel1")]
    patch_pc_helpers(interfaces=interfaces)

    assert detect_port_channels(device) == {
        "portchannels": {},
        "member_mapping": {},
    }


def test_detect_port_channels_member_with_lag_none_skipped(patch_pc_helpers):
    device = SimpleNamespace(id=1, name="sw1")
    interfaces = [_make_iface("Ethernet0", speed=10000, lag=None)]
    patch_pc_helpers(interfaces=interfaces)

    assert detect_port_channels(device) == {
        "portchannels": {},
        "member_mapping": {},
    }


# ---------------------------------------------------------------------------
# detect_port_channels — LAG name regex variants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lag_name, expected_pc",
    [
        # Each named pattern matches exactly once.
        ("PortChannel1", "PortChannel1"),
        ("Port-Channel2", "PortChannel2"),
        ("LAG3", "PortChannel3"),
        ("ae4", "PortChannel4"),
        ("bond5", "PortChannel5"),
        # Numeric fallback when no named pattern matches.
        ("po-uplink-7", "PortChannel7"),
        # Each named pattern is also case-insensitive.
        ("portchannel99", "PortChannel99"),
        ("PORT-CHANNEL10", "PortChannel10"),
        ("lag42", "PortChannel42"),
        ("AE8", "PortChannel8"),
        ("BOND6", "PortChannel6"),
    ],
)
def test_detect_port_channels_lag_name_variants(
    lag_name, expected_pc, patch_pc_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    lag = _make_lag(lag_name)
    member = _make_iface("Ethernet0", speed=10000, lag=lag)
    patch_pc_helpers(interfaces=[lag, member])

    result = detect_port_channels(device)

    assert expected_pc in result["portchannels"]
    assert result["member_mapping"]["Ethernet0"] == expected_pc
    assert result["portchannels"][expected_pc]["members"] == ["Ethernet0"]


def test_detect_port_channels_unnamed_lag_in_lag_interfaces_uses_index(
    patch_pc_helpers,
):
    # ``trunk`` matches no named pattern and contains no digits — fallback
    # uses ``lag_interfaces.index(parent) + 1`` because the parent is itself
    # typed ``lag`` and present in the interface list (index 0 → "1").
    device = SimpleNamespace(id=1, name="sw1")
    trunk = _make_lag("trunk")
    member = _make_iface("Ethernet0", speed=10000, lag=trunk)
    patch_pc_helpers(interfaces=[trunk, member])

    result = detect_port_channels(device)

    assert "PortChannel1" in result["portchannels"]
    assert result["member_mapping"] == {"Ethernet0": "PortChannel1"}


def test_detect_port_channels_unnamed_lag_not_in_list_uses_string_one(
    patch_pc_helpers,
):
    # The LAG parent is referenced via ``member.lag`` but is NOT in the
    # interface list (so it does not appear in ``lag_interfaces``). The
    # fallback returns the literal string ``"1"``.
    device = SimpleNamespace(id=1, name="sw1")
    parent = SimpleNamespace(name="trunk", id=99, type=None, lag=None)
    member = _make_iface("Ethernet0", speed=10000, lag=parent)
    patch_pc_helpers(interfaces=[member])

    result = detect_port_channels(device)

    assert "PortChannel1" in result["portchannels"]
    assert result["member_mapping"] == {"Ethernet0": "PortChannel1"}


# ---------------------------------------------------------------------------
# detect_port_channels — members, ordering, dedup, defaults
# ---------------------------------------------------------------------------


def test_detect_port_channels_members_sorted_by_numeric_suffix(patch_pc_helpers):
    device = SimpleNamespace(id=1, name="sw1")
    lag = _make_lag("PortChannel1")
    eth124 = _make_iface("Ethernet124", speed=100000, lag=lag)
    eth120 = _make_iface("Ethernet120", speed=100000, lag=lag)
    # Append in unsorted order; production must sort the resulting members.
    patch_pc_helpers(interfaces=[lag, eth124, eth120])

    result = detect_port_channels(device)

    assert result["portchannels"]["PortChannel1"]["members"] == [
        "Ethernet120",
        "Ethernet124",
    ]


def test_detect_port_channels_dedups_same_sonic_name(patch_pc_helpers):
    # Two distinct NetBox interfaces converge on the same SONiC name — only
    # one entry should be kept on the PortChannel members list.
    device = SimpleNamespace(id=1, name="sw1")
    lag = _make_lag("PortChannel1")
    a = _make_iface("Eth1/1", speed=100000, lag=lag)
    b = _make_iface("Eth1/1-dup", speed=100000, lag=lag)
    patch_pc_helpers(
        interfaces=[lag, a, b],
        sonic_name_lookup={"Eth1/1": "Ethernet0", "Eth1/1-dup": "Ethernet0"},
    )

    result = detect_port_channels(device)

    assert result["portchannels"]["PortChannel1"]["members"] == ["Ethernet0"]
    assert result["member_mapping"] == {"Ethernet0": "PortChannel1"}


def test_detect_port_channels_default_config_and_member_mapping(patch_pc_helpers):
    device = SimpleNamespace(id=1, name="sw1")
    lag = _make_lag("PortChannel1")
    member = _make_iface("Ethernet0", speed=10000, lag=lag)
    patch_pc_helpers(interfaces=[lag, member])

    result = detect_port_channels(device)

    pc = result["portchannels"]["PortChannel1"]
    assert pc["admin_status"] == "up"
    assert pc["fast_rate"] == "true"
    assert pc["min_links"] == "1"
    assert pc["mtu"] == "9100"
    assert pc["members"] == ["Ethernet0"]
    assert result["member_mapping"] == {"Ethernet0": "PortChannel1"}


def test_detect_port_channels_multiple_lags(patch_pc_helpers):
    # Two LAGs with different name patterns — each gets its own PortChannel.
    device = SimpleNamespace(id=1, name="sw1")
    lag1 = _make_lag("PortChannel1", lag_id=99)
    lag2 = _make_lag("ae5", lag_id=100)
    eth0 = _make_iface("Ethernet0", speed=100000, lag=lag1)
    eth4 = _make_iface("Ethernet4", speed=100000, lag=lag2)
    patch_pc_helpers(interfaces=[lag1, lag2, eth0, eth4])

    result = detect_port_channels(device)

    assert set(result["portchannels"].keys()) == {"PortChannel1", "PortChannel5"}
    assert result["portchannels"]["PortChannel1"]["members"] == ["Ethernet0"]
    assert result["portchannels"]["PortChannel5"]["members"] == ["Ethernet4"]
    assert result["member_mapping"] == {
        "Ethernet0": "PortChannel1",
        "Ethernet4": "PortChannel5",
    }
