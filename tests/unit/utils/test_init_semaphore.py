# SPDX-License-Identifier: Apache-2.0

"""Regression tests for :class:`osism.utils.RedisSemaphore.acquire`.

These run the production Lua ``_ACQUIRE_LUA`` against an in-memory
``fakeredis`` server (which executes Lua via ``lupa``), so they exercise the
real server-side check-and-acquire rather than asserting on a mock's recorded
calls. A faithful many-client race needs a real Redis and lives outside the
unit suite; these tests lock in the two invariants the atomic implementation
guarantees:

* the holder set never exceeds ``maxsize`` (TOCTOU over-admit fix), and
* the expired-holder reclaim boundary advances on every retry, so a slot that
  frees up while a caller waits is eventually granted (stale-boundary fix).
"""

import time

import fakeredis
import pytest

import osism.utils as utils_pkg


@pytest.fixture
def redis():
    """A fresh in-memory Redis with Lua scripting support per test."""
    return fakeredis.FakeStrictRedis()


def test_acquire_then_release_roundtrip(redis):
    sem = utils_pkg.RedisSemaphore(redis, "job", 2, timeout=1)

    assert sem.acquire() is True
    assert sem.identifier is not None
    assert redis.zcard("semaphore:job") == 1

    sem.release()
    assert sem.identifier is None
    assert redis.zcard("semaphore:job") == 0


def test_acquire_never_exceeds_maxsize(redis):
    """maxsize concurrent holders are admitted; the next caller is refused and
    the holder set stays capped — the invariant the atomic script enforces."""
    maxsize = 3
    held = []
    for _ in range(maxsize):
        sem = utils_pkg.RedisSemaphore(redis, "job", maxsize, timeout=1)
        assert sem.acquire() is True
        held.append(sem)

    assert redis.zcard("semaphore:job") == maxsize

    # One more, with the set already full: must be refused, set unchanged.
    overflow = utils_pkg.RedisSemaphore(redis, "job", maxsize, timeout=1)
    assert overflow.acquire() is False
    assert redis.zcard("semaphore:job") == maxsize

    for sem in held:
        sem.release()
    assert redis.zcard("semaphore:job") == 0


def test_acquire_returns_false_when_full_for_whole_window(redis):
    """A genuinely full semaphore times out (no slot ever frees).

    The holder is freshly scored, so it never ages past HOLDER_EXPIRY within
    the short window and the caller exhausts its timeout.
    """
    redis.zadd("semaphore:job", {"holder": time.time()})
    sem = utils_pkg.RedisSemaphore(redis, "job", 1, timeout=0.2)

    assert sem.acquire() is False
    assert sem.identifier is None
    assert redis.zcard("semaphore:job") == 1  # untouched


def test_reclaim_boundary_advances_across_retries(redis, mocker):
    """The expiry cutoff is recomputed from the current time on every retry,
    so a holder that ages past HOLDER_EXPIRY while the caller waits is
    reclaimed and the slot is granted before the timeout.

    With a cutoff frozen at the loop's start this caller would never reclaim
    the holder and would spuriously time out. HOLDER_EXPIRY is shrunk so the
    holder ages out within a fraction of a second.
    """
    mocker.patch.object(utils_pkg.RedisSemaphore, "HOLDER_EXPIRY", 0.1)
    # One holder occupying the only slot, scored at "now"; it is not yet expired
    # on the first attempt but ages past HOLDER_EXPIRY while the caller retries.
    redis.zadd("semaphore:job", {"stale": time.time()})
    sem = utils_pkg.RedisSemaphore(redis, "job", 1, timeout=2)

    assert sem.acquire() is True
    members = {m.decode() for m in redis.zrange("semaphore:job", 0, -1)}
    assert members == {sem.identifier}  # stale reclaimed, only new holder left
