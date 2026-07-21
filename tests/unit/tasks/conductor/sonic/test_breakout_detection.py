# SPDX-License-Identifier: Apache-2.0

"""Tests for ``detect_breakout_ports``.

Lives in ``osism.tasks.conductor.sonic.interface`` and is one of the two large
topology-detection helpers driving the rest of the SONiC config pipeline. It is
exercised here against in-memory NetBox stubs; the IO-bound helpers
(``get_cached_device_interfaces``, ``get_port_config``) are patched on the
``interface`` module.
"""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import interface as interface_module
from osism.tasks.conductor.sonic.interface import (
    detect_breakout_ports,
    _emit_breakout,
    _parse_lanes,
    _parse_breakout_mode,
    get_declared_breakout_modes,
)

from ._detection_helpers import _make_iface, _make_sonic_device

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _netbox_breakout_interfaces(*, speed=None, type_value=None, port=49):
    """Build a 4-subport NetBox-format breakout group ``Eth1/<port>/1..4``."""
    return [
        _make_iface(f"Eth1/{port}/{i}", speed=speed, type_value=type_value)
        for i in (1, 2, 3, 4)
    ]


def _port_config_for_port(
    sonic_port="Ethernet0",
    alias="hundredGigE49",
    lanes="1,2,3,4",
    index="1",
    speed="100000",
):
    """Build a single-entry port_config dict for breakout-master lookups.

    Defaults model the NetBox-format breakout case (``alias=hundredGigE<n>``,
    100G, four lanes). Override ``alias`` to ``Eth1/<n>`` for SONiC-format
    masters, and ``lanes``/``speed`` for the 400G 8-lane case.
    """
    return {
        sonic_port: {
            "alias": alias,
            "lanes": lanes,
            "index": index,
            "speed": speed,
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_breakout_helpers(mocker):
    """Patch ``get_cached_device_interfaces`` and ``get_port_config``.

    Pass ``interfaces`` / ``port_config`` for the happy path, or
    ``cache_side_effect`` / ``port_config_side_effect`` to simulate failures.
    Returns a namespace exposing the two patched mocks.
    """

    def _patch(
        *,
        interfaces=None,
        port_config=None,
        cache_side_effect=None,
        port_config_side_effect=None,
    ):
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

        if port_config_side_effect is not None:
            cfg = mocker.patch(
                "osism.tasks.conductor.sonic.interface.get_port_config",
                side_effect=port_config_side_effect,
            )
        else:
            cfg = mocker.patch(
                "osism.tasks.conductor.sonic.interface.get_port_config",
                return_value=port_config if port_config is not None else {},
            )
        return SimpleNamespace(cache=cache, get_port_config=cfg)

    return _patch


# ---------------------------------------------------------------------------
# detect_breakout_ports — early exits / error paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "custom_fields, expect_warning_substring",
    [
        pytest.param({}, "sw1", id="no_sonic_parameters_key"),
        pytest.param({"sonic_parameters": None}, "sw1", id="sonic_parameters_none"),
        pytest.param({"sonic_parameters": {}}, "sw1", id="sonic_parameters_empty"),
        pytest.param(
            {"sonic_parameters": {"hwsku": ""}}, "sw1", id="hwsku_empty_string"
        ),
    ],
)
def test_detect_breakout_ports_missing_hwsku_returns_empty(
    custom_fields, expect_warning_substring, patch_breakout_helpers, mocker
):
    device = SimpleNamespace(id=1, name="sw1", custom_fields=custom_fields)
    patch_breakout_helpers(interfaces=[])
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    result = detect_breakout_ports(device)

    assert result == {"breakout_cfgs": {}, "breakout_ports": {}}
    warning.assert_called_once()
    assert expect_warning_substring in warning.call_args.args[0]


def test_detect_breakout_ports_no_custom_fields_attr(patch_breakout_helpers, mocker):
    # Devices without a ``custom_fields`` attribute at all also fall through
    # the HWSKU lookup.
    device = SimpleNamespace(id=1, name="sw1")
    patch_breakout_helpers(interfaces=[])
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }
    warning.assert_called_once()


def test_detect_breakout_ports_empty_port_config_returns_empty(
    patch_breakout_helpers, mocker
):
    device = _make_sonic_device()
    patch_breakout_helpers(interfaces=[], port_config={})
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }
    warning.assert_called_once()
    assert "TEST-HWSKU" in warning.call_args.args[0]


def test_detect_breakout_ports_get_port_config_raises_returns_empty(
    patch_breakout_helpers, mocker
):
    device = _make_sonic_device()
    patch_breakout_helpers(
        interfaces=[],
        port_config_side_effect=RuntimeError("disk failure"),
    )
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }
    warning.assert_called_once()
    assert "TEST-HWSKU" in warning.call_args.args[0]
    assert "disk failure" in warning.call_args.args[0]


def test_detect_breakout_ports_cache_raises_returns_empty(
    patch_breakout_helpers, mocker
):
    device = _make_sonic_device()
    patch_breakout_helpers(cache_side_effect=RuntimeError("netbox down"))
    warning = mocker.patch("osism.tasks.conductor.sonic.interface.logger.warning")

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }
    warning.assert_called_once()
    assert "sw1" in warning.call_args.args[0]
    assert "netbox down" in warning.call_args.args[0]


# ---------------------------------------------------------------------------
# detect_breakout_ports — NetBox-format breakout (Eth1/49/1..4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected_mode",
    [
        (10_000_000, "4x10G"),
        (25_000_000, "4x25G"),
        (50_000_000, "4x50G"),
        (100_000_000, "4x100G"),
        (200_000_000, "4x200G"),
    ],
)
def test_detect_breakout_ports_netbox_format_supported_speeds(
    speed, expected_mode, patch_breakout_helpers
):
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=speed)
    port_config = _port_config_for_port()

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"] == {
        "Ethernet0": {
            "breakout_owner": "MANUAL",
            "brkout_mode": expected_mode,
            "port": "1/49",
        }
    }
    assert result["breakout_ports"] == {
        "Ethernet0": {"master": "Ethernet0"},
        "Ethernet1": {"master": "Ethernet0"},
        "Ethernet2": {"master": "Ethernet0"},
        "Ethernet3": {"master": "Ethernet0"},
    }


def test_detect_breakout_ports_netbox_unsupported_speed_skipped(
    patch_breakout_helpers,
):
    # 40G with 4 subports is not in the supported speed table → continue.
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=40_000_000)
    port_config = _port_config_for_port()

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_netbox_speed_resolved_from_port_type(
    patch_breakout_helpers,
):
    # ``interface.speed`` is missing (None); speed comes from ``type.value``.
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=None, type_value="25gbase-x-sfp28")
    port_config = _port_config_for_port()

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"]["Ethernet0"]["brkout_mode"] == "4x25G"
    assert len(result["breakout_ports"]) == 4


def test_detect_breakout_ports_netbox_8_lane_master_uses_offset_2(
    patch_breakout_helpers,
):
    # 400G master with 8 lanes — subport offsets multiply by 2, so the
    # breakout sub-ports map to Ethernet0,2,4,6 instead of 0,1,2,3.
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=100_000_000)
    port_config = _port_config_for_port(lanes="1,2,3,4,5,6,7,8")

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"] == {
        "Ethernet0": {
            "breakout_owner": "MANUAL",
            "brkout_mode": "4x100G",
            "port": "1/49",
        }
    }
    assert result["breakout_ports"] == {
        "Ethernet0": {"master": "Ethernet0"},
        "Ethernet2": {"master": "Ethernet0"},
        "Ethernet4": {"master": "Ethernet0"},
        "Ethernet6": {"master": "Ethernet0"},
    }


def test_detect_breakout_ports_netbox_single_subport_not_breakout(
    patch_breakout_helpers,
):
    device = _make_sonic_device()
    interfaces = [_make_iface("Eth1/49/1", speed=100_000_000)]
    port_config = _port_config_for_port()

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_netbox_processed_groups_dedup(
    patch_breakout_helpers, mocker
):
    # All four sub-ports of Eth1/49 share the group key ``1/49``. With
    # ``processed_groups`` in place, only the first iteration runs the per-
    # group work; the next three short-circuit on the dedup check. We pin
    # this with the call count of ``_handle_breakout_interface`` (called
    # twice on the first iter — once for the sonic name, once for the master
    # — and not at all on the others).
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=100_000_000)
    port_config = _port_config_for_port()

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)
    spy = mocker.spy(interface_module, "_handle_breakout_interface")

    result = detect_breakout_ports(device)

    assert spy.call_count == 2
    assert list(result["breakout_cfgs"].keys()) == ["Ethernet0"]
    assert len(result["breakout_ports"]) == 4


def test_detect_breakout_ports_netbox_two_independent_groups(
    patch_breakout_helpers,
):
    # Two distinct breakout groups (Eth1/49 and Eth1/50) yield two masters.
    device = _make_sonic_device()
    interfaces = _netbox_breakout_interfaces(speed=100_000_000) + [
        _make_iface(f"Eth1/50/{i}", speed=100_000_000) for i in (1, 2, 3, 4)
    ]
    port_config = {
        **_port_config_for_port(),
        **_port_config_for_port(
            sonic_port="Ethernet4",
            alias="hundredGigE50",
            lanes="5,6,7,8",
            index="2",
        ),
    }

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert set(result["breakout_cfgs"].keys()) == {"Ethernet0", "Ethernet4"}
    assert result["breakout_cfgs"]["Ethernet0"]["port"] == "1/49"
    assert result["breakout_cfgs"]["Ethernet4"]["port"] == "1/50"
    assert len(result["breakout_ports"]) == 8


# ---------------------------------------------------------------------------
# detect_breakout_ports — SONiC 400G breakout (8-lane master, +2 spacing)
# ---------------------------------------------------------------------------


def test_detect_breakout_ports_sonic_400g_first_group(patch_breakout_helpers):
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=100_000_000) for n in (0, 2, 4, 6)]
    port_config = _port_config_for_port(
        alias="Eth1/1", lanes="1,2,3,4,5,6,7,8", speed="400000"
    )

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"] == {
        "Ethernet0": {
            "breakout_owner": "MANUAL",
            "brkout_mode": "4x100G",
            "port": "1/1",
        }
    }
    assert result["breakout_ports"] == {
        f"Ethernet{n}": {"master": "Ethernet0"} for n in (0, 2, 4, 6)
    }


def test_detect_breakout_ports_sonic_400g_second_group(patch_breakout_helpers):
    # Master ``Ethernet8`` → physical port ``1/2`` (the 2nd 400G cage).
    device = _make_sonic_device()
    interfaces = [
        _make_iface(f"Ethernet{n}", speed=100_000_000) for n in (8, 10, 12, 14)
    ]
    port_config = _port_config_for_port(
        sonic_port="Ethernet8",
        alias="Eth1/2",
        lanes="9,10,11,12,13,14,15,16",
        index="2",
        speed="400000",
    )

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"]["Ethernet8"]["port"] == "1/2"
    assert result["breakout_cfgs"]["Ethernet8"]["brkout_mode"] == "4x100G"


def test_detect_breakout_ports_sonic_400g_speed_mismatch_skipped(
    patch_breakout_helpers,
):
    # 8-lane master, but the four interfaces are at 50G — not 100G — so the
    # 400G branch's per-port speed check fails and the group is rejected.
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=50_000_000) for n in (0, 2, 4, 6)]
    port_config = _port_config_for_port(
        alias="Eth1/1", lanes="1,2,3,4,5,6,7,8", speed="400000"
    )

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_sonic_400g_4_lane_master_falls_through(
    patch_breakout_helpers,
):
    # Master ``Ethernet0`` only has 4 lanes — not a 400G port. Four
    # consecutive interfaces at 25G then trigger the SONiC standard branch.
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(4)]
    port_config = _port_config_for_port(alias="Eth1/1")

    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"] == {
        "Ethernet0": {
            "breakout_owner": "MANUAL",
            "brkout_mode": "4x25G",
            "port": "1/1",
        }
    }
    assert result["breakout_ports"] == {
        f"Ethernet{n}": {"master": "Ethernet0"} for n in range(4)
    }


# ---------------------------------------------------------------------------
# detect_breakout_ports — SONiC standard breakout (Ethernet0..3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "speed, expected_mode",
    [
        # Explicit speeds are kbps as NetBox stores them; detection
        # normalizes them to Mbps before the breakout mode lookup.
        (10_000_000, "4x10G"),
        (25_000_000, "4x25G"),
        (50_000_000, "4x50G"),
    ],
)
def test_detect_breakout_ports_sonic_standard_supported_speeds(
    speed, expected_mode, patch_breakout_helpers
):
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=speed) for n in range(4)]
    # The 400G branch peeks at ``Ethernet0`` in the port_config; provide a
    # 4-lane entry so it skips the 400G code path cleanly.
    port_config = _port_config_for_port(alias="Eth1/1", speed=str(speed // 1000))
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"] == {
        "Ethernet0": {
            "breakout_owner": "MANUAL",
            "brkout_mode": expected_mode,
            "port": "1/1",
        }
    }
    assert result["breakout_ports"] == {
        f"Ethernet{n}": {"master": "Ethernet0"} for n in range(4)
    }


def test_detect_breakout_ports_sonic_standard_at_100g_skipped(
    patch_breakout_helpers,
):
    # Regular 100G ports (4 consecutive Ethernet0..3) are NOT a breakout —
    # the speed filter (``<= 50000``) excludes them.
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=100_000_000) for n in range(4)]
    port_config = _port_config_for_port(alias="Eth1/1")
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_sonic_standard_only_three_interfaces(
    patch_breakout_helpers,
):
    # A 3-port group is incomplete — no breakout configured.
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(3)]
    port_config = _port_config_for_port(alias="Eth1/1")
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_sonic_standard_native_ports_not_breakout(
    patch_breakout_helpers,
):
    # Four consecutive single-lane 25G ports that are each their own
    # port_config entry are NATIVE ports, not a breakout cage, and must not be
    # misdetected as a 4x25G breakout. A real breakout is a single multi-lane
    # master with the intermediate lanes absent (they materialize only when the
    # cage is broken out). This guards native low-speed switches such as
    # DellEMC-S5212f / AS7326-56X (25G) and AS5835-54T (10G).
    device = _make_sonic_device()
    interfaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(4)]
    port_config = {
        f"Ethernet{n}": {
            "lanes": str(29 + n),  # one lane each -> native ports
            "alias": f"twentyfiveGigE1/{n + 1}",
            "index": str(n + 1),
            "speed": "25000",
        }
        for n in range(4)
    }
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    assert detect_breakout_ports(device) == {
        "breakout_cfgs": {},
        "breakout_ports": {},
    }


def test_detect_breakout_ports_sonic_standard_speed_resolved_from_port_type(
    patch_breakout_helpers,
):
    device = _make_sonic_device()
    interfaces = [
        _make_iface(f"Ethernet{n}", speed=None, type_value="25gbase-x-sfp28")
        for n in range(4)
    ]
    port_config = _port_config_for_port(alias="Eth1/1")
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)

    result = detect_breakout_ports(device)

    assert result["breakout_cfgs"]["Ethernet0"]["brkout_mode"] == "4x25G"


# ---------------------------------------------------------------------------
# _parse_lanes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "s,out",
    [
        ("1,2,3,4", ["1", "2", "3", "4"]),
        (
            "73,74,75,76,77,78,79,80",
            ["73", "74", "75", "76", "77", "78", "79", "80"],
        ),
        ("1-4", ["1", "2", "3", "4"]),
        ("29", ["29"]),
        ("", []),
        ("  ", []),
        ("a,b", []),
        ("4-1", []),
        ("1-", []),
        ("x-3", []),
        (None, []),
        (29, []),
        (["1", "2"], []),
    ],
)
def test_parse_lanes(s, out):
    assert _parse_lanes(s) == out


# ---------------------------------------------------------------------------
# _parse_breakout_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "m,out",
    [
        ("4x10G", (4, 10000)),
        ("2x50G", (2, 50000)),
        ("8x50G", (8, 50000)),
        ("4x100G", (4, 100000)),
        ("2x200G", (2, 200000)),
        ("1x400G", None),
        ("0x10G", None),
        ("4x0G", None),
        ("4x10g", None),
        (" 4x10G ", (4, 10000)),
        ("bogus", None),
        ("4x", None),
        ("x10G", None),
        ("", None),
        (None, None),
        (10, None),
        ({}, None),
    ],
)
def test_parse_breakout_mode(m, out):
    assert _parse_breakout_mode(m) == out


# ---------------------------------------------------------------------------
# get_declared_breakout_modes
# ---------------------------------------------------------------------------


def test_declared_modes_map():
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Ethernet0": "4x10G", "Eth1/9": "2x50G"},
            }
        }
    )
    assert get_declared_breakout_modes(d) == {"Ethernet0": "4x10G", "Eth1/9": "2x50G"}


@pytest.mark.parametrize(
    "cf",
    [
        {"sonic_parameters": {"hwsku": "x"}},
        {"sonic_parameters": {"breakout": None}},
        {"sonic_parameters": {"breakout": "Ethernet0: 4x10G"}},
        {"sonic_parameters": {"breakout": []}},
        {"sonic_parameters": None},
        {},
        None,
    ],
)
def test_declared_modes_malformed_or_absent(cf):
    assert get_declared_breakout_modes(_make_sonic_device(custom_fields=cf)) == {}


# ---------------------------------------------------------------------------
# detect_breakout_ports — declared-mode pass (Task 5)
# ---------------------------------------------------------------------------


_GATE_PC = {
    "Ethernet0": {
        "lanes": "1,2,3,4",
        "alias": "Eth1/1",
        "index": "1",
        "speed": "25000",
    }
}  # Eth1/1/2/3 absent -> gate accepts


def test_declared_4x10g(patch_breakout_helpers):
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "4x10G"}}
        }
    )
    patch_breakout_helpers(
        interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4")
    )
    r = detect_breakout_ports(d)
    assert r["breakout_cfgs"]["Ethernet0"]["brkout_mode"] == "4x10G"
    assert {k: v["lanes"] for k, v in r["breakout_ports"].items()} == {
        "Ethernet0": "1",
        "Ethernet1": "2",
        "Ethernet2": "3",
        "Ethernet3": "4",
    }
    assert all(v["declared"] for v in r["breakout_ports"].values())


def test_declared_2x50g(patch_breakout_helpers):
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "2x50G"}}
        }
    )
    patch_breakout_helpers(
        interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4")
    )
    assert {
        k: v["lanes"] for k, v in detect_breakout_ports(d)["breakout_ports"].items()
    } == {"Ethernet0": "1,2", "Ethernet2": "3,4"}


def test_declared_8x50g(patch_breakout_helpers):
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "8x50G"}}
        }
    )
    patch_breakout_helpers(
        interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4,5,6,7,8")
    )
    r = detect_breakout_ports(d)
    assert set(r["breakout_ports"]) == {f"Ethernet{n}" for n in range(8)}
    assert r["breakout_ports"]["Ethernet0"]["lanes"] == "1"


def test_declared_4x100g_8lane(patch_breakout_helpers):
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "4x100G"}}
        }
    )
    patch_breakout_helpers(
        interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4,5,6,7,8")
    )
    assert {
        k: v["lanes"] for k, v in detect_breakout_ports(d)["breakout_ports"].items()
    } == {
        "Ethernet0": "1,2",
        "Ethernet2": "3,4",
        "Ethernet4": "5,6",
        "Ethernet6": "7,8",
    }


def test_declared_key_eth1(patch_breakout_helpers):
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Eth1/1": "4x10G"},
            }
        }
    )
    patch_breakout_helpers(
        interfaces=[],
        port_config=_port_config_for_port(lanes="1,2,3,4", alias="Eth1/1"),
    )
    assert (
        detect_breakout_ports(d)["breakout_cfgs"]["Ethernet0"]["brkout_mode"] == "4x10G"
    )


def test_declared_mixed_layout_port_index(patch_breakout_helpers):
    pc = {
        **{
            f"Ethernet{n}": {
                "lanes": str(29 + n),
                "alias": f"Eth{n + 1}(Port{n + 1})",
                "index": str(n + 1),
                "speed": "25000",
            }
            for n in range(12)
        },
        "Ethernet12": {
            "lanes": "41,42,43,44",
            "alias": "Eth13(Port13)",
            "index": "13",
            "speed": "100000",
        },
    }
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Ethernet12": "4x25G"},
            }
        }
    )
    patch_breakout_helpers(interfaces=[], port_config=pc)
    assert detect_breakout_ports(d)["breakout_cfgs"]["Ethernet12"]["port"] == "1/13"


def test_inference_control(patch_breakout_helpers):
    ifaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(4)]
    patch_breakout_helpers(interfaces=ifaces, port_config=_GATE_PC)
    assert (
        detect_breakout_ports(_make_sonic_device())["breakout_cfgs"]["Ethernet0"][
            "brkout_mode"
        ]
        == "4x25G"
    )


def test_invalid_mode_suppresses_inference(patch_breakout_helpers):
    ifaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(4)]
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Ethernet0": "3x25G"},
            }
        }
    )  # 4 % 3 != 0
    patch_breakout_helpers(interfaces=ifaces, port_config=_GATE_PC)
    assert detect_breakout_ports(d) == {"breakout_cfgs": {}, "breakout_ports": {}}


def test_collision_fail_closed(patch_breakout_helpers):
    ifaces = [_make_iface(f"Ethernet{n}", speed=25_000_000) for n in range(4)]
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Ethernet0": "4x25G", "Eth1/1": "4x25G"},
            }
        }
    )
    patch_breakout_helpers(interfaces=ifaces, port_config=_GATE_PC)
    assert detect_breakout_ports(d) == {"breakout_cfgs": {}, "breakout_ports": {}}


def test_unresolvable_and_malformed(patch_breakout_helpers):
    for bmap in (
        {"Ethernetfoo": "4x10G"},
        {"Eth1/1/1": "4x10G"},
        {"Eth2/1": "4x10G"},
        {"Ethernet99": "4x10G"},
        {123: "4x10G"},
    ):
        d = _make_sonic_device(
            custom_fields={"sonic_parameters": {"hwsku": "x", "breakout": bmap}}
        )
        patch_breakout_helpers(
            interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4")
        )
        assert detect_breakout_ports(d) == {
            "breakout_cfgs": {},
            "breakout_ports": {},
        }


def test_declared_single_lane_master_no_emit_and_suppressed(patch_breakout_helpers):
    """A declared 4x25G on a single-lane master fails L%count validation
    (L=1). No breakout is emitted, and the master is suppressed so the
    NetBox-format inference that would otherwise fire (Eth1/49/1..4 at 25G)
    also emits nothing."""
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "4x25G"}}
        }
    )
    interfaces = _netbox_breakout_interfaces(speed=25_000_000)
    port_config = _port_config_for_port(lanes="29", speed="25000")
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)
    assert detect_breakout_ports(d) == {"breakout_cfgs": {}, "breakout_ports": {}}


def test_multiple_unresolvable_keys_logged_per_key(patch_breakout_helpers, loguru_logs):
    """Two unresolvable keys both normalize to master=None and land in the
    same bucket. That is not a collision: each key should get its own
    "could not be resolved" message, not a misleading "collision for None"."""
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {
                "hwsku": "x",
                "breakout": {"Ethernetfoo": "4x10G", "Eth2/1": "4x10G"},
            }
        }
    )
    patch_breakout_helpers(
        interfaces=[], port_config=_port_config_for_port(lanes="1,2,3,4")
    )
    assert detect_breakout_ports(d) == {"breakout_cfgs": {}, "breakout_ports": {}}

    messages = [r["message"] for r in loguru_logs]
    assert not any("collision for None" in m for m in messages)
    for key in ("Ethernetfoo", "Eth2/1"):
        assert any("could not be resolved" in m and key in m for m in messages), key


def test_declared_malformed_master_lanes_no_emit(patch_breakout_helpers):
    """Malformed lanes on the declared master parse to [] (L==0): no emit,
    master suppressed (the NetBox-format inference is silenced too)."""
    d = _make_sonic_device(
        custom_fields={
            "sonic_parameters": {"hwsku": "x", "breakout": {"Ethernet0": "4x25G"}}
        }
    )
    interfaces = _netbox_breakout_interfaces(speed=25_000_000)
    port_config = _port_config_for_port(lanes="a,b", speed="25000")
    patch_breakout_helpers(interfaces=interfaces, port_config=port_config)
    assert detect_breakout_ports(d) == {"breakout_cfgs": {}, "breakout_ports": {}}


def test_emit_breakout_missing_index_leaves_no_partial_state():
    """A master lacking ``index`` must fail before any children are staged,
    so no orphan breakout_ports entries survive the error."""
    port_config = {"Ethernet0": {"lanes": "1,2,3,4"}}  # no "index"
    breakout_cfgs: dict = {}
    breakout_ports: dict = {}
    suppressed: set = set()
    with pytest.raises(KeyError):
        _emit_breakout(
            "Ethernet0",
            2,
            50000,
            port_config,
            breakout_cfgs,
            breakout_ports,
            suppressed,
        )
    assert breakout_ports == {}
    assert breakout_cfgs == {}
