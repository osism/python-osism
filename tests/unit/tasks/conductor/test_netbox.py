# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest
import yaml

from osism.tasks.conductor.netbox import (
    get_device_oob_ip,
    get_nb_device_query_list_ironic,
    get_nb_device_query_list_sonic,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


# The two query-list helpers are structurally identical; parametrize over them
# instead of duplicating every test. Each variant carries the setting attribute
# it reads and the function under test.
QUERY_LIST_VARIANTS = [
    pytest.param(
        "NETBOX_FILTER_CONDUCTOR_IRONIC",
        get_nb_device_query_list_ironic,
        id="ironic",
    ),
    pytest.param(
        "NETBOX_FILTER_CONDUCTOR_SONIC",
        get_nb_device_query_list_sonic,
        id="sonic",
    ),
]


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


@pytest.fixture
def patch_filter_setting(mocker):
    """Patch one of the ``NETBOX_FILTER_CONDUCTOR_*`` settings."""

    def _set(setting_name, value):
        mocker.patch(f"osism.tasks.conductor.netbox.settings.{setting_name}", new=value)

    return _set


@pytest.fixture
def patch_location_lookups(mocker):
    location = mocker.patch("osism.tasks.conductor.netbox.netbox.get_location_id")
    rack = mocker.patch("osism.tasks.conductor.netbox.netbox.get_rack_id")
    return SimpleNamespace(get_location_id=location, get_rack_id=rack)


@pytest.fixture
def mock_nb(mocker):
    """Replace ``osism.utils.nb`` (lazy attribute) with a fresh MagicMock."""
    nb = mocker.MagicMock()
    mocker.patch("osism.utils.nb", new=nb, create=True)
    return nb


class _IPRecord:
    """Stand-in for a pynetbox IP record.

    ``ipaddress.ip_interface`` accepts strings, so the function under test
    relies on pynetbox records being stringified to the address. The simple
    ``SimpleNamespace`` shim used elsewhere does not satisfy that contract.
    """

    def __init__(self, address):
        self.address = address

    def __str__(self):
        return self.address


def _make_device(
    name="dev",
    device_id=1,
    oob_ip=None,
):
    return SimpleNamespace(name=name, id=device_id, oob_ip=oob_ip)


def _make_interface(interface_id, mgmt_only=False):
    return SimpleNamespace(id=interface_id, mgmt_only=mgmt_only)


def _make_ip(address):
    return _IPRecord(address)


# ---------------------------------------------------------------------------
# get_nb_device_query_list_{ironic,sonic} – happy paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_simple_filters_pass_through(patch_filter_setting, setting, query_func):
    patch_filter_setting(setting, "- site: dc1\n- tag: ironic\n")

    assert query_func() == [{"site": "dc1"}, {"tag": "ironic"}]


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_all_supported_pass_through_filters_unchanged(
    patch_filter_setting, patch_location_lookups, setting, query_func
):
    patch_filter_setting(
        setting,
        "- site: dc1\n"
        "- region: eu-west\n"
        "- site_group: prod\n"
        "- tag: ironic\n"
        "- status: active\n",
    )

    assert query_func() == [
        {"site": "dc1"},
        {"region": "eu-west"},
        {"site_group": "prod"},
        {"tag": "ironic"},
        {"status": "active"},
    ]
    patch_location_lookups.get_location_id.assert_not_called()
    patch_location_lookups.get_rack_id.assert_not_called()


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_location_resolved_and_renamed(
    patch_filter_setting, patch_location_lookups, setting, query_func
):
    patch_filter_setting(setting, "- location: dc1-room-3\n")
    patch_location_lookups.get_location_id.return_value = 17

    assert query_func() == [{"location_id": 17}]
    patch_location_lookups.get_location_id.assert_called_once_with("dc1-room-3")


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_rack_resolved_and_renamed(
    patch_filter_setting, patch_location_lookups, setting, query_func
):
    patch_filter_setting(setting, "- rack: r42\n")
    patch_location_lookups.get_rack_id.return_value = 99

    assert query_func() == [{"rack_id": 99}]
    patch_location_lookups.get_rack_id.assert_called_once_with("r42")


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_location_and_rack_combined(
    patch_filter_setting, patch_location_lookups, setting, query_func
):
    patch_filter_setting(setting, "- location: room-1\n  rack: r1\n")
    patch_location_lookups.get_location_id.return_value = 5
    patch_location_lookups.get_rack_id.return_value = 11

    assert query_func() == [{"location_id": 5, "rack_id": 11}]


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_empty_list_returns_empty(patch_filter_setting, setting, query_func):
    patch_filter_setting(setting, "[]\n")

    assert query_func() == []


# ---------------------------------------------------------------------------
# get_nb_device_query_list_{ironic,sonic} – error paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_invalid_yaml_raises_yamlerror_and_logs(
    patch_filter_setting, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "foo: [unterminated\n")

    with pytest.raises(yaml.YAMLError):
        query_func()
    assert _has_log(
        loguru_logs,
        "ERROR",
        f"Setting {setting} needs to be an array of mappings",
    )


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_non_list_raises_typeerror_and_logs(
    patch_filter_setting, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "foo: bar\n")

    with pytest.raises(TypeError):
        query_func()
    assert _has_log(
        loguru_logs,
        "ERROR",
        f"Setting {setting} needs to be an array of mappings",
    )


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_string_element_raises_typeerror_and_logs(
    patch_filter_setting, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "- foo\n")

    with pytest.raises(TypeError):
        query_func()
    assert _has_log(
        loguru_logs,
        "ERROR",
        f"Setting {setting} needs to be an array of mappings",
    )


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_unsupported_filter_raises_valueerror_and_logs(
    patch_filter_setting, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "- manufacturer: dell\n")

    with pytest.raises(ValueError):
        query_func()
    assert _has_log(loguru_logs, "ERROR", f"Unknown value in {setting}")


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_location_unresolved_raises_valueerror_and_logs(
    patch_filter_setting, patch_location_lookups, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "- location: missing\n")
    patch_location_lookups.get_location_id.return_value = None

    with pytest.raises(ValueError):
        query_func()
    assert _has_log(loguru_logs, "ERROR", f"Unknown value in {setting}")


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_rack_unresolved_raises_valueerror_and_logs(
    patch_filter_setting, patch_location_lookups, loguru_logs, setting, query_func
):
    patch_filter_setting(setting, "- rack: missing\n")
    patch_location_lookups.get_rack_id.return_value = None

    with pytest.raises(ValueError):
        query_func()
    assert _has_log(loguru_logs, "ERROR", f"Unknown value in {setting}")


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_null_setting_raises_typeerror(patch_filter_setting, setting, query_func):
    """A YAML payload of ``null`` parses to ``None`` (not a list)."""
    patch_filter_setting(setting, "")

    with pytest.raises(TypeError):
        query_func()


@pytest.mark.parametrize("setting,query_func", QUERY_LIST_VARIANTS)
def test_list_with_null_element_raises_typeerror(
    patch_filter_setting, setting, query_func
):
    """A list element that is ``None`` is not a dict."""
    patch_filter_setting(setting, "- null\n")

    with pytest.raises(TypeError):
        query_func()


# ---------------------------------------------------------------------------
# get_device_oob_ip – oob_ip set on device
# ---------------------------------------------------------------------------


def test_oob_ip_uses_oob_field_when_set(mock_nb):
    device = _make_device(oob_ip=_IPRecord("10.0.0.5/24"))

    assert get_device_oob_ip(device) == ("10.0.0.5", 24)
    mock_nb.dcim.interfaces.filter.assert_not_called()
    mock_nb.ipam.ip_addresses.filter.assert_not_called()


def test_oob_ip_falsy_oob_ip_falls_back_to_mgmt(mock_nb):
    """``oob_ip = None`` → fall back to mgmt-only interface lookup."""
    device = _make_device(device_id=7, oob_ip=None)
    iface = _make_interface(interface_id=42, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = [_make_ip("10.0.0.6/24")]

    assert get_device_oob_ip(device) == ("10.0.0.6", 24)
    mock_nb.dcim.interfaces.filter.assert_called_once_with(device_id=7)
    mock_nb.ipam.ip_addresses.filter.assert_called_once_with(assigned_object_id=42)


def test_oob_ip_skips_non_mgmt_interfaces(mock_nb):
    device = _make_device(device_id=8)
    non_mgmt = _make_interface(interface_id=1, mgmt_only=False)
    mgmt = _make_interface(interface_id=2, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [non_mgmt, mgmt]
    mock_nb.ipam.ip_addresses.filter.return_value = [_make_ip("192.168.0.10/16")]

    assert get_device_oob_ip(device) == ("192.168.0.10", 16)
    # Only the mgmt-only interface should have triggered an IP lookup.
    mock_nb.ipam.ip_addresses.filter.assert_called_once_with(assigned_object_id=2)


def test_oob_ip_first_mgmt_without_ips_falls_through_to_second(mock_nb):
    device = _make_device(device_id=9)
    first_mgmt = _make_interface(interface_id=11, mgmt_only=True)
    second_mgmt = _make_interface(interface_id=22, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [first_mgmt, second_mgmt]
    mock_nb.ipam.ip_addresses.filter.side_effect = [
        [],
        [_make_ip("10.0.0.7/24")],
    ]

    assert get_device_oob_ip(device) == ("10.0.0.7", 24)
    assert mock_nb.ipam.ip_addresses.filter.call_count == 2


def test_oob_ip_no_mgmt_interfaces_returns_none(mock_nb):
    device = _make_device(device_id=1)
    mock_nb.dcim.interfaces.filter.return_value = [
        _make_interface(interface_id=1, mgmt_only=False),
        _make_interface(interface_id=2, mgmt_only=False),
    ]

    assert get_device_oob_ip(device) is None
    mock_nb.ipam.ip_addresses.filter.assert_not_called()


def test_oob_ip_empty_interfaces_returns_none(mock_nb):
    device = _make_device(device_id=1)
    mock_nb.dcim.interfaces.filter.return_value = []

    assert get_device_oob_ip(device) is None
    mock_nb.ipam.ip_addresses.filter.assert_not_called()


def test_oob_ip_mgmt_interface_without_ips_returns_none(mock_nb):
    device = _make_device(device_id=1)
    iface = _make_interface(interface_id=42, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = []

    assert get_device_oob_ip(device) is None


def test_oob_ip_ip_with_blank_address_skipped(mock_nb):
    device = _make_device(device_id=1)
    iface = _make_interface(interface_id=42, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = [_make_ip("")]

    assert get_device_oob_ip(device) is None


def test_oob_ip_ipv6_returns_address_and_prefix(mock_nb):
    device = _make_device(oob_ip=_IPRecord("2001:db8::1/64"))

    assert get_device_oob_ip(device) == ("2001:db8::1", 64)


def test_oob_ip_malformed_oob_returns_none_and_warns(mock_nb, loguru_logs):
    device = _make_device(name="dev-malformed", oob_ip=_IPRecord("not-an-ip"))

    assert get_device_oob_ip(device) is None
    assert _has_log(
        loguru_logs,
        "WARNING",
        "Could not get OOB IP for device dev-malformed",
    )


def test_oob_ip_interfaces_filter_raises_returns_none_and_warns(mock_nb, loguru_logs):
    device = _make_device(name="dev-down", device_id=1, oob_ip=None)
    mock_nb.dcim.interfaces.filter.side_effect = RuntimeError("netbox down")

    assert get_device_oob_ip(device) is None
    assert _has_log(
        loguru_logs,
        "WARNING",
        "Could not get OOB IP for device dev-down",
    )


def test_oob_ip_ip_addresses_filter_raises_returns_none_and_warns(mock_nb, loguru_logs):
    device = _make_device(name="dev-ipam", device_id=1, oob_ip=None)
    iface = _make_interface(interface_id=42, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.side_effect = RuntimeError("ipam down")

    assert get_device_oob_ip(device) is None
    assert _has_log(
        loguru_logs,
        "WARNING",
        "Could not get OOB IP for device dev-ipam",
    )


def test_oob_ip_uses_keyword_arguments_for_netbox_filters(mock_nb):
    device = _make_device(device_id=123, oob_ip=None)
    iface = _make_interface(interface_id=456, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = [_make_ip("10.0.0.8/24")]

    get_device_oob_ip(device)

    interfaces_call = mock_nb.dcim.interfaces.filter.call_args
    assert interfaces_call.args == ()
    assert interfaces_call.kwargs == {"device_id": 123}

    ip_call = mock_nb.ipam.ip_addresses.filter.call_args
    assert ip_call.args == ()
    assert ip_call.kwargs == {"assigned_object_id": 456}


def test_oob_ip_device_without_oob_ip_attribute_falls_back(mock_nb):
    """``hasattr(device, 'oob_ip')`` is False → mgmt-interface path runs."""
    device = SimpleNamespace(name="dev-no-oob-attr", id=5)
    iface = _make_interface(interface_id=1, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = [_make_ip("10.0.0.9/24")]

    assert get_device_oob_ip(device) == ("10.0.0.9", 24)


def test_oob_ip_first_assigned_address_wins(mock_nb):
    device = _make_device(device_id=1, oob_ip=None)
    iface = _make_interface(interface_id=42, mgmt_only=True)
    mock_nb.dcim.interfaces.filter.return_value = [iface]
    mock_nb.ipam.ip_addresses.filter.return_value = [
        _make_ip("10.0.0.10/24"),
        _make_ip("10.0.0.11/24"),
    ]

    assert get_device_oob_ip(device) == ("10.0.0.10", 24)
