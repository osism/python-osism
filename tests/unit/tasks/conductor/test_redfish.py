# SPDX-License-Identifier: Apache-2.0

from unittest.mock import DEFAULT, MagicMock, patch

import pytest

from osism.tasks.conductor import redfish

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Sentinel marking "do not set this attribute on the mock" so builders can
# distinguish ``ethernet=None`` from "no ethernet attribute at all".
_UNSET = object()


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _no_problem_logs(records):
    return not any(r["level"] in ("ERROR", "WARNING") for r in records)


class _RaisesOn:
    """Stand-in resource member whose ``identity`` is readable but whose
    ``trigger`` attribute raises when accessed.

    The per-item ``except`` branches log ``member.identity``, so the identity
    must stay readable while a *different* attribute access triggers the error.
    A plain ``MagicMock`` cannot raise on attribute read without leaking the
    descriptor to every other mock, hence this small explicit shim.
    """

    def __init__(self, identity, trigger):
        self.identity = identity
        self._trigger = trigger

    def __getattr__(self, name):
        if name == self._trigger:
            raise RuntimeError("boom")
        raise AttributeError(name)


def _patch_connection(conn):
    """Patch ``get_redfish_connection`` to return ``conn``."""
    return patch.object(redfish, "get_redfish_connection", return_value=conn)


def _make_interface(
    identity="1",
    name=None,
    description=None,
    mac_address=None,
    permanent_mac_address=None,
    speed_mbps=None,
    mtu_size=None,
    link_status=None,
    interface_enabled=None,
):
    iface = MagicMock()
    iface.identity = identity
    iface.name = name
    iface.description = description
    iface.mac_address = mac_address
    iface.permanent_mac_address = permanent_mac_address
    iface.speed_mbps = speed_mbps
    iface.mtu_size = mtu_size
    iface.link_status = link_status
    iface.interface_enabled = interface_enabled
    return iface


def _make_system(interfaces, identity="1"):
    system = MagicMock()
    system.identity = identity
    system.ethernet_interfaces.get_members.return_value = interfaces
    return system


def _make_adapter(
    identity="1",
    name=None,
    description=None,
    manufacturer=None,
    model=None,
    part_number=None,
    serial_number=None,
    firmware_version=None,
):
    adapter = MagicMock()
    adapter.identity = identity
    adapter.name = name
    adapter.description = description
    adapter.manufacturer = manufacturer
    adapter.model = model
    adapter.part_number = part_number
    adapter.serial_number = serial_number
    adapter.firmware_version = firmware_version
    return adapter


def _make_ethernet(mac_address=None, permanent_mac_address=None):
    ethernet = MagicMock()
    ethernet.mac_address = mac_address
    ethernet.permanent_mac_address = permanent_mac_address
    return ethernet


def _make_device_func(
    identity="1",
    name=None,
    description=None,
    device_enabled=None,
    ethernet_enabled=None,
    ethernet=_UNSET,
):
    device_func = MagicMock()
    device_func.identity = identity
    device_func.name = name
    device_func.description = description
    device_func.device_enabled = device_enabled
    device_func.ethernet_enabled = ethernet_enabled
    if ethernet is _UNSET:
        del device_func.ethernet
    else:
        device_func.ethernet = ethernet
    return device_func


def _make_devfunc_adapter(device_funcs, identity="1", name=None):
    adapter = MagicMock()
    adapter.identity = identity
    adapter.name = name
    adapter.network_device_functions.get_members.return_value = device_funcs
    return adapter


def _make_chassis(adapters, identity="1"):
    chassis = MagicMock()
    chassis.identity = identity
    chassis.network_adapters.get_members.return_value = adapters
    return chassis


def _conn_with_systems(systems):
    conn = MagicMock()
    conn.get_system_collection.return_value.get_members.return_value = systems
    return conn


def _conn_with_chassis(chassis_list):
    conn = MagicMock()
    conn.get_chassis_collection.return_value.get_members.return_value = chassis_list
    return conn


# ---------------------------------------------------------------------------
# _normalize_redfish_data
# ---------------------------------------------------------------------------


def test_normalize_removes_none_values():
    assert redfish._normalize_redfish_data({"a": None, "b": "x"}) == {"b": "x"}


def test_normalize_serializes_dict_to_json():
    assert redfish._normalize_redfish_data({"d": {"k": "v"}}) == {"d": '{"k": "v"}'}


def test_normalize_serializes_list_to_json():
    assert redfish._normalize_redfish_data({"l": [1, 2]}) == {"l": "[1, 2]"}


def test_normalize_bool_true_becomes_lowercase_string():
    assert redfish._normalize_redfish_data({"b": True}) == {"b": "true"}


def test_normalize_bool_false_becomes_lowercase_string():
    assert redfish._normalize_redfish_data({"b": False}) == {"b": "false"}


def test_normalize_int_becomes_string():
    assert redfish._normalize_redfish_data({"n": 25000}) == {"n": "25000"}


def test_normalize_float_becomes_string():
    assert redfish._normalize_redfish_data({"n": 1.5}) == {"n": "1.5"}


def test_normalize_plain_string_kept_as_is():
    assert redfish._normalize_redfish_data({"s": "eth0"}) == {"s": "eth0"}


def test_normalize_empty_dict_returns_empty_dict():
    assert redfish._normalize_redfish_data({}) == {}


def test_normalize_mixed_input_keeps_all_non_none_keys():
    data = {
        "none": None,
        "dict": {"k": "v"},
        "list": [1, 2],
        "true": True,
        "false": False,
        "int": 7,
        "float": 2.5,
        "str": "keep",
    }

    assert redfish._normalize_redfish_data(data) == {
        "dict": '{"k": "v"}',
        "list": "[1, 2]",
        "true": "true",
        "false": "false",
        "int": "7",
        "float": "2.5",
        "str": "keep",
    }


# ---------------------------------------------------------------------------
# get_resources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resource_type, target",
    [
        pytest.param("EthernetInterfaces", "_get_ethernet_interfaces", id="ethernet"),
        pytest.param("NetworkAdapters", "_get_network_adapters", id="adapters"),
        pytest.param(
            "NetworkDeviceFunctions",
            "_get_network_device_functions",
            id="device-functions",
        ),
    ],
)
def test_get_resources_delegates_to_matching_helper(resource_type, target):
    with patch.multiple(
        redfish,
        _get_ethernet_interfaces=DEFAULT,
        _get_network_adapters=DEFAULT,
        _get_network_device_functions=DEFAULT,
    ) as helpers:
        helpers[target].return_value = ["sentinel"]
        result = redfish.get_resources("node-1", resource_type)

    assert result == ["sentinel"]
    helpers[target].assert_called_once_with("node-1")
    for name, helper in helpers.items():
        if name != target:
            helper.assert_not_called()


def test_get_resources_unknown_type_returns_empty_and_warns(loguru_logs):
    with patch.multiple(
        redfish,
        _get_ethernet_interfaces=DEFAULT,
        _get_network_adapters=DEFAULT,
        _get_network_device_functions=DEFAULT,
    ) as helpers:
        result = redfish.get_resources("node-1", "Bogus")

    assert result == []
    assert _has_log(loguru_logs, "WARNING", "Resource type Bogus not supported")
    for helper in helpers.values():
        helper.assert_not_called()


# ---------------------------------------------------------------------------
# _get_ethernet_interfaces
# ---------------------------------------------------------------------------


def test_get_ethernet_interfaces_no_connection_returns_empty(loguru_logs):
    with _patch_connection(None):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Could not establish Redfish connection")


def test_get_ethernet_interfaces_top_level_exception_returns_empty(loguru_logs):
    with patch.object(
        redfish, "get_redfish_connection", side_effect=RuntimeError("boom")
    ):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Error retrieving EthernetInterfaces")


def test_get_ethernet_interfaces_system_without_attribute_yields_nothing(loguru_logs):
    system = MagicMock()
    system.identity = "1"
    del system.ethernet_interfaces
    conn = _conn_with_systems([system])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == []
    assert _no_problem_logs(loguru_logs)


def test_get_ethernet_interfaces_none_attribute_yields_nothing(loguru_logs):
    system = MagicMock()
    system.identity = "1"
    system.ethernet_interfaces = None
    conn = _conn_with_systems([system])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == []
    assert _no_problem_logs(loguru_logs)


def test_get_ethernet_interfaces_collects_from_all_systems():
    system1 = _make_system(
        [
            _make_interface(
                identity="1",
                name="eth0",
                mac_address="aa:bb:cc:00:00:01",
                speed_mbps=25000,
            ),
            _make_interface(identity="2", name="eth1", mac_address="aa:bb:cc:00:00:02"),
        ],
        identity="System.1",
    )
    system2 = _make_system(
        [
            _make_interface(identity="1", name="eth0", mac_address="aa:bb:cc:00:00:03"),
            _make_interface(identity="2", name="eth1", interface_enabled=False),
        ],
        identity="System.2",
    )
    conn = _conn_with_systems([system1, system2])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == [
        {
            "id": "1",
            "name": "eth0",
            "mac_address": "aa:bb:cc:00:00:01",
            "speed_mbps": "25000",
        },
        {"id": "2", "name": "eth1", "mac_address": "aa:bb:cc:00:00:02"},
        {"id": "1", "name": "eth0", "mac_address": "aa:bb:cc:00:00:03"},
        {"id": "2", "name": "eth1", "interface_enabled": "false"},
    ]


def test_get_ethernet_interfaces_exposes_all_optional_attributes():
    iface = _make_interface(
        identity="1",
        name="eth0",
        description="Onboard NIC",
        mac_address="aa:bb:cc:00:00:01",
        permanent_mac_address="aa:bb:cc:00:00:00",
        speed_mbps=25000,
        mtu_size=9000,
        link_status="LinkUp",
        interface_enabled=True,
    )
    conn = _conn_with_systems([_make_system([iface])])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == [
        {
            "id": "1",
            "name": "eth0",
            "description": "Onboard NIC",
            "mac_address": "aa:bb:cc:00:00:01",
            "permanent_mac_address": "aa:bb:cc:00:00:00",
            "speed_mbps": "25000",
            "mtu_size": "9000",
            "link_status": "LinkUp",
            "interface_enabled": "true",
        }
    ]


def test_get_ethernet_interfaces_drops_none_mac_address():
    iface = _make_interface(identity="1", name="eth0", mac_address=None)
    conn = _conn_with_systems([_make_system([iface])])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == [{"id": "1", "name": "eth0"}]
    assert "mac_address" not in result[0]


def test_get_ethernet_interfaces_skips_interface_that_raises(loguru_logs):
    good = _make_interface(identity="1", name="eth0")
    bad = _RaisesOn("bad", trigger="speed_mbps")
    conn = _conn_with_systems([_make_system([good, bad])])

    with _patch_connection(conn):
        result = redfish._get_ethernet_interfaces("node-1")

    assert result == [{"id": "1", "name": "eth0"}]
    assert _has_log(loguru_logs, "WARNING", "Error processing EthernetInterface bad")


# ---------------------------------------------------------------------------
# _get_network_adapters
# ---------------------------------------------------------------------------


def test_get_network_adapters_no_connection_returns_empty(loguru_logs):
    with _patch_connection(None):
        result = redfish._get_network_adapters("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Could not establish Redfish connection")


def test_get_network_adapters_top_level_exception_returns_empty(loguru_logs):
    with patch.object(
        redfish, "get_redfish_connection", side_effect=RuntimeError("boom")
    ):
        result = redfish._get_network_adapters("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Error retrieving NetworkAdapters")


def test_get_network_adapters_chassis_without_attribute_yields_nothing(loguru_logs):
    chassis = MagicMock()
    chassis.identity = "1"
    del chassis.network_adapters
    conn = _conn_with_chassis([chassis])

    with _patch_connection(conn):
        result = redfish._get_network_adapters("node-1")

    assert result == []
    assert _no_problem_logs(loguru_logs)


def test_get_network_adapters_returns_normalized_entries():
    adapter1 = _make_adapter(
        identity="1",
        name="NIC.Slot.1",
        description="Slot 1",
        manufacturer="Intel",
        model="X710",
        part_number="PN-1",
        serial_number="SN-1",
        firmware_version="1.0.0",
    )
    adapter2 = _make_adapter(identity="2", name="NIC.Slot.2", manufacturer="Mellanox")
    conn = _conn_with_chassis([_make_chassis([adapter1, adapter2])])

    with _patch_connection(conn):
        result = redfish._get_network_adapters("node-1")

    assert result == [
        {
            "id": "1",
            "name": "NIC.Slot.1",
            "description": "Slot 1",
            "manufacturer": "Intel",
            "model": "X710",
            "part_number": "PN-1",
            "serial_number": "SN-1",
            "firmware_version": "1.0.0",
        },
        {"id": "2", "name": "NIC.Slot.2", "manufacturer": "Mellanox"},
    ]


def test_get_network_adapters_skips_adapter_that_raises(loguru_logs):
    good = _make_adapter(identity="1", name="NIC.Slot.1")
    bad = _RaisesOn("bad", trigger="model")
    conn = _conn_with_chassis([_make_chassis([good, bad])])

    with _patch_connection(conn):
        result = redfish._get_network_adapters("node-1")

    assert result == [{"id": "1", "name": "NIC.Slot.1"}]
    assert _has_log(loguru_logs, "WARNING", "Error processing NetworkAdapter bad")


# ---------------------------------------------------------------------------
# _get_network_device_functions
# ---------------------------------------------------------------------------


def test_get_network_device_functions_no_connection_returns_empty(loguru_logs):
    with _patch_connection(None):
        result = redfish._get_network_device_functions("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Could not establish Redfish connection")


def test_get_network_device_functions_top_level_exception_returns_empty(loguru_logs):
    with patch.object(
        redfish, "get_redfish_connection", side_effect=RuntimeError("boom")
    ):
        result = redfish._get_network_device_functions("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Error retrieving NetworkDeviceFunctions")


def test_get_network_device_functions_adapter_without_device_functions_continues(
    loguru_logs,
):
    bad_adapter = MagicMock()
    bad_adapter.identity = "bad-adapter"
    bad_adapter.name = "Bad"
    del bad_adapter.network_device_functions

    good_adapter = _make_devfunc_adapter(
        [_make_device_func(identity="df-1", name="Function 1")],
        identity="good-adapter",
        name="Good",
    )
    conn = _conn_with_chassis([_make_chassis([bad_adapter, good_adapter])])

    with _patch_connection(conn):
        result = redfish._get_network_device_functions("node-1")

    assert _has_log(
        loguru_logs, "WARNING", "Error processing NetworkAdapter bad-adapter"
    )
    assert [entry["id"] for entry in result] == ["df-1"]
    assert result[0]["adapter_id"] == "good-adapter"


def test_get_network_device_functions_skips_device_function_that_raises(loguru_logs):
    good = _make_device_func(identity="df-1", name="Function 1")
    bad = _RaisesOn("df-bad", trigger="name")
    adapter = _make_devfunc_adapter(
        [good, bad], identity="adapter-1", name="NIC.Slot.1"
    )
    conn = _conn_with_chassis([_make_chassis([adapter])])

    with _patch_connection(conn):
        result = redfish._get_network_device_functions("node-1")

    assert [entry["id"] for entry in result] == ["df-1"]
    assert _has_log(
        loguru_logs, "WARNING", "Error processing NetworkDeviceFunction df-bad"
    )


def test_get_network_device_functions_extracts_mac_from_ethernet():
    device_func = _make_device_func(
        identity="df-1",
        name="Function 1",
        device_enabled=True,
        ethernet_enabled=True,
        ethernet=_make_ethernet(
            mac_address="aa:bb:cc:dd:ee:ff",
            permanent_mac_address="11:22:33:44:55:66",
        ),
    )
    adapter = _make_devfunc_adapter(
        [device_func], identity="adapter-1", name="NIC.Slot.1"
    )
    conn = _conn_with_chassis([_make_chassis([adapter])])

    with _patch_connection(conn):
        result = redfish._get_network_device_functions("node-1")

    assert result == [
        {
            "id": "df-1",
            "name": "Function 1",
            "device_enabled": "true",
            "ethernet_enabled": "true",
            "mac_address": "aa:bb:cc:dd:ee:ff",
            "permanent_mac_address": "11:22:33:44:55:66",
            "adapter_id": "adapter-1",
            "adapter_name": "NIC.Slot.1",
        }
    ]


def test_get_network_device_functions_without_ethernet_strips_macs():
    device_func = _make_device_func(identity="df-1", name="Function 1")
    adapter = _make_devfunc_adapter(
        [device_func], identity="adapter-1", name="NIC.Slot.1"
    )
    conn = _conn_with_chassis([_make_chassis([adapter])])

    with _patch_connection(conn):
        result = redfish._get_network_device_functions("node-1")

    assert result == [
        {
            "id": "df-1",
            "name": "Function 1",
            "adapter_id": "adapter-1",
            "adapter_name": "NIC.Slot.1",
        }
    ]
    assert "mac_address" not in result[0]
    assert "permanent_mac_address" not in result[0]
