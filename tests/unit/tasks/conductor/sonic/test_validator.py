# SPDX-License-Identifier: Apache-2.0

"""Tests for the SONiC ConfigDB validator.

Focus is on the cross-table leafref post-pass added in #2252; per-row schema
validation is exercised end-to-end by the existing CLI tests and only checked
here for non-regression.
"""

from osism.tasks.conductor.sonic.validator import validate_config


def _leafref_errors(result):
    return [e for e in result.errors if "leafref" in e.message]


def test_leafref_passes_when_target_exists():
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PORTCHANNEL": {"PortChannel0": {"admin_status": "up"}},
        "PORTCHANNEL_MEMBER": {
            "PortChannel0|Ethernet0": {
                "name": "PortChannel0",
                "port": "Ethernet0",
            },
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_leafref_fails_when_port_missing():
    """The headline AC: PORTCHANNEL_MEMBER → non-existent PORT must fail."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PORTCHANNEL": {"PortChannel0": {"admin_status": "up"}},
        "PORTCHANNEL_MEMBER": {
            "PortChannel0|Ethernet999": {
                "name": "PortChannel0",
                "port": "Ethernet999",
            },
        },
    }
    result = validate_config(config)
    errors = _leafref_errors(result)
    assert any(
        e.table == "PORTCHANNEL_MEMBER"
        and e.path == "PortChannel0|Ethernet999.port"
        and "Ethernet999" in e.message
        for e in errors
    ), errors


def test_union_leafref_accepts_either_target():
    """VLAN_MEMBER.port is a union of PORT and PORTCHANNEL leafrefs."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PORTCHANNEL": {"PortChannel0": {"admin_status": "up"}},
        "VLAN": {"Vlan100": {}},
        "VLAN_MEMBER": {
            "Vlan100|Ethernet0": {"name": "Vlan100", "port": "Ethernet0"},
            "Vlan100|PortChannel0": {"name": "Vlan100", "port": "PortChannel0"},
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_leafref_fails_when_no_target_matches():
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PORTCHANNEL": {"PortChannel0": {"admin_status": "up"}},
        "VLAN": {"Vlan100": {}},
        "VLAN_MEMBER": {
            "Vlan100|Ghost": {"name": "Vlan100", "port": "Ghost"},
        },
    }
    result = validate_config(config)
    errors = [e for e in _leafref_errors(result) if e.table == "VLAN_MEMBER"]
    assert errors
    msg = errors[0].message
    assert "PORT.name" in msg and "PORTCHANNEL.name" in msg


def test_leafref_resolves_via_non_key_target_field():
    """TUNNEL.src_ip → PEER_SWITCH.address_ipv4: target_field is not the row key,
    so the value must resolve via the inner field in `_collect_target_keysets`."""
    config = {
        # Row key deliberately differs from address_ipv4 so the only way the
        # leafref can resolve is via the inner non-key field.
        "PEER_SWITCH": {"peer_switch_name": {"address_ipv4": "10.0.0.1"}},
        "TUNNEL": {
            "MuxTunnel0": {"src_ip": "10.0.0.1", "tunnel_type": "IPINIP"},
        },
    }
    result = validate_config(config)
    assert [
        e for e in _leafref_errors(result) if e.table == "TUNNEL"
    ] == [], result.errors


def test_leafref_fails_when_target_table_is_empty():
    """Empty target tables must not be treated as a wildcard match."""
    config = {
        "BUFFER_PROFILE": {},
        "BUFFER_PORT_INGRESS_PROFILE_LIST": {
            "Ethernet0": {"profile_list": ["p1"]},
        },
        # Seed PORT so the simple-key 'port' leafref on this table resolves
        # and only the profile_list error remains.
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
    }
    result = validate_config(config)
    errors = [
        e
        for e in _leafref_errors(result)
        if e.table == "BUFFER_PORT_INGRESS_PROFILE_LIST"
        and "profile_list" in (e.path or "")
    ]
    assert any("p1" in e.message for e in errors), errors


def test_leaf_list_of_leafrefs_checks_each_element():
    config = {
        "BUFFER_PROFILE": {"p1": {}, "p2": {}},
        "BUFFER_PORT_INGRESS_PROFILE_LIST": {
            # row key carries the simple-key 'port' leafref → PORT.name; we
            # don't want that to dominate this assertion, so seed PORT too.
            "Ethernet0": {"profile_list": ["p1", "p2"]},
            "Ethernet1": {"profile_list": ["p1", "missing"]},
        },
        "PORT": {
            "Ethernet0": {"lanes": "0", "speed": "10000"},
            "Ethernet1": {"lanes": "1", "speed": "10000"},
        },
    }
    result = validate_config(config)
    errors = [
        e
        for e in _leafref_errors(result)
        if e.table == "BUFFER_PORT_INGRESS_PROFILE_LIST"
        and "profile_list" in (e.path or "")
    ]
    assert any("missing" in e.message for e in errors), errors


def test_simple_key_row_key_is_treated_as_leafref_value():
    """INTERFACE.<row_key> is a leafref into PORT.name; the row dict often
    has no explicit `name` field, so the validator must use the row key."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "INTERFACE": {"Ethernet999": {}},
    }
    result = validate_config(config)
    errors = [e for e in _leafref_errors(result) if e.table == "INTERFACE"]
    assert any("Ethernet999" in e.message for e in errors), errors


def test_composite_row_key_skips_simple_key_shortcut():
    """When the row key contains '|' it's a composite key and we deliberately
    don't try to split it; without an explicit field the leafref is skipped."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        # INTERFACE_IPPREFIX_LIST style key — composite. Not a real check today.
        "INTERFACE": {"Ethernet0|10.0.0.1/31": {}},
    }
    result = validate_config(config)
    leafref_errors_for_interface = [
        e for e in _leafref_errors(result) if e.table == "INTERFACE"
    ]
    assert leafref_errors_for_interface == []


def test_unknown_table_emits_warning_not_error():
    config = {"NOT_A_REAL_TABLE": {"x": {}}}
    result = validate_config(config)
    assert any("NOT_A_REAL_TABLE" in w for w in result.warnings)
    assert _leafref_errors(result) == []
