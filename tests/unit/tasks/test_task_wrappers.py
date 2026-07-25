# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the thin Celery task wrappers.

Covers the five wrapper modules ``osism/tasks/{ansible,ceph,kolla,kubernetes,
reconciler}.py``. The four ansible-style wrappers delegate to
``run_ansible_in_environment`` with a hard-coded worker name; ``reconciler``
shells out to ``/run.sh`` under a Redlock. Every external effect -- the ansible
runner, the Redis locks, ``subprocess.Popen`` and the task-output stream -- is
mocked, so the tests need neither a broker nor a reachable Redis.

The bound tasks (``bind=True``) are exercised through ``task.__wrapped__(...)``
(already bound to the task instance, so ``self.request.id`` is ``None``) except
where a real request id is needed, in which case ``task.apply(task_id=...)``
runs the task eagerly in-process. The periodic-task receivers are plain
functions and are called directly.
"""

import io
import os
import subprocess
from unittest.mock import call

import pytest
from pottery import ReleaseUnlockedLock

from osism.tasks import ansible, ceph, kolla, kubernetes, reconciler

# ---------------------------------------------------------------------------
# Variant tables
# ---------------------------------------------------------------------------

# App configuration / queue routing: every wrapper module with its route
# pattern, the queue it maps to, and the task names it registers explicitly.
APP_VARIANTS = [
    pytest.param(
        ansible,
        "osism.tasks.ansible.*",
        "osism-ansible",
        [
            "osism.tasks.ansible.gather_facts",
            "osism.tasks.ansible.run",
            "osism.tasks.ansible.noop",
        ],
        id="ansible",
    ),
    pytest.param(
        ceph,
        "osism.tasks.ceph.*",
        "ceph-ansible",
        ["osism.tasks.ceph.run"],
        id="ceph",
    ),
    pytest.param(
        kolla,
        "osism.tasks.kolla.*",
        "kolla-ansible",
        ["osism.tasks.kolla.run"],
        id="kolla",
    ),
    pytest.param(
        kubernetes,
        "osism.tasks.kubernetes.*",
        "kubernetes",
        ["osism.tasks.kubernetes.run"],
        id="kubernetes",
    ),
    pytest.param(
        reconciler,
        "osism.tasks.reconciler.*",
        "reconciler",
        [
            "osism.tasks.reconciler.run",
            "osism.tasks.reconciler.run_on_change",
        ],
        id="reconciler",
    ),
]

# The two real ``setup_periodic_tasks`` receivers (ansible + reconciler) share
# a structure: read a schedule setting, create a Redlock under a fixed key, and
# -- when both the schedule is positive and the lock is acquired -- register a
# periodic task. Each variant carries the schedule setting name, the lock key
# and the attribute name of the task scheduled via its ``.s()`` signature.
PERIODIC_VARIANTS = [
    pytest.param(
        ansible,
        "GATHER_FACTS_SCHEDULE",
        "lock_osism_tasks_ansible_setup_periodic_tasks",
        "gather_facts",
        id="ansible",
    ),
    pytest.param(
        reconciler,
        "INVENTORY_RECONCILER_SCHEDULE",
        "lock_osism_tasks_reconciler_setup_periodic_tasks",
        "run_on_change",
        id="reconciler",
    ),
]

# ``ceph``/``kolla``/``kubernetes`` ``run`` tasks are byte-identical except for
# the worker string forwarded to ``run_ansible_in_environment``. Note that the
# kubernetes worker (``osism-kubernetes``) deliberately differs from its queue
# name (``kubernetes``).
WORKER_RUN_VARIANTS = [
    pytest.param(ceph, "ceph-ansible", id="ceph"),
    pytest.param(kolla, "kolla-ansible", id="kolla"),
    pytest.param(kubernetes, "osism-kubernetes", id="kubernetes"),
]


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


# ---------------------------------------------------------------------------
# App configuration & queue routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module, pattern, queue, task_names", APP_VARIANTS)
def test_app_uses_default_queue(module, pattern, queue, task_names):
    """Every app applies ``Config`` and defaults to the ``default`` queue."""
    assert module.app.conf.task_default_queue == "default"


@pytest.mark.parametrize("module, pattern, queue, task_names", APP_VARIANTS)
def test_app_routes_module_pattern_to_queue(module, pattern, queue, task_names):
    """The module route pattern maps to the expected queue."""
    assert module.app.conf.task_routes[pattern] == {"queue": queue}


@pytest.mark.parametrize("module, pattern, queue, task_names", APP_VARIANTS)
def test_tasks_registered_under_explicit_names(module, pattern, queue, task_names):
    """Tasks are registered under their explicit ``osism.tasks.*`` names."""
    for name in task_names:
        assert name in module.app.tasks


# ---------------------------------------------------------------------------
# setup_periodic_tasks -- ansible + reconciler (real receivers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module, schedule_attr, lock_key, scheduled", PERIODIC_VARIANTS
)
def test_setup_periodic_tasks_schedules_when_lock_acquired(
    mocker, module, schedule_attr, lock_key, scheduled
):
    """Positive schedule + acquired lock registers the periodic task once."""
    mocker.patch.object(module.settings, schedule_attr, 123.0)
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    create = mocker.patch.object(module.utils, "create_redlock", return_value=lock)
    sender = mocker.MagicMock()

    module.setup_periodic_tasks(sender)

    create.assert_called_once_with(key=lock_key)
    lock.acquire.assert_called_once_with(timeout=10)
    sender.add_periodic_task.assert_called_once_with(
        123.0, getattr(module, scheduled).s(), expires=10
    )


@pytest.mark.parametrize(
    "module, schedule_attr, lock_key, scheduled", PERIODIC_VARIANTS
)
def test_setup_periodic_tasks_skips_when_schedule_disabled(
    mocker, module, schedule_attr, lock_key, scheduled
):
    """A schedule of ``0`` short-circuits before acquiring the lock."""
    mocker.patch.object(module.settings, schedule_attr, 0)
    lock = mocker.MagicMock()
    create = mocker.patch.object(module.utils, "create_redlock", return_value=lock)
    sender = mocker.MagicMock()

    module.setup_periodic_tasks(sender)

    # The lock is still created, but the short-circuit ``and`` means it is
    # never acquired and nothing is scheduled.
    create.assert_called_once_with(key=lock_key)
    lock.acquire.assert_not_called()
    sender.add_periodic_task.assert_not_called()


@pytest.mark.parametrize(
    "module, schedule_attr, lock_key, scheduled", PERIODIC_VARIANTS
)
def test_setup_periodic_tasks_skips_when_lock_not_acquired(
    mocker, module, schedule_attr, lock_key, scheduled
):
    """A positive schedule but an unacquired lock schedules nothing."""
    mocker.patch.object(module.settings, schedule_attr, 123.0)
    lock = mocker.MagicMock()
    lock.acquire.return_value = False
    mocker.patch.object(module.utils, "create_redlock", return_value=lock)
    sender = mocker.MagicMock()

    module.setup_periodic_tasks(sender)

    sender.add_periodic_task.assert_not_called()


@pytest.mark.parametrize("module, worker", WORKER_RUN_VARIANTS)
def test_setup_periodic_tasks_is_noop(mocker, module, worker):
    """ceph/kolla/kubernetes receivers are ``pass`` -- the sender is untouched."""
    sender = mocker.MagicMock()

    module.setup_periodic_tasks(sender)

    assert sender.mock_calls == []


# ---------------------------------------------------------------------------
# ansible.gather_facts
# ---------------------------------------------------------------------------


def test_gather_facts_delegates_with_defaults(mocker):
    """``gather_facts`` delegates the seven positional args and no lock check."""
    delegate = mocker.patch(
        "osism.tasks.ansible.run_ansible_in_environment", return_value="RESULT"
    )
    check = mocker.patch("osism.tasks.ansible.utils.check_task_lock_and_exit")

    result = ansible.gather_facts.__wrapped__()

    delegate.assert_called_once_with(
        None, "osism-ansible", "generic", "facts", [], True, False
    )
    assert result == "RESULT"
    check.assert_not_called()


def test_gather_facts_forwards_publish_false(mocker):
    """``publish=False`` is forwarded as the sixth positional argument."""
    delegate = mocker.patch("osism.tasks.ansible.run_ansible_in_environment")

    ansible.gather_facts.__wrapped__(publish=False)

    delegate.assert_called_once_with(
        None, "osism-ansible", "generic", "facts", [], False, False
    )


# ---------------------------------------------------------------------------
# ansible.run
# ---------------------------------------------------------------------------


def test_ansible_run_delegates_with_defaults(mocker):
    """``run`` checks the lock, then delegates the eight positional args."""
    delegate = mocker.patch(
        "osism.tasks.ansible.run_ansible_in_environment", return_value="RESULT"
    )
    check = mocker.patch("osism.tasks.ansible.utils.check_task_lock_and_exit")

    result = ansible.run.__wrapped__("env1", "site", ["-l", "x"])

    check.assert_called_once_with()
    delegate.assert_called_once_with(
        None, "osism-ansible", "env1", "site", ["-l", "x"], True, False, 3600
    )
    assert result == "RESULT"


def test_ansible_run_forwards_arguments(mocker):
    """Explicit ``publish``/``locking``/``auto_release_time`` are forwarded."""
    delegate = mocker.patch("osism.tasks.ansible.run_ansible_in_environment")
    mocker.patch("osism.tasks.ansible.utils.check_task_lock_and_exit")

    ansible.run.__wrapped__(
        "env1", "site", ["-v"], publish=False, locking=True, auto_release_time=60
    )

    delegate.assert_called_once_with(
        None, "osism-ansible", "env1", "site", ["-v"], False, True, 60
    )


def test_ansible_run_aborts_when_task_lock_active(mocker):
    """The lock check runs before delegation; ``SystemExit`` skips the runner."""
    delegate = mocker.patch("osism.tasks.ansible.run_ansible_in_environment")
    mocker.patch(
        "osism.tasks.ansible.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )

    with pytest.raises(SystemExit):
        ansible.run.__wrapped__("env1", "site", [])

    delegate.assert_not_called()


# ---------------------------------------------------------------------------
# ansible.noop
# ---------------------------------------------------------------------------


def test_noop_returns_true():
    """``noop`` returns ``True``."""
    assert ansible.noop.__wrapped__() is True


# ---------------------------------------------------------------------------
# ceph/kolla/kubernetes.run (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module, worker", WORKER_RUN_VARIANTS)
def test_worker_run_delegates_with_defaults(mocker, module, worker):
    """Each wrapper forwards its worker string and a hard-coded ``locking=False``."""
    delegate = mocker.patch(
        f"{module.__name__}.run_ansible_in_environment", return_value="RESULT"
    )
    check = mocker.patch(f"{module.__name__}.utils.check_task_lock_and_exit")

    result = module.run.__wrapped__("env1", "pb", ["-v"])

    check.assert_called_once_with()
    delegate.assert_called_once_with(
        None, worker, "env1", "pb", ["-v"], True, False, 3600
    )
    assert result == "RESULT"


@pytest.mark.parametrize("module, worker", WORKER_RUN_VARIANTS)
def test_worker_run_forwards_overrides(mocker, module, worker):
    """``publish`` and ``auto_release_time`` overrides are forwarded positionally."""
    delegate = mocker.patch(f"{module.__name__}.run_ansible_in_environment")
    mocker.patch(f"{module.__name__}.utils.check_task_lock_and_exit")

    module.run.__wrapped__("env1", "pb", ["-v"], publish=False, auto_release_time=120)

    delegate.assert_called_once_with(
        None, worker, "env1", "pb", ["-v"], False, False, 120
    )


@pytest.mark.parametrize("module, worker", WORKER_RUN_VARIANTS)
def test_worker_run_aborts_when_task_lock_active(mocker, module, worker):
    """A ``SystemExit`` from the lock check short-circuits delegation."""
    delegate = mocker.patch(f"{module.__name__}.run_ansible_in_environment")
    mocker.patch(
        f"{module.__name__}.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )

    with pytest.raises(SystemExit):
        module.run.__wrapped__("env1", "pb", [])

    delegate.assert_not_called()


# ---------------------------------------------------------------------------
# reconciler.run
# ---------------------------------------------------------------------------


def test_reconciler_run_aborts_when_task_lock_active(mocker):
    """A locked task fails fast before creating a Redlock or spawning ``/run.sh``."""
    mocker.patch(
        "osism.tasks.reconciler.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )
    create = mocker.patch("osism.tasks.reconciler.utils.create_redlock")
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")

    result = reconciler.run.__wrapped__(publish=False)

    assert result == reconciler.LOCK_TIMEOUT_RC
    create.assert_not_called()
    popen.assert_not_called()


def test_reconciler_run_fails_fast_when_lock_not_acquired(mocker):
    """Without the lock, ``/run.sh`` is never spawned and the task reports failure."""
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    lock = mocker.MagicMock()
    lock.acquire.return_value = False
    create = mocker.patch(
        "osism.tasks.reconciler.utils.create_redlock", return_value=lock
    )
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")

    result = reconciler.run.__wrapped__(publish=False)

    create.assert_called_once_with(
        key="lock_osism_tasks_reconciler_run", auto_release_time=60
    )
    lock.acquire.assert_called_once_with(timeout=reconciler.LOCK_ACQUIRE_TIMEOUT)
    popen.assert_not_called()
    assert result == reconciler.LOCK_TIMEOUT_RC


def test_reconciler_run_publishes_output(mocker):
    """With the lock and ``publish=True`` each stdout line is forwarded."""
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    proc = mocker.MagicMock()
    proc.stdout = io.BytesIO(b"line one\nline two\n")
    proc.wait.return_value = 0
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=proc)

    # ``apply`` runs the task eagerly so ``self.request.id`` is a real value.
    reconciler.run.apply(task_id="test-id")

    popen.assert_called_once_with(
        "/run.sh",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=os.environ.copy(),
    )
    assert push.call_args_list == [
        call("test-id", "line one\n"),
        call("test-id", "line two\n"),
    ]
    proc.wait.assert_called_once_with(timeout=60)
    finish.assert_called_once_with("test-id", rc=0)
    lock.release.assert_called_once_with()


def test_reconciler_run_without_publish_drains_but_skips_output(mocker):
    """With ``publish=False`` stdout is still drained but nothing is published."""
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    proc = mocker.MagicMock()
    # Real bytes so the production ``TextIOWrapper`` drain loop consumes the
    # pipe; if the loop were skipped a filled pipe would deadlock ``wait()``.
    proc.stdout = io.BytesIO(b"noise one\nnoise two\n")
    proc.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=proc)

    reconciler.run.__wrapped__(publish=False)

    # The drain loop wrapped and exhausted the pipe (``TextIOWrapper`` closes
    # the buffer on completion) even though nothing is forwarded downstream.
    assert proc.stdout.closed
    push.assert_not_called()
    finish.assert_not_called()
    proc.wait.assert_called_once_with(timeout=60)


def test_reconciler_run_warns_when_lock_already_released(mocker, loguru_logs):
    """A ``ReleaseUnlockedLock`` on release is logged as a warning, not raised."""
    mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    lock.release.side_effect = ReleaseUnlockedLock(
        key="lock_osism_tasks_reconciler_run", masters=set()
    )
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    proc = mocker.MagicMock()
    proc.stdout = io.BytesIO(b"")
    proc.wait.return_value = 0
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=proc)

    # Must not propagate.
    reconciler.run.__wrapped__()

    assert _has_log(loguru_logs, "WARNING", "auto-released")


# ---------------------------------------------------------------------------
# reconciler.run_on_change
# ---------------------------------------------------------------------------


def test_run_on_change_returns_none_when_lock_not_acquired(mocker):
    """Without the lock, ``/run.sh`` is never spawned and the task returns ``None``."""
    lock = mocker.MagicMock()
    lock.acquire.return_value = False
    create = mocker.patch(
        "osism.tasks.reconciler.utils.create_redlock", return_value=lock
    )
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen")

    result = reconciler.run_on_change.__wrapped__()

    create.assert_called_once_with(
        key="lock_osism_tasks_reconciler_run_on_change", auto_release_time=60
    )
    lock.acquire.assert_called_once_with(timeout=20)
    popen.assert_not_called()
    assert result is None


def test_run_on_change_drains_script_output_into_log(mocker, loguru_logs):
    """``run_on_change`` spawns ``/run.sh`` and drains its output into the log."""
    check = mocker.patch("osism.tasks.reconciler.utils.check_task_lock_and_exit")
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    push = mocker.patch("osism.tasks.reconciler.utils.push_task_output")
    finish = mocker.patch("osism.tasks.reconciler.utils.finish_task_output")
    proc = mocker.MagicMock()
    # Real bytes so the production ``TextIOWrapper`` drain loop consumes the
    # pipe; without draining a filled pipe would deadlock the bare ``wait()``.
    proc.stdout = io.BytesIO(b"reconcile line\n")
    popen = mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=proc)

    reconciler.run_on_change.__wrapped__()

    # ``stdout=PIPE`` is required to drain; the exact match also proves there
    # is no ``env`` kwarg (unlike ``run``).
    popen.assert_called_once_with(
        "/run.sh", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    # Pipe fully consumed (``TextIOWrapper`` closes the buffer on completion)
    # and each line forwarded to the log.
    assert proc.stdout.closed
    assert _has_log(loguru_logs, "INFO", "reconcile line")
    # A timeout backstops the final reap, matching ``run``.
    proc.wait.assert_called_once_with(timeout=60)
    # ``run_on_change`` publishes nowhere and has no task-lock check.
    push.assert_not_called()
    finish.assert_not_called()
    check.assert_not_called()
    lock.release.assert_called_once_with()


def test_run_on_change_warns_when_lock_already_released(mocker, loguru_logs):
    """A ``ReleaseUnlockedLock`` on release is logged as a warning, not raised."""
    lock = mocker.MagicMock()
    lock.acquire.return_value = True
    lock.release.side_effect = ReleaseUnlockedLock(
        key="lock_osism_tasks_reconciler_run_on_change", masters=set()
    )
    mocker.patch("osism.tasks.reconciler.utils.create_redlock", return_value=lock)
    proc = mocker.MagicMock()
    proc.stdout = io.BytesIO(b"")
    mocker.patch("osism.tasks.reconciler.subprocess.Popen", return_value=proc)

    # Must not propagate.
    reconciler.run_on_change.__wrapped__()

    assert _has_log(loguru_logs, "WARNING", "auto-released")
