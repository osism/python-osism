# SPDX-License-Identifier: Apache-2.0

"""Redis-semaphore integration tests against a live Redis.

``RedisSemaphore`` caps concurrent NetBox API requests: ``osism.tasks.netbox``
builds one per NetBox URL through ``create_netbox_semaphore``. Holders live in a
sorted set and are admitted by a server-side Lua script (``ZREMRANGEBYSCORE``
plus ``ZCARD`` plus ``ZADD``), so what these tests exercise is Redis behaviour:
the expiry reclaim, the capacity limit, and the atomicity that stops two
clients from taking the same free slot. ``fakeredis`` reimplements all of that
in Python, which is why this coverage belongs against the real server.
"""

import hashlib
import threading
import time
import uuid

import pytest

from osism import settings, utils

pytestmark = pytest.mark.integration


@pytest.fixture
def redis_client():
    """The shared Redis client the semaphore itself uses.

    ``create_netbox_semaphore`` wires this very client into the semaphores it
    builds, so seeding and inspecting through it observes what the code under
    test sees. It is a cached module global held for the whole session, so it
    is not closed here: that would break every later test that touches it.
    """
    return utils.redis


@pytest.fixture
def semaphore_key(redis_client):
    """A key unique to this test, removed from Redis afterwards.

    ``RedisSemaphore`` prefixes what it is handed, so the sorted set lives under
    ``semaphore:<key>``. Raw seeding and inspection use that prefixed form.
    """
    key = f"itest-sem-{uuid.uuid4()}"
    yield key
    redis_client.delete(f"semaphore:{key}")


def test_acquire_up_to_maxsize(redis_client, semaphore_key):
    """``maxsize`` holders are admitted, and releasing them empties the set."""
    maxsize = 3
    held = []

    for _ in range(maxsize):
        sem = utils.RedisSemaphore(redis_client, semaphore_key, maxsize, timeout=5)
        assert sem.acquire() is True
        held.append(sem)

    assert redis_client.zcard(f"semaphore:{semaphore_key}") == maxsize

    for sem in held:
        sem.release()

    assert redis_client.zcard(f"semaphore:{semaphore_key}") == 0


def test_acquire_beyond_maxsize_returns_false(redis_client, semaphore_key):
    """A caller beyond ``maxsize`` times out and returns False without raising."""
    holder = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)
    assert holder.acquire() is True

    overflow = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=0.5)

    assert overflow.acquire() is False
    assert overflow.identifier is None
    assert redis_client.zcard(f"semaphore:{semaphore_key}") == 1

    holder.release()


def test_release_frees_slot(redis_client, semaphore_key):
    """The slot a holder gives up is granted to the caller that was refused."""
    holder = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)
    assert holder.acquire() is True

    waiter = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=0.5)
    assert waiter.acquire() is False

    holder.release()

    assert waiter.acquire() is True
    assert redis_client.zcard(f"semaphore:{semaphore_key}") == 1

    waiter.release()


def test_release_without_acquire_is_noop(redis_client, semaphore_key):
    """Releasing a semaphore that was never acquired touches nothing."""
    sem = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)

    sem.release()

    assert sem.identifier is None
    assert redis_client.zcard(f"semaphore:{semaphore_key}") == 0


def test_expired_holder_reclaimed(redis_client, semaphore_key):
    """A holder older than ``HOLDER_EXPIRY`` is reclaimed and its slot granted.

    The aged entry is seeded through the Redis client so the reclaim runs
    deterministically, without waiting out the 60s expiry.
    """
    redis_key = f"semaphore:{semaphore_key}"
    aged_score = time.time() - utils.RedisSemaphore.HOLDER_EXPIRY - 1
    redis_client.zadd(redis_key, {"stale": aged_score})

    sem = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)

    assert sem.acquire() is True

    members = {member.decode() for member in redis_client.zrange(redis_key, 0, -1)}
    assert members == {sem.identifier}

    sem.release()


def test_context_manager_roundtrip(redis_client, semaphore_key):
    """``with sem:`` holds a slot for the block and frees it on exit."""
    redis_key = f"semaphore:{semaphore_key}"
    sem = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)

    with sem as entered:
        assert entered is sem
        assert redis_client.zcard(redis_key) == 1

    assert redis_client.zcard(redis_key) == 0
    assert sem.identifier is None


def test_context_manager_timeout_raises(redis_client, semaphore_key):
    """``with sem:`` raises ``TimeoutError`` when no slot frees up in time."""
    redis_key = f"semaphore:{semaphore_key}"
    # Scored at "now", so it never ages past HOLDER_EXPIRY within the window
    # and the caller exhausts its timeout instead of reclaiming the slot.
    redis_client.zadd(redis_key, {"holder": time.time()})

    sem = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=0.2)

    with pytest.raises(TimeoutError) as excinfo:
        with sem:
            pytest.fail("the semaphore was acquired although it is full")

    assert str(excinfo.value) == f"Could not acquire semaphore {redis_key}"
    assert redis_client.zcard(redis_key) == 1


def test_create_netbox_semaphore_key_and_maxsize(redis_client):
    """The NetBox helper derives its key from the URL and works against Redis."""
    url = f"https://netbox-{uuid.uuid4()}.example"
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    redis_key = f"semaphore:netbox_semaphore_{url_hash}"

    sem = utils.create_netbox_semaphore(url, max_connections=2)

    try:
        assert isinstance(sem, utils.RedisSemaphore)
        assert sem.key == redis_key
        assert sem.maxsize == 2

        assert sem.acquire() is True
        members = {member.decode() for member in redis_client.zrange(redis_key, 0, -1)}
        assert members == {sem.identifier}

        sem.release()
        assert redis_client.zcard(redis_key) == 0
    finally:
        redis_client.delete(redis_key)


def test_create_netbox_semaphore_default_maxsize():
    """Without ``max_connections`` the helper falls back to the setting."""
    sem = utils.create_netbox_semaphore(f"https://netbox-{uuid.uuid4()}.example")

    assert sem.maxsize == settings.NETBOX_MAX_CONNECTIONS


def test_concurrent_acquire_never_exceeds_maxsize(redis_client, semaphore_key):
    """Under a real race only ``maxsize`` of many contending clients get in.

    The atomic Lua script is what makes this hold: a capacity check and a slot
    reservation split across two round trips would let several clients observe
    the same free slot and all take it. This is the many-client race the unit
    suite defers to a live server.
    """
    maxsize = 3
    thread_count = 12
    redis_key = f"semaphore:{semaphore_key}"
    # A timeout on the barrier turns a thread that never arrives into a failed
    # assertion rather than a hung CI job.
    barrier = threading.Barrier(thread_count, timeout=30)
    acquired = []
    acquired_lock = threading.Lock()

    def contend():
        sem = utils.RedisSemaphore(redis_client, semaphore_key, maxsize, timeout=0.5)
        barrier.wait()
        if sem.acquire():
            with acquired_lock:
                acquired.append(sem)

    threads = [threading.Thread(target=contend) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # No thread releases before the join, so the holder count is stable here.
    assert len(acquired) == maxsize
    assert redis_client.zcard(redis_key) == maxsize

    for sem in acquired:
        sem.release()

    assert redis_client.zcard(redis_key) == 0
