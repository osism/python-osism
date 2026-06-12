# SPDX-License-Identifier: Apache-2.0

"""Distributed-locking integration tests against a live Redis.

Covers the Redlock helper used by ``run_ansible_in_environment`` for per-play
locking and the task-lock flag used by ``osism lock`` / ``osism unlock``.
"""

import uuid

import pytest

from osism import utils

pytestmark = pytest.mark.integration


def test_redlock_acquire_and_release():
    """A Redlock can be acquired and released against the live Redis."""
    lock = utils.create_redlock(key=f"itest-lock-{uuid.uuid4()}")

    assert lock.acquire(timeout=10)
    lock.release()


def test_task_lock_set_check_remove():
    """``set_task_lock`` / ``is_task_locked`` / ``remove_task_lock`` round-trip."""
    # Start from a known-unlocked state so the test is independent of prior runs.
    utils.remove_task_lock()
    assert utils.is_task_locked() is None

    assert utils.set_task_lock(user="tester", reason="integration test") is True

    lock_info = utils.is_task_locked()
    assert lock_info is not None
    assert lock_info["locked"] is True
    assert lock_info["user"] == "tester"
    assert lock_info["reason"] == "integration test"

    assert utils.remove_task_lock() is True
    assert utils.is_task_locked() is None
