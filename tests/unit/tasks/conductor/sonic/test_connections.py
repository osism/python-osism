# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic import connections

# ---------------------------------------------------------------------------
# get_connected_device_via_interface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "build_interface",
    [
        pytest.param(
            lambda make_iface, make_ep: make_iface(
                mgmt_only=True, connected_endpoints=[make_ep(2)]
            ),
            id="mgmt_only",
        ),
        pytest.param(
            lambda *_: SimpleNamespace(name="Ethernet0", mgmt_only=False),
            id="no_connected_endpoints_attr",
        ),
        pytest.param(
            lambda make_iface, _make_ep: make_iface(connected_endpoints=[]),
            id="empty_connected_endpoints",
        ),
        pytest.param(
            lambda make_iface, _make_ep: make_iface(connected_endpoints=None),
            id="connected_endpoints_none",
        ),
        pytest.param(
            lambda make_iface, make_ep: make_iface(
                connected_endpoints=[make_ep(2)], connected_endpoints_reachable=False
            ),
            id="not_reachable",
        ),
        pytest.param(
            lambda _make_iface, make_ep: SimpleNamespace(
                name="Ethernet0",
                mgmt_only=False,
                connected_endpoints=[make_ep(2)],
            ),
            id="reachable_attribute_missing",
        ),
        pytest.param(
            lambda make_iface, make_ep: make_iface(connected_endpoints=[make_ep(1)]),
            id="excludes_source_device",
        ),
        pytest.param(
            lambda make_iface, make_ep: make_iface(
                connected_endpoints=[make_ep(1), make_ep(1)]
            ),
            id="all_endpoints_are_source",
        ),
        pytest.param(
            lambda make_iface, _make_ep: make_iface(
                connected_endpoints=[SimpleNamespace()]
            ),
            id="endpoint_without_device_attr",
        ),
    ],
)
def test_get_connected_device_via_interface_returns_none(
    build_interface, make_interface, make_endpoint
):
    interface = build_interface(make_interface, make_endpoint)

    assert connections.get_connected_device_via_interface(interface, 1) is None


def test_get_connected_device_via_interface_returns_first_non_source_device(
    make_interface, make_endpoint
):
    endpoint = make_endpoint(2, name="peer")
    interface = make_interface(connected_endpoints=[endpoint])

    result = connections.get_connected_device_via_interface(interface, 1)

    assert result is endpoint.device
    assert result.id == 2


def test_get_connected_device_via_interface_skips_source_picks_next(
    make_interface, make_endpoint
):
    src = make_endpoint(1)
    other = make_endpoint(7, name="peer")
    interface = make_interface(connected_endpoints=[src, other])

    result = connections.get_connected_device_via_interface(interface, 1)

    assert result is other.device


def test_get_connected_device_via_interface_endpoint_with_none_device_caught(
    mocker, make_interface
):
    # endpoint.device is present but None — accessing endpoint.device.id
    # raises AttributeError, which is caught by the inner try/except.
    debug = mocker.patch("osism.tasks.conductor.sonic.connections.logger.debug")
    bad = SimpleNamespace(device=None)
    interface = make_interface(connected_endpoints=[bad])

    assert connections.get_connected_device_via_interface(interface, 1) is None
    debug.assert_called_once()
    assert "Ethernet0" in debug.call_args.args[0]


def test_get_connected_device_via_interface_no_mgmt_only_attribute(make_endpoint):
    # Interfaces without a `mgmt_only` attribute are not treated as mgmt-only.
    endpoint = make_endpoint(2)
    interface = SimpleNamespace(
        name="Ethernet0",
        connected_endpoints=[endpoint],
        connected_endpoints_reachable=True,
    )

    result = connections.get_connected_device_via_interface(interface, 1)

    assert result is endpoint.device


# ---------------------------------------------------------------------------
# get_connected_interfaces
# ---------------------------------------------------------------------------


def test_get_connected_interfaces_two_connected_no_portchannels(
    make_interface, make_device, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface_a = make_interface(name="Ethernet0")
    iface_b = make_interface(name="Ethernet4")
    peer = make_device(2)

    patch_connection_helpers(
        [iface_a, iface_b],
        connection_lookup={id(iface_a): peer, id(iface_b): peer},
    )

    connected, portchannels = connections.get_connected_interfaces(device)

    assert connected == {"Ethernet0", "Ethernet4"}
    assert portchannels == set()


def test_get_connected_interfaces_returns_set_instances(patch_connection_helpers):
    device = SimpleNamespace(id=1, name="sw1")
    patch_connection_helpers([])

    connected, portchannels = connections.get_connected_interfaces(device)

    assert isinstance(connected, set)
    assert isinstance(portchannels, set)


def test_get_connected_interfaces_skips_mgmt_only(
    make_interface, make_device, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    mgmt = make_interface(name="mgmt0", mgmt_only=True)
    data = make_interface(name="Ethernet0")
    peer = make_device(2)

    patch_connection_helpers([mgmt, data], connection_lookup={id(data): peer})

    connected, _ = connections.get_connected_interfaces(device)

    assert connected == {"Ethernet0"}


def test_get_connected_interfaces_unconnected_interface_excluded(
    make_interface, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet0")

    patch_connection_helpers([iface])  # connection_lookup empty

    connected, portchannels = connections.get_connected_interfaces(device)

    assert connected == set()
    assert portchannels == set()


@pytest.mark.parametrize(
    "member_mapping, expected_portchannels",
    [
        pytest.param(
            {"Ethernet0": "PortChannel1"}, {"PortChannel1"}, id="member_marks_pc"
        ),
        pytest.param({"Ethernet99": "PortChannel9"}, set(), id="no_member_match"),
    ],
)
def test_get_connected_interfaces_portchannel_member_mapping(
    make_interface,
    make_device,
    patch_connection_helpers,
    member_mapping,
    expected_portchannels,
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet0")
    peer = make_device(2)

    patch_connection_helpers([iface], connection_lookup={id(iface): peer})

    connected, portchannels = connections.get_connected_interfaces(
        device, portchannel_info={"member_mapping": member_mapping}
    )

    assert connected == {"Ethernet0"}
    assert portchannels == expected_portchannels


def test_get_connected_interfaces_helper_exception_logs_warning(mocker, make_interface):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet0")

    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
        return_value=[iface],
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_connected_device_via_interface",
        side_effect=RuntimeError("boom"),
    )
    warning = mocker.patch("osism.tasks.conductor.sonic.connections.logger.warning")

    connected, portchannels = connections.get_connected_interfaces(device)

    assert connected == set()
    assert portchannels == set()
    warning.assert_called_once()
    assert "sw1" in warning.call_args.args[0]


def test_get_connected_interfaces_continues_after_per_interface_exception(
    mocker, make_interface
):
    """An exception on one interface must not abort processing of subsequent ones."""
    device = SimpleNamespace(id=1, name="sw1")
    bad_iface = make_interface(name="Ethernet0")
    good_iface = make_interface(name="Ethernet4")
    peer = SimpleNamespace(id=2, name="peer")

    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
        return_value=[bad_iface, good_iface],
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_connected_device_via_interface",
        side_effect=[RuntimeError("boom"), peer],
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.convert_netbox_interface_to_sonic",
        return_value="Ethernet4",
    )

    connected, _ = connections.get_connected_interfaces(device)

    assert connected == {"Ethernet4"}


def test_get_connected_interfaces_cache_lookup_failure_returns_empty(mocker):
    device = SimpleNamespace(id=1, name="sw1")
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
        side_effect=RuntimeError("netbox down"),
    )
    warning = mocker.patch("osism.tasks.conductor.sonic.connections.logger.warning")

    connected, portchannels = connections.get_connected_interfaces(device)

    assert connected == set()
    assert portchannels == set()
    warning.assert_called_once()


def test_get_connected_interfaces_uses_sonic_converted_name(
    make_interface, make_device, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="ethernet1/1")
    peer = make_device(2)

    patch_connection_helpers(
        [iface],
        connection_lookup={id(iface): peer},
        sonic_name_lookup={id(iface): "Ethernet0"},
    )

    connected, _ = connections.get_connected_interfaces(device)

    assert connected == {"Ethernet0"}


# ---------------------------------------------------------------------------
# get_connected_device_for_sonic_interface
# ---------------------------------------------------------------------------


def test_get_connected_device_for_sonic_interface_delegates_for_portchannel(mocker):
    device = SimpleNamespace(id=1, name="sw1")
    sentinel = SimpleNamespace(name="peer")
    delegate = mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_connected_device_for_port_channel",
        return_value=sentinel,
    )

    result = connections.get_connected_device_for_sonic_interface(
        device, "PortChannel5"
    )

    delegate.assert_called_once_with(device, "PortChannel5")
    assert result is sentinel


def test_get_connected_device_for_sonic_interface_regular_match_returns_device(
    make_interface, make_device, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet0")
    peer = make_device(2)

    patch_connection_helpers([iface], connection_lookup={id(iface): peer})

    result = connections.get_connected_device_for_sonic_interface(device, "Ethernet0")

    assert result is peer


def test_get_connected_device_for_sonic_interface_regular_no_match_returns_none(
    make_interface, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet4")

    mocks = patch_connection_helpers([iface])

    result = connections.get_connected_device_for_sonic_interface(device, "Ethernet0")

    assert result is None
    mocks.via.assert_not_called()


def test_get_connected_device_for_sonic_interface_match_but_unconnected(
    make_interface, patch_connection_helpers
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet0")

    patch_connection_helpers([iface])  # no peer in connection_lookup → None

    assert (
        connections.get_connected_device_for_sonic_interface(device, "Ethernet0")
        is None
    )


def test_get_connected_device_for_sonic_interface_helper_raises_returns_none(mocker):
    device = SimpleNamespace(id=1, name="sw1")
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
        side_effect=RuntimeError("boom"),
    )
    debug = mocker.patch("osism.tasks.conductor.sonic.connections.logger.debug")

    result = connections.get_connected_device_for_sonic_interface(device, "Ethernet0")

    assert result is None
    debug.assert_called_once()
    assert "Ethernet0" in debug.call_args.args[0]


def test_get_connected_device_for_sonic_interface_empty_interfaces(
    patch_connection_helpers,
):
    device = SimpleNamespace(id=1, name="sw1")
    patch_connection_helpers([])

    assert (
        connections.get_connected_device_for_sonic_interface(device, "Ethernet0")
        is None
    )


# ---------------------------------------------------------------------------
# get_connected_device_for_port_channel
# ---------------------------------------------------------------------------


def test_get_connected_device_for_port_channel_unknown_pc_returns_none(
    patch_detect_port_channels,
):
    device = SimpleNamespace(id=1, name="sw1")
    patch_detect_port_channels({})

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is None
    )


def test_get_connected_device_for_port_channel_no_members_returns_none(
    patch_detect_port_channels,
):
    device = SimpleNamespace(id=1, name="sw1")
    patch_detect_port_channels({"PortChannel1": {"members": []}})

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is None
    )


def test_get_connected_device_for_port_channel_single_member_connected(
    make_interface,
    make_device,
    patch_connection_helpers,
    patch_detect_port_channels,
):
    device = SimpleNamespace(id=1, name="sw1")
    iface = make_interface(name="Ethernet120")
    peer = make_device(2, name="peer")

    patch_detect_port_channels({"PortChannel1": {"members": ["Ethernet120"]}})
    patch_connection_helpers([iface], connection_lookup={id(iface): peer})

    result = connections.get_connected_device_for_port_channel(device, "PortChannel1")

    assert result is peer


def test_get_connected_device_for_port_channel_falls_through_to_second_member(
    make_interface,
    make_device,
    patch_connection_helpers,
    patch_detect_port_channels,
):
    device = SimpleNamespace(id=1, name="sw1")
    iface_a = make_interface(name="Ethernet120")
    iface_b = make_interface(name="Ethernet124")
    peer = make_device(2, name="peer")

    patch_detect_port_channels(
        {"PortChannel1": {"members": ["Ethernet120", "Ethernet124"]}}
    )
    patch_connection_helpers(
        [iface_a, iface_b],
        connection_lookup={id(iface_b): peer},  # iface_a has no peer
    )

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is peer
    )


def test_get_connected_device_for_port_channel_all_members_unconnected(
    make_interface,
    patch_connection_helpers,
    patch_detect_port_channels,
):
    device = SimpleNamespace(id=1, name="sw1")
    iface_a = make_interface(name="Ethernet120")
    iface_b = make_interface(name="Ethernet124")

    patch_detect_port_channels(
        {"PortChannel1": {"members": ["Ethernet120", "Ethernet124"]}}
    )
    patch_connection_helpers([iface_a, iface_b])  # empty connection_lookup

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is None
    )


def test_get_connected_device_for_port_channel_member_without_matching_interface(
    make_interface,
    patch_connection_helpers,
    patch_detect_port_channels,
):
    # The detected member name does not match any NetBox interface.
    device = SimpleNamespace(id=1, name="sw1")
    iface_other = make_interface(name="Ethernet0")

    patch_detect_port_channels({"PortChannel1": {"members": ["EthernetMissing"]}})
    mocks = patch_connection_helpers([iface_other])

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is None
    )
    mocks.via.assert_not_called()


def test_get_connected_device_for_port_channel_detect_raises_returns_none(mocker):
    device = SimpleNamespace(id=1, name="sw1")
    mocker.patch(
        "osism.tasks.conductor.sonic.interface.detect_port_channels",
        side_effect=RuntimeError("boom"),
    )
    debug = mocker.patch("osism.tasks.conductor.sonic.connections.logger.debug")

    assert (
        connections.get_connected_device_for_port_channel(device, "PortChannel1")
        is None
    )
    debug.assert_called_once()
    assert "PortChannel1" in debug.call_args.args[0]


# ---------------------------------------------------------------------------
# find_interconnected_devices
# ---------------------------------------------------------------------------


def test_find_interconnected_devices_empty_input():
    assert connections.find_interconnected_devices([]) == []


def test_find_interconnected_devices_no_matching_roles(make_device, wire_topology):
    leaf = make_device(1, role_slug="leaf")
    wire_topology(device_interfaces={}, connections_map={})

    assert connections.find_interconnected_devices([leaf]) == []


def test_find_interconnected_devices_single_spine_no_peers(make_device, wire_topology):
    spine = make_device(1, role_slug="spine")
    wire_topology(device_interfaces={1: []}, connections_map={})

    # Single device with no in-role peers — the device never enters
    # role_graphs, so the BFS has nothing to walk and returns no groups.
    assert connections.find_interconnected_devices([spine]) == []


def test_find_interconnected_devices_two_spines_paired(
    make_interface, make_device, wire_topology
):
    spine_a = make_device(1, name="spine-a", role_slug="spine")
    spine_b = make_device(2, name="spine-b", role_slug="spine")
    iface_a = make_interface(name="Ethernet0")
    iface_b = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={1: [iface_a], 2: [iface_b]},
        connections_map={id(iface_a): spine_b, id(iface_b): spine_a},
    )

    groups = connections.find_interconnected_devices([spine_a, spine_b])

    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {1, 2}


def test_find_interconnected_devices_chain_of_three(
    make_interface, make_device, wire_topology
):
    a = make_device(1, role_slug="spine")
    b = make_device(2, role_slug="spine")
    c = make_device(3, role_slug="spine")

    a_b = make_interface(name="Ethernet0")
    b_a = make_interface(name="Ethernet0")
    b_c = make_interface(name="Ethernet1")
    c_b = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={1: [a_b], 2: [b_a, b_c], 3: [c_b]},
        connections_map={
            id(a_b): b,
            id(b_a): a,
            id(b_c): c,
            id(c_b): b,
        },
    )

    groups = connections.find_interconnected_devices([a, b, c])

    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {1, 2, 3}


def test_find_interconnected_devices_two_disjoint_pairs(
    make_interface, make_device, wire_topology
):
    a = make_device(1, role_slug="spine")
    b = make_device(2, role_slug="spine")
    c = make_device(3, role_slug="spine")
    d = make_device(4, role_slug="spine")

    a_b = make_interface(name="Ethernet0")
    b_a = make_interface(name="Ethernet0")
    c_d = make_interface(name="Ethernet0")
    d_c = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={1: [a_b], 2: [b_a], 3: [c_d], 4: [d_c]},
        connections_map={
            id(a_b): b,
            id(b_a): a,
            id(c_d): d,
            id(d_c): c,
        },
    )

    groups = connections.find_interconnected_devices([a, b, c, d])

    sets = sorted(({dev.id for dev in g} for g in groups), key=sorted)
    assert sets == [{1, 2}, {3, 4}]


def test_find_interconnected_devices_filters_non_target_roles(
    make_interface, make_device, wire_topology
):
    spine = make_device(1, role_slug="spine")
    leaf = make_device(2, role_slug="leaf")
    iface = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={1: [iface]},
        connections_map={id(iface): leaf},
    )

    # Spine only connects to a leaf — leaf is filtered out, spine has no
    # in-role peer, so no group is produced.
    assert connections.find_interconnected_devices([spine, leaf]) == []


def test_find_interconnected_devices_separate_groups_per_role(
    make_interface, make_device, wire_topology
):
    spine_a = make_device(1, role_slug="spine")
    spine_b = make_device(2, role_slug="spine")
    super_a = make_device(3, role_slug="superspine")
    super_b = make_device(4, role_slug="superspine")

    sa_sb = make_interface(name="Ethernet0")
    sb_sa = make_interface(name="Ethernet0")
    sa_super = make_interface(name="Ethernet1")
    super_sa = make_interface(name="Ethernet0")
    suA_suB = make_interface(name="Ethernet1")
    suB_suA = make_interface(name="Ethernet1")

    wire_topology(
        device_interfaces={
            1: [sa_sb, sa_super],
            2: [sb_sa],
            3: [super_sa, suA_suB],
            4: [suB_suA],
        },
        connections_map={
            id(sa_sb): spine_b,
            id(sb_sa): spine_a,
            id(sa_super): super_a,  # cross-role link, ignored
            id(super_sa): spine_a,  # cross-role link, ignored
            id(suA_suB): super_b,
            id(suB_suA): super_a,
        },
    )

    groups = connections.find_interconnected_devices(
        [spine_a, spine_b, super_a, super_b]
    )

    sets = sorted(({dev.id for dev in g} for g in groups), key=sorted)
    assert sets == [{1, 2}, {3, 4}]


def test_find_interconnected_devices_skips_device_with_cache_error(
    mocker, make_interface, make_device
):
    a = make_device(1, name="spine-a", role_slug="spine")
    b = make_device(2, name="spine-b", role_slug="spine")
    c = make_device(3, name="spine-c", role_slug="spine")

    b_c = make_interface(name="Ethernet0")
    c_b = make_interface(name="Ethernet0")

    def _interfaces(device_id):
        if device_id == 1:
            raise RuntimeError("netbox down")
        return {2: [b_c], 3: [c_b]}.get(device_id, [])

    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_cached_device_interfaces",
        side_effect=_interfaces,
    )
    mocker.patch(
        "osism.tasks.conductor.sonic.connections.get_connected_device_via_interface",
        side_effect=lambda iface, _id: {id(b_c): c, id(c_b): b}.get(id(iface)),
    )
    warning = mocker.patch("osism.tasks.conductor.sonic.connections.logger.warning")

    groups = connections.find_interconnected_devices([a, b, c])

    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {2, 3}
    warning.assert_called_once()
    assert "spine-a" in warning.call_args.args[0]


def test_find_interconnected_devices_custom_target_roles(
    make_interface, make_device, wire_topology
):
    leaf_a = make_device(1, role_slug="leaf")
    leaf_b = make_device(2, role_slug="leaf")
    spine = make_device(3, role_slug="spine")
    iface_a = make_interface(name="Ethernet0")
    iface_b = make_interface(name="Ethernet0")
    iface_spine = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={
            1: [iface_a],
            2: [iface_b],
            3: [iface_spine],
        },
        connections_map={
            id(iface_a): leaf_b,
            id(iface_b): leaf_a,
            id(iface_spine): leaf_a,  # filtered: spine is not in target_roles
        },
    )

    groups = connections.find_interconnected_devices(
        [leaf_a, leaf_b, spine], target_roles=["leaf"]
    )

    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {1, 2}


@pytest.mark.parametrize(
    "no_role_device",
    [
        pytest.param(SimpleNamespace(id=1, name="weird", role=None), id="role_is_none"),
        pytest.param(SimpleNamespace(id=1, name="weird"), id="role_attr_missing"),
    ],
)
def test_find_interconnected_devices_skips_devices_without_role(
    no_role_device, make_interface, make_device, wire_topology
):
    spine_a = make_device(2, role_slug="spine")
    spine_b = make_device(3, role_slug="spine")
    a_b = make_interface(name="Ethernet0")
    b_a = make_interface(name="Ethernet0")

    wire_topology(
        device_interfaces={2: [a_b], 3: [b_a]},
        connections_map={id(a_b): spine_b, id(b_a): spine_a},
    )

    groups = connections.find_interconnected_devices([no_role_device, spine_a, spine_b])

    # The role-less device is silently skipped; the two spines still pair up.
    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {2, 3}


# ---------------------------------------------------------------------------
# load_vip_addresses_cache / clear_vip_addresses_cache
# ---------------------------------------------------------------------------


def test_load_vip_addresses_cache_populates(mocker, reset_vip_cache):
    vip_a = SimpleNamespace(address="10.0.0.1/32")
    vip_b = SimpleNamespace(address="10.0.0.2/32")
    nb = mocker.patch("osism.tasks.conductor.sonic.connections.utils.nb")
    nb.ipam.ip_addresses.filter.return_value = iter([vip_a, vip_b])

    connections.load_vip_addresses_cache()

    nb.ipam.ip_addresses.filter.assert_called_once_with(role="vip")
    assert connections._vip_addresses_cache == [vip_a, vip_b]


def test_load_vip_addresses_cache_handles_netbox_error(mocker, reset_vip_cache):
    nb = mocker.patch("osism.tasks.conductor.sonic.connections.utils.nb")
    nb.ipam.ip_addresses.filter.side_effect = RuntimeError("netbox down")
    warning = mocker.patch("osism.tasks.conductor.sonic.connections.logger.warning")

    connections.load_vip_addresses_cache()

    assert connections._vip_addresses_cache == []
    warning.assert_called_once()


def test_clear_vip_addresses_cache_resets_to_none(reset_vip_cache):
    connections._vip_addresses_cache = ["something"]

    connections.clear_vip_addresses_cache()

    assert connections._vip_addresses_cache is None


def test_load_after_clear_triggers_fresh_call(mocker, reset_vip_cache):
    nb = mocker.patch("osism.tasks.conductor.sonic.connections.utils.nb")
    nb.ipam.ip_addresses.filter.return_value = iter([])

    connections.load_vip_addresses_cache()
    connections.clear_vip_addresses_cache()
    nb.ipam.ip_addresses.filter.return_value = iter(
        [SimpleNamespace(address="10.0.0.9/32")]
    )
    connections.load_vip_addresses_cache()

    assert nb.ipam.ip_addresses.filter.call_count == 2
    assert len(connections._vip_addresses_cache) == 1


def test_load_vip_addresses_cache_overwrites_existing(mocker, reset_vip_cache):
    connections._vip_addresses_cache = [SimpleNamespace(address="stale")]
    nb = mocker.patch("osism.tasks.conductor.sonic.connections.utils.nb")
    nb.ipam.ip_addresses.filter.return_value = iter([])

    connections.load_vip_addresses_cache()

    assert connections._vip_addresses_cache == []
