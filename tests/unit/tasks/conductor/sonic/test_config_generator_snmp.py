# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_snmp_configuration`` in ``config_generator``."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.config_generator import _add_snmp_configuration

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


@pytest.fixture
def patch_snmp_secrets(mocker):
    """Patch ``deep_decrypt`` and ``get_vault`` to no-ops in the module's
    namespace so the SNMP tests don't need a real vault.

    The orchestrator binds them at import time, so we patch the rebound
    references on the ``config_generator`` module rather than on
    ``conductor.utils``.
    """

    mocker.patch("osism.tasks.conductor.sonic.config_generator.get_vault")
    mocker.patch(
        "osism.tasks.conductor.sonic.config_generator.deep_decrypt",
        side_effect=lambda data, vault: None,
    )


def _snmp_device(custom_fields=None, **ctx):
    return SimpleNamespace(
        name="leaf-1",
        config_context=ctx,
        custom_fields=custom_fields if custom_fields is not None else {},
    )


def test_add_snmp_configuration_defaults(patch_snmp_secrets):
    config = {}

    _add_snmp_configuration(config, _snmp_device(), oob_ip=None)

    assert config["SNMP_SERVER"]["SYSTEM"] == {
        "sysContact": "info@example.com",
        "sysLocation": "Data Center",
        "traps": "enable",
    }


def test_add_snmp_configuration_traps_disabled_omits_key(patch_snmp_secrets):
    config = {}

    _add_snmp_configuration(
        config,
        _snmp_device(_segment_snmp_server_traps=False),
        oob_ip=None,
    )

    assert "traps" not in config["SNMP_SERVER"]["SYSTEM"]


def test_add_snmp_configuration_oob_ip_populates_agent_address(patch_snmp_secrets):
    config = {}

    _add_snmp_configuration(config, _snmp_device(), oob_ip="10.42.0.5")

    assert config["SNMP_AGENT_ADDRESS_CONFIG"] == {
        "10.42.0.5|161|mgmt": {"name": "agentEntry1"}
    }


def test_add_snmp_configuration_no_oob_ip_omits_agent_address(patch_snmp_secrets):
    config = {}

    _add_snmp_configuration(config, _snmp_device(), oob_ip=None)

    assert "SNMP_AGENT_ADDRESS_CONFIG" not in config


def test_add_snmp_configuration_user_pulls_secrets_from_node_secrets(
    patch_snmp_secrets,
):
    config = {}
    device = _snmp_device(
        custom_fields={
            "secrets": {
                "_segment_snmp_server_userauthpass": "auth-secret",
                "_segment_snmp_server_userprivpass": "priv-secret",
            }
        },
        _segment_snmp_server_username="snmpuser",
    )

    _add_snmp_configuration(config, device, oob_ip=None)

    assert config["SNMP_SERVER_USER"]["snmpuser"] == {
        "shaKey": "auth-secret",
        "aesKey": "priv-secret",
    }
    assert config["SNMP_SERVER_GROUP_MEMBER"]["monitoring|snmpuser"] == {
        "securityModel": ["usm"]
    }


def test_add_snmp_configuration_user_falls_back_to_obfuscated_secrets(
    patch_snmp_secrets,
):
    config = {}
    device = _snmp_device(_segment_snmp_server_username="snmpuser")

    _add_snmp_configuration(config, device, oob_ip=None)

    assert config["SNMP_SERVER_USER"]["snmpuser"] == {
        "shaKey": "OBFUSCATEDAUTHSECRET",
        "aesKey": "OBFUSCATEDPRIVSECRET",
    }


def test_add_snmp_configuration_user_with_hosts_creates_targets(patch_snmp_secrets):
    config = {}
    device = _snmp_device(
        _segment_snmp_server_username="snmpuser",
        _segment_snmp_server_hosts=["10.0.0.10", "10.0.0.11"],
    )

    _add_snmp_configuration(config, device, oob_ip=None)

    assert set(config["SNMP_SERVER_PARAMS"].keys()) == {
        "targetEntry1",
        "targetEntry2",
    }
    assert config["SNMP_SERVER_TARGET"]["targetEntry1"]["ip"] == "10.0.0.10"
    assert config["SNMP_SERVER_TARGET"]["targetEntry2"]["ip"] == "10.0.0.11"
    # All targets must reference the user via SNMP_SERVER_PARAMS.
    for entry in config["SNMP_SERVER_PARAMS"].values():
        assert entry == {"security-level": "auth-priv", "user": "snmpuser"}


def test_add_snmp_configuration_no_user_omits_user_target_sections(
    patch_snmp_secrets,
):
    config = {}

    _add_snmp_configuration(config, _snmp_device(), oob_ip=None)

    for absent in (
        "SNMP_SERVER_USER",
        "SNMP_SERVER_GROUP_MEMBER",
        "SNMP_SERVER_PARAMS",
        "SNMP_SERVER_TARGET",
    ):
        assert absent not in config


def test_add_snmp_configuration_secrets_none_treated_as_empty(patch_snmp_secrets):
    """``custom_fields["secrets"] is None`` is the production-default for
    devices without an encrypted-secrets field — the helper must treat it as
    ``{}`` rather than dereferencing ``None.get``."""
    config = {}
    device = _snmp_device(
        custom_fields={"secrets": None},
        _segment_snmp_server_username="snmpuser",
    )

    _add_snmp_configuration(config, device, oob_ip=None)

    assert config["SNMP_SERVER_USER"]["snmpuser"] == {
        "shaKey": "OBFUSCATEDAUTHSECRET",
        "aesKey": "OBFUSCATEDPRIVSECRET",
    }
