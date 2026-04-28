# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SONiC ``config_generator`` orchestrator
(``generate_sonic_config``) and the public cache-clear helpers.

Service-level behavior (metalbox cache, NTP, DNS, log-server, SNMP) lives in
sibling ``test_config_generator_<concern>.py`` files; this file deliberately
leaves their helpers patched so the orchestrator's own glue is exercised in
isolation.
"""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import (
    TOP_LEVEL_SCAFFOLD_KEYS,
    clear_all_caches,
    clear_metalbox_devices_cache,
    clear_metalbox_ip_cache,
    generate_sonic_config,
    natural_sort_key,
)

from ._config_generator_helpers import make_base_config, patch_base_config

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_orchestrator_helpers(mocker):
    """Patch every helper the orchestrator delegates to.

    Returns a ``SimpleNamespace`` exposing each mock so individual tests can
    customize side effects (e.g. swap a ``return_value`` for a non-empty
    ``oob_ip_result``). Each helper is patched at its **import site** in
    ``config_generator`` — patching at the source module would not catch the
    rebound reference the orchestrator already imported.
    """

    def patch(name, **kw):
        return mocker.patch(
            f"osism.tasks.conductor.sonic.config_generator.{name}", **kw
        )

    return SimpleNamespace(
        get_port_config=patch("get_port_config", return_value={}),
        detect_port_channels=patch(
            "detect_port_channels",
            return_value={"portchannels": {}, "member_mapping": {}},
        ),
        detect_breakout_ports=patch(
            "detect_breakout_ports",
            return_value={"breakout_cfgs": {}, "breakout_ports": {}},
        ),
        convert_netbox_interface_to_sonic=patch(
            "convert_netbox_interface_to_sonic",
            side_effect=lambda iface, _device: iface.name,
        ),
        get_speed_from_port_type=patch("get_speed_from_port_type", return_value=None),
        get_connected_interfaces=patch(
            "get_connected_interfaces", return_value=(set(), set())
        ),
        get_device_oob_ip=patch("get_device_oob_ip", return_value=None),
        get_device_vlans=patch("get_device_vlans", return_value={}),
        get_device_loopbacks=patch("get_device_loopbacks", return_value={}),
        get_device_interface_ips=patch("get_device_interface_ips", return_value={}),
        get_device_platform=patch(
            "get_device_platform", return_value="x86_64-generic-r0"
        ),
        get_device_hostname=patch("get_device_hostname", return_value="leaf-1"),
        get_device_mac_address=patch(
            "get_device_mac_address", return_value="aa:bb:cc:dd:ee:ff"
        ),
        _get_vrf_info=patch(
            "_get_vrf_info",
            return_value={"vrfs": {}, "interface_vrf_mapping": {}},
        ),
        _get_transfer_role_ipv4_addresses=patch(
            "_get_transfer_role_ipv4_addresses", return_value={}
        ),
        _add_port_configurations=patch("_add_port_configurations"),
        _add_interface_configurations=patch("_add_interface_configurations"),
        _add_bgp_configurations=patch("_add_bgp_configurations"),
        _add_ntp_configuration=patch("_add_ntp_configuration"),
        _add_dns_configuration=patch("_add_dns_configuration"),
        _add_vlan_configuration=patch("_add_vlan_configuration"),
        _add_loopback_configuration=patch("_add_loopback_configuration"),
        _add_log_server_configuration=patch("_add_log_server_configuration"),
        _add_snmp_configuration=patch("_add_snmp_configuration"),
        _add_vrf_configuration=patch("_add_vrf_configuration"),
        _add_portchannel_configuration=patch("_add_portchannel_configuration"),
        get_cached_device_interfaces=patch(
            "get_cached_device_interfaces", return_value=[]
        ),
        _get_metalbox_ip_for_device=patch(
            "_get_metalbox_ip_for_device", return_value="10.0.0.1"
        ),
        calculate_local_asn_from_ipv4=patch(
            "calculate_local_asn_from_ipv4", return_value=4200000001
        ),
    )


@pytest.fixture
def make_orchestrator_device():
    """Build a minimal NetBox-shaped device the orchestrator can consume."""

    def _factory(device_id=1, name="leaf-1", primary_ip4=None, primary_ip6=None):
        return SimpleNamespace(
            id=device_id,
            name=name,
            primary_ip4=primary_ip4,
            primary_ip6=primary_ip6,
        )

    return _factory


def _ip(address):
    """Build a stub for ``device.primary_ip4`` / ``primary_ip6``."""
    return SimpleNamespace(address=address)


# ---------------------------------------------------------------------------
# natural_sort_key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "port_name,expected",
    [
        ("Ethernet0", 0),
        ("Ethernet120", 120),
        ("PortChannel", 0),  # No digits → falls back to 0.
        ("Ethernet1/3/2", 1),  # Picks the first digit run.
        ("", 0),  # Empty string → no match → 0.
    ],
)
def test_natural_sort_key(port_name, expected):
    assert natural_sort_key(port_name) == expected


def test_natural_sort_key_returns_int():
    # Sorting routines depend on a comparable int — pin the type explicitly.
    assert isinstance(natural_sort_key("Ethernet42"), int)


# ---------------------------------------------------------------------------
# generate_sonic_config — required keys / DEVICE_METADATA population
# ---------------------------------------------------------------------------


def test_generate_sonic_config_returns_required_top_level_keys(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "Test-HWSKU")

    # Every scaffold key the production code commits to must be present.
    for key in TOP_LEVEL_SCAFFOLD_KEYS:
        assert key in config


def test_generate_sonic_config_populates_device_metadata_localhost(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    patch_orchestrator_helpers.get_device_hostname.return_value = "spine-7"
    patch_orchestrator_helpers.get_device_platform.return_value = "x86_64-foo-r0"
    patch_orchestrator_helpers.get_device_mac_address.return_value = "11:22:33:44:55:66"
    device = make_orchestrator_device(name="spine-7")

    config = generate_sonic_config(device, "Custom-HWSKU")

    assert config["DEVICE_METADATA"]["localhost"] == {
        "hostname": "spine-7",
        "hwsku": "Custom-HWSKU",
        "platform": "x86_64-foo-r0",
        "mac": "11:22:33:44:55:66",
    }


def test_generate_sonic_config_preserves_existing_localhost_keys(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """Pre-existing ``DEVICE_METADATA.localhost`` keys must survive the update.

    Production base configs ship platform-independent fields under
    ``localhost`` (e.g. ``type=LeafRouter``); ``.update()`` should add /
    overwrite the orchestrator's keys without dropping the rest.
    """
    base = make_base_config()
    base["DEVICE_METADATA"]["localhost"] = {"type": "LeafRouter", "hwsku": "OLD"}
    patch_base_config(mocker, base_config=base)
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "NEW-HWSKU")

    assert config["DEVICE_METADATA"]["localhost"]["type"] == "LeafRouter"
    assert config["DEVICE_METADATA"]["localhost"]["hwsku"] == "NEW-HWSKU"


# ---------------------------------------------------------------------------
# generate_sonic_config — base-config loading / deepcopy / fallback
# ---------------------------------------------------------------------------


def test_generate_sonic_config_uses_deepcopy_per_device(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """Two devices must not share the same base-config dict object.

    Without ``deepcopy`` the second device's mutations would leak back into
    the first device's config (and into the cached base config) — a real bug
    we got bitten by before this test existed.
    """
    base = make_base_config()
    base["DEVICE_METADATA"]["shared"] = {"flag": "original"}
    patch_base_config(mocker, base_config=base)

    device_a = make_orchestrator_device(device_id=1, name="dev-a")
    device_b = make_orchestrator_device(device_id=2, name="dev-b")

    config_a = generate_sonic_config(device_a, "HWSKU-A")
    # Mutate device_a's config; device_b must not see it.
    config_a["DEVICE_METADATA"]["shared"]["flag"] = "mutated"

    config_b = generate_sonic_config(device_b, "HWSKU-B")

    assert config_b["DEVICE_METADATA"]["shared"] == {"flag": "original"}
    assert config_a["DEVICE_METADATA"] is not config_b["DEVICE_METADATA"]


def test_generate_sonic_config_starts_from_scaffold_when_base_absent(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker, exists=False)
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "Test-HWSKU")

    # Scaffold keys exist even though ``open`` was never called.
    for key in TOP_LEVEL_SCAFFOLD_KEYS:
        assert key in config
    assert config["DEVICE_METADATA"]["localhost"]["hwsku"] == "Test-HWSKU"


def test_generate_sonic_config_starts_fresh_when_base_load_raises(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker, exists=True, raise_on_open=OSError("disk on fire"))
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "Test-HWSKU")

    # Scaffold survived the failed load, hostname still made it through.
    assert "DEVICE_METADATA" in config
    assert config["DEVICE_METADATA"]["localhost"]["hwsku"] == "Test-HWSKU"


# ---------------------------------------------------------------------------
# generate_sonic_config — primary-IP / AS routing
# ---------------------------------------------------------------------------


def test_generate_sonic_config_router_id_and_local_asn_from_primary_ip4(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.return_value = 4200045123
    device = make_orchestrator_device(primary_ip4=_ip("192.168.45.123/32"))

    config = generate_sonic_config(device, "Test-HWSKU")

    assert config["BGP_GLOBALS"]["default"]["router_id"] == "192.168.45.123"
    assert config["BGP_GLOBALS"]["default"]["local_asn"] == "4200045123"
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.assert_called_once_with(
        "192.168.45.123"
    )


def test_generate_sonic_config_calculate_asn_value_error_logged_no_local_asn(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """A ``ValueError`` from the AS calculator must be swallowed.

    ``router_id`` should still be set from ``primary_ip4`` and the function
    must return successfully — only ``local_asn`` is omitted.
    """
    patch_base_config(mocker)
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.side_effect = ValueError(
        "bad octet"
    )
    device = make_orchestrator_device(primary_ip4=_ip("10.0.0.1/32"))

    config = generate_sonic_config(device, "HWSKU")

    assert config["BGP_GLOBALS"]["default"]["router_id"] == "10.0.0.1"
    assert "local_asn" not in config["BGP_GLOBALS"]["default"]


def test_generate_sonic_config_router_id_falls_back_to_primary_ip6(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    device = make_orchestrator_device(
        primary_ip4=None, primary_ip6=_ip("2001:db8::1/128")
    )

    config = generate_sonic_config(device, "HWSKU")

    assert config["BGP_GLOBALS"]["default"]["router_id"] == "2001:db8::1"
    # IPv6-only path must not invoke the IPv4 ASN calculator.
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.assert_not_called()
    assert "local_asn" not in config["BGP_GLOBALS"].get("default", {})


def test_generate_sonic_config_no_primary_ip_skips_bgp_globals_default(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """Edge case: a device without any primary IP (rare in production but
    worth pinning) must not produce a partial ``BGP_GLOBALS["default"]``."""
    patch_base_config(mocker)
    device = make_orchestrator_device(primary_ip4=None, primary_ip6=None)

    config = generate_sonic_config(device, "HWSKU")

    assert "default" not in config["BGP_GLOBALS"]
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.assert_not_called()


def test_generate_sonic_config_device_as_mapping_overrides_calculator(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """Spine/superspine devices use a pre-computed group AS — the calculator
    is bypassed entirely so the group's minimum AS wins."""
    patch_base_config(mocker)
    device = make_orchestrator_device(device_id=42, primary_ip4=_ip("192.168.45.99/32"))

    config = generate_sonic_config(device, "HWSKU", device_as_mapping={42: 4200099999})

    assert config["BGP_GLOBALS"]["default"]["local_asn"] == "4200099999"
    patch_orchestrator_helpers.calculate_local_asn_from_ipv4.assert_not_called()


# ---------------------------------------------------------------------------
# generate_sonic_config — OOB / management routing
# ---------------------------------------------------------------------------


def test_generate_sonic_config_populates_mgmt_interface_and_static_route(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    patch_orchestrator_helpers.get_device_oob_ip.return_value = ("10.42.0.5", 24)
    patch_orchestrator_helpers._get_metalbox_ip_for_device.return_value = "10.42.0.1"
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU")

    assert config["MGMT_INTERFACE"]["eth0"] == {"admin_status": "up"}
    assert "eth0|10.42.0.5/24" in config["MGMT_INTERFACE"]
    assert config["STATIC_ROUTE"]["mgmt|0.0.0.0/0"] == {"nexthop": "10.42.0.1"}
    patch_orchestrator_helpers._get_metalbox_ip_for_device.assert_called_once_with(
        device
    )
    # SNMP receives the OOB IP for SNMP_AGENT_ADDRESS_CONFIG wiring.
    _, _, snmp_oob = patch_orchestrator_helpers._add_snmp_configuration.call_args.args
    assert snmp_oob == "10.42.0.5"


def test_generate_sonic_config_no_oob_ip_leaves_mgmt_empty_and_passes_none(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    patch_orchestrator_helpers.get_device_oob_ip.return_value = None
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU")

    assert config["MGMT_INTERFACE"] == {}
    # STATIC_ROUTE was scaffolded but never populated.
    assert "mgmt|0.0.0.0/0" not in config["STATIC_ROUTE"]
    _, _, snmp_oob = patch_orchestrator_helpers._add_snmp_configuration.call_args.args
    assert snmp_oob is None


# ---------------------------------------------------------------------------
# generate_sonic_config — breakout merge
# ---------------------------------------------------------------------------


def test_generate_sonic_config_merges_breakout_cfgs_and_ports(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    patch_orchestrator_helpers.detect_breakout_ports.return_value = {
        "breakout_cfgs": {"Ethernet0": {"brkout_mode": "4x25G"}},
        "breakout_ports": {"Ethernet0": {"master": "Ethernet0"}},
    }
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU")

    assert config["BREAKOUT_CFG"]["Ethernet0"] == {"brkout_mode": "4x25G"}
    assert config["BREAKOUT_PORTS"]["Ethernet0"] == {"master": "Ethernet0"}


# ---------------------------------------------------------------------------
# generate_sonic_config — config_version normalization
# ---------------------------------------------------------------------------


def test_generate_sonic_config_version_short_form_gets_prefix(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU", config_version="4_2_0")

    assert config["VERSIONS"]["DATABASE"]["VERSION"] == "version_4_2_0"


def test_generate_sonic_config_version_long_form_kept_as_is(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker)
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU", config_version="version_4_2_0")

    assert config["VERSIONS"]["DATABASE"]["VERSION"] == "version_4_2_0"


def test_generate_sonic_config_version_default_when_missing(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker, base_config=make_base_config())
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU", config_version=None)

    assert config["VERSIONS"]["DATABASE"]["VERSION"] == "version_4_0_1"


def test_generate_sonic_config_version_existing_in_base_preserved(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    patch_base_config(mocker, base_config=make_base_config(version="version_4_5_0"))
    device = make_orchestrator_device()

    config = generate_sonic_config(device, "HWSKU", config_version=None)

    assert config["VERSIONS"]["DATABASE"]["VERSION"] == "version_4_5_0"


# ---------------------------------------------------------------------------
# generate_sonic_config — netbox_interfaces collection
# ---------------------------------------------------------------------------


def test_generate_sonic_config_handles_interfaces_without_optional_fields(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """``speed`` / ``type`` / ``tags`` are optional on NetBox interfaces — the
    orchestrator must tolerate any of them being missing or ``None`` and fall
    through to ``get_speed_from_port_type`` only when both are absent."""
    patch_base_config(mocker)
    iface_no_speed = SimpleNamespace(name="Ethernet0", speed=None, type=None, tags=[])
    iface_with_type = SimpleNamespace(
        name="Ethernet1",
        speed=None,
        type=SimpleNamespace(value="25gbase-x-sfp28"),
        tags=[],
    )
    patch_orchestrator_helpers.get_cached_device_interfaces.return_value = [
        iface_no_speed,
        iface_with_type,
    ]
    patch_orchestrator_helpers.get_speed_from_port_type.return_value = 25_000_000

    # Should not raise; the orchestrator builds netbox_interfaces internally
    # before delegating to _add_port_configurations (which is mocked).
    config = generate_sonic_config(make_orchestrator_device(), "HWSKU")

    assert isinstance(config, dict)
    patch_orchestrator_helpers._add_port_configurations.assert_called_once()


def test_generate_sonic_config_get_cached_interfaces_failure_logged(
    mocker, patch_orchestrator_helpers, make_orchestrator_device
):
    """If the per-device interface fetch fails, ``netbox_interfaces`` stays
    empty (warning logged) and the orchestrator continues — the section
    helpers will simply receive an empty mapping."""
    patch_base_config(mocker)
    patch_orchestrator_helpers.get_cached_device_interfaces.side_effect = RuntimeError(
        "netbox unreachable"
    )

    config = generate_sonic_config(make_orchestrator_device(), "HWSKU")

    assert isinstance(config, dict)
    # _add_port_configurations was still called with an (empty) dict.
    args, _ = patch_orchestrator_helpers._add_port_configurations.call_args
    # netbox_interfaces is the 6th positional argument: (config, port_config,
    # connected_interfaces, portchannel_info, breakout_info,
    # netbox_interfaces, vlan_info, device).
    assert args[5] == {}


# ---------------------------------------------------------------------------
# clear_*_cache helpers
# ---------------------------------------------------------------------------


def test_clear_metalbox_ip_cache_resets_to_empty_dict():
    config_generator._metalbox_ip_cache = {1: "10.0.0.1"}

    clear_metalbox_ip_cache()

    assert config_generator._metalbox_ip_cache == {}


def test_clear_metalbox_devices_cache_resets_to_none():
    config_generator._metalbox_devices_cache = {1: {"device": object()}}

    clear_metalbox_devices_cache()

    assert config_generator._metalbox_devices_cache is None


def test_clear_all_caches_clears_everything_and_port_config(mocker):
    """``clear_all_caches`` is the single entry point ``sync_sonic`` uses;
    if any of the resets is dropped we get cross-run contamination."""
    cpc = mocker.patch(
        "osism.tasks.conductor.sonic.config_generator.clear_port_config_cache"
    )
    config_generator._metalbox_ip_cache = {1: "10.0.0.1"}
    config_generator._metalbox_devices_cache = {1: {}}

    clear_all_caches()

    assert config_generator._metalbox_ip_cache == {}
    assert config_generator._metalbox_devices_cache is None
    cpc.assert_called_once_with()
