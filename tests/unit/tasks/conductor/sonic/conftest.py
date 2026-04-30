# SPDX-License-Identifier: Apache-2.0

"""Shared fixtures for the SONiC unit tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def reset_config_generator_caches():
    """Reset every module global the ``config_generator`` orchestrator touches.

    Without this, a previous test's ``_metalbox_ip_cache`` /
    ``_metalbox_devices_cache`` would leak into the next one and make the
    suite order-dependent. Files that exercise ``config_generator`` opt in
    via ``pytestmark = pytest.mark.usefixtures(...)`` so the reset never runs
    for unrelated SONiC tests.
    """
    from osism.tasks.conductor.sonic import config_generator

    config_generator.clear_all_caches()
    yield
    config_generator.clear_all_caches()


@pytest.fixture
def mock_nb(mocker):
    """Replace ``utils.nb`` for the duration of one test.

    ``utils.nb`` is normally lazily wired through ``__getattr__`` and would
    try to reach a real NetBox instance — ``create=True`` is needed because
    the attribute may not be bound yet.
    """
    nb = MagicMock()
    mocker.patch("osism.utils.nb", new=nb, create=True)
    return nb


@pytest.fixture
def make_interface():
    """Build a minimal NetBox-shaped interface stub."""

    def _factory(
        name="Ethernet0",
        mgmt_only=False,
        connected_endpoints=None,
        connected_endpoints_reachable=True,
    ):
        return SimpleNamespace(
            name=name,
            mgmt_only=mgmt_only,
            connected_endpoints=connected_endpoints,
            connected_endpoints_reachable=connected_endpoints_reachable,
        )

    return _factory


@pytest.fixture
def make_endpoint():
    """Build a connected-endpoint stub with a nested device."""

    def _factory(device_id, **device_attrs):
        return SimpleNamespace(device=SimpleNamespace(id=device_id, **device_attrs))

    return _factory


@pytest.fixture
def make_device():
    """Build a NetBox-shaped device stub with a ``role.slug``."""

    def _factory(device_id, name=None, role_slug="spine"):
        return SimpleNamespace(
            id=device_id,
            name=name or f"device-{device_id}",
            role=SimpleNamespace(slug=role_slug),
        )

    return _factory


@pytest.fixture
def patch_connection_helpers(mocker):
    """Patch the helpers consumed by ``get_connected_interfaces`` and friends.

    Returns ``patch(interfaces, *, connection_lookup=None, sonic_name_lookup=None)``.
    Both lookups are keyed by ``id(interface)``; ``sonic_name_lookup`` defaults
    to ``interface.name`` for any interface not in the map. The call returns a
    namespace exposing the three patched mocks (``cache``, ``via``, ``convert``)
    so individual tests can make additional call assertions.
    """

    def _patch(interfaces, *, connection_lookup=None, sonic_name_lookup=None):
        connection_lookup = connection_lookup or {}
        sonic_name_lookup = sonic_name_lookup or {}
        cache = mocker.patch(
            "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
            return_value=interfaces,
        )
        via = mocker.patch(
            "osism.tasks.conductor.sonic.connections.get_connected_device_via_interface",
            side_effect=lambda iface, _device_id: connection_lookup.get(id(iface)),
        )
        convert = mocker.patch(
            "osism.tasks.conductor.sonic.connections.convert_netbox_interface_to_sonic",
            side_effect=lambda iface, _device: sonic_name_lookup.get(
                id(iface), iface.name
            ),
        )
        return SimpleNamespace(cache=cache, via=via, convert=convert)

    return _patch


@pytest.fixture
def wire_topology(mocker):
    """Patch the helpers consumed by ``find_interconnected_devices``.

    ``device_interfaces`` maps ``device_id`` → ``[interface]``;
    ``connections_map`` maps ``id(interface)`` → peer device.
    """

    def _wire(*, device_interfaces, connections_map):
        cache = mocker.patch(
            "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
            side_effect=lambda device_id: device_interfaces.get(device_id, []),
        )
        via = mocker.patch(
            "osism.tasks.conductor.sonic.connections.get_connected_device_via_interface",
            side_effect=lambda iface, _source_id: connections_map.get(id(iface)),
        )
        return SimpleNamespace(cache=cache, via=via)

    return _wire


@pytest.fixture
def patch_detect_port_channels(mocker):
    """Patch ``detect_port_channels`` and derive ``member_mapping`` from it."""

    def _patch(portchannels):
        return mocker.patch(
            "osism.tasks.conductor.sonic.interface.detect_port_channels",
            return_value={
                "portchannels": portchannels,
                "member_mapping": {
                    member: pc
                    for pc, info in portchannels.items()
                    for member in info.get("members", [])
                },
            },
        )

    return _patch


@pytest.fixture
def reset_vip_cache():
    """Reset ``connections._vip_addresses_cache`` around each test."""
    from osism.tasks.conductor.sonic import connections

    connections._vip_addresses_cache = None
    yield
    connections._vip_addresses_cache = None
