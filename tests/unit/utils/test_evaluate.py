# tests/unit/utils/test_evaluate.py
# SPDX-License-Identifier: Apache-2.0

from osism.utils.evaluate import evaluate_request

from ._fakes import by_name


def _resolver(table, calls=None):
    def resolve(expr):
        if calls is not None:
            calls.append(expr)
        if expr in table:
            return {"value": table[expr]}
        return {"error": f"AnsibleUndefinedVariable: '{expr}' is undefined"}

    return by_name(resolve)


def _req(names, raw, secrets=(), raw_all=None, facts=None):
    request = {
        "names": names,
        "secrets": list(secrets),
        "raw": raw,
        "raw_all": raw_all or {},
    }
    if facts is not None:
        request["facts"] = facts
    return request


def test_static_closure_and_secret_hits():
    r = evaluate_request(
        _resolver({"c": "v", "redis_master_password": "s3cr3t-value-1"}),
        _req(
            ["c"],
            {
                "c": "redis://{{ redis_master_password }}@h",
                "redis_master_password": "x",
            },
            secrets=["redis_master_password"],
        ),
    )
    assert r["closures"]["c"]["secret_hits"] == ["redis_master_password"]


def test_chained_dynamic_keys_resolve_in_one_evaluation():
    calls = []
    raw = {
        "d": "{{ vars[n] | b64encode }}",
        "n": "k1",
        "k1": "{{ vars[m] }}",
        "m": "db_password",
        "db_password": "x",
    }
    r = evaluate_request(
        _resolver(
            {"n": "k1", "m": "db_password", "d": "ZZ", "db_password": "long-secret-1"},
            calls,
        ),
        _req(["d"], raw, secrets=["db_password"]),
    )
    assert r["closures"]["d"]["secret_hits"] == ["db_password"]
    assert not r["closures"]["d"]["unanalysable"]
    assert calls.count("n") == 1 and calls.count("m") == 1


def test_all_secrets_are_rendered_even_when_unreached():
    # Review round 3, point 3: the literal net needs every value in S.
    r = evaluate_request(
        _resolver({"a": "1", "db_password": "long-secret-1"}),
        _req(["a"], {"a": "1"}, secrets=["db_password"]),
    )
    assert r["values"]["db_password"] == {"value": "long-secret-1"}


def test_unresolvable_key_is_unanalysable():
    r = evaluate_request(
        _resolver({}), _req(["d"], {"d": "{{ vars[x.split('-') | first] }}"})
    )
    assert r["closures"]["d"]["unanalysable"]


def test_key_render_error_is_unanalysable():
    r = evaluate_request(_resolver({}), _req(["d"], {"d": "{{ vars[n] }}"}))
    assert r["closures"]["d"]["unanalysable"]


def test_cross_host_uses_every_hosts_definition():
    raw = {
        "ep": "{{ hostvars[other]['endpoint'] }}",
        "endpoint": "plain",
        "other": "node2",
    }
    r = evaluate_request(
        _resolver({}),
        _req(
            ["ep"],
            raw,
            secrets=["redis_master_password"],
            raw_all={"endpoint": ["plain", "x{{ redis_master_password }}"]},
        ),
    )
    assert r["closures"]["ep"]["secret_hits"] == ["redis_master_password"]


def test_undefined_and_default_are_reported():
    r = evaluate_request(
        _resolver({"e": "fb"}), _req(["e"], {"e": "{{ nope | default('fb') }}"})
    )
    assert r["closures"]["e"]["undefined"] == ["nope"]
    assert r["closures"]["e"]["fallback"] == ["nope"]


# Final review I2: a fallback note needs an undefined name under default/d.


def test_fact_names_count_as_defined():
    raw = {
        "internal_address": "{{ ansible_default_ipv4.address"
        "|default(ansible_all_ipv4_addresses[0]) }}"
    }
    r = evaluate_request(
        _resolver({"internal_address": "192.0.2.10"}),
        _req(
            ["internal_address"],
            raw,
            facts=["ansible_all_ipv4_addresses", "ansible_default_ipv4"],
        ),
    )
    assert r["closures"]["internal_address"]["undefined"] == []
    assert r["closures"]["internal_address"]["fallback"] == []


def test_d_alias_is_a_fallback():
    r = evaluate_request(_resolver({}), _req(["e"], {"e": "{{ nope | d('fb') }}"}))
    assert r["closures"]["e"]["fallback"] == ["nope"]


def test_undefined_outside_default_is_not_a_fallback():
    r = evaluate_request(
        _resolver({}),
        _req(["e"], {"e": "{{ nope }}-{{ other | default('x') }}"}),
    )
    assert r["closures"]["e"]["undefined"] == ["nope", "other"]
    assert r["closures"]["e"]["fallback"] == ["other"]


def test_default_argument_and_nested_values_are_fallbacks():
    r = evaluate_request(
        _resolver({}),
        _req(
            ["e", "a"],
            {
                "e": {"k": ["{{ x | default(y) }}"]},
                "a": "{{ e }}",
            },
        ),
    )
    assert r["closures"]["e"]["fallback"] == ["x", "y"]
    assert r["closures"]["a"]["fallback"] == ["x", "y"]


# Final review minor 3: names are looked up, never templated as expressions.


def _vars_resolver(table, calls):
    def resolve(expr):
        calls.append(expr)
        for name, value in table.items():
            if expr == f"{name!r} in vars":
                return {"value": True}
            if expr == f"vars[{name!r}]":
                return {"value": value}
        if expr.endswith(" in vars"):
            return {"value": False}
        return {"error": f"TypeError: unexpected expression {expr}"}

    return resolve


def test_names_are_resolved_as_vars_lookups():
    calls = []
    r = evaluate_request(
        _vars_resolver({"a ~ db_password": "lit", "b": 1}, calls),
        _req(["a ~ db_password", "b"], {"a ~ db_password": "lit", "b": 1}),
    )
    assert r["values"]["a ~ db_password"] == {"value": "lit"}
    assert r["values"]["b"] == {"value": 1}
    assert "a ~ db_password" not in calls and "b" not in calls


def test_absent_name_reports_undefined():
    r = evaluate_request(_vars_resolver({}, []), _req(["zz"], {}))
    assert r["values"]["zz"] == {"error": "AnsibleUndefinedVariable: 'zz' is undefined"}
