# SPDX-License-Identifier: Apache-2.0

import pytest

from osism.data.plans import (
    Parallel,
    PlanError,
    Run,
    Select,
    Sequence,
    resolve,
    selection_keys,
)


def test_selection_removes_entire_unselected_subtree():
    shared_tail = Run("glance")
    plan = Select(
        "ceph_backend",
        {
            "ansible": Sequence(Run("ceph"), Run("ceph-pools"), shared_tail),
            "adm": Sequence(Run("cephadm"), Run("cephadm-osds"), shared_tail),
        },
    )
    assert resolve(plan, {"ceph_backend": "adm"}) == Sequence(
        Run("cephadm"),
        Run("cephadm-osds"),
        Run("glance"),
    )


def test_replacement_keeps_consumers_after_selected_prerequisites():
    prerequisite = Select(
        "bootstrap",
        {
            "old": Run("common"),
            "new": Parallel(Run("logs"), Run("toolbox")),
        },
    )
    consumers = Parallel(Run("mariadb"), Run("rabbitmq"))
    assert resolve(Sequence(prerequisite, consumers), {"bootstrap": "new"}) == Sequence(
        Parallel(Run("logs"), Run("toolbox")),
        consumers,
    )


@pytest.mark.parametrize("context", [{}, {"backend": "unknown"}])
def test_selection_fails_closed(context):
    with pytest.raises(PlanError, match="Selection 'backend'"):
        resolve(Select("backend", {"one": Run("a")}), context)


@pytest.mark.parametrize("plan", [Parallel(), Sequence(), "not a plan"])
def test_invalid_plan_rejected(plan):
    with pytest.raises(PlanError):
        resolve(plan, {})


def test_selection_keys_include_nested_alternatives():
    plan = Select(
        "outer",
        {
            "one": Select("inner", {"a": Run("a")}),
            "two": Run("b"),
        },
    )
    assert selection_keys(plan) == {"outer", "inner"}
    # Facts for an unselected alternative are not required during resolution.
    assert resolve(plan, {"outer": "two"}) == Run("b")


def test_selection_copies_alternatives():
    alternatives = {"a": Run("a")}
    plan = Select("backend", alternatives)
    alternatives.clear()
    assert resolve(plan, {"backend": "a"}) == Run("a")


def role_names(plan):
    if isinstance(plan, Run):
        return [plan.name]
    return [name for step in plan.steps for name in role_names(step)]


def ordering_edges(plan):
    """Role order imposed by sequence barriers, independent of Celery flattening."""
    if isinstance(plan, Run):
        return set()
    edges = set().union(*(ordering_edges(step) for step in plan.steps))
    if isinstance(plan, Sequence):
        for before, after in zip(plan.steps, plan.steps[1:]):
            edges.update((a, b) for a in role_names(before) for b in role_names(after))
    return edges


@pytest.mark.parametrize("backend", ["ceph-ansible", "cephadm"])
def test_nutshell_selects_one_complete_ceph_workflow(backend):
    from collections import Counter
    from osism.data.enums import MAP_ROLE2ROLE

    plan = resolve(
        MAP_ROLE2ROLE["nutshell"], {"kvs_backend": "valkey", "ceph_backend": backend}
    )
    names = Counter(role_names(plan))
    for consumer in [
        "glance",
        "cinder",
        "nova",
        "kolla-ceph-rgw",
        "prometheus",
        "grafana",
        "copy-ceph-keys",
        "cephclient",
    ]:
        assert names[consumer] == 1
    if backend == "cephadm":
        assert names["cephadm-bootstrap"] == 1
        assert names["cephadm-osds"] == 1
        assert not names["ceph"]
        assert not names["ceph-pools"]
        assert not names["ceph-bootstrap-dashboard"]
    else:
        assert names["ceph"] == 1
        assert names["ceph-pools"] == 1
        assert not any(name.startswith("cephadm-") for name in names)


def test_cephadm_readiness_order():
    from osism.data.enums import _cephadm_plan

    edges = ordering_edges(_cephadm_plan())
    prefix = [
        "cephadm-bootstrap",
        "cephclient",
        "cephadm-hosts",
        "cephadm-config",
        "cephadm-mons",
        "cephadm-osds",
        "cephadm-pools",
        "copy-ceph-keys",
    ]
    assert set(zip(prefix, prefix[1:])) <= edges
    assert ("copy-ceph-keys", "cephadm-rgw") in edges
    assert ("cephadm-rgw", "wait-for-keystone") in edges
    for consumer in ["kolla-ceph-rgw", "glance", "cinder", "nova"]:
        assert ("wait-for-keystone", consumer) in edges
    assert ("prometheus", "grafana") in edges
    # Do not accidentally serialize monitoring behind RGW readiness.
    assert ("cephadm-rgw", "prometheus") not in edges


@pytest.mark.parametrize(
    "release,expected",
    [
        ((0, 0, 0), "ceph-ansible"),
        ((10, 9, 99), "ceph-ansible"),
        ((11, 0, 0), "cephadm"),
        ((12, 0, 0), "cephadm"),
        ("latest", "cephadm"),
    ],
)
def test_osism_ceph_backend_cutover(release, expected):
    from osism.data.plans import selections_for_osism

    assert selections_for_osism(release) == {"ceph_backend": expected}
