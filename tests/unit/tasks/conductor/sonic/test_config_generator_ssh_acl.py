# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_ssh_acl_configuration`` in ``config_generator``."""

from types import SimpleNamespace

import pytest

from osism.tasks.conductor.sonic.config_generator import _add_ssh_acl_configuration

pytestmark = pytest.mark.usefixtures("reset_config_generator_caches")


def _device(name="leaf-1"):
    return SimpleNamespace(name=name)


def test_add_ssh_acl_configuration_emits_ctrlplane_table_and_accept_rule():
    config = {}

    _add_ssh_acl_configuration(config, _device(), ("10.42.0.5", 24))

    assert config["ACL_TABLE"] == {
        "SSH_ONLY": {
            "policy_desc": "SSH_ONLY",
            "type": "CTRLPLANE",
            "services": ["SSH"],
        }
    }
    assert config["ACL_RULE"] == {
        "SSH_ONLY|RULE_1": {
            "PRIORITY": "9999",
            "PACKET_ACTION": "ACCEPT",
            "SRC_IP": "10.42.0.0/24",
            "IP_TYPE": "IP",
        }
    }


@pytest.mark.parametrize(
    "oob_ip,prefix_len,expected_src",
    [
        ("10.42.0.5", 24, "10.42.0.0/24"),  # host bits stripped
        ("192.168.45.123", 26, "192.168.45.64/26"),  # non-octet boundary
        ("10.42.0.0", 24, "10.42.0.0/24"),  # already the network address
    ],
)
def test_add_ssh_acl_configuration_normalises_src_ip_to_network_address(
    oob_ip, prefix_len, expected_src
):
    """The OOB IP is a host address — the rule must carry its subnet."""
    config = {}

    _add_ssh_acl_configuration(config, _device(), (oob_ip, prefix_len))

    assert config["ACL_RULE"]["SSH_ONLY|RULE_1"]["SRC_IP"] == expected_src


def test_add_ssh_acl_configuration_replaces_preexisting_tables():
    """ACL_TABLE / ACL_RULE are owned tables — entries carried over from the
    base config_db.json are replaced wholesale on regen."""
    config = {
        "ACL_TABLE": {"OPERATOR_TABLE": {"type": "L3"}},
        "ACL_RULE": {"OPERATOR_TABLE|RULE_1": {"PACKET_ACTION": "DROP"}},
    }

    _add_ssh_acl_configuration(config, _device(), ("10.42.0.5", 24))

    assert "OPERATOR_TABLE" not in config["ACL_TABLE"]
    assert "OPERATOR_TABLE|RULE_1" not in config["ACL_RULE"]
    assert "SSH_ONLY" in config["ACL_TABLE"]
    assert "SSH_ONLY|RULE_1" in config["ACL_RULE"]
