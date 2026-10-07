# SPDX-License-Identifier: Apache-2.0

import json

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


# Final review C1: shapes that reached a secret without being modelled.


def test_fqcn_vars_lookup_is_a_reference():
    for plugin in ("vars", "ansible.builtin.vars", "ansible.legacy.vars"):
        r = references(f"{{{{ lookup('{plugin}', 'redis_master_password') }}}}")
        assert r.names == {"redis_master_password"} and not r.unanalysable
        r = references(f"{{{{ query('{plugin}', n) | first }}}}")
        assert [k.expression for k in r.dynamic_keys] == ["n"]


def test_get_on_vars_and_hostvars_is_a_subscript():
    r = references(
        "{{ hostvars[inventory_hostname].get('redis_master_password') | b64encode }}"
    )
    assert r.names == {"redis_master_password"} and not r.unanalysable
    assert references("{{ vars.get('a', 'x') }}").names == {"a"}
    r = references("{{ hostvars[h].get('endpoint') }}")
    assert r.cross_host_names == {"endpoint"} and r.names == {"h"}
    assert references("{{ hostvars.node2.get('endpoint') }}").cross_host_names == {
        "endpoint"
    }
    r = references("{{ vars.get(n) }}")
    assert [k.expression for k in r.dynamic_keys] == ["n"] and "get" not in r.names


def test_mapping_methods_are_unanalysable():
    for expr in (
        "{{ vars.get }}",
        "{{ vars.values() | list }}",
        "{{ vars.items() | list }}",
        "{{ hostvars[h].values() | list }}",
        "{{ hostvars.node2.keys() | list }}",
        "{{ hostvars.raw_get('node2') }}",
        "{{ hostvars[h]._vars }}",
    ):
        assert references(expr).unanalysable, expr


def test_map_extract_vars_is_modelled_by_its_constant_items():
    r = references(
        "{{ ['redis_master_password'] | map('extract', vars) | first | b64encode }}"
    )
    assert r.names == {"redis_master_password"} and not r.unanalysable
    assert references("{{ names | map('extract', vars) | list }}").unanalysable


def test_map_extract_hostvars_first_key_is_cross_host():
    r = references(
        "{{ groups['all'] | map('extract', hostvars, 'ipmi_password') "
        "| select('defined') | list }}"
    )
    assert r.cross_host_names == {"ipmi_password"} and not r.unanalysable
    r = references(
        "{{ groups['x'] | map('extract', hostvars, ['ansible_facts', 'hostname']) "
        "| list }}"
    )
    assert r.cross_host_names == {"ansible_facts"} and not r.unanalysable
    assert references("{{ groups['x'] | map('extract', hostvars, k) }}").unanalysable
    assert references("{{ groups['x'] | map('extract', hostvars) }}").unanalysable


def test_alias_of_vars_is_unanalysable():
    assert references(
        "{% set v = vars %}{{ v.redis_master_password | b64encode }}"
    ).unanalysable


def test_bare_vars_and_hostvars_are_unanalysable():
    assert references("{{ vars }}").unanalysable
    assert references("{{ hostvars }}").unanalysable
    assert references("{{ hostvars[inventory_hostname] }}").unanalysable
    assert references("{{ hostvars | dict2items }}").unanalysable
    assert references("{{ 'x' | extract(vars) }}").unanalysable


def test_star_args_to_a_vars_lookup_are_unanalysable():
    assert references("{{ lookup('vars', *names) }}").unanalysable
    assert references("{{ vars.get(*names) }}").unanalysable


def test_defaulted_names_are_those_under_default_or_d():
    r = references("{{ a | default(b) }}{{ c | d('x') }}{{ e }}")
    assert r.defaulted == {"a", "b", "c"}
    r = references("{{ vars[k] | default('fb') }}")
    assert r.dynamic_keys[0].defaulted is True
    assert references("{{ vars[k] }}").dynamic_keys[0].defaulted is False
    assert references({"x": ["{{ hostvars[h]['p'] | default(1) }}"]}).defaulted == {
        "h",
        "p",
    }


def test_unsafe_text_survives_the_request_as_a_literal():
    from osism.utils.template_deps import UnsafeText, encode_unsafe

    raw = {"a": UnsafeText("{{ secret_password }}"), "b": ["{{ c }}"]}
    assert references(raw).names == {"c"}
    encoded = json.loads(json.dumps(encode_unsafe(raw)))
    assert references(encoded).names == {"c"}
