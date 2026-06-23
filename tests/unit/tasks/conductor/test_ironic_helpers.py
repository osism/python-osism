# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the pure helpers in ``osism/tasks/conductor/ironic.py``.

These cover everything that can be exercised without the full sync
orchestration: the hostname/AS derivation, the metalbox primary-IP lookups,
the recursive Jinja2 renderer, the ``_prepare_node_attributes`` builder and the
display prettifier.

Patch sites follow the existing conventions in this test tree:

* ``_get_metalbox_primary_ip4`` and ``_get_metalbox_primary_ip4_fallback`` do
  ``from osism import utils`` inside the function and then use ``utils.nb``.
  That resolves to ``osism.utils.nb``, so the NetBox client is replaced via
  ``mocker.patch("osism.utils.nb", ...)`` (same approach as ``test_netbox`` and
  the sonic tests).
* The remaining collaborators are imported at module level into ``ironic.py``
  and are patched at ``osism.tasks.conductor.ironic.<name>``.
"""

import json
from types import SimpleNamespace

import pytest

from osism.tasks.conductor.ironic import (
    _derive_as_from_hostname_yrzn,
    _get_metalbox_primary_ip4,
    _get_metalbox_primary_ip4_fallback,
    _prepare_node_attributes,
    _prettify_for_display,
    _render_templates,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _device(name="server-1", custom_fields=None, config_context=None):
    """Build a NetBox-device stand-in as suggested by the issue."""
    return SimpleNamespace(
        name=name,
        custom_fields={} if custom_fields is None else custom_fields,
        config_context={} if config_context is None else config_context,
    )


@pytest.fixture
def mock_nb(mocker):
    """Replace ``osism.utils.nb`` (lazy attribute) with a fresh MagicMock."""
    nb = mocker.MagicMock()
    mocker.patch("osism.utils.nb", new=nb, create=True)
    return nb


@pytest.fixture
def patch_ironic_setting(mocker):
    """Patch ``settings.NETBOX_FILTER_CONDUCTOR_IRONIC`` as seen by ironic.py."""

    def _set(value):
        mocker.patch(
            "osism.tasks.conductor.ironic.settings.NETBOX_FILTER_CONDUCTOR_IRONIC",
            new=value,
        )

    return _set


# ---------------------------------------------------------------------------
# _derive_as_from_hostname_yrzn
# ---------------------------------------------------------------------------


def test_derive_as_storage_example():
    # stor -> type 5; server "60" and rack "59" already two digits.
    assert _derive_as_from_hostname_yrzn("stor-nw-22-60-59-6") == "4200155960"


def test_derive_as_non_storage_pads_single_digits():
    # comp -> type 4; server "3" -> "03", rack "7" -> "07".
    # 42 001 4 <rack=07> <server=03> -> 4200140703
    assert _derive_as_from_hostname_yrzn("comp-nw-22-3-7-1") == "4200140703"


def test_derive_as_fewer_than_five_parts_returns_none():
    assert _derive_as_from_hostname_yrzn("a-b-c-d") is None


def test_derive_as_non_stor_type_is_four():
    # Any first segment other than "stor" yields the type digit 4.
    result = _derive_as_from_hostname_yrzn("net-nw-22-3-7-1")
    assert result == "4200140703"
    assert result[5] == "4"


def test_derive_as_two_digit_values_not_repadded():
    # server "12" and rack "34" already two digits -> no extra padding.
    assert _derive_as_from_hostname_yrzn("comp-nw-22-12-34-1") == "4200143412"


def test_derive_as_single_digit_padded_with_leading_zero():
    result = _derive_as_from_hostname_yrzn("comp-nw-22-3-7-1")
    assert result.endswith("0703")  # rack "07", server "03"


# ---------------------------------------------------------------------------
# _get_metalbox_primary_ip4_fallback
# ---------------------------------------------------------------------------


def test_fallback_invalid_yaml_returns_none(mock_nb, patch_ironic_setting):
    patch_ironic_setting("foo: [unterminated\n")

    assert _get_metalbox_primary_ip4_fallback() is None
    mock_nb.dcim.devices.filter.assert_not_called()


def test_fallback_non_list_setting_returns_none(mock_nb, patch_ironic_setting):
    patch_ironic_setting("foo: bar\n")

    assert _get_metalbox_primary_ip4_fallback() is None
    mock_nb.dcim.devices.filter.assert_not_called()


def test_fallback_non_dict_element_is_skipped(
    mock_nb, patch_ironic_setting, loguru_logs
):
    patch_ironic_setting("- just-a-string\n")

    assert _get_metalbox_primary_ip4_fallback() is None
    mock_nb.dcim.devices.filter.assert_not_called()
    assert _has_log(
        loguru_logs, "WARNING", "No metalbox found via fallback filter either"
    )


def test_fallback_strips_tag_and_adds_role(mock_nb, patch_ironic_setting):
    patch_ironic_setting("[{'status': 'active', 'tag': ['managed-by-ironic']}]")
    mock_nb.dcim.devices.filter.return_value = [
        SimpleNamespace(primary_ip4="10.0.0.5/24")
    ]

    assert _get_metalbox_primary_ip4_fallback() == "10.0.0.5"
    mock_nb.dcim.devices.filter.assert_called_once_with(
        status="active", role="metalbox"
    )


def test_fallback_returns_second_metalbox_ip_when_first_has_none(
    mock_nb, patch_ironic_setting
):
    patch_ironic_setting("[{'status': 'active'}]")
    mock_nb.dcim.devices.filter.return_value = [
        SimpleNamespace(primary_ip4=None),
        SimpleNamespace(primary_ip4="10.0.0.6/24"),
    ]

    assert _get_metalbox_primary_ip4_fallback() == "10.0.0.6"


def test_fallback_all_metalboxes_without_ip_returns_none_and_warns(
    mock_nb, patch_ironic_setting, loguru_logs
):
    patch_ironic_setting("[{'status': 'active'}]")
    mock_nb.dcim.devices.filter.return_value = [
        SimpleNamespace(primary_ip4=None),
        SimpleNamespace(primary_ip4=None),
    ]

    assert _get_metalbox_primary_ip4_fallback() is None
    assert _has_log(
        loguru_logs, "WARNING", "No metalbox found via fallback filter either"
    )


def test_fallback_no_metalboxes_returns_none_and_warns(
    mock_nb, patch_ironic_setting, loguru_logs
):
    patch_ironic_setting("[{'status': 'active'}]")
    mock_nb.dcim.devices.filter.return_value = []

    assert _get_metalbox_primary_ip4_fallback() is None
    assert _has_log(
        loguru_logs, "WARNING", "No metalbox found via fallback filter either"
    )


# ---------------------------------------------------------------------------
# _get_metalbox_primary_ip4
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_oob(mocker):
    return mocker.patch("osism.tasks.conductor.ironic.get_device_oob_ip")


@pytest.fixture
def patch_fallback(mocker):
    return mocker.patch(
        "osism.tasks.conductor.ironic._get_metalbox_primary_ip4_fallback"
    )


def _wire_metalboxes(nb, metalboxes, interfaces_by_box, ips_by_iface):
    """Configure the three chained ``nb`` filter calls used for subnet lookup."""
    nb.dcim.devices.filter.return_value = metalboxes
    nb.dcim.interfaces.filter.side_effect = lambda device_id: interfaces_by_box.get(
        device_id, []
    )
    nb.ipam.ip_addresses.filter.side_effect = (
        lambda assigned_object_id: ips_by_iface.get(assigned_object_id, [])
    )


def test_metalbox_no_oob_returns_none_without_fallback(
    mock_nb, patch_oob, patch_fallback
):
    patch_oob.return_value = None

    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) is None
    patch_fallback.assert_not_called()


def test_metalbox_returns_primary_ip_for_matching_subnet(
    mock_nb, patch_oob, patch_fallback
):
    patch_oob.return_value = ("10.0.0.5", 24)
    metalbox = SimpleNamespace(id=1, primary_ip4="10.0.0.1/24")
    _wire_metalboxes(
        mock_nb,
        [metalbox],
        {1: [SimpleNamespace(id=11)]},
        {11: [SimpleNamespace(address="10.0.0.1/24")]},
    )

    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) == "10.0.0.1"
    patch_fallback.assert_not_called()


def test_metalbox_falls_back_when_no_subnet_matches(mock_nb, patch_oob, patch_fallback):
    patch_oob.return_value = ("10.0.0.5", 24)
    patch_fallback.return_value = "172.16.0.1"
    metalbox = SimpleNamespace(id=1, primary_ip4="10.0.0.1/24")
    _wire_metalboxes(
        mock_nb,
        [metalbox],
        {1: [SimpleNamespace(id=11)]},
        {11: [SimpleNamespace(address="192.168.1.1/24")]},
    )

    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) == "172.16.0.1"
    patch_fallback.assert_called_once_with()


def test_metalbox_matching_subnet_without_primary_ip_returns_none(
    mock_nb, patch_oob, patch_fallback
):
    patch_oob.return_value = ("10.0.0.5", 24)
    metalbox = SimpleNamespace(id=1, primary_ip4=None)
    _wire_metalboxes(
        mock_nb,
        [metalbox],
        {1: [SimpleNamespace(id=11)]},
        {11: [SimpleNamespace(address="10.0.0.9/24")]},
    )

    # The early ``return None`` means the fallback is intentionally skipped.
    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) is None
    patch_fallback.assert_not_called()


def test_metalbox_matches_on_second_interface(mock_nb, patch_oob, patch_fallback):
    patch_oob.return_value = ("10.0.0.5", 24)
    metalbox = SimpleNamespace(id=1, primary_ip4="10.0.0.1/24")
    _wire_metalboxes(
        mock_nb,
        [metalbox],
        {1: [SimpleNamespace(id=11), SimpleNamespace(id=12)]},
        {
            11: [SimpleNamespace(address="192.168.1.1/24")],
            12: [SimpleNamespace(address="10.0.0.2/24")],
        },
    )

    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) == "10.0.0.1"


def test_metalbox_only_matching_ipv4_is_considered(mock_nb, patch_oob, patch_fallback):
    patch_oob.return_value = ("10.0.0.5", 24)
    metalbox = SimpleNamespace(id=1, primary_ip4="10.0.0.1/24")
    _wire_metalboxes(
        mock_nb,
        [metalbox],
        {1: [SimpleNamespace(id=11)]},
        {
            11: [
                SimpleNamespace(address="fd00::1/64"),
                SimpleNamespace(address="10.0.0.7/24"),
            ]
        },
    )

    assert _get_metalbox_primary_ip4(SimpleNamespace(name="d")) == "10.0.0.1"
    patch_fallback.assert_not_called()


# ---------------------------------------------------------------------------
# _render_templates
# ---------------------------------------------------------------------------


def test_render_flat_dict_renders_jinja_value():
    obj = {"greeting": "Hello {{ name }}"}

    assert _render_templates(obj, {"name": "World"}) is None
    assert obj == {"greeting": "Hello World"}


def test_render_nested_dict():
    obj = {"outer": {"inner": "{{ v }}"}}

    _render_templates(obj, {"v": "x"})

    assert obj == {"outer": {"inner": "x"}}


def test_render_nested_list():
    obj = {"items": ["{{ a }}", "static"]}

    _render_templates(obj, {"a": "1"})

    assert obj == {"items": ["1", "static"]}


def test_render_list_of_dicts():
    obj = [{"k": "{{ a }}"}, {"k": "plain"}]

    _render_templates(obj, {"a": "z"})

    assert obj == [{"k": "z"}, {"k": "plain"}]


def test_render_string_without_braces_unchanged():
    obj = {"k": "no templating here"}

    _render_templates(obj, {"x": "1"})

    assert obj == {"k": "no templating here"}


def test_render_non_string_values_unchanged():
    obj = {"i": 5, "n": None, "d": {"x": 1}, "b": True}

    _render_templates(obj, {})

    assert obj == {"i": 5, "n": None, "d": {"x": 1}, "b": True}


def test_render_multiple_template_vars_all_available():
    obj = {"k": "{{ a }}-{{ b }}"}

    _render_templates(obj, {"a": "1", "b": "2"})

    assert obj == {"k": "1-2"}


def test_render_mutates_in_place_and_returns_none():
    obj = {"k": "{{ a }}"}

    result = _render_templates(obj, {"a": "v"})

    assert result is None
    assert obj["k"] == "v"


# ---------------------------------------------------------------------------
# _prepare_node_attributes
# ---------------------------------------------------------------------------


# The yrzn001 mapping mirrored from the production SUPPORTED_IPA_TYPES so the
# kernel-enrichment tests stay independent of future edits to the real dict.
_YRZN_MAPPING = {
    "yrzn001": {
        "osism-ipa-as": "frr_local_as",
        "osism-ipa-ipv4": "frr_loopback_v4",
        "osism-ipa-ipv6": "frr_loopback_v6",
        "osism-ipa-metalbox": None,
    },
}


@pytest.fixture
def prep(mocker):
    """Patch every collaborator of ``_prepare_node_attributes``."""
    m = SimpleNamespace()
    m.vault = mocker.sentinel.vault
    m.get_vault = mocker.patch(
        "osism.tasks.conductor.ironic.get_vault", return_value=m.vault
    )
    # deep_decrypt / deep_merge are stubbed as no-ops; their real behaviour is
    # covered by the conductor.utils tests.
    m.deep_decrypt = mocker.patch("osism.tasks.conductor.ironic.deep_decrypt")
    m.deep_merge = mocker.patch("osism.tasks.conductor.ironic.deep_merge")
    m.get_device_oob_ip = mocker.patch(
        "osism.tasks.conductor.ironic.get_device_oob_ip", return_value=None
    )
    m.derive_as = mocker.patch(
        "osism.tasks.conductor.ironic._derive_as_from_hostname_yrzn",
        return_value=None,
    )
    m.get_metalbox = mocker.patch(
        "osism.tasks.conductor.ironic._get_metalbox_primary_ip4", return_value=None
    )
    mocker.patch(
        "osism.tasks.conductor.ironic.SUPPORTED_IPA_TYPES", new=dict(_YRZN_MAPPING)
    )
    return m


# -- base merging -----------------------------------------------------------


def test_prepare_base_only_sets_resource_class_and_empty_extra(prep):
    attrs, tvars = _prepare_node_attributes(_device(), lambda: {})

    assert attrs == {"resource_class": "server-1", "extra": {}}
    assert tvars == {
        "remote_board_username": "admin",
        "remote_board_password": "password",
    }
    prep.deep_merge.assert_not_called()


def test_prepare_decrypts_and_merges_config_context_ironic_parameters(prep):
    cc_ironic = {"driver": "redfish"}
    device = _device(config_context={"ironic_parameters": cc_ironic})

    _prepare_node_attributes(device, lambda: {})

    assert any(
        c.args[0] is cc_ironic and c.args[1] is prep.vault
        for c in prep.deep_decrypt.call_args_list
    )
    assert prep.deep_merge.call_count == 1
    assert prep.deep_merge.call_args.args[1] is cc_ironic


def test_prepare_decrypts_and_merges_custom_field_ironic_parameters(prep):
    cf_ironic = {"driver": "redfish"}
    device = _device(custom_fields={"ironic_parameters": cf_ironic})

    _prepare_node_attributes(device, lambda: {})

    assert any(c.args[0] is cf_ironic for c in prep.deep_decrypt.call_args_list)
    assert prep.deep_merge.call_count == 1
    assert prep.deep_merge.call_args.args[1] is cf_ironic


def test_prepare_merges_config_context_before_custom_field(prep):
    cc_ironic = {"a": 1}
    cf_ironic = {"b": 2}
    device = _device(
        custom_fields={"ironic_parameters": cf_ironic},
        config_context={"ironic_parameters": cc_ironic},
    )

    _prepare_node_attributes(device, lambda: {})

    assert prep.deep_merge.call_count == 2
    first, second = prep.deep_merge.call_args_list
    assert first.args[1] is cc_ironic
    assert second.args[1] is cf_ironic
    decrypted = [c.args[0] for c in prep.deep_decrypt.call_args_list]
    assert decrypted.index(cc_ironic) < decrypted.index(cf_ironic)


# -- driver pruning ---------------------------------------------------------


def test_prepare_prunes_redfish_keys_for_ipmi_driver(prep):
    base = {
        "driver": "ipmi",
        "driver_info": {
            "ipmi_address": "1.2.3.4",
            "redfish_address": "5.6.7.8",
            "redfish_password": "x",
        },
    }

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["driver_info"] == {"ipmi_address": "1.2.3.4"}


def test_prepare_prunes_ipmi_keys_for_redfish_driver(prep):
    base = {
        "driver": "redfish",
        "driver_info": {
            "redfish_address": "5.6.7.8",
            "ipmi_address": "1.2.3.4",
            "ipmi_port": "623",
        },
    }

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["driver_info"] == {"redfish_address": "5.6.7.8"}


def test_prepare_unknown_driver_keeps_all_driver_info(prep):
    base = {
        "driver": "mystery",
        "driver_info": {"ipmi_address": "1.2.3.4", "redfish_address": "5.6.7.8"},
    }

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["driver_info"] == {
        "ipmi_address": "1.2.3.4",
        "redfish_address": "5.6.7.8",
    }


# -- template variables -----------------------------------------------------


def test_prepare_template_vars_default_board_credentials(prep):
    _, tvars = _prepare_node_attributes(_device(), lambda: {})

    assert tvars["remote_board_username"] == "admin"
    assert tvars["remote_board_password"] == "password"


def test_prepare_template_vars_honor_node_secrets(prep):
    device = _device(
        custom_fields={
            "secrets": {
                "remote_board_username": "root",
                "remote_board_password": "s3cret",
            }
        }
    )

    _, tvars = _prepare_node_attributes(device, lambda: {})

    assert tvars["remote_board_username"] == "root"
    assert tvars["remote_board_password"] == "s3cret"


def test_prepare_template_vars_includes_oob_address(prep):
    prep.get_device_oob_ip.return_value = ("10.0.0.5", 24)

    _, tvars = _prepare_node_attributes(_device(), lambda: {})

    assert tvars["remote_board_address"] == "10.0.0.5"


def test_prepare_template_vars_omits_address_when_no_oob(prep):
    prep.get_device_oob_ip.return_value = None

    _, tvars = _prepare_node_attributes(_device(), lambda: {})

    assert "remote_board_address" not in tvars


def test_prepare_template_vars_propagate_ironic_osism_secrets(prep):
    device = _device(
        custom_fields={"secrets": {"ironic_osism_token": "  abc  ", "other": "x"}}
    )

    _, tvars = _prepare_node_attributes(device, lambda: {})

    assert tvars["ironic_osism_token"] == "abc"
    assert "other" not in tvars


# -- kernel append params (osism-ipa-type=yrzn001) --------------------------


def test_prepare_appends_frr_kernel_params_for_yrzn(prep):
    base = {
        "instance_info": {
            "kernel_append_params": "console=ttyS0 osism-ipa-type=yrzn001"
        }
    }
    device = _device(
        custom_fields={
            "frr_parameters": {
                "frr_local_as": 65001,
                "frr_loopback_v4": "10.1.1.1",
                "frr_loopback_v6": "fd00::1",
            }
        }
    )

    attrs, _ = _prepare_node_attributes(device, lambda: base)

    expected = (
        "console=ttyS0 osism-ipa-type=yrzn001 "
        "osism-ipa-as=65001 osism-ipa-ipv4=10.1.1.1 osism-ipa-ipv6=fd00::1"
    )
    assert attrs["instance_info"]["kernel_append_params"] == expected


def test_prepare_appends_only_available_frr_params(prep):
    base = {"instance_info": {"kernel_append_params": "osism-ipa-type=yrzn001"}}
    device = _device(custom_fields={"frr_parameters": {"frr_loopback_v4": "10.1.1.1"}})

    attrs, _ = _prepare_node_attributes(device, lambda: base)

    assert (
        attrs["instance_info"]["kernel_append_params"]
        == "osism-ipa-type=yrzn001 osism-ipa-ipv4=10.1.1.1"
    )


def test_prepare_appends_metalbox_ip_when_resolved(prep):
    prep.get_metalbox.return_value = "10.9.9.9"
    base = {"instance_info": {"kernel_append_params": "osism-ipa-type=yrzn001"}}

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert (
        attrs["instance_info"]["kernel_append_params"]
        == "osism-ipa-type=yrzn001 osism-ipa-metalbox=10.9.9.9"
    )


def test_prepare_omits_metalbox_when_not_resolved(prep):
    prep.get_metalbox.return_value = None
    base = {"instance_info": {"kernel_append_params": "osism-ipa-type=yrzn001"}}

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["instance_info"]["kernel_append_params"] == "osism-ipa-type=yrzn001"


def test_prepare_derives_as_when_frr_local_as_absent(prep):
    prep.derive_as.return_value = "4200155960"
    base = {"instance_info": {"kernel_append_params": "osism-ipa-type=yrzn001"}}
    device = _device(name="stor-nw-22-60-59-6")

    attrs, _ = _prepare_node_attributes(device, lambda: base)

    assert (
        attrs["instance_info"]["kernel_append_params"]
        == "osism-ipa-type=yrzn001 osism-ipa-as=4200155960"
    )
    prep.derive_as.assert_called_once_with("stor-nw-22-60-59-6")


def test_prepare_unknown_ipa_type_skips_enrichment(prep):
    base = {"instance_info": {"kernel_append_params": "osism-ipa-type=zzz999"}}
    device = _device(custom_fields={"frr_parameters": {"frr_local_as": 1}})

    attrs, _ = _prepare_node_attributes(device, lambda: base)

    assert attrs["instance_info"]["kernel_append_params"] == "osism-ipa-type=zzz999"
    prep.get_metalbox.assert_not_called()
    prep.derive_as.assert_not_called()


# -- skip_kernel_params -----------------------------------------------------


def test_prepare_skip_kernel_params_removes_named_params(prep):
    base = {
        "instance_info": {
            "kernel_append_params": "osism-ipa-as=999 console=ttyS0 quiet"
        }
    }

    attrs, _ = _prepare_node_attributes(
        _device(), lambda: base, skip_kernel_params=["osism-ipa-as"]
    )

    assert attrs["instance_info"]["kernel_append_params"] == "console=ttyS0 quiet"


# -- extra_kernel_params ----------------------------------------------------


def test_prepare_extra_kernel_params_appended_with_single_space(prep):
    base = {"instance_info": {"kernel_append_params": "root=/dev/sda"}}

    attrs, _ = _prepare_node_attributes(
        _device(), lambda: base, extra_kernel_params=["quiet", "splash"]
    )

    assert (
        attrs["instance_info"]["kernel_append_params"] == "root=/dev/sda quiet splash"
    )


def test_prepare_extra_kernel_params_first_param_has_no_leading_space(prep):
    base = {"instance_info": {"kernel_append_params": ""}}

    attrs, _ = _prepare_node_attributes(
        _device(), lambda: base, extra_kernel_params=["console=ttyS0"]
    )

    assert attrs["instance_info"]["kernel_append_params"] == "console=ttyS0"


# -- driver_info persistence ------------------------------------------------


def test_prepare_stores_kernel_params_in_driver_info(prep):
    base = {"instance_info": {"kernel_append_params": "foo=bar"}}

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["driver_info"]["kernel_append_params"] == "foo=bar"


# -- extra updates ----------------------------------------------------------


def test_prepare_serializes_instance_info_into_extra(prep):
    base = {"instance_info": {"kernel_append_params": "x=y"}}

    attrs, _ = _prepare_node_attributes(_device(), lambda: base)

    assert attrs["extra"]["instance_info"] == json.dumps(
        {"kernel_append_params": "x=y"}
    )


def test_prepare_serializes_netplan_parameters_into_extra(prep):
    device = _device(custom_fields={"netplan_parameters": {"version": 2}})

    attrs, _ = _prepare_node_attributes(device, lambda: {})

    assert attrs["extra"]["netplan_parameters"] == json.dumps({"version": 2})


def test_prepare_serializes_frr_parameters_into_extra_after_decrypt(prep):
    frr = {"frr_local_as": 65000}
    device = _device(custom_fields={"frr_parameters": frr})

    attrs, _ = _prepare_node_attributes(device, lambda: {})

    assert attrs["extra"]["frr_parameters"] == json.dumps(frr)
    assert any(c.args[0] is frr for c in prep.deep_decrypt.call_args_list)


def test_prepare_extra_empty_when_no_optional_fields(prep):
    attrs, _ = _prepare_node_attributes(_device(), lambda: {})

    assert attrs["extra"] == {}


# -- returns ----------------------------------------------------------------


def test_prepare_returns_attributes_and_template_vars_tuple(prep):
    result = _prepare_node_attributes(_device(), lambda: {})

    assert isinstance(result, tuple)
    assert len(result) == 2
    attrs, tvars = result
    assert attrs["resource_class"] == "server-1"
    assert "remote_board_username" in tvars


# ---------------------------------------------------------------------------
# _prettify_for_display
# ---------------------------------------------------------------------------


def test_prettify_parses_json_string_in_extra():
    obj = {"extra": {"instance_info": '{"foo": "bar"}'}}

    result = _prettify_for_display(obj)

    assert result["extra"]["instance_info"] == {"foo": "bar"}


def test_prettify_leaves_non_json_string_untouched():
    obj = {"extra": {"note": "not-json"}}

    result = _prettify_for_display(obj)

    assert result["extra"]["note"] == "not-json"


def test_prettify_dict_without_extra_is_deep_copied():
    obj = {"a": 1, "b": {"c": 2}}

    result = _prettify_for_display(obj)

    assert result == obj
    assert result is not obj
    assert result["b"] is not obj["b"]


def test_prettify_non_dict_is_deep_copied():
    obj = [1, [2, 3]]

    result = _prettify_for_display(obj)

    assert result == obj
    assert result is not obj
