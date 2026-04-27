# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import mock_open

import pytest
import yaml

from osism.tasks.conductor import config as config_module
from osism.tasks.conductor.config import get_configuration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# (section, key) tuples for fields that resolve via ``openstack.image_get``.
IMAGE_FIELDS = [
    pytest.param("instance_info", "image_source", id="image_source"),
    pytest.param("driver_info", "deploy_kernel", id="deploy_kernel"),
    pytest.param("driver_info", "deploy_ramdisk", id="deploy_ramdisk"),
]

# Keys under ``driver_info`` that resolve via ``openstack.network_get``.
NETWORK_FIELDS = [
    pytest.param("cleaning_network", id="cleaning_network"),
    pytest.param("provisioning_network", id="provisioning_network"),
]


def _patch_open(mocker, payload):
    """Route ``open`` inside ``config`` to an in-memory YAML payload."""
    if isinstance(payload, dict):
        data = yaml.safe_dump(payload)
    else:
        data = payload
    return mocker.patch(
        "osism.tasks.conductor.config.open", mock_open(read_data=data), create=True
    )


def _payload_with(section, key, value):
    """Build a minimal ``ironic_parameters`` payload with one field set."""
    return {"ironic_parameters": {section: {key: value}}}


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


@pytest.fixture
def patch_openstack(mocker):
    """Patch the openstack helpers imported into config."""
    image_get = mocker.patch("osism.tasks.conductor.config.openstack.image_get")
    network_get = mocker.patch("osism.tasks.conductor.config.openstack.network_get")
    return SimpleNamespace(image_get=image_get, network_get=network_get)


@pytest.fixture
def enable_ironic(mocker):
    """Toggle the ENABLE_IRONIC flag without touching the environment."""

    def _set(value):
        mocker.patch(
            "osism.tasks.conductor.config.Config.enable_ironic", new=value, create=True
        )

    return _set


# ---------------------------------------------------------------------------
# Empty configuration / ironic disabled
# ---------------------------------------------------------------------------


def test_empty_file_returns_empty_dict_and_warns(
    mocker, patch_openstack, enable_ironic, loguru_logs
):
    enable_ironic("True")
    _patch_open(mocker, "")

    assert get_configuration() == {}
    patch_openstack.image_get.assert_not_called()
    patch_openstack.network_get.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "conductor configuration is empty")


def test_ironic_disabled_returns_yaml_untouched(mocker, patch_openstack, enable_ironic):
    enable_ironic("False")
    payload = {
        "ironic_parameters": {
            "instance_info": {"image_source": "ubuntu"},
            "driver_info": {"deploy_kernel": "kernel"},
        }
    }
    _patch_open(mocker, payload)

    assert get_configuration() == payload
    patch_openstack.image_get.assert_not_called()
    patch_openstack.network_get.assert_not_called()


@pytest.mark.parametrize("flag", ["false", "no", "0", "off", "anything-else", ""])
def test_ironic_disabled_for_various_falsy_strings(
    mocker, patch_openstack, enable_ironic, flag
):
    enable_ironic(flag)
    _patch_open(mocker, {"foo": "bar"})

    assert get_configuration() == {"foo": "bar"}
    patch_openstack.image_get.assert_not_called()


@pytest.mark.parametrize("flag", ["true", "True", "TRUE", "yes", "YES", "Yes"])
def test_ironic_enabled_for_truthy_strings_processes_config(
    mocker, patch_openstack, enable_ironic, flag
):
    enable_ironic(flag)
    payload = {
        "ironic_parameters": {
            "instance_info": {"image_source": "ubuntu"},
        }
    }
    _patch_open(mocker, payload)
    patch_openstack.image_get.return_value = SimpleNamespace(id="image-uuid")

    result = get_configuration()

    patch_openstack.image_get.assert_called_once_with("ubuntu")
    assert result["ironic_parameters"]["instance_info"]["image_source"] == "image-uuid"


def test_ironic_enabled_without_ironic_parameters_returns_as_is_and_logs_error(
    mocker, patch_openstack, enable_ironic, loguru_logs
):
    enable_ironic("True")
    payload = {"unrelated": {"key": "value"}}
    _patch_open(mocker, payload)

    assert get_configuration() == payload
    patch_openstack.image_get.assert_not_called()
    patch_openstack.network_get.assert_not_called()
    assert _has_log(
        loguru_logs,
        "ERROR",
        "ironic_parameters not found in the conductor configuration",
    )


# ---------------------------------------------------------------------------
# image_source / deploy_kernel / deploy_ramdisk resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section,key", IMAGE_FIELDS)
def test_image_field_name_resolved_to_uuid(
    mocker, patch_openstack, enable_ironic, section, key
):
    enable_ironic("True")
    _patch_open(mocker, _payload_with(section, key, "named-image"))
    patch_openstack.image_get.return_value = SimpleNamespace(id="resolved-uuid")

    result = get_configuration()

    patch_openstack.image_get.assert_called_once_with("named-image")
    assert result["ironic_parameters"][section][key] == "resolved-uuid"


@pytest.mark.parametrize("section,key", IMAGE_FIELDS)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param("11111111-1111-1111-1111-111111111111", id="uuid"),
        pytest.param("http://example.com/images/file.qcow2", id="url"),
    ],
)
def test_image_field_uuid_or_url_pass_through(
    mocker, patch_openstack, enable_ironic, section, key, value
):
    enable_ironic("True")
    _patch_open(mocker, _payload_with(section, key, value))

    result = get_configuration()

    patch_openstack.image_get.assert_not_called()
    assert result["ironic_parameters"][section][key] == value


@pytest.mark.parametrize("section,key", IMAGE_FIELDS)
def test_image_field_unresolved_keeps_original_and_warns(
    mocker, patch_openstack, enable_ironic, loguru_logs, section, key
):
    enable_ironic("True")
    _patch_open(mocker, _payload_with(section, key, "missing-image"))
    patch_openstack.image_get.return_value = None

    result = get_configuration()

    assert result["ironic_parameters"][section][key] == "missing-image"
    assert _has_log(
        loguru_logs,
        "WARNING",
        "Could not resolve image ID for missing-image",
    )


def test_instance_info_present_without_image_source_is_noop(
    mocker, patch_openstack, enable_ironic
):
    enable_ironic("True")
    _patch_open(
        mocker,
        {"ironic_parameters": {"instance_info": {"other_key": "value"}}},
    )

    result = get_configuration()

    patch_openstack.image_get.assert_not_called()
    assert result["ironic_parameters"]["instance_info"] == {"other_key": "value"}


# ---------------------------------------------------------------------------
# cleaning_network / provisioning_network resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", NETWORK_FIELDS)
def test_network_field_name_resolved_to_id(mocker, patch_openstack, enable_ironic, key):
    enable_ironic("True")
    _patch_open(mocker, _payload_with("driver_info", key, "named-network"))
    patch_openstack.network_get.return_value = SimpleNamespace(id="resolved-net-id")

    result = get_configuration()

    patch_openstack.network_get.assert_called_once_with("named-network")
    assert result["ironic_parameters"]["driver_info"][key] == "resolved-net-id"


@pytest.mark.parametrize("key", NETWORK_FIELDS)
def test_network_field_unresolved_keeps_original_and_warns(
    mocker, patch_openstack, enable_ironic, loguru_logs, key
):
    enable_ironic("True")
    _patch_open(mocker, _payload_with("driver_info", key, "missing-network"))
    patch_openstack.network_get.return_value = None

    result = get_configuration()

    assert result["ironic_parameters"]["driver_info"][key] == "missing-network"
    assert _has_log(
        loguru_logs,
        "WARNING",
        "Could not resolve network ID for missing-network",
    )


# ---------------------------------------------------------------------------
# Empty/missing sections
# ---------------------------------------------------------------------------


def test_empty_ironic_parameters_processed_without_calls(
    mocker, patch_openstack, enable_ironic
):
    enable_ironic("True")
    _patch_open(mocker, {"ironic_parameters": {}})

    result = get_configuration()

    assert result == {"ironic_parameters": {}}
    patch_openstack.image_get.assert_not_called()
    patch_openstack.network_get.assert_not_called()


def test_driver_info_present_without_supported_keys_is_noop(
    mocker, patch_openstack, enable_ironic
):
    enable_ironic("True")
    payload = {"ironic_parameters": {"driver_info": {"unrelated": "value"}}}
    _patch_open(mocker, payload)

    result = get_configuration()

    assert result == payload
    patch_openstack.image_get.assert_not_called()
    patch_openstack.network_get.assert_not_called()


def test_full_configuration_resolves_all_fields(mocker, patch_openstack, enable_ironic):
    enable_ironic("True")
    payload = {
        "ironic_parameters": {
            "instance_info": {"image_source": "ubuntu"},
            "driver_info": {
                "deploy_kernel": "kernel",
                "deploy_ramdisk": "ramdisk",
                "cleaning_network": "cleaning",
                "provisioning_network": "provisioning",
            },
        }
    }
    _patch_open(mocker, payload)
    patch_openstack.image_get.side_effect = [
        SimpleNamespace(id="image-uuid"),
        SimpleNamespace(id="kernel-uuid"),
        SimpleNamespace(id="ramdisk-uuid"),
    ]
    patch_openstack.network_get.side_effect = [
        SimpleNamespace(id="cleaning-id"),
        SimpleNamespace(id="provisioning-id"),
    ]

    result = get_configuration()

    assert result == {
        "ironic_parameters": {
            "instance_info": {"image_source": "image-uuid"},
            "driver_info": {
                "deploy_kernel": "kernel-uuid",
                "deploy_ramdisk": "ramdisk-uuid",
                "cleaning_network": "cleaning-id",
                "provisioning_network": "provisioning-id",
            },
        }
    }
    assert patch_openstack.image_get.call_count == 3
    assert patch_openstack.network_get.call_count == 2


# ---------------------------------------------------------------------------
# File location
# ---------------------------------------------------------------------------


def test_reads_configuration_from_etc_conductor_yml(
    mocker, patch_openstack, enable_ironic
):
    enable_ironic("False")
    opener = _patch_open(mocker, {"foo": "bar"})

    get_configuration()

    opener.assert_called_once_with("/etc/conductor.yml")


# ---------------------------------------------------------------------------
# Module sanity
# ---------------------------------------------------------------------------


def test_module_exposes_get_configuration():
    assert callable(config_module.get_configuration)
