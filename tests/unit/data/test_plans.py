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
