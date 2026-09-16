# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism apply`` command.

The apply command routes a role to one of the celery task queues
(osism-ansible, ceph-ansible, kolla-ansible, kubernetes) based on the
role-to-environment mapping, expands collections into task groups and
chains, and retries failed roles. These tests characterize:

- ``_prepare_task``: environment resolution (explicit, mapped, ``custom``
  fallback), prefix stripping (``ceph-``/``kolla-``), sub-environments,
  the ``kolla_action`` extra argument and the osism-ansible runtime
  override;
- ``_handle_collection``/``handle_collection``: recursive group/chain
  construction from explicit execution plans, dry-run (noop tasks), show-tree
  (log-only) mode and the scheduling/log contract;
- ``handle_role``/``handle_loadbalancer_task``: exit-code pass-through,
  the ``GroupResult`` dispatch and the child-task semantics (a group
  failure propagates as an exception; a strict xfail pins that a failed
  child must propagate its rc);
- ``take_action``: task-lock enforcement, the role/environment table,
  the time-based Ansible-facts freshness check, ``//`` role splitting,
  retries and the collection branch (a strict xfail pins that a
  successful collection must not skip the following ``//`` segments).
"""

import time
import types
from unittest.mock import MagicMock, call, patch

import pytest

from osism import utils as osism_utils
from osism.commands import apply
from osism.data import enums, playbooks
from osism.data.plans import Parallel, Run, Select, Sequence

from ._helpers import assert_not_called_before_lock_check, make_command, parse_args


@pytest.fixture(autouse=True)
def _reset_lazy_state():
    """Keep lazily initialized module state from leaking between tests.

    ``osism.data.playbooks`` caches the playbook maps injected via
    ``_set_playbook_maps`` and ``take_action`` stores the facts-check
    backoff timestamp on ``osism.utils``.
    """
    osism_utils.__dict__.pop("_last_ansible_facts_check", None)
    yield
    playbooks._reset_caches()
    osism_utils.__dict__.pop("_last_ansible_facts_check", None)


@pytest.fixture
def task_mocks(mocker):
    """Patch the celery task entry points used by ``_prepare_task``."""
    return types.SimpleNamespace(
        ansible_run=mocker.patch("osism.tasks.ansible.run"),
        ansible_noop=mocker.patch("osism.tasks.ansible.noop"),
        ceph_run=mocker.patch("osism.tasks.ceph.run"),
        kolla_run=mocker.patch("osism.tasks.kolla.run"),
        kubernetes_run=mocker.patch("osism.tasks.kubernetes.run"),
    )


@pytest.fixture
def take_action_mocks(mocker):
    """Patch the utils helpers consulted by ``take_action``."""
    return types.SimpleNamespace(
        lock=mocker.patch("osism.commands.apply.utils.check_task_lock_and_exit"),
        facts=mocker.patch("osism.commands.apply.utils.check_ansible_facts"),
    )


def _set_playbook_maps(role2environment=None, role2runtime=None):
    """Inject the lazy playbook maps; the autouse fixture resets them."""
    playbooks.MAP_ROLE2ENVIRONMENT = role2environment or {}
    playbooks.MAP_ROLE2RUNTIME = role2runtime or {}


def _prepare_task(cmd, **overrides):
    params = dict(
        arguments=[],
        environment=None,
        overwrite=None,
        sub=None,
        role="testrole",
        action="deploy",
        wait=True,
        format="log",
        timeout=300,
        task_timeout=3600,
    )
    params.update(overrides)
    return cmd._prepare_task(**params)


def _public_collection_kwargs(**overrides):
    params = dict(
        arguments=[],
        environment=None,
        overwrite=None,
        sub=None,
        collection="testcollection",
        action="deploy",
        wait=True,
        format="log",
        timeout=300,
        task_timeout=3600,
        retry=0,
        dry_run=False,
        show_tree=False,
        release=None,
    )
    params.update(overrides)
    return params


def _collection_kwargs(**overrides):
    counter = overrides.pop("counter", 0)
    params = _public_collection_kwargs(**overrides)
    params["counter"] = counter
    return params


def _handle_role(cmd, **overrides):
    params = dict(
        arguments=[],
        environment=None,
        overwrite=None,
        sub=None,
        role="testrole",
        action="deploy",
        wait=True,
        format="log",
        timeout=300,
        task_timeout=3600,
    )
    params.update(overrides)
    return cmd.handle_role(**params)


# _prepare_task


def test_prepare_task_ceph_role_forces_ceph_environment(task_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="ceph", environment=None, arguments=["-v"])

    task_mocks.ceph_run.si.assert_called_once_with(
        "ceph", "ceph", ["-v"], auto_release_time=3600
    )
    assert t is task_mocks.ceph_run.si.return_value


def test_prepare_task_strips_ceph_prefix(task_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="ceph-osds", environment="ceph")

    task_mocks.ceph_run.si.assert_called_once_with(
        "ceph", "osds", [], auto_release_time=3600
    )
    assert t is task_mocks.ceph_run.si.return_value


def test_prepare_task_ceph_role_in_osism_ansible_runtime(task_mocks):
    """A ceph-environment play shipped by osism-ansible (the cephadm deploy
    plays, and the ceph validators) must run in the osism-ansible runtime, not
    in the ceph-ansible container which has no such playbook."""
    _set_playbook_maps(
        role2environment={"cephadm-bootstrap": "ceph"},
        role2runtime={"osism-ansible": ["cephadm-bootstrap"]},
    )
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="cephadm-bootstrap", arguments=["-e x=1"])

    task_mocks.ansible_run.si.assert_called_once_with(
        "ceph", "cephadm-bootstrap", ["-e x=1"], auto_release_time=3600
    )
    task_mocks.ceph_run.si.assert_not_called()
    assert t is task_mocks.ansible_run.si.return_value


def test_prepare_task_ceph_ansible_role_still_reaches_ceph_ansible(task_mocks):
    """This looks like a duplicate of test_prepare_task_strips_ceph_prefix but
    is not: that test runs with EMPTY maps, so the override's guard is never
    evaluated (it fails the runtime-membership check trivially). Here
    role2runtime populates "ceph-ansible" (not "osism-ansible"), so the guard
    is actually evaluated and must decline -- proving the override only claims
    roles osism-ansible advertises for the ceph environment, and ceph-ansible's
    own roles still reach ceph-ansible with the ceph- prefix stripped."""
    _set_playbook_maps(
        role2environment={"ceph-mons": "ceph"},
        role2runtime={"ceph-ansible": ["ceph-mons"]},
    )
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="ceph-mons", arguments=[])

    task_mocks.ceph_run.si.assert_called_once_with(
        "ceph", "mons", [], auto_release_time=3600
    )
    task_mocks.ansible_run.si.assert_not_called()
    assert t is task_mocks.ceph_run.si.return_value


def test_prepare_task_ceph_override_ignores_other_environments(task_mocks):
    """The environment check is what stops the override swallowing an
    osism-ansible role registered for a DIFFERENT environment."""
    _set_playbook_maps(
        role2environment={"facts": "generic"},
        role2runtime={"osism-ansible": ["facts"]},
    )
    cmd = make_command(apply.Run)

    _prepare_task(cmd, role="facts", arguments=[])

    task_mocks.ceph_run.si.assert_not_called()


def test_prepare_task_sub_environment_suffix(task_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)

    _prepare_task(cmd, role="ceph-osds", environment="ceph", sub="zone-a")
    _prepare_task(cmd, role="kubeadm", environment="kubernetes", sub="zone-a")
    _prepare_task(cmd, role="keystone", environment="kolla", sub="zone-a")

    task_mocks.ceph_run.si.assert_called_once_with(
        "ceph.zone-a", "osds", [], auto_release_time=3600
    )
    task_mocks.kubernetes_run.si.assert_called_once_with(
        "kubernetes.zone-a", "kubeadm", [], auto_release_time=3600
    )
    task_mocks.kolla_run.si.assert_called_once_with(
        "kolla.zone-a", "keystone", ["-e kolla_action=deploy"], auto_release_time=3600
    )


def test_prepare_task_kubernetes_environment_from_mapping(task_mocks):
    _set_playbook_maps(role2environment={"kubeadm": "kubernetes"})
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="kubeadm", arguments=["-l node1"])

    task_mocks.kubernetes_run.si.assert_called_once_with(
        "kubernetes", "kubeadm", ["-l node1"], auto_release_time=3600
    )
    assert t is task_mocks.kubernetes_run.si.return_value


def test_prepare_task_kolla_strips_prefix_and_adds_action(task_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)

    t = _prepare_task(
        cmd, role="kolla-keystone", environment="kolla", arguments=["-l control"]
    )

    task_mocks.kolla_run.si.assert_called_once_with(
        "kolla",
        "keystone",
        ["-e kolla_action=deploy", "-l control"],
        auto_release_time=3600,
    )
    assert t is task_mocks.kolla_run.si.return_value


def test_prepare_task_kolla_role_in_osism_ansible_runtime(task_mocks):
    _set_playbook_maps(
        role2environment={"keystone": "kolla"},
        role2runtime={"osism-ansible": ["keystone"]},
    )
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="keystone", arguments=["-l control"])

    task_mocks.ansible_run.si.assert_called_once_with(
        "kolla", "keystone", ["-l control"], auto_release_time=3600
    )
    task_mocks.kolla_run.si.assert_not_called()
    assert t is task_mocks.ansible_run.si.return_value


def test_prepare_task_kolla_facts_reaches_kolla_ansible(task_mocks):
    """A kolla-ansible playbook whose bare name collides with an osism-ansible
    playbook registered for a DIFFERENT environment must still reach
    kolla-ansible. osism-ansible ships generic/facts.yml, so it advertises
    `facts -> generic`; kolla-ansible advertises `kolla-facts -> kolla`. The
    runtime override may only claim roles osism-ansible registered *for kolla*
    (stepca, fix-gh973, ...), never a generic one."""
    _set_playbook_maps(
        role2environment={"facts": "generic", "kolla-facts": "kolla"},
        role2runtime={"osism-ansible": ["facts"], "kolla-ansible": ["kolla-facts"]},
    )
    cmd = make_command(apply.Run)

    _prepare_task(cmd, role="facts", environment="kolla")
    _prepare_task(cmd, role="kolla-facts")

    assert task_mocks.kolla_run.si.call_count == 2
    task_mocks.kolla_run.si.assert_has_calls(
        [
            call("kolla", "facts", ["-e kolla_action=deploy"], auto_release_time=3600),
            call("kolla", "facts", ["-e kolla_action=deploy"], auto_release_time=3600),
        ]
    )
    task_mocks.ansible_run.si.assert_not_called()


def test_prepare_task_kolla_environment_osism_role_still_overrides(task_mocks):
    """The override's real purpose keeps working: a role osism-ansible registers
    *for the kolla environment* (playbooks/kolla/stepca.yml) runs in
    osism-ansible, not kolla-ansible."""
    _set_playbook_maps(
        role2environment={"stepca": "kolla"},
        role2runtime={"osism-ansible": ["stepca"]},
    )
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="stepca")

    task_mocks.ansible_run.si.assert_called_once_with(
        "kolla", "stepca", [], auto_release_time=3600
    )
    task_mocks.kolla_run.si.assert_not_called()
    assert t is task_mocks.ansible_run.si.return_value


def test_prepare_task_common_role_stays_in_kolla(task_mocks):
    _set_playbook_maps(
        role2environment={"common": "kolla"},
        role2runtime={"osism-ansible": ["common"]},
    )
    cmd = make_command(apply.Run)

    _prepare_task(cmd, role="common")

    task_mocks.kolla_run.si.assert_called_once_with(
        "kolla", "common", ["-e kolla_action=deploy"], auto_release_time=3600
    )
    task_mocks.ansible_run.si.assert_not_called()


def test_prepare_task_unknown_role_falls_back_to_custom(task_mocks, loguru_logs):
    _set_playbook_maps()
    cmd = make_command(apply.Run)

    t = _prepare_task(cmd, role="myplay", arguments=["-v"])

    task_mocks.ansible_run.si.assert_called_once_with(
        "custom", "myplay", ["-v"], auto_release_time=3600
    )
    messages = [r["message"] for r in loguru_logs]
    assert "Trying to run play myplay in environment custom" in messages
    assert t is task_mocks.ansible_run.si.return_value


def test_prepare_task_overwrite_replaces_default_environment(task_mocks):
    _set_playbook_maps(role2environment={"myplay": "generic"})
    cmd = make_command(apply.Run)

    _prepare_task(cmd, role="myplay", overwrite="other")

    task_mocks.ansible_run.si.assert_called_once_with(
        "other", "myplay", [], auto_release_time=3600
    )


# _handle_collection


def test_handle_collection_parallel_and_sequence(mocker):
    cmd = make_command(apply.Run)
    prepare = mocker.patch.object(cmd, "_prepare_task", side_effect=lambda *a: a[4])
    group = mocker.patch(
        "celery.group", side_effect=lambda steps: ("parallel", tuple(steps))
    )
    chain = mocker.patch("celery.chain", side_effect=lambda *steps: ("sequence", steps))
    result = cmd._handle_collection(
        Parallel(Sequence(Run("parent"), Parallel(Run("a"), Run("b"))), Run("peer")),
        **_collection_kwargs(),
    )
    assert result == (
        "parallel",
        (("sequence", ("parent", ("parallel", ("a", "b")))), "peer"),
    )
    assert prepare.call_count == 4
    assert group.call_count == 2
    chain.assert_called_once()


@pytest.mark.parametrize("show_tree,dry_run", [(True, False), (False, True)])
def test_handle_collection_preview_never_prepares_roles(
    mocker, task_mocks, show_tree, dry_run
):
    cmd = make_command(apply.Run)
    prepare = mocker.patch.object(cmd, "_prepare_task")
    cmd._handle_collection(
        Parallel(Run("a"), Run("b")),
        **_collection_kwargs(show_tree=show_tree, dry_run=dry_run),
    )
    prepare.assert_not_called()
    assert task_mocks.ansible_noop.si.call_count == (0 if show_tree else 2)


# handle_collection


def test_handle_collection_applies_prepared_group(loguru_logs):
    cmd = make_command(apply.Run)
    prepared = MagicMock()
    cmd._handle_collection = MagicMock(return_value=prepared)
    collection_roles = Parallel(Run("a"))

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": collection_roles}):
        cmd.handle_collection(**_public_collection_kwargs())

    args = cmd._handle_collection.call_args
    assert args.args[0] is collection_roles
    assert args.args[1] == 0
    prepared.apply_async.assert_called_once_with()
    messages = [r["message"] for r in loguru_logs]
    assert "Collection testcollection is prepared for execution" in messages
    assert (
        "All tasks of the collection testcollection are prepared for execution"
        in messages
    )
    assert "Tasks are running in the background" in messages


def test_handle_collection_returns_zero_exit_code(loguru_logs):
    """``handle_collection`` has to return an exit code, not ``None``.

    ``take_action`` tests the result with ``if rc != 0``, and ``None != 0`` is
    True, so returning ``None`` made every collection look like a failure and
    skip the remaining ``//`` segments.
    """
    cmd = make_command(apply.Run)
    cmd._handle_collection = MagicMock(return_value=MagicMock())

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("a"))}):
        rc = cmd.handle_collection(**_public_collection_kwargs())

    assert rc == 0


def test_handle_collection_show_tree_does_not_apply(loguru_logs):
    cmd = make_command(apply.Run)
    prepared = MagicMock()
    cmd._handle_collection = MagicMock(return_value=prepared)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("a"))}):
        cmd.handle_collection(**_public_collection_kwargs(show_tree=True))

    prepared.apply_async.assert_not_called()
    messages = [r["message"] for r in loguru_logs]
    assert "Showing execution tree for collection testcollection" in messages
    assert "Tasks are running in the background" not in messages


def test_handle_collection_dry_run_logs_but_still_applies(loguru_logs):
    """Characterize current behavior: the dry-run log claims that no tasks
    are scheduled (as does the ``--dry-run`` help text), but the prepared
    (noop) group is still applied async and occupies the queue. Follow-up:
    either skip ``apply_async`` under dry-run or fix log and help text."""
    cmd = make_command(apply.Run)
    prepared = MagicMock()
    cmd._handle_collection = MagicMock(return_value=prepared)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("a"))}):
        cmd.handle_collection(**_public_collection_kwargs(dry_run=True))

    prepared.apply_async.assert_called_once_with()
    messages = [r["message"] for r in loguru_logs]
    assert "Dry run for collection testcollection. No tasks are scheduled." in messages
    assert "Tasks are running in the background" not in messages


# handle_role / handle_loadbalancer_task


def test_handle_role_passes_rc_from_handle_task(mocker):
    handle_task = mocker.patch("osism.tasks.handle_task", return_value=3)
    cmd = make_command(apply.Run)
    cmd._prepare_task = MagicMock()
    task = cmd._prepare_task.return_value.apply_async.return_value

    rc = _handle_role(cmd)

    assert rc == 3
    assert cmd._prepare_task.call_args.args[4] == "testrole"
    handle_task.assert_called_once_with(task, True, "log", 300)


def test_handle_role_group_result_routes_to_loadbalancer_handler(mocker):
    from celery.result import GroupResult

    handle_task = mocker.patch("osism.tasks.handle_task")
    cmd = make_command(apply.Run)
    cmd._prepare_task = MagicMock()
    task = MagicMock(spec=GroupResult)
    task.task_id = "group-task-id"
    cmd._prepare_task.return_value.apply_async.return_value = task
    cmd.handle_loadbalancer_task = MagicMock(return_value=5)

    rc = _handle_role(cmd, role="loadbalancer")

    assert rc == 5
    cmd.handle_loadbalancer_task.assert_called_once_with(task, True, "log", 300)
    handle_task.assert_not_called()


def test_handle_loadbalancer_task_wait_uses_parent_rc(mocker, loguru_logs):
    handle_task = mocker.patch("osism.tasks.handle_task", return_value=2)
    cmd = make_command(apply.Run)
    t = MagicMock()
    t.children = [MagicMock(task_id="child-1"), MagicMock(task_id="child-2")]

    rc = cmd.handle_loadbalancer_task(t, True, "log", 300)

    assert rc == 2
    handle_task.assert_called_once_with(t.parent, True, "log", 300)
    t.parent.get.assert_not_called()
    t.get.assert_called_once_with()
    messages = [r["message"] for r in loguru_logs]
    assert any(
        "Task child-1 (loadbalancer) is running in background" in m for m in messages
    )
    assert any(
        "Task child-2 (loadbalancer) is running in background" in m for m in messages
    )


def test_handle_loadbalancer_task_no_wait_collects_parent(mocker):
    handle_task = mocker.patch("osism.tasks.handle_task", return_value=0)
    cmd = make_command(apply.Run)
    t = MagicMock()
    t.children = []

    rc = cmd.handle_loadbalancer_task(t, False, "log", 300)

    assert rc == 0
    handle_task.assert_called_once_with(t.parent, False, "log", 300)
    t.parent.get.assert_called_once_with()
    t.get.assert_called_once_with()


@pytest.mark.xfail(
    strict=True,
    reason="handle_loadbalancer_task returns only the parent rc and reads the "
    "children solely for logging, so a failed loadbalancer child playbook "
    "still exits 0; the child rcs have to be read the same way as the parent "
    "rc (handle_task / the task-output stream) and the worst one propagated",
)
def test_handle_loadbalancer_task_child_failure_propagates(mocker):
    """A non-zero rc recorded for a child task must surface in the return
    value. The rc lives in the task-output stream read by ``handle_task``,
    not in the Celery result, so ``child.get()`` cannot supply it."""
    cmd = make_command(apply.Run)
    t = MagicMock()
    child = MagicMock(task_id="child-1")
    t.children = [child]

    def fake_handle_task(task, wait, format, timeout):
        return 99 if task is child else 0

    mocker.patch("osism.tasks.handle_task", side_effect=fake_handle_task)

    rc = cmd.handle_loadbalancer_task(t, True, "log", 300)

    assert rc == 99


def test_handle_loadbalancer_task_group_failure_propagates(mocker):
    handle_task = mocker.patch("osism.tasks.handle_task", return_value=0)
    cmd = make_command(apply.Run)
    t = MagicMock()
    t.children = [MagicMock(task_id="child-1")]
    t.get.side_effect = RuntimeError("child task failed")

    with pytest.raises(RuntimeError, match="child task failed"):
        cmd.handle_loadbalancer_task(t, True, "log", 300)

    handle_task.assert_called_once_with(t.parent, True, "log", 300)


def test_handle_loadbalancer_task_absorbs_ansible_failure(mocker):
    """A failed play must not surface as a traceback here.

    Now that the task raises on a non-zero Ansible rc, ``t.get()`` re-raises
    it. The rc has already been read from the task-output stream by
    ``handle_task``, so the exception carries no new information and must be
    absorbed -- unlike the unexpected exceptions pinned above, which still
    propagate.
    """
    from osism.tasks import AnsibleFailure

    handle_task = mocker.patch("osism.tasks.handle_task", return_value=4)
    cmd = make_command(apply.Run)
    t = MagicMock()
    t.children = [MagicMock(task_id="child-1")]
    t.get.side_effect = AnsibleFailure("play failed")

    rc = cmd.handle_loadbalancer_task(t, True, "log", 300)

    assert rc == 4
    handle_task.assert_called_once_with(t.parent, True, "log", 300)


# take_action


def test_take_action_checks_task_lock_first(take_action_mocks):
    _set_playbook_maps(role2environment={"myrole": "generic"})
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    take_action_mocks.lock.side_effect = assert_not_called_before_lock_check(
        cmd.handle_role
    )
    parsed_args = cmd.get_parser("test").parse_args(["myrole"])

    rc = cmd.take_action(parsed_args)

    assert rc == 0
    take_action_mocks.lock.assert_called_once_with()
    cmd.handle_role.assert_called_once()


def test_take_action_without_role_prints_table(capsys, take_action_mocks, loguru_logs):
    _set_playbook_maps(role2environment={"rolea": "enva", "roleb": "envb"})
    cmd = make_command(apply.Run)
    parsed_args = cmd.get_parser("test").parse_args([])

    rc = cmd.take_action(parsed_args)

    assert rc == 0
    out = capsys.readouterr().out
    assert "Role" in out and "Environment" in out
    assert "rolea" in out and "enva" in out
    assert "roleb" in out and "envb" in out
    take_action_mocks.facts.assert_not_called()
    messages = [r["message"] for r in loguru_logs]
    assert (
        "No role given for execution. The roles listed in the table can be used."
        in messages
    )


def test_take_action_runs_facts_check_when_stale(take_action_mocks):
    _set_playbook_maps(role2environment={"myrole": "generic"})
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["myrole"])

    before = time.time()
    cmd.take_action(parsed_args)

    take_action_mocks.facts.assert_called_once_with()
    assert osism_utils.__dict__["_last_ansible_facts_check"] >= before


def test_take_action_skips_facts_check_when_recent(take_action_mocks):
    _set_playbook_maps(role2environment={"myrole": "generic"})
    osism_utils._last_ansible_facts_check = time.time()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["myrole"])

    cmd.take_action(parsed_args)

    take_action_mocks.facts.assert_not_called()


@pytest.mark.parametrize("role", ["gather-facts", "facts"])
def test_take_action_skips_facts_check_for_facts_roles(take_action_mocks, role):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args([role])

    cmd.take_action(parsed_args)

    take_action_mocks.facts.assert_not_called()
    cmd.handle_role.assert_called_once()


def test_take_action_skips_facts_check_for_show_tree(take_action_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["--show-tree", "myrole"])

    cmd.take_action(parsed_args)

    take_action_mocks.facts.assert_not_called()


def test_take_action_splits_roles_on_double_slash(take_action_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["rolea//roleb"])

    rc = cmd.take_action(parsed_args)

    assert rc == 0
    assert [c.args[4] for c in cmd.handle_role.call_args_list] == ["rolea", "roleb"]


def test_take_action_retries_until_attempts_exhausted(take_action_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(return_value=1)
    parsed_args = cmd.get_parser("test").parse_args(["--retry", "2", "myrole"])

    rc = cmd.take_action(parsed_args)

    assert rc == 1
    assert cmd.handle_role.call_count == 3


def test_take_action_retry_stops_after_success(take_action_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_role = MagicMock(side_effect=[1, 0])
    parsed_args = cmd.get_parser("test").parse_args(["--retry", "2", "myrole"])

    rc = cmd.take_action(parsed_args)

    assert rc == 0
    assert cmd.handle_role.call_count == 2


def test_take_action_routes_collection_to_handle_collection(take_action_mocks):
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd.handle_collection = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["testcollection"])

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("a"))}):
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    cmd.handle_collection.assert_called_once()
    assert cmd.handle_collection.call_args.args[4] == "testcollection"


def test_take_action_collection_chain_continues_after_success(take_action_mocks):
    """A successful collection segment must not swallow the following ``//``
    segments: ``osism apply testcollection//other`` has to schedule the
    collection and then run the ``other`` role."""
    _set_playbook_maps()
    cmd = make_command(apply.Run)
    cmd._handle_collection = MagicMock(return_value=MagicMock())
    cmd.handle_role = MagicMock(return_value=0)
    parsed_args = cmd.get_parser("test").parse_args(["testcollection//other"])

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("a"))}):
        rc = cmd.take_action(parsed_args)

    assert rc == 0
    cmd.handle_role.assert_called_once()
    assert cmd.handle_role.call_args.args[4] == "other"


# take_action release preflight


def _bounded_collection():
    return Select("kvs_backend", {"redis": Run("redis"), "valkey": Run("valkey")})


def test_apply_accepts_openstack_version_argument():
    _, parsed = parse_args(apply.Run, ["--openstack-version", "2026.1", "nutshell"])

    assert parsed.openstack_version == "2026.1"


def test_apply_openstack_version_defaults_to_none():
    _, parsed = parse_args(apply.Run, ["nutshell"])

    assert parsed.openstack_version is None


def test_apply_openstack_version_help_warns_about_ordering():
    """``arguments`` is ``REMAINDER``: a flag after the role is swallowed."""
    cmd = make_command(apply.Run)
    parser = cmd.get_parser("test")
    action = next(
        a for a in parser._actions if "--openstack-version" in a.option_strings
    )

    assert "before the collection name" in action.help


def test_apply_openstack_version_help_names_the_versions_file():
    """The fallback source has to be the one the CLI actually reads.

    The manager configuration is not it: openstack_version is stripped from
    that file for a stable release, so help text pointing an operator there
    would describe a source that is absent on every pinned deployment.
    """
    from osism.data import releases

    cmd = make_command(apply.Run)
    parser = cmd.get_parser("test")
    action = next(
        a for a in parser._actions if "--openstack-version" in a.option_strings
    )

    assert releases.VERSIONS_FILE in action.help
    assert "/opt/configuration" not in action.help


def test_take_action_passes_resolved_release_to_collection(take_action_mocks):
    cmd, parsed = parse_args(
        apply.Run, ["--openstack-version", "2026.1", "testcollection"]
    )
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": _bounded_collection()}):
        cmd.take_action(parsed)

    assert cmd.handle_collection.call_args.kwargs["release"] == (2026, 1)


def test_take_action_unbounded_collection_never_resolves_release(
    take_action_mocks, mocker
):
    resolve = mocker.patch.object(apply.Run, "_resolve_release")
    cmd, parsed = parse_args(apply.Run, ["testcollection"])
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": Parallel(Run("plain"))}):
        cmd.take_action(parsed)

    resolve.assert_not_called()
    assert cmd.handle_collection.call_args.kwargs["release"] is None


def test_take_action_undeterminable_release_exits(
    take_action_mocks, mocker, loguru_logs
):
    from osism.data import releases

    mocker.patch.object(
        releases,
        "openstack_release",
        side_effect=releases.ReleaseUndetermined("/some/versions.yml not found."),
    )
    cmd, parsed = parse_args(apply.Run, ["testcollection"])
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": _bounded_collection()}):
        with pytest.raises(SystemExit) as excinfo:
            cmd.take_action(parsed)

    assert excinfo.value.code == 1
    cmd.handle_collection.assert_not_called()
    messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any(
        "Collection testcollection contains roles that depend on the OpenStack "
        "release, but the release could not be determined: "
        "/some/versions.yml not found." == m
        for m in messages
    )
    assert any(
        m.startswith("Supply the release with OPENSTACK_VERSION=")
        and "--openstack-version" in m
        for m in messages
    )


def test_take_action_undeterminable_release_advice_is_order_independent(
    take_action_mocks, mocker, loguru_logs
):
    """The advice must not recommend a flag placement that silently fails.

    ``arguments`` is ``nargs=argparse.REMAINDER``, so a flag placed after the
    collection name is swallowed as an Ansible argument rather than parsed.
    The advice therefore leads with the env-var form and, if it mentions the
    flag at all, says where it must go. It names no file to edit either: the
    versions file it failed to read belongs to the kolla-ansible container.
    """
    from osism.data import releases

    mocker.patch.object(
        releases,
        "openstack_release",
        side_effect=releases.ReleaseUndetermined("/some/versions.yml not found."),
    )
    cmd, parsed = parse_args(apply.Run, ["testcollection"])
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": _bounded_collection()}):
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)

    messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any(
        m
        == (
            "Supply the release with OPENSTACK_VERSION=<release> osism apply "
            "<collection>, or with --openstack-version <release> before the "
            "collection name."
        )
        for m in messages
    )


def test_take_action_unparseable_release_prints_bare_message(
    take_action_mocks, mocker, loguru_logs
):
    cmd, parsed = parse_args(
        apply.Run, ["--openstack-version", "master", "testcollection"]
    )
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(enums.MAP_ROLE2ROLE, {"testcollection": _bounded_collection()}):
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)

    messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any(
        m == "Could not parse OpenStack release 'master' "
        "(expected a release like 2025.1)."
        for m in messages
    )
    assert not any("could not be determined" in m for m in messages)


def test_take_action_preflight_schedules_nothing_across_slashes(
    take_action_mocks, mocker
):
    """The guarantee is command-wide, not collection-wide.

    Resolving inside the dispatch loop would let the first entry reach
    apply_async before the second one failed.
    """
    from osism.data import releases

    mocker.patch.object(
        releases,
        "openstack_release",
        side_effect=releases.ReleaseUndetermined("/some/versions.yml not found."),
    )
    cmd, parsed = parse_args(apply.Run, ["unbounded//testcollection"])
    cmd._handle_collection = MagicMock()

    with patch.dict(
        enums.MAP_ROLE2ROLE,
        {"unbounded": Parallel(Run("plain")), "testcollection": _bounded_collection()},
    ):
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)

    cmd._handle_collection.assert_not_called()


def test_take_action_resolves_the_release_once_per_invocation(
    take_action_mocks, mocker
):
    from osism.data import releases

    resolve = mocker.patch.object(releases, "openstack_release", return_value=(2026, 1))
    cmd, parsed = parse_args(apply.Run, ["testcollection//othercollection"])
    cmd.handle_collection = MagicMock(return_value=0)

    with patch.dict(
        enums.MAP_ROLE2ROLE,
        {
            "testcollection": _bounded_collection(),
            "othercollection": _bounded_collection(),
        },
    ):
        cmd.take_action(parsed)

    resolve.assert_called_once()
    assert [c.kwargs["release"] for c in cmd.handle_collection.call_args_list] == [
        (2026, 1),
        (2026, 1),
    ]


def test_take_action_names_every_affected_collection(
    take_action_mocks, mocker, loguru_logs
):
    from osism.data import releases

    mocker.patch.object(
        releases,
        "openstack_release",
        side_effect=releases.ReleaseUndetermined("/some/versions.yml not found."),
    )
    cmd, parsed = parse_args(apply.Run, ["testcollection//othercollection"])

    with patch.dict(
        enums.MAP_ROLE2ROLE,
        {
            "testcollection": _bounded_collection(),
            "othercollection": _bounded_collection(),
        },
    ):
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)

    messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any(
        m.startswith("Collections othercollection, testcollection contain roles")
        for m in messages
    )


# bounds are collection membership, never role availability


def test_take_action_explicit_bounded_role_ignores_bounds(take_action_mocks, mocker):
    """``osism apply valkey`` on 2025.1 must dispatch.

    valkey's play exists on 2025.1; the ``since="2025.2"`` bound says only that
    collections should not deploy it there. Reading the bound as availability
    would reject a legitimate command.
    """
    resolve = mocker.patch.object(apply.Run, "_resolve_release")
    cmd, parsed = parse_args(apply.Run, ["--openstack-version", "2025.1", "valkey"])
    cmd.handle_role = MagicMock(return_value=0)

    cmd.take_action(parsed)

    resolve.assert_not_called()
    # handle_role is called positionally: (arguments, environment, overwrite,
    # sub, role, ...), so the role is args[4].
    assert cmd.handle_role.call_args.args[4] == "valkey"


def test_take_action_explicit_redis_still_dispatches_on_2026_1(
    take_action_mocks, mocker
):
    resolve = mocker.patch.object(apply.Run, "_resolve_release")
    cmd, parsed = parse_args(apply.Run, ["--openstack-version", "2026.1", "redis"])
    cmd.handle_role = MagicMock(return_value=0)

    cmd.take_action(parsed)

    resolve.assert_not_called()
    assert cmd.handle_role.call_args.args[4] == "redis"


def test_real_celery_canvas_waits_for_parallel_prerequisites(mocker):
    from celery import Celery

    app = Celery("plan-test", broker="memory://", backend="cache+memory://")
    app.conf.update(task_always_eager=True, task_eager_propagates=True)
    events = []

    @app.task
    def record(name):
        events.append(name)

    cmd = make_command(apply.Run)
    mocker.patch.object(cmd, "_prepare_task", side_effect=lambda *a: record.si(a[4]))
    canvas = cmd._handle_collection(
        Sequence(Run("parent"), Parallel(Run("a"), Run("b")), Run("tail")),
        **_collection_kwargs(),
    )
    try:
        canvas.apply_async().get()
        assert events[0] == "parent"
        assert set(events[1:3]) == {"a", "b"}
        assert events[3] == "tail"
    finally:
        app.close()


def test_take_action_invalid_later_plan_prevents_earlier_dispatch(take_action_mocks):
    cmd, parsed = parse_args(apply.Run, ["valid//invalid"])
    cmd.handle_collection = MagicMock()
    with patch.dict(
        enums.MAP_ROLE2ROLE,
        {
            "valid": Run("a"),
            "invalid": Select("missing", {"one": Run("b")}),
        },
    ):
        with pytest.raises(SystemExit):
            cmd.take_action(parsed)
    cmd.handle_collection.assert_not_called()
