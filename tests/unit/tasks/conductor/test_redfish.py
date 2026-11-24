# SPDX-License-Identifier: Apache-2.0

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import DEFAULT, MagicMock, patch

import pytest
from sushy import exceptions as sushy_exceptions

from osism.tasks import conductor
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


def _utc(hour, minute, second):
    return datetime(2026, 11, 24, hour, minute, second, tzinfo=timezone.utc)


def _make_manager(identity="1", datetime_value=None, local_offset=None):
    manager = MagicMock()
    manager.identity = identity
    manager.datetime = datetime_value
    manager.datetimelocaloffset = local_offset
    return manager


def _conn_with_managers(members):
    """Return a connection whose manager collection holds ``members``.

    ``members`` maps each identity to the manager ``get_member`` returns for
    it, or to the exception ``get_member`` raises for it.
    """
    conn = MagicMock()
    collection = conn.get_manager_collection.return_value
    collection.members_identities = tuple(members)

    def get_member(identity):
        member = members[identity]
        if isinstance(member, Exception):
            raise member
        return member

    collection.get_member.side_effect = get_member
    return conn


def _patch_utcnow(*instants):
    """Patch ``_utcnow`` to return ``instants`` one call after another."""
    return patch.object(redfish, "_utcnow", side_effect=list(instants))


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


# ---------------------------------------------------------------------------
# _parse_redfish_datetime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "2026-11-24T10:15:32Z",
        "2026-11-24T10:15:32+00:00",
        "2026-11-24T11:15:32+01:00",
    ],
)
def test_parse_redfish_datetime_aware_value(value):
    parsed = redfish._parse_redfish_datetime(value)

    assert parsed.tzinfo is not None
    assert parsed == _utc(10, 15, 32)


@pytest.mark.parametrize(
    "local_offset, expected",
    [
        ("+02:00", timedelta(hours=2)),
        ("-05:30", -timedelta(hours=5, minutes=30)),
    ],
)
def test_parse_redfish_datetime_naive_value_uses_local_offset(local_offset, expected):
    parsed = redfish._parse_redfish_datetime("2026-11-24T10:15:32", local_offset)

    assert parsed.utcoffset() == expected
    assert parsed.replace(tzinfo=None) == datetime(2026, 11, 24, 10, 15, 32)


def test_parse_redfish_datetime_embedded_offset_wins_over_local_offset():
    parsed = redfish._parse_redfish_datetime("2026-11-24T10:15:32+00:00", "+02:00")

    assert parsed.utcoffset() == timedelta(0)
    assert parsed == _utc(10, 15, 32)


@pytest.mark.parametrize("value", [None, "", "not-a-date", 12345])
def test_parse_redfish_datetime_invalid_value_returns_none(value):
    assert redfish._parse_redfish_datetime(value) is None


@pytest.mark.parametrize("local_offset", [None, "", "UTC", "+99:00"])
def test_parse_redfish_datetime_naive_value_without_usable_offset_returns_none(
    local_offset,
):
    assert redfish._parse_redfish_datetime("2026-11-24T10:15:32", local_offset) is None


# ---------------------------------------------------------------------------
# get_clock
# ---------------------------------------------------------------------------


def test_get_clock_measures_offset_against_request_midpoint(loguru_logs):
    manager = _make_manager("1", "2026-11-24T10:15:32+00:00", "+00:00")
    conn = _conn_with_managers({"/redfish/v1/Managers/1": manager})

    with _patch_connection(conn), _patch_utcnow(_utc(10, 15, 30), _utc(10, 15, 32)):
        result = redfish.get_clock("node-1")

    assert result == [
        {
            "manager_id": "1",
            "datetime": "2026-11-24T10:15:32+00:00",
            "datetime_local_offset": "+00:00",
            "conductor_datetime": "2026-11-24T10:15:31.000+00:00",
            "offset_seconds": 1.0,
            "error": None,
        }
    ]
    assert _no_problem_logs(loguru_logs)
    assert _has_log(loguru_logs, "INFO", "Retrieved 1 manager clocks from node-1")


def test_get_clock_controller_behind_gives_negative_offset():
    manager = _make_manager("1", "2026-11-24T10:15:29+00:00", "+00:00")
    conn = _conn_with_managers({"/redfish/v1/Managers/1": manager})

    with _patch_connection(conn), _patch_utcnow(_utc(10, 15, 30), _utc(10, 15, 32)):
        result = redfish.get_clock("node-1")

    assert result[0]["offset_seconds"] == -2.0


def test_get_clock_renders_conductor_time_in_redfish_utc_offset():
    manager = _make_manager("1", "2026-11-24T11:15:32+01:00", "+01:00")
    conn = _conn_with_managers({"/redfish/v1/Managers/1": manager})

    with _patch_connection(conn), _patch_utcnow(_utc(10, 15, 30), _utc(10, 15, 32)):
        result = redfish.get_clock("node-1")

    assert result[0]["conductor_datetime"] == "2026-11-24T11:15:31.000+01:00"
    assert result[0]["offset_seconds"] == 1.0


def test_get_clock_reads_managers_one_by_one_in_collection_order():
    conn = _conn_with_managers(
        {
            "/redfish/v1/Managers/1": _make_manager("1", "2026-11-24T10:15:32Z"),
            "/redfish/v1/Managers/2": _make_manager("2", "2026-11-24T10:15:35Z"),
        }
    )
    clock = _patch_utcnow(
        _utc(10, 15, 30), _utc(10, 15, 32), _utc(10, 15, 33), _utc(10, 15, 35)
    )

    with _patch_connection(conn), clock as utcnow:
        result = redfish.get_clock("node-1")

    assert [row["manager_id"] for row in result] == ["1", "2"]
    assert [row["offset_seconds"] for row in result] == [1.0, 1.0]
    assert utcnow.call_count == 4
    conn.get_manager_collection.return_value.get_members.assert_not_called()


def test_get_clock_result_is_json_serializable():
    conn = _conn_with_managers(
        {
            "/redfish/v1/Managers/1": _make_manager("1", "2026-11-24T10:15:32Z"),
            "/redfish/v1/Managers/2": _make_manager("2"),
        }
    )
    clock = _patch_utcnow(
        _utc(10, 15, 30), _utc(10, 15, 32), _utc(10, 15, 33), _utc(10, 15, 35)
    )

    with _patch_connection(conn), clock:
        result = redfish.get_clock("node-1")

    assert json.loads(json.dumps(result)) == result


def test_get_clock_no_connection_returns_empty(loguru_logs):
    with _patch_connection(None):
        result = redfish.get_clock("node-1")

    assert result == []
    assert _has_log(
        loguru_logs, "ERROR", "Could not establish Redfish connection to node-1"
    )


def test_get_clock_without_managers_returns_empty(loguru_logs):
    conn = _conn_with_managers({})

    with _patch_connection(conn):
        result = redfish.get_clock("node-1")

    assert result == []
    assert _no_problem_logs(loguru_logs)


def test_get_clock_without_manager_collection_returns_empty(loguru_logs):
    conn = MagicMock()
    conn.get_manager_collection.side_effect = sushy_exceptions.MissingAttributeError(
        attribute="Managers/@odata.id", resource="/redfish/v1/"
    )

    with _patch_connection(conn):
        result = redfish.get_clock("node-1")

    assert result == []
    assert _has_log(loguru_logs, "ERROR", "Error retrieving manager clocks from node-1")


def test_get_clock_reports_manager_that_cannot_be_read(loguru_logs):
    error = sushy_exceptions.ConnectionError(
        url="https://bmc.example.com", error="timed out"
    )
    conn = _conn_with_managers(
        {
            "/redfish/v1/Managers/1": error,
            "/redfish/v1/Managers/2": _make_manager("2", "2026-11-24T10:15:32Z"),
        }
    )
    # The failed read takes only the timestamp before its request.
    clock = _patch_utcnow(_utc(10, 15, 29), _utc(10, 15, 30), _utc(10, 15, 32))

    with _patch_connection(conn), clock:
        result = redfish.get_clock("node-1")

    assert result[0] == {
        "manager_id": "/redfish/v1/Managers/1",
        "datetime": None,
        "datetime_local_offset": None,
        "conductor_datetime": None,
        "offset_seconds": None,
        "error": str(error),
    }
    assert result[1]["manager_id"] == "2"
    assert result[1]["offset_seconds"] == 1.0
    assert result[1]["error"] is None
    assert json.loads(json.dumps(result)) == result
    assert _has_log(loguru_logs, "WARNING", "Error reading manager")


def test_get_clock_keeps_manager_without_datetime(loguru_logs):
    conn = _conn_with_managers({"/redfish/v1/Managers/1": _make_manager("1")})

    with _patch_connection(conn), _patch_utcnow(_utc(10, 15, 30), _utc(10, 15, 32)):
        result = redfish.get_clock("node-1")

    assert len(result) == 1
    assert result[0]["datetime"] is None
    assert result[0]["offset_seconds"] is None
    assert result[0]["conductor_datetime"].endswith("+00:00")
    assert result[0]["error"] is None
    assert _has_log(loguru_logs, "WARNING", "does not report DateTime")


@pytest.mark.parametrize(
    "value, local_offset",
    [
        pytest.param("not-a-date", "+00:00", id="unparseable"),
        pytest.param("2026-11-24T10:15:32", None, id="naive-without-offset"),
    ],
)
def test_get_clock_keeps_manager_with_incomparable_datetime(
    loguru_logs, value, local_offset
):
    manager = _make_manager("1", value, local_offset)
    conn = _conn_with_managers({"/redfish/v1/Managers/1": manager})

    with _patch_connection(conn), _patch_utcnow(_utc(10, 15, 30), _utc(10, 15, 32)):
        result = redfish.get_clock("node-1")

    assert len(result) == 1
    assert result[0]["datetime"] == value
    assert result[0]["offset_seconds"] is None
    assert result[0]["error"] is None
    assert _has_log(
        loguru_logs, "WARNING", "cannot be compared with the conductor clock"
    )


def test_get_clock_ignores_ssl_errors():
    with _patch_connection(_conn_with_managers({})) as connect:
        redfish.get_clock("node-1")

    connect.assert_called_once_with("node-1", ignore_ssl_errors=True)


# ---------------------------------------------------------------------------
# get_redfish_clock task
# ---------------------------------------------------------------------------


def test_get_redfish_clock_task_delegates_to_get_clock():
    with patch.object(
        conductor, "_get_redfish_clock", return_value=["sentinel"]
    ) as get_clock:
        result = conductor.get_redfish_clock.__wrapped__("node-1")

    assert result == ["sentinel"]
    get_clock.assert_called_once_with("node-1")
    assert "get_redfish_clock" in conductor.__all__
