# tests/unit/utils/test_hostvars.py
# SPDX-License-Identifier: Apache-2.0

import base64

import pytest

from osism.utils import hostvars as hv
from osism.utils.evaluate import evaluate_request
from osism.utils.render import Stack


@pytest.fixture
def world(mocker):
    def make(
        raw,
        values,
        *,
        global_files=None,
        env_local=None,
        missing=None,
        all_raw=None,
        secrets_names=(),
    ):
        """values: {None: {...}, 'kolla': {...}} rendered per stack (env table overrides global)."""
        calls = []
        env_local = env_local or {}
        mocker.patch.object(hv, "list_environments", return_value=sorted(env_local))
        mocker.patch.object(
            hv,
            "build_stack",
            side_effect=lambda e, root=None: Stack(
                e, ("G",) if e is None else ("G", e), tuple((missing or {}).get(e, ()))
            ),
        )
        gf = dict(global_files or {})
        sec = {n: "x" for n in secrets_names}

        def load_stack_files(stack, pw, allow_missing=False):
            files = [("G/configuration.yml", gf), ("G/secrets.yml", sec)]
            if stack.environment:
                files.append(
                    (
                        f"{stack.environment}/configuration.yml",
                        env_local.get(stack.environment, {}),
                    )
                )
            return files

        mocker.patch.object(hv, "load_stack_files", side_effect=load_stack_files)
        mocker.patch.object(
            hv,
            "environment_local_names",
            side_effect=lambda e, pw, root=None: set(env_local.get(e, {})),
        )

        def renderer(host, request, inv, stack, pw, facts=None, timeout=300):
            calls.append(stack.environment)
            table = {**values.get(None, {}), **values.get(stack.environment, {})}

            def resolve(expr):
                if expr not in table:
                    return {"error": f"AnsibleUndefinedVariable: '{expr}' is undefined"}
                value = table[expr]
                if isinstance(value, Exception):
                    return {"error": f"{type(value).__name__}: {value}"}
                return {"value": value}

            return evaluate_request(resolve, request)

        def rows(variable=None, environment=None, show=False, facts=None):
            return hv.effective_rows(
                "node1",
                variable,
                environment,
                show,
                inventory_path="/inv",
                vault_password="pw",
                facts=facts,
                raw_hostvars=raw,
                all_raw_hostvars=all_raw or {"node1": raw},
                renderer=renderer,
            )

        rows.calls = calls
        return rows

    return make


def _r(rows):
    return [(r.environment, r.value) for r in rows]


def test_rendered_value_and_one_call(world):
    get = world({"a": "{{ b }}", "b": "x"}, {None: {"a": "x", "b": "x"}})
    assert _r(get("a")) == [(None, "x")]
    assert get.calls == [None]


def test_transitive_secret_is_masked_with_source(world):
    rows = world(
        {"redis_connection_string": "redis://default:{{ redis_master_password }}@h"},
        {
            None: {
                "redis_connection_string": "redis://default:s3cr3t-value-123@h",
                "redis_master_password": "s3cr3t-value-123",
            }
        },
        secrets_names={"redis_master_password"},
    )("redis_connection_string")
    assert rows[0].value == "***" and rows[0].notes == [
        "masked: derived from redis_master_password"
    ]


def test_show_secrets_disables_masking(world):
    rows = world(
        {"c": "{{ db_password }}", "db_password": "p"},
        {None: {"c": "verysecret", "db_password": "verysecret"}},
    )("c", show=True)
    assert rows[0].value == "verysecret" and not rows[0].masked


def test_filtered_dynamic_secret_is_masked(world):
    rows = world(
        {"d": "{{ vars[n] | b64encode }}", "n": "db_password", "db_password": "x"},
        {
            None: {
                "d": base64.b64encode(b"long-secret-1").decode(),
                "n": "db_password",
                "db_password": "long-secret-1",
            }
        },
    )("d")
    assert rows[0].masked and "db_password" in rows[0].notes[0]


def test_unresolvable_dynamic_key_is_masked_as_unanalysable(world):
    rows = world(
        {"d": "{{ vars[x.split('-') | first] }}", "x": "a-b"},
        {None: {"d": "v", "x": "a-b"}},
    )("d")
    assert rows[0].masked and rows[0].notes == [
        "masked: could not analyse dependencies"
    ]


def test_benign_dynamic_reference_is_shown(world):
    raw = {
        "h": "{{ hostvars[inventory_hostname]['ansible_' + iface]['ipv4']['address'] }}",
        "iface": "eth0",
    }
    rows = world(
        raw,
        {
            None: {
                "h": "10.0.0.5",
                "'ansible_' + iface": "ansible_eth0",
                "iface": "eth0",
            }
        },
    )("h")
    assert rows[0].value == "10.0.0.5" and not rows[0].masked


def test_cross_host_taint(world):
    raw = {
        "ep": "{{ hostvars[other]['endpoint'] }}",
        "endpoint": "plain",
        "other": "node2",
    }
    all_raw = {"node1": raw, "node2": {"endpoint": "x{{ redis_master_password }}"}}
    rows = world(
        raw,
        {
            None: {
                "ep": "xs3cr3t-value",
                "other": "node2",
                "redis_master_password": "s3cr3t-value",
            }
        },
        all_raw=all_raw,
        secrets_names={"redis_master_password"},
    )("ep")
    assert rows[0].masked


def test_literal_net_catches_unreached_secret(world):
    # Review round 3, point 3: no taint path, yet the secret value appears.
    rows = world(
        {"u": "{{ lookup('env', 'X') }}"},
        {None: {"u": "pre-long-secret-1-post", "db_password": "long-secret-1"}},
        secrets_names={"db_password"},
    )("u")
    assert rows[0].value == "pre-***-post"


def test_environment_row_from_dependency_override_only_for_that_env(world):
    # Review round 3, point 6: global names do not create rows everywhere.
    get = world(
        {"X": "{{ Y }}", "Y": "g", "G1": "1"},
        {None: {"X": "g", "Y": "g", "G1": "1"}, "kolla": {"X": "k", "Y": "k"}},
        env_local={"kolla": {"Y": "k"}, "ceph": {}},
    )
    assert _r(get("X")) == [(None, "g"), ("kolla", "k")]
    assert _r(get("G1")) == [(None, "1")]


def test_environment_row_from_dynamic_dependency(world):
    rows = world(
        {"X": "{{ vars['Y'] }}", "Y": "g"},
        {None: {"X": "g", "Y": "g"}, "kolla": {"X": "k", "Y": "k"}},
        env_local={"kolla": {"Y": "k"}},
    )("X")
    assert ("kolla", "k") in _r(rows)


def test_unanalysable_is_measured_per_environment(world):
    get = world(
        {"X": "{{ vars[y.split('.')|first] }}", "y": "a.b"},
        {None: {"X": "g"}, "kolla": {"X": "k"}, "ceph": {"X": "g"}},
        env_local={"kolla": {}, "ceph": {}},
    )
    assert _r(get("X", show=True)) == [(None, "g"), ("kolla", "k")]


def test_environment_only_variable_in_full_dump_and_single(world):
    # Review round 3, point 5: defined only in kolla/configuration.yml.
    get = world(
        {}, {"kolla": {"kolla_only": "v"}}, env_local={"kolla": {"kolla_only": "v"}}
    )
    assert ("kolla_only", "kolla") in [(r.variable, r.environment) for r in get(None)]
    assert _r(get("kolla_only")) == [("kolla", "v")]


def test_calls_are_one_per_rendered_stack(world):
    get = world(
        {"X": "{{ Y }}", "Y": "g"},
        {None: {"X": "g", "Y": "g"}, "kolla": {"X": "k"}},
        env_local={"kolla": {"Y": "k"}, "ceph": {}, "manager": {}},
    )
    get("X")
    assert sorted(get.calls, key=str) == sorted([None, "kolla"], key=str)


def test_absent_variable_returns_empty(world):
    assert world({"a": "1"}, {None: {"a": "1"}})("nope") == []


def test_unknown_environment_raises_with_list(world):
    get = world({"a": "1"}, {None: {"a": "1"}}, env_local={"kolla": {}, "ceph": {}})
    with pytest.raises(
        hv.HostvarsError, match="unknown environment nope; available: ceph, kolla"
    ):
        get("a", environment="nope")


def test_missing_environment_file_marks_only_candidates(world):
    # Review focus 4
    get = world(
        {"X": "{{ Y }}", "Y": "g", "Z": "z"},
        {None: {"X": "g", "Y": "g", "Z": "z"}},
        env_local={"kolla": {"Y": "k"}},
        missing={"kolla": ("kolla/images.yml",)},
    )
    kolla = [r for r in get("X") if r.environment == "kolla"][0]
    assert kolla.failed and kolla.notes == [
        "render failed: kolla/images.yml missing; this environment cannot be applied"
    ]
    assert _r(get("Z")) == [(None, "z")]
    assert None in get.calls and "kolla" not in get.calls


def test_error_detail_withheld_for_tainted(world):
    rows = world(
        {"c": "{{ db_password | bad }}", "db_password": "x"},
        {
            None: {
                "db_password": "long-secret-1",
                "c": TypeError("No filter named 'bad'"),
            }
        },
    )("c")
    assert rows[0].failed and rows[0].notes == [
        "render failed (detail withheld; use --show-secrets)"
    ]


def test_error_detail_sanitised_for_untainted(mocker):
    mocker.patch.object(hv, "list_environments", return_value=[])
    mocker.patch.object(
        hv, "build_stack", side_effect=lambda e, root=None: Stack(e, ("G",), ())
    )
    mocker.patch.object(
        hv,
        "load_stack_files",
        side_effect=lambda *a, **k: [("G/secrets.yml", {"db_password": "x"})],
    )
    mocker.patch.object(hv, "environment_local_names", return_value=set())

    def renderer(host, request, *a, **k):
        return {
            "values": {
                "u": {"error": "TypeError: cannot use long-secret-1 here"},
                "db_password": {"value": "long-secret-1"},
            },
            "closures": {
                "u": {
                    "names": ["q"],
                    "unanalysable": False,
                    "undefined": ["q"],
                    "secret_hits": [],
                    "fallback": [],
                }
            },
        }

    rows = hv.effective_rows(
        "node1",
        "u",
        None,
        False,
        inventory_path="/inv",
        vault_password="pw",
        facts=None,
        raw_hostvars={"u": "{{ q }}"},
        all_raw_hostvars={"node1": {"u": "{{ q }}"}},
        renderer=renderer,
    )
    assert rows[0].notes == ["render failed: TypeError: cannot use *** here"]


def test_cross_host_vault_value_taints(world):
    raw = {"t": "{{ hostvars['node2']['token'] | b64encode }}"}
    all_raw = {
        "node1": raw,
        "node2": {"token": {"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n61"}},
    }
    rows = world(raw, {None: {"t": "ZW5jb2RlZA=="}}, all_raw=all_raw)("t")
    assert rows[0].masked and rows[0].notes == ["masked: derived from token"]


def test_environment_stack_failure_withholds_ansible_output(world, mocker):
    from osism.utils.render import RenderError

    get = world(
        {"X": "{{ Y }}", "Y": "g"},
        {None: {"X": "g", "Y": "g"}},
        env_local={"kolla": {"Y": "k"}},
    )
    real = hv.effective_rows

    def failing_renderer(host, request, inv, stack, pw, facts=None, timeout=300):
        if stack.environment == "kolla":
            raise RenderError("fatal: kolla-only-secret-xyz leaked", safe=False)
        return evaluate_request(
            lambda e: (
                {"value": {"X": "g", "Y": "g"}[e]}
                if e in ("X", "Y")
                else {"error": f"AnsibleUndefinedVariable: '{e}' is undefined"}
            ),
            request,
        )

    rows = real(
        "node1",
        "X",
        None,
        False,
        inventory_path="/inv",
        vault_password="pw",
        facts=None,
        raw_hostvars={"X": "{{ Y }}", "Y": "g"},
        all_raw_hostvars={"node1": {"X": "{{ Y }}", "Y": "g"}},
        renderer=failing_renderer,
    )
    kolla = [r for r in rows if r.environment == "kolla"][0]
    assert kolla.notes == [
        "render failed (Ansible failed for this stack; detail withheld; use --show-secrets)"
    ]
    assert "kolla-only-secret-xyz" not in repr(rows)


def test_missing_fact_gives_failed_row(world):
    # Review focus 1
    rows = world(
        {"h": "{{ ansible_eth0['ipv4']['address'] }}"},
        {None: {"h": NameError("'ansible_eth0' is undefined")}},
    )("h")
    assert rows[0].failed and rows[0].notes[0].startswith("render failed: ")


def test_fallback_note(world):
    rows = world({"e": "{{ nope | default('fb') }}"}, {None: {"e": "fb"}})("e")
    assert rows[0].notes == ["fallback: nope undefined here, a role may define it"]


def test_nested_secret_masks_whole_value(world):
    # Review focus 2
    rows = world(
        {"s": {"a": ["{{ db_password }}"]}, "db_password": "x"},
        {None: {"s": {"a": ["long-secret-1"]}, "db_password": "long-secret-1"}},
    )("s")
    assert rows[0].value == "***"


# Beyond the brief: paths where a value or an error text could reach output.


def test_unknown_environment_is_not_joined_into_a_path(world):
    get = world({"a": "1"}, {None: {"a": "1"}}, env_local={"kolla": {}})
    with pytest.raises(hv.HostvarsError):
        get("a", environment="../../etc")
    assert hv.build_stack.call_count == 0
    assert hv.environment_local_names.call_count == 0


def test_literal_net_sets_masked(world):
    rows = world(
        {"u": "{{ lookup('env', 'X') }}"},
        {None: {"u": "long-secret-1", "db_password": "long-secret-1"}},
        secrets_names={"db_password"},
    )("u")
    assert rows[0].value == "***" and rows[0].masked


def test_fallback_note_is_sanitised(world):
    # A dynamic key resolving to a secret value enters `undefined`.
    raw = {"e": "{{ vars[k] | default('fb') }}", "k": "{{ q }}"}
    rows = world(
        raw,
        {
            None: {
                "e": "fb",
                "k": "long-secret-1",
                "q": "long-secret-1",
                "db_password": "long-secret-1",
            }
        },
        secrets_names={"db_password"},
    )("e")
    assert rows[0].notes == ["fallback: *** undefined here, a role may define it"]


def test_show_secrets_shows_error_detail(world):
    rows = world(
        {"c": "{{ db_password | bad }}", "db_password": "x"},
        {None: {"db_password": "long-secret-1", "c": TypeError("bad long-secret-1")}},
    )("c", show=True)
    assert rows[0].notes == ["render failed: TypeError: bad long-secret-1"]


def test_primary_unsafe_failure_withheld(mocker):
    from osism.utils.render import RenderError

    mocker.patch.object(hv, "list_environments", return_value=[])
    mocker.patch.object(
        hv, "build_stack", side_effect=lambda e, root=None: Stack(e, ("G",), ())
    )
    mocker.patch.object(hv, "load_stack_files", return_value=[])

    def renderer(*a, **k):
        raise RenderError("fatal: leaked-secret-xyz", safe=False)

    kwargs = dict(
        inventory_path="/inv",
        vault_password="pw",
        facts=None,
        raw_hostvars={"a": "1"},
        all_raw_hostvars={"node1": {"a": "1"}},
        renderer=renderer,
    )
    with pytest.raises(hv.HostvarsError) as exc:
        hv.effective_rows("node1", "a", None, False, **kwargs)
    assert str(exc.value) == hv.STACK_WITHHELD
    assert exc.value.__suppress_context__
    with pytest.raises(hv.HostvarsError, match="leaked-secret-xyz"):
        hv.effective_rows("node1", "a", None, True, **kwargs)


def test_unreadable_environment_fails_its_rows_only(world, mocker):
    from osism.utils.render import RenderError

    get = world({"a": "1"}, {None: {"a": "1"}}, env_local={"kolla": {}})
    hv.environment_local_names.side_effect = RenderError(
        "cannot decrypt kolla/secrets.yml (AnsibleError)"
    )
    rows = get("a")
    assert _r(rows) == [(None, "1"), ("kolla", None)]
    assert rows[1].failed and rows[1].notes == [
        "render failed: cannot decrypt kolla/secrets.yml (AnsibleError)"
    ]


def test_cross_host_plaintext_password_key_is_masked(world):
    # The key rule applies to every host's names, not only the queried one's.
    raw = {
        "bmc": "{{ hostvars['node2']['ipmi_password'] }}",
        "ep": "{{ hostvars['node2']['endpoint'] }}",
    }
    all_raw = {
        "node1": raw,
        "node2": {
            "ipmi_password": "Node2-Plain-Pw",
            "endpoint": "https://admin:{{ ipmi_password }}@x",
        },
    }
    get = world(
        raw,
        {None: {"bmc": "Node2-Plain-Pw", "ep": "https://admin:Node2-Plain-Pw@x"}},
        all_raw=all_raw,
    )
    for name in ("bmc", "ep"):
        rows = get(name)
        assert rows[0].value == "***" and rows[0].masked
        assert rows[0].notes == ["masked: derived from ipmi_password"]
        assert "Node2-Plain-Pw" not in repr(rows)


_VAULT = {"__ansible_vault": "$ANSIBLE_VAULT;1.1;AES256\n61"}


def test_nested_vault_value_is_masked(world):
    raw = {"ldap": {"bind_password": _VAULT, "token": _VAULT}}
    rows = world(
        raw,
        {None: {"ldap": {"bind_password": "ldap-bind-pw-1", "token": "ldap-token-1"}}},
    )("ldap")
    assert rows[0].value == "***" and rows[0].masked
    assert rows[0].notes == ["masked: derived from ldap"]


def test_cross_host_nested_vault_value_is_masked(world):
    raw = {"cfg": "{{ hostvars['node2']['ldap'] }}"}
    all_raw = {"node1": raw, "node2": {"ldap": {"servers": [{"bind": _VAULT}]}}}
    rows = world(
        raw, {None: {"cfg": {"servers": [{"bind": "ldap-bind-pw-1"}]}}}, all_raw=all_raw
    )("cfg")
    assert rows[0].value == "***" and rows[0].masked
    assert rows[0].notes == ["masked: derived from ldap"]


# Final review C1: template shapes that reached a secret unmasked.

_B64 = base64.b64encode(b"s3cr3t-value-123").decode()


@pytest.mark.parametrize(
    "template",
    [
        "{{ lookup('ansible.builtin.vars', 'redis_master_password') | b64encode }}",
        "{{ hostvars[inventory_hostname].get('redis_master_password') | b64encode }}",
        "{{ ['redis_master_password'] | map('extract', vars) | first | b64encode }}",
        "{% set v = vars %}{{ v.redis_master_password | b64encode }}",
    ],
)
def test_unmodelled_secret_shapes_are_masked(world, template):
    rows = world(
        {"enc": template},
        {None: {"enc": _B64, "redis_master_password": "s3cr3t-value-123"}},
        secrets_names={"redis_master_password"},
    )("enc")
    assert rows[0].value == "***" and rows[0].masked
    assert _B64 not in repr(rows)


def test_cross_host_map_extract_plaintext_is_masked(world):
    raw = {
        "bmc_list": "{{ groups['all'] | map('extract', hostvars, 'ipmi_password') "
        "| select('defined') | list }}"
    }
    all_raw = {"node1": raw, "node2": {"ipmi_password": "Node2PlainIpmiPw"}}
    rows = world(raw, {None: {"bmc_list": ["Node2PlainIpmiPw"]}}, all_raw=all_raw)(
        "bmc_list"
    )
    assert rows[0].value == "***" and rows[0].notes == [
        "masked: derived from ipmi_password"
    ]
    assert "Node2PlainIpmiPw" not in repr(rows)


def test_benign_map_extract_hostvars_is_shown(world):
    raw = {
        "names": "{{ groups['all'] | map('extract', hostvars, "
        "['ansible_facts', 'hostname']) | list }}"
    }
    all_raw = {"node1": raw, "node2": {}}
    rows = world(raw, {None: {"names": ["node1", "node2"]}}, all_raw=all_raw)("names")
    assert rows[0].value == ["node1", "node2"] and not rows[0].masked


@pytest.mark.parametrize("template", ["{{ vars }}", "{{ hostvars }}"])
def test_bare_variable_maps_are_masked(world, template):
    rows = world({"all": template}, {None: {"all": {"a": "1"}}})("all")
    assert rows[0].masked and rows[0].notes == [
        "masked: could not analyse dependencies"
    ]


# Final review I2: no false fallback notes.


def test_fact_backed_default_has_no_fallback_note(world):
    raw = {
        "internal_address": "{{ ansible_default_ipv4.address"
        "|default(ansible_all_ipv4_addresses[0]) }}"
    }
    facts = {
        "ansible_default_ipv4": {"address": "192.0.2.10"},
        "ansible_all_ipv4_addresses": ["192.0.2.10"],
    }
    rows = world(raw, {None: {"internal_address": "192.0.2.10"}})(
        "internal_address", facts=facts
    )
    assert rows[0].value == "192.0.2.10" and rows[0].notes == []


def test_d_alias_fallback_note(world):
    rows = world({"e": "{{ nope | d('fb') }}"}, {None: {"e": "fb"}})("e")
    assert rows[0].notes == ["fallback: nope undefined here, a role may define it"]


def test_undefined_outside_default_gets_no_fallback_note(world):
    rows = world(
        {"e": "{{ nope if false else 'x' }}{{ other | default('y') }}"},
        {None: {"e": "xy"}},
    )("e")
    assert rows[0].notes == ["fallback: other undefined here, a role may define it"]
