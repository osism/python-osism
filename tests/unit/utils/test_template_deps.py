# SPDX-License-Identifier: Apache-2.0

from osism.utils.template_deps import references


def test_plain_names():
    r = references("{{ a }}-{{ b | default('x') }}")
    assert r.names == {"a", "b"} and not r.unanalysable


def test_unknown_filters_do_not_break_analysis():
    r = references("{{ s | b64encode }} {{ 'api' | kolla_address(host) }}")
    assert r.names == {"s", "host"} and not r.unanalysable


def test_constant_vars_subscript_yields_target():
    assert references("{{ vars['Y'] }}").names == {"Y"}


def test_constant_hostvars_subscript_same_host():
    r = references("{{ hostvars[inventory_hostname]['Y'] }}")
    assert r.names == {"Y"} and r.cross_host_names == frozenset()


def test_constant_hostvars_subscript_other_host_is_cross_host():
    r = references("{{ hostvars[h]['Y'] }}")
    assert "Y" in r.cross_host_names and "h" in r.names


def test_dynamic_key_is_unparsed():
    r = references(
        "{{ hostvars[inventory_hostname]['ansible_' + management_interface]['ipv4'] }}"
    )
    assert [k.expression for k in r.dynamic_keys] == [
        "'ansible_' + management_interface"
    ]
    assert "management_interface" in r.names


def test_dynamic_key_unparseable_expression_is_none():
    r = references("{{ vars[x.split('-') | first] }}")
    assert r.dynamic_keys[0].expression is None


def test_lookup_vars_constant_and_dynamic():
    assert "Y" in references("{{ lookup('vars', 'Y') }}").names
    assert references("{{ lookup('vars', n) }}").dynamic_keys


def test_loop_and_set_names_are_not_references():
    r = references(
        "{% for host in groups['x'] %}{{ hostvars[host]['id'] }}{% endfor %}"
        "{% set z = 1 %}{{ z }}"
    )
    assert "host" not in r.names and "z" not in r.names
    assert "id" in r.cross_host_names


def test_recurses_into_structures():
    # Review focus 2
    r = references({"a": ["{{ redis_master_password }}", 2], "b": "lit"})
    assert r.names == {"redis_master_password"}


def test_attribute_forms_are_references():
    assert references("{{ vars.db_password | b64encode }}").names == {"db_password"}
    r = references("{{ hostvars[h].endpoint }}")
    assert r.cross_host_names == {"endpoint"} and r.names == {"h"}
    assert references("{{ hostvars.node2.endpoint }}").cross_host_names == {"endpoint"}
    assert references("{{ hostvars[inventory_hostname].Y }}").names == {"Y"}


def test_later_binding_does_not_hide_earlier_reference():
    r = references(
        "{{ db_password }}{% for db_password in [] %}{{ db_password }}{% endfor %}"
    )
    assert r.names == {"db_password"}


def test_set_binds_only_after_itself():
    assert references("{{ z }}{% set z = 1 %}{{ z }}").names == {"z"}
    assert references("{% set z = 1 %}{{ z }}").names == frozenset()


def test_if_branches_are_walked():
    r = references("{% if a %}{{ b }}{% elif c %}{{ d }}{% else %}{{ e }}{% endif %}")
    assert r.names == {"a", "b", "c", "d", "e"}


def test_dynamic_key_using_bound_name_is_unresolvable():
    assert [
        k.expression
        for k in references(
            "{% set n = 'db_password' %}{{ vars[n] | b64encode }}"
        ).dynamic_keys
    ] == [None]
    assert [
        k.expression
        for k in references(
            "{% for n in ['a'] %}{{ vars[n] }}{% endfor %}"
        ).dynamic_keys
    ] == [None]
    assert [k.expression for k in references("{{ vars[n] }}").dynamic_keys] == ["n"]


def test_macro_is_unanalysable():
    assert (
        references("{% macro m() %}{{ x }}{% endmacro %}{{ m() }}").unanalysable is True
    )


def test_syntax_error_is_unanalysable():
    assert references("{{ a ").unanalysable is True


def test_non_template_string_has_no_refs():
    r = references("plain")
    assert r.names == frozenset() and not r.dynamic_keys
