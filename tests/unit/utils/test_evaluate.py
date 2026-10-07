# tests/unit/utils/test_evaluate.py
# SPDX-License-Identifier: Apache-2.0

from osism.utils.evaluate import evaluate_request


def _resolver(table, calls=None):
    def resolve(expr):
        if calls is not None:
            calls.append(expr)
        if expr in table:
            return {"value": table[expr]}
        return {"error": f"AnsibleUndefinedVariable: '{expr}' is undefined"}

    return resolve


def _req(names, raw, secrets=(), raw_all=None):
    return {
        "names": names,
        "secrets": list(secrets),
        "raw": raw,
        "raw_all": raw_all or {},
    }


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
    assert r["closures"]["e"]["uses_default"] is True
