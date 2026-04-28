# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the metalbox-discovery service caches in
``config_generator``: ``_load_metalbox_devices_cache`` (the NetBox crawl) and
``_get_metalbox_ip_for_device`` (the per-device subnet match)."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import config_generator
from osism.tasks.conductor.sonic.config_generator import (
    _get_metalbox_ip_for_device,
    _load_metalbox_devices_cache,
)

from ._config_generator_helpers import make_iface, make_ip, seed_metalbox_cache

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


# ---------------------------------------------------------------------------
# _load_metalbox_devices_cache
# ---------------------------------------------------------------------------


def test_load_metalbox_devices_cache_filters_mgmt_only_and_flags_vlan(mock_nb):
    metalbox = SimpleNamespace(id=10, name="metalbox-1")
    eth_iface = make_iface("Ethernet0", mgmt_only=False, iface_id=100)
    mgmt_iface = make_iface("eth0", mgmt_only=True, iface_id=101)
    vlan_iface = make_iface(
        "Vlan100", mgmt_only=False, type_value="virtual", iface_id=102
    )
    mock_nb.dcim.devices.filter.return_value = [metalbox]
    mock_nb.dcim.interfaces.filter.return_value = [
        eth_iface,
        mgmt_iface,
        vlan_iface,
    ]
    mock_nb.ipam.ip_addresses.filter.side_effect = [
        [make_ip("10.0.0.1/24")],  # eth_iface
        [make_ip("192.168.1.1/24")],  # vlan_iface
    ]

    _load_metalbox_devices_cache()

    cache = config_generator._metalbox_devices_cache
    assert set(cache[10]["interfaces"].keys()) == {100, 102}
    # ``is_vlan`` is the result of a short-circuited and-chain, so non-VLAN
    # interfaces may carry a falsy non-bool (e.g. ``None`` when ``type`` is
    # absent). Compare on truthiness, not identity.
    assert not cache[10]["interfaces"][100]["is_vlan"]
    assert cache[10]["interfaces"][102]["is_vlan"]
    assert [ip.address for ip in cache[10]["interfaces"][100]["ips"]] == ["10.0.0.1/24"]


def test_load_metalbox_devices_cache_per_metalbox_interface_failure_isolated(
    mock_nb,
):
    """One metalbox failing to enumerate interfaces must not poison the cache
    for the others — the failing entry just gets an empty ``interfaces`` dict."""
    mb_a = SimpleNamespace(id=1, name="mb-a")
    mb_b = SimpleNamespace(id=2, name="mb-b")
    eth = make_iface("Ethernet0", iface_id=99)
    mock_nb.dcim.devices.filter.return_value = [mb_a, mb_b]
    mock_nb.dcim.interfaces.filter.side_effect = [
        RuntimeError("transient"),  # mb-a
        [eth],  # mb-b
    ]
    mock_nb.ipam.ip_addresses.filter.return_value = [make_ip("10.0.0.1/24")]

    _load_metalbox_devices_cache()

    cache = config_generator._metalbox_devices_cache
    assert cache[1]["interfaces"] == {}
    assert 99 in cache[2]["interfaces"]


def test_load_metalbox_devices_cache_top_level_failure_resets_cache(mock_nb):
    mock_nb.dcim.devices.filter.side_effect = RuntimeError("netbox down")

    _load_metalbox_devices_cache()

    assert config_generator._metalbox_devices_cache == {}


def test_load_metalbox_devices_cache_filters_ip_without_address(mock_nb):
    """``if ip_addr.address`` filters falsy addresses; non-empty ones survive."""
    metalbox = SimpleNamespace(id=10, name="mb")
    eth = make_iface("Ethernet0", iface_id=100)
    mock_nb.dcim.devices.filter.return_value = [metalbox]
    mock_nb.dcim.interfaces.filter.return_value = [eth]
    mock_nb.ipam.ip_addresses.filter.return_value = [
        make_ip(""),  # falsy — dropped
        make_ip(None),  # falsy — dropped
        make_ip("10.0.0.1/24"),  # kept
    ]

    _load_metalbox_devices_cache()

    ips = config_generator._metalbox_devices_cache[10]["interfaces"][100]["ips"]
    assert [ip.address for ip in ips] == ["10.0.0.1/24"]


# ---------------------------------------------------------------------------
# _get_metalbox_ip_for_device
# ---------------------------------------------------------------------------


def test_get_metalbox_ip_oob_lookup_returns_none(mocker):
    mocker.patch.object(config_generator, "get_device_oob_ip", return_value=None)
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) is None
    # ``None`` is cached so we never re-enter the lookup for this device.
    assert config_generator._metalbox_ip_cache[1] is None


def test_get_metalbox_ip_subnet_match_returns_ip(mocker):
    mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    eth = make_iface("Ethernet0", iface_id=100)
    seed_metalbox_cache(interfaces=[(eth, False, ["10.0.0.1/24"])])
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) == "10.0.0.1"
    assert config_generator._metalbox_ip_cache[1] == "10.0.0.1"


def test_get_metalbox_ip_no_subnet_match_returns_none(mocker):
    mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    eth = make_iface("Ethernet0", iface_id=100)
    seed_metalbox_cache(interfaces=[(eth, False, ["192.168.1.1/24"])])
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) is None
    assert config_generator._metalbox_ip_cache[1] is None


def test_get_metalbox_ip_skips_ipv6_addresses(mocker):
    """``IPv4Address`` raises ``ValueError`` on an IPv6 string; the loop must
    swallow it and keep looking at the next IP."""
    mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    eth = make_iface("Ethernet0", iface_id=100)
    seed_metalbox_cache(
        interfaces=[
            (eth, False, ["2001:db8::1/64", "10.0.0.1/24"]),
        ]
    )
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) == "10.0.0.1"


def test_get_metalbox_ip_returns_match_on_vlan_interface(mocker):
    mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    vlan = make_iface("Vlan100", type_value="virtual", iface_id=200)
    seed_metalbox_cache(interfaces=[(vlan, True, ["10.0.0.1/24"])])
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) == "10.0.0.1"


def test_get_metalbox_ip_second_call_hits_cache(mocker):
    oob_mock = mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    eth = make_iface("Ethernet0", iface_id=100)
    seed_metalbox_cache(interfaces=[(eth, False, ["10.0.0.1/24"])])
    device = SimpleNamespace(id=1, name="leaf-1")

    first = _get_metalbox_ip_for_device(device)
    second = _get_metalbox_ip_for_device(device)

    assert first == second == "10.0.0.1"
    # Second call short-circuited on the IP cache; no extra OOB lookup.
    oob_mock.assert_called_once_with(device)


def test_get_metalbox_ip_when_devices_cache_is_none(mocker):
    mocker.patch.object(
        config_generator, "get_device_oob_ip", return_value=("10.0.0.5", 24)
    )
    # Autouse already left _metalbox_devices_cache at None.
    assert config_generator._metalbox_devices_cache is None
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) is None
    assert config_generator._metalbox_ip_cache[1] is None


def test_get_metalbox_ip_outer_exception_returns_none(mocker):
    """A malformed OOB IP string causes ``IPv4Network`` to raise — the outer
    ``try`` catches it and the device gets a ``None`` cached result."""
    mocker.patch.object(
        config_generator,
        "get_device_oob_ip",
        return_value=("not-an-ip", 24),
    )
    device = SimpleNamespace(id=1, name="leaf-1")

    assert _get_metalbox_ip_for_device(device) is None
    assert config_generator._metalbox_ip_cache[1] is None
