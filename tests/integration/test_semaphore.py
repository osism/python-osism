# SPDX-License-Identifier: Apache-2.0

"""Redis-semaphore integration tests against a live Redis.

``RedisSemaphore`` caps concurrent NetBox API requests: ``osism.tasks.netbox``
builds one per NetBox URL through ``create_netbox_semaphore``. Holders live in a
sorted set and are admitted by a server-side Lua script (``ZREMRANGEBYSCORE``
plus ``ZCARD`` plus ``ZADD``).

The script's logic is not what needs a live server:
``tests/unit/utils/test_init_semaphore.py`` runs the production ``_ACQUIRE_LUA``
against ``fakeredis``, which executes Lua through ``lupa``. What only the real
server provides is Redis' own Lua sandbox and ``redis.call`` bindings, the
numeric coercion of the ``now``, ``maxsize`` and expiry arguments that ``lupa``
only approximates, and the race the unit suite explicitly defers to here:
many clients contending for the same free slot at the same moment.
"""

import concurrent.futures
import hashlib
import threading
import uuid

import pytest

from osism import utils

pytestmark = pytest.mark.integration


def semaphore_redis_key(key):
    """The prefixed key ``RedisSemaphore`` stores its sorted set under."""
    return f"semaphore:{key}"


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
    redis_client.delete(semaphore_redis_key(key))


def test_release_frees_slot(redis_client, semaphore_key):
    """The slot a holder gives up is granted to the caller that was refused.

    The unit suite covers a slot freed by expiry, never one freed by
    ``release`` and granted to a waiter inside its retry loop.
    """
    holder = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=5)
    assert holder.acquire() is True

    waiter = utils.RedisSemaphore(redis_client, semaphore_key, 1, timeout=0.5)
    assert waiter.acquire() is False

    holder.release()

    assert waiter.acquire() is True
    assert redis_client.zcard(waiter.key) == 1

    waiter.release()


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


def test_concurrent_acquire_never_exceeds_maxsize(redis_client, semaphore_key):
    """Under a real race only ``maxsize`` of many contending clients get in.

    The atomic Lua script is what makes this hold: a capacity check and a slot
    reservation split across two round trips would let several clients observe
    the same free slot and all take it. This is the many-client race the unit
    suite defers to a live server; ``fakeredis`` never reproduces it, because a
    single sequential client cannot over-admit.

    One round only lands the interleaving that exposes an over-admitting
    implementation about nine times in ten, so the race is run repeatedly. A
    round costs a full acquire timeout, since the losers each wait theirs out,
    which is why the timeout here is much shorter than elsewhere in this file.

    Every thread hands its result back through a future, so a worker that dies
    fails the test. Left unchecked it would only warn, and the race this test
    exists for would silently shrink to the threads that survived.
    """
    maxsize = 3
    thread_count = 12
    rounds = 5
    redis_key = semaphore_redis_key(semaphore_key)

    def contend(barrier):
        sem = utils.RedisSemaphore(redis_client, semaphore_key, maxsize, timeout=0.1)
        barrier.wait()
        return sem if sem.acquire() else None

    for _ in range(rounds):
        # A timeout on the barrier turns a thread that never arrives into a
        # failed assertion rather than a hung CI job.
        barrier = threading.Barrier(thread_count, timeout=30)

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as pool:
            futures = [pool.submit(contend, barrier) for _ in range(thread_count)]
            acquired = [sem for sem in (future.result() for future in futures) if sem]

        # Nothing is released before every future has been collected, so the
        # holder count is stable here.
        assert len(acquired) == maxsize
        assert redis_client.zcard(redis_key) == maxsize

        for sem in acquired:
            sem.release()

        assert redis_client.zcard(redis_key) == 0
        redis_client.delete(redis_key)
