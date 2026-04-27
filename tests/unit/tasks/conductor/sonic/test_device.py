# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.device import (
    get_device_hostname,
    get_device_mac_address,
    get_device_platform,
)

# ---------------------------------------------------------------------------
# get_device_platform
# ---------------------------------------------------------------------------


def test_get_device_platform_uses_custom_field_when_set():
    device = SimpleNamespace(
        custom_fields={"sonic_parameters": {"platform": "x86_64-custom-r0"}}
    )

    assert get_device_platform(device, "Accton-AS7326-56X-O-EC-A") == "x86_64-custom-r0"


def test_get_device_platform_generates_when_sonic_parameters_empty():
    device = SimpleNamespace(custom_fields={"sonic_parameters": {}})

    assert (
        get_device_platform(device, "Accton-AS7326-56X-O-EC-A")
        == "x86_64-accton_as7326_56x_o_ec_a-r0"
    )


def test_get_device_platform_generates_when_sonic_parameters_missing():
    device = SimpleNamespace(custom_fields={})

    assert (
        get_device_platform(device, "Accton-AS7326-56X-O-EC-A")
        == "x86_64-accton_as7326_56x_o_ec_a-r0"
    )


def test_get_device_platform_generates_when_custom_fields_attr_missing():
    # No custom_fields attribute at all — defensive hasattr check must hold.
    device = SimpleNamespace()

    assert (
        get_device_platform(device, "Accton-AS7326-56X-O-EC-A")
        == "x86_64-accton_as7326_56x_o_ec_a-r0"
    )


def test_get_device_platform_generates_when_sonic_parameters_is_none():
    # The truthiness check on sonic_parameters guards against a None value.
    device = SimpleNamespace(custom_fields={"sonic_parameters": None})

    assert get_device_platform(device, "Foo") == "x86_64-foo-r0"


@pytest.mark.parametrize("falsy", [None, ""])
def test_get_device_platform_falls_back_when_platform_falsy(falsy):
    device = SimpleNamespace(custom_fields={"sonic_parameters": {"platform": falsy}})

    assert (
        get_device_platform(device, "Accton-AS7326-56X-O-EC-A")
        == "x86_64-accton_as7326_56x_o_ec_a-r0"
    )


def test_get_device_platform_hwsku_without_hyphens():
    device = SimpleNamespace(custom_fields={})

    assert get_device_platform(device, "Foo") == "x86_64-foo-r0"


def test_get_device_platform_hwsku_lowercased_and_hyphen_replaced():
    device = SimpleNamespace(custom_fields={})

    # Confirms BOTH transformations are applied: lowercase + hyphen→underscore.
    assert (
        get_device_platform(device, "Mixed-Case-HWSKU") == "x86_64-mixed_case_hwsku-r0"
    )


def test_get_device_platform_hwsku_already_lowercase_unchanged():
    device = SimpleNamespace(custom_fields={})

    assert get_device_platform(device, "already-lower") == "x86_64-already_lower-r0"


def test_get_device_platform_custom_field_takes_precedence_over_hwsku():
    # Even though hwsku could generate a platform, the custom field wins.
    device = SimpleNamespace(
        custom_fields={"sonic_parameters": {"platform": "x86_64-override-r0"}}
    )

    assert get_device_platform(device, "Some-HWSKU") == "x86_64-override-r0"


# ---------------------------------------------------------------------------
# get_device_hostname
# ---------------------------------------------------------------------------


def test_get_device_hostname_uses_inventory_hostname_when_set():
    device = SimpleNamespace(
        name="sw-1", custom_fields={"inventory_hostname": "sw-leaf-01"}
    )

    assert get_device_hostname(device) == "sw-leaf-01"


def test_get_device_hostname_falls_back_when_inventory_hostname_empty():
    device = SimpleNamespace(name="sw-1", custom_fields={"inventory_hostname": ""})

    assert get_device_hostname(device) == "sw-1"


def test_get_device_hostname_falls_back_when_inventory_hostname_none():
    device = SimpleNamespace(name="sw-1", custom_fields={"inventory_hostname": None})

    assert get_device_hostname(device) == "sw-1"


def test_get_device_hostname_falls_back_when_key_missing():
    device = SimpleNamespace(name="sw-1", custom_fields={})

    assert get_device_hostname(device) == "sw-1"


def test_get_device_hostname_falls_back_when_custom_fields_attr_missing():
    device = SimpleNamespace(name="sw-1")

    assert get_device_hostname(device) == "sw-1"


def test_get_device_hostname_returns_device_name_unchanged():
    # The fallback path simply returns device.name as-is, no normalization.
    device = SimpleNamespace(name="Mixed-Case_Name", custom_fields={})

    assert get_device_hostname(device) == "Mixed-Case_Name"


# ---------------------------------------------------------------------------
# get_device_mac_address
# ---------------------------------------------------------------------------


DEFAULT_MAC = "00:00:00:00:00:00"


def _mgmt_iface(mac, name="eth0"):
    return SimpleNamespace(mgmt_only=True, mac_address=mac, name=name)


def _data_iface(mac="aa:aa:aa:aa:aa:aa", name="Ethernet0"):
    return SimpleNamespace(mgmt_only=False, mac_address=mac, name=name)


def _patch_filter(mocker, return_value=None, side_effect=None):
    mock_nb = mocker.patch("osism.tasks.conductor.sonic.device.utils.nb")
    if side_effect is not None:
        mock_nb.dcim.interfaces.filter.side_effect = side_effect
    else:
        mock_nb.dcim.interfaces.filter.return_value = return_value
    return mock_nb


def test_get_device_mac_address_single_mgmt_interface(mocker):
    _patch_filter(mocker, return_value=[_mgmt_iface("aa:bb:cc:dd:ee:ff")])
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == "aa:bb:cc:dd:ee:ff"


def test_get_device_mac_address_skips_non_mgmt_interface(mocker):
    _patch_filter(
        mocker,
        return_value=[
            _data_iface(name="Ethernet0"),
            _mgmt_iface("aa:bb:cc:dd:ee:ff", name="eth0"),
        ],
    )
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == "aa:bb:cc:dd:ee:ff"


@pytest.mark.parametrize("falsy_mac", [None, ""])
def test_get_device_mac_address_falsy_mac_returns_default(mocker, falsy_mac):
    # The inner `if interface.mac_address` guard skips falsy MACs; with no
    # other mgmt interface to fall through to, the default is returned.
    _patch_filter(mocker, return_value=[_mgmt_iface(falsy_mac)])
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == DEFAULT_MAC


def test_get_device_mac_address_no_interfaces_returns_default(mocker):
    _patch_filter(mocker, return_value=[])
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == DEFAULT_MAC


def test_get_device_mac_address_no_mgmt_interfaces_returns_default(mocker):
    _patch_filter(
        mocker,
        return_value=[_data_iface(name="Ethernet0"), _data_iface(name="Ethernet1")],
    )
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == DEFAULT_MAC


def test_get_device_mac_address_filter_raises_returns_default(mocker):
    warning = mocker.patch("osism.tasks.conductor.sonic.device.logger.warning")
    _patch_filter(mocker, side_effect=Exception("netbox down"))
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == DEFAULT_MAC
    warning.assert_called_once()
    message = warning.call_args.args[0]
    assert "sw-1" in message
    assert "netbox down" in message


def test_get_device_mac_address_iteration_raises_returns_default(mocker):
    # An exception raised while iterating must also be caught (the try/except
    # wraps the whole loop, not just the .filter call).
    warning = mocker.patch("osism.tasks.conductor.sonic.device.logger.warning")

    class _Boom:
        def __iter__(self):
            raise RuntimeError("iter boom")

    _patch_filter(mocker, return_value=_Boom())
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == DEFAULT_MAC
    warning.assert_called_once()


def test_get_device_mac_address_returns_first_of_multiple_mgmt(mocker):
    # Loop must break on the first match — second mgmt interface is ignored.
    _patch_filter(
        mocker,
        return_value=[
            _mgmt_iface("11:11:11:11:11:11", name="eth0"),
            _mgmt_iface("22:22:22:22:22:22", name="eth1"),
        ],
    )
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == "11:11:11:11:11:11"


def test_get_device_mac_address_skips_falsy_then_uses_next_mgmt(mocker):
    # First mgmt-only with falsy MAC must NOT terminate the loop — the next
    # mgmt-only with a real MAC should be picked up.
    _patch_filter(
        mocker,
        return_value=[
            _mgmt_iface(None, name="eth0"),
            _mgmt_iface("aa:bb:cc:dd:ee:ff", name="eth1"),
        ],
    )
    device = SimpleNamespace(name="sw-1", id=42)

    assert get_device_mac_address(device) == "aa:bb:cc:dd:ee:ff"


def test_get_device_mac_address_calls_filter_with_device_id(mocker):
    mock_nb = _patch_filter(mocker, return_value=[])
    device = SimpleNamespace(name="sw-1", id=42)

    get_device_mac_address(device)

    mock_nb.dcim.interfaces.filter.assert_called_once_with(device_id=42)


def test_get_device_mac_address_logs_debug_on_match(mocker):
    debug = mocker.patch("osism.tasks.conductor.sonic.device.logger.debug")
    _patch_filter(mocker, return_value=[_mgmt_iface("aa:bb:cc:dd:ee:ff", name="eth0")])
    device = SimpleNamespace(name="sw-1", id=42)

    get_device_mac_address(device)

    debug.assert_called_once()
    message = debug.call_args.args[0]
    assert "aa:bb:cc:dd:ee:ff" in message
    assert "eth0" in message
