# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``_add_ctrlplane_acls`` in ``config_generator`` (#2330)."""

import pytest

from osism.tasks.conductor.sonic.config_generator import (
    ON_DEMAND_OWNED_TABLE_KEYS,
    TOP_LEVEL_SCAFFOLD_KEYS,
    _add_ctrlplane_acls,
)


def test_add_ctrlplane_acls_emits_snmp_and_gnmi_ctrlplane_tables():
    config = {}

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    assert config["ACL_TABLE"] == {
        "SNMP_ONLY": {
            "policy_desc": "SNMP_ONLY",
            "type": "CTRLPLANE",
            "services": ["SNMP"],
        },
        "GNMI_ONLY": {
            "policy_desc": "GNMI_ONLY",
            "type": "CTRLPLANE",
            "services": ["EXTERNAL_CLIENT"],
        },
    }


def test_add_ctrlplane_acls_rules_accept_network_normalised_oob_subnet():
    """SRC_IP must carry the network address, not the device's host IP."""
    config = {}

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    assert config["ACL_RULE"]["SNMP_ONLY|RULE_1"] == {
        "PRIORITY": "9999",
        "PACKET_ACTION": "ACCEPT",
        "SRC_IP": "10.42.0.0/24",
        "IP_TYPE": "IP",
    }
    assert config["ACL_RULE"]["GNMI_ONLY|RULE_1"] == {
        "PRIORITY": "9999",
        "PACKET_ACTION": "ACCEPT",
        "SRC_IP": "10.42.0.0/24",
        "IP_TYPE": "IP",
        "L4_DST_PORT": "8080",
    }


def test_add_ctrlplane_acls_gnmi_rule_requires_dst_port_snmp_does_not():
    """caclmgrd's EXTERNAL_CLIENT service has no built-in destination port;
    without L4_DST_PORT in the rule it skips the whole table and the gNMI
    restriction would silently not exist. SNMP has a fixed service port
    (161) in caclmgrd's ACL_SERVICES, so its rule must not pin one."""
    config = {}

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    assert config["ACL_RULE"]["GNMI_ONLY|RULE_1"]["L4_DST_PORT"] == "8080"
    assert "L4_DST_PORT" not in config["ACL_RULE"]["SNMP_ONLY|RULE_1"]


def test_add_ctrlplane_acls_gnmi_port_follows_telemetry_table():
    """A TELEMETRY|gnmi|port from the base config wins over the 8080 default
    (and non-string values are normalised to the string ConfigDB expects)."""
    config = {"TELEMETRY": {"gnmi": {"port": 50051}}}

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    assert config["ACL_RULE"]["GNMI_ONLY|RULE_1"]["L4_DST_PORT"] == "50051"


@pytest.mark.parametrize(
    "port",
    [None, "", "  ", "not-a-port", "8080.5", 0, 70000, -1],
    ids=[
        "null",
        "empty",
        "blank",
        "non-numeric",
        "float",
        "zero",
        "too-big",
        "negative",
    ],
)
def test_add_ctrlplane_acls_unusable_gnmi_port_falls_back_to_default(port):
    """A present-but-unusable TELEMETRY|gnmi|port must not leak into the rule:
    caclmgrd cannot bind it and would skip the whole EXTERNAL_CLIENT table,
    silently leaving gNMI unrestricted. The helper substitutes the 8080
    default instead -- safe, because the gNMI container cannot bind such a
    value either, so there is no live listener the rule could mismatch."""
    config = {"TELEMETRY": {"gnmi": {"port": port}}}

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    assert config["ACL_RULE"]["GNMI_ONLY|RULE_1"]["L4_DST_PORT"] == "8080"


def test_add_ctrlplane_acls_merges_into_co_owned_tables_per_key():
    """ACL_TABLE / ACL_RULE are multi-owner (SSH, SNMP, gNMI): the helper must
    merge only its own keys, never rebind the table wholesale, so a sibling
    control-plane helper's entries survive. Stale carry-over from a prior regen
    is cleared by the central owned-table drop in generate_sonic_config, not
    here (see the ownership model and MULTI_OWNER_OWNED_TABLE_KEYS)."""
    config = {
        "ACL_TABLE": {"SSH_ONLY": {"type": "CTRLPLANE", "services": ["SSH"]}},
        "ACL_RULE": {"SSH_ONLY|RULE_1": {"PRIORITY": "9999"}},
    }

    _add_ctrlplane_acls(config, "10.42.0.5", 24)

    # A sibling helper's entries are left untouched ...
    assert config["ACL_TABLE"]["SSH_ONLY"] == {"type": "CTRLPLANE", "services": ["SSH"]}
    assert config["ACL_RULE"]["SSH_ONLY|RULE_1"] == {"PRIORITY": "9999"}
    # ... and this helper's own entries are added alongside them.
    assert set(config["ACL_TABLE"]) == {"SSH_ONLY", "SNMP_ONLY", "GNMI_ONLY"}
    assert set(config["ACL_RULE"]) == {
        "SSH_ONLY|RULE_1",
        "SNMP_ONLY|RULE_1",
        "GNMI_ONLY|RULE_1",
    }


def test_add_ctrlplane_acls_non_ipv4_oob_ip_emits_nothing():
    """The rules are IPv4-only (SRC_IP); an IPv6 OOB IP must not produce
    half-correct tables — and must not break config generation either."""
    config = {}

    _add_ctrlplane_acls(config, "2001:db8::5", 64)

    assert "ACL_TABLE" not in config
    assert "ACL_RULE" not in config


def test_ctrlplane_acl_tables_are_on_demand_owned():
    """#2330 requires ACL_TABLE/ACL_RULE to be rebuilt from scratch on every
    regen and absent without an OOB IP. Both guarantees hang on the keys
    being on-demand owned: owned tables are dropped from the base config up
    front, and on-demand (unlike scaffolded) tables are not re-created as
    empty dicts."""
    for key in ("ACL_TABLE", "ACL_RULE"):
        assert key in ON_DEMAND_OWNED_TABLE_KEYS
        assert key not in TOP_LEVEL_SCAFFOLD_KEYS
