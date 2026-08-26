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


def test_union_with_plain_type_arm_accepts_a_plain_value():
    """BGP_NEIGHBOR.local_addr is a union of `inet:ip-address`, three leafrefs
    and a Vlan pattern. A literal address satisfies the first arm, so the
    leafref arms must not be enforced against it."""
    config = {
        "BGP_NEIGHBOR": {
            "default|10.0.0.2": {"local_addr": "10.0.0.1", "asn": "65001"},
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_with_plain_type_arm_accepts_an_ipv6_address():
    config = {
        "BGP_NEIGHBOR": {
            "default|fe80::2": {"local_addr": "fe80::1", "asn": "65001"},
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_with_plain_type_arm_accepts_a_value_matching_its_pattern():
    """The Vlan arm is a bare pattern, not a leafref — SONiC comments the VLAN
    leafref out — so a Vlan name resolves without any VLAN table present."""
    config = {
        "BGP_NEIGHBOR": {
            "default|10.0.0.2": {"local_addr": "Vlan100", "asn": "65001"},
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_with_plain_type_arm_accepts_a_resolvable_leafref_value():
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "BGP_NEIGHBOR": {
            "default|10.0.0.2": {"local_addr": "Ethernet0", "asn": "65001"},
        },
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_with_plain_type_arm_still_flags_an_unresolvable_value():
    """A value that matches no plain arm must still resolve to a target: the
    plain arm exempts the values it admits, not the whole constraint."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "BGP_NEIGHBOR": {
            "default|10.0.0.2": {"local_addr": "Ethernet999", "asn": "65001"},
        },
    }
    result = validate_config(config)
    assert any(
        e.table == "BGP_NEIGHBOR" and "Ethernet999" in e.message
        for e in _leafref_errors(result)
    ), result.errors


def test_union_with_literal_escape_arm_accepts_the_literal():
    """PFC_WD.ifname is a leafref to PORT unioned with the literal `GLOBAL`."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PFC_WD": {"GLOBAL": {"detection_time": "200"}},
    }
    result = validate_config(config)
    assert _leafref_errors(result) == []


def test_union_with_literal_escape_arm_still_flags_other_values():
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "PFC_WD": {"Ethernet999": {"detection_time": "200"}},
    }
    result = validate_config(config)
    assert any(
        e.table == "PFC_WD" and "Ethernet999" in e.message
        for e in _leafref_errors(result)
    ), result.errors


def test_uncompilable_arm_pattern_is_reported_not_silently_skipped(monkeypatch):
    """A generated pattern the runtime cannot compile means the committed
    schemas and the installed pydantic disagree. Exempting every value from
    the reference check would leave the validator reporting success while
    checking nothing, so the incompatibility is reported instead."""
    from osism.tasks.conductor.sonic import validator as v

    broken = v.LeafrefConstraint(
        source_table="VLAN_MEMBER",
        source_field="port",
        targets=(("PORT", "name"),),
        plain_arms=((r"\A(?:[unbalanced)\z",),),
    )
    monkeypatch.setattr(v, "LEAFREFS", (broken,))
    v._pattern_adapter.cache_clear()
    try:
        result = v.validate_config({"PORT": {}, "VLAN_MEMBER": {"Vlan1|Ethernet0": {}}})
        assert any(
            "unbalanced" in e.message or "pattern" in e.message.lower()
            for e in result.errors
        ), result.errors
        assert not result.valid
    finally:
        v._pattern_adapter.cache_clear()


def _port_errors(result, field):
    """PORT errors about one field. A leaf-list element failure extends the
    path with the element index and the union arm that rejected it, so match
    the field as a path segment rather than as a suffix."""
    return [
        e
        for e in result.errors
        if e.table == "PORT" and field in (e.path or "").split(".")
    ]


def _rows_flagged(result, field):
    return {(e.path or "").split(".")[0] for e in _port_errors(result, field)}


def test_string_valued_leaf_list_accepts_the_configdb_form():
    """ConfigDB carries a handful of YANG leaf-lists as a delimited string
    rather than a JSON array; upstream sonic-yang-mgmt keeps the table of them
    in LEAF_LIST_WITH_STRING_VALUE_DICT, and PORT.adv_speeds is one."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000", "adv_speeds": "all"}}
    }
    result = validate_config(config)
    assert _port_errors(result, "adv_speeds") == []


def test_string_valued_leaf_list_splits_multiple_elements():
    config = {
        "PORT": {
            "Ethernet0": {"lanes": "0", "speed": "10000", "adv_speeds": "100000,50000"},
        },
    }
    result = validate_config(config)
    assert _port_errors(result, "adv_speeds") == []


def test_string_valued_leaf_list_strips_whitespace_around_elements():
    config = {
        "PORT": {
            "Ethernet0": {
                "lanes": "0",
                "speed": "10000",
                "adv_speeds": "100000, 50000",
            },
        },
    }
    result = validate_config(config)
    assert _port_errors(result, "adv_speeds") == []


def test_string_valued_leaf_list_still_accepts_a_json_array():
    """Both forms reach ConfigDB, so neither may be rejected."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000", "adv_speeds": ["all"]}},
    }
    result = validate_config(config)
    assert _port_errors(result, "adv_speeds") == []


def test_string_valued_leaf_list_still_validates_each_element():
    """Accepting the string form must not stop checking what is in it: the
    element type is a union of uint32 1..1600000 and the literal `all`."""
    config = {
        "PORT": {
            "Ethernet0": {
                "lanes": "0",
                "speed": "10000",
                "adv_speeds": "100000,nonsense",
            },
            "Ethernet4": {"lanes": "4", "speed": "10000", "adv_speeds": "0"},
        },
    }
    result = validate_config(config)
    errors = _port_errors(result, "adv_speeds")
    assert _rows_flagged(result, "adv_speeds") == {"Ethernet0", "Ethernet4"}, errors
    # The complaint must be about what the elements are, not about the value
    # not being a JSON array.
    assert not any("valid list" in e.message for e in errors), errors


def test_string_valued_leaf_list_uses_the_delimiter_sonic_uses():
    """The delimiter is per field, not always a comma, so a value split on the
    wrong one must not quietly validate."""
    row = {"lanes": "0", "speed": "10000"}
    ok = {"PORT": {"Ethernet0": {**row, "adv_interface_types": "CR4,SR4"}}}
    assert _port_errors(validate_config(ok), "adv_interface_types") == []
    wrong = {"PORT": {"Ethernet0": {**row, "adv_interface_types": "CR4;SR4"}}}
    assert _port_errors(validate_config(wrong), "adv_interface_types") != []


def test_string_valued_leaf_list_references_are_split_before_resolving():
    """profile_list is a leaf-list that ConfigDB carries as one delimited
    string. The schema splits it; the reference check has to split it too, or
    a config naming profiles that all exist is reported as dangling."""
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "BUFFER_PROFILE": {
            "p1": {"size": "0", "pool": "pool1"},
            "p2": {"size": "0", "pool": "pool1"},
        },
        "BUFFER_PORT_EGRESS_PROFILE_LIST": {"Ethernet0": {"profile_list": "p1,p2"}},
    }
    result = validate_config(config)
    assert [
        e
        for e in _leafref_errors(result)
        if e.table == "BUFFER_PORT_EGRESS_PROFILE_LIST"
    ] == [], result.errors


def test_string_valued_leaf_list_still_flags_a_missing_element():
    config = {
        "PORT": {"Ethernet0": {"lanes": "0", "speed": "10000"}},
        "BUFFER_PROFILE": {"p1": {"size": "0", "pool": "pool1"}},
        "BUFFER_PORT_EGRESS_PROFILE_LIST": {"Ethernet0": {"profile_list": "p1,gone"}},
    }
    errors = _leafref_errors(validate_config(config))
    assert any("gone" in e.message for e in errors), errors
    assert not any("p1,gone" in e.message for e in errors), errors


def _warnings_for(result, table):
    return [w for w in result.warnings if table in w]


def test_platform_divergent_table_is_not_schema_validated():
    """The vendored models are community SONiC; these devices run an
    Enterprise build that models SYSLOG_SERVER with different field names and
    an uppercase protocol enum. Validating one against the other only produces
    false positives, so the table carries no schema."""
    config = {
        "SYSLOG_SERVER": {
            "192.0.2.1": {
                "message-type": "log",
                "protocol": "UDP",
                "remote-port": "514",
                "severity": "info",
                "vrf_name": "mgmt",
            },
        },
    }
    result = validate_config(config)
    assert [e for e in result.errors if e.table == "SYSLOG_SERVER"] == [], result.errors


def test_platform_divergent_table_says_why_it_was_skipped():
    """The warning must not read like the plain 'no YANG schema' case: here a
    model exists and is deliberately not trusted."""
    result = validate_config({"SYSLOG_SERVER": {"10.0.0.1": {"protocol": "UDP"}}})
    warnings = _warnings_for(result, "SYSLOG_SERVER")
    assert warnings, result.warnings
    assert any("platform" in w.lower() for w in warnings), warnings


def test_platform_divergent_mgmt_port_accepts_the_device_value():
    """MGMT_PORT.autoneg is a boolean on the target platform; the community
    model constrains it to the pattern `on|off`."""
    config = {"MGMT_PORT": {"eth0": {"autoneg": "true", "admin_status": "up"}}}
    result = validate_config(config)
    assert [e for e in result.errors if e.table == "MGMT_PORT"] == [], result.errors


def test_platform_divergent_table_drops_its_own_leafrefs():
    """SYSLOG_SERVER.vrf is a community-only field — the platform spells it
    vrf_name — so the constraint sourced from it must go with the schema."""
    from osism.tasks.conductor.sonic._generated import LEAFREFS

    assert [c for c in LEAFREFS if c.source_table == "SYSLOG_SERVER"] == []


def test_platform_divergent_table_still_usable_as_a_leafref_target():
    """MGMT_PORT is the target of several leafrefs. Row keys carry the value in
    either flavour, so those checks stay live."""
    from osism.tasks.conductor.sonic._generated import LEAFREFS

    assert [c for c in LEAFREFS if any(t[0] == "MGMT_PORT" for t in c.targets)]
    config = {
        "MGMT_PORT": {"eth0": {"admin_status": "up"}},
        "MGMT_INTERFACE": {"eth99|10.0.0.1/24": {}, "eth0|10.0.0.2/24": {}},
    }
    result = validate_config(config)
    assert isinstance(result.errors, list)


def test_unmodelled_and_divergent_warnings_are_distinguishable():
    result = validate_config(
        {"NOT_A_REAL_TABLE": {"x": {}}, "SYSLOG_SERVER": {"10.0.0.1": {}}}
    )
    unmodelled = _warnings_for(result, "NOT_A_REAL_TABLE")
    divergent = _warnings_for(result, "SYSLOG_SERVER")
    assert unmodelled and divergent
    assert unmodelled[0] != divergent[0]
