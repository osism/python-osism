# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the concurrency primitives and task-lock helpers in
:mod:`osism.utils`.

Companion to ``test_init_connections.py`` and ``test_init_task_output.py``.
Covers the ``RedisSemaphore`` class, ``create_redlock``,
``create_netbox_semaphore`` and the global task-lock helpers
(``set_task_lock``, ``remove_task_lock``, ``is_task_locked`` and
``check_task_lock_and_exit``).

``_init_redis`` is patched per-test to return a ``MagicMock`` redis client.
``time.time``/``time.sleep`` and ``uuid.uuid4`` are patched so the semaphore
acquisition loop terminates deterministically.
"""

import hashlib
import json
import re

import pytest

import osism.utils as utils_pkg

# ---------------------------------------------------------------------------
# RedisSemaphore.__init__
# ---------------------------------------------------------------------------


def test_init_stores_attributes(mocker):
    redis = mocker.MagicMock()

    sem = utils_pkg.RedisSemaphore(redis, "job", 7, timeout=15)

    assert sem.redis is redis
    assert sem.key == "semaphore:job"
    assert sem.maxsize == 7
    assert sem.timeout == 15
    assert sem.identifier is None


def test_init_timeout_defaults_to_none(mocker):
    sem = utils_pkg.RedisSemaphore(mocker.MagicMock(), "job", 1)

    assert sem.timeout is None


def test_init_prefixes_key_even_when_already_prefixed(mocker):
    """The ``semaphore:`` prefix is applied unconditionally — an input that
    already starts with it is prefixed again (no double-strip)."""
    sem = utils_pkg.RedisSemaphore(mocker.MagicMock(), "semaphore:job", 1)

    assert sem.key == "semaphore:semaphore:job"


# ---------------------------------------------------------------------------
# RedisSemaphore.acquire
# ---------------------------------------------------------------------------


def test_acquire_grants_slot_on_first_try(mocker):
    """Acquisition is a single atomic ``EVAL``: cleanup, capacity check and
    reservation happen server-side (see ``_ACQUIRE_LUA``). A returned ``1``
    means the slot was reserved, so ``acquire`` records the identifier and
    returns without sleeping."""
    redis = mocker.MagicMock()
    redis.eval.return_value = 1
    sem = utils_pkg.RedisSemaphore(redis, "job", 2, timeout=10)
    mocker.patch("osism.utils.time.time", return_value=100.0)
    sleep = mocker.patch("osism.utils.time.sleep")
    uuid4 = mocker.patch("osism.utils.uuid.uuid4", return_value="fixed-id")

    assert sem.acquire() is True

    redis.eval.assert_called_once_with(
        utils_pkg.RedisSemaphore._ACQUIRE_LUA,
        1,  # numkeys
        "semaphore:job",
        100.0,  # now
        2,  # maxsize
        "fixed-id",  # identifier
        utils_pkg.RedisSemaphore.HOLDER_EXPIRY,
    )
    assert sem.identifier == "fixed-id"
    uuid4.assert_called_once_with()
    sleep.assert_not_called()


def test_acquire_returns_false_when_full_for_whole_window(mocker):
    """A ``0`` from the Lua script means no slot was free; the loop retries
    until the deadline and then gives up without recording an identifier."""
    redis = mocker.MagicMock()
    redis.eval.return_value = 0  # the script's capacity check never passes
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    # end_time=0+10; while-check 0.001 enters, now read 0.002, while-check 11 exits.
    mocker.patch("osism.utils.time.time", side_effect=[0, 0.001, 0.002, 11])
    sleep = mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    assert sem.identifier is None
    sleep.assert_called_once_with(0.01)


def test_acquire_recomputes_now_each_iteration(mocker):
    """The reclaim boundary advances between retries. ``now`` is read afresh
    inside the loop and handed to the script on every ``eval`` (which runs
    ``ZREMRANGEBYSCORE key 0 now-expiry`` server-side), so a holder that ages
    past ``HOLDER_EXPIRY`` while a caller waits is reclaimed on the next retry
    rather than being pinned to the first ``now``."""
    redis = mocker.MagicMock()
    redis.eval.return_value = 0  # never acquires → loop runs to the deadline
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    # end_time=100+10; two iterations read now=101 then now=102; 111 exits.
    mocker.patch(
        "osism.utils.time.time",
        side_effect=[100, 100.5, 101, 101.5, 102, 111],
    )
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    assert redis.eval.call_count == 2
    now_per_call = [call.args[3] for call in redis.eval.call_args_list]
    assert now_per_call == [101, 102]  # advancing, not frozen at the first now


def test_acquire_default_timeout_is_ten_seconds(mocker):
    """With both the call and instance timeout unset the loop deadline is
    ``now + 10``. The while-check enters at 9.5 (< 10) and exits at 10.5,
    so exactly one ``eval`` runs."""
    redis = mocker.MagicMock()
    redis.eval.return_value = 0  # never acquires, loop runs to deadline
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=None)
    # end_time=0+10; while-check 9.5 enters, now read 9.6, while-check 10.5 exits.
    mocker.patch("osism.utils.time.time", side_effect=[0, 9.5, 9.6, 10.5])
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    assert redis.eval.call_count == 1


def test_acquire_explicit_timeout_overrides_instance(mocker):
    """An explicit ``timeout=5`` wins over the instance's ``timeout=999``.
    The deadline is ``now + 5``; the side_effect supplies exactly the values
    one short window consumes. Had the instance value been used, the loop
    would request a further ``time.time`` value and raise ``StopIteration``."""
    redis = mocker.MagicMock()
    redis.eval.return_value = 0
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=999)
    # end_time=0+5; while-check 4.5 enters, now read 4.6, while-check 5.5 exits.
    mocker.patch("osism.utils.time.time", side_effect=[0, 4.5, 4.6, 5.5])
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire(timeout=5) is False

    assert redis.eval.call_count == 1


def test_acquire_uses_fresh_uuid_per_call(mocker):
    redis = mocker.MagicMock()
    redis.eval.return_value = 1
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    mocker.patch("osism.utils.time.time", return_value=50.0)
    mocker.patch("osism.utils.time.sleep")
    uuid4 = mocker.patch("osism.utils.uuid.uuid4", side_effect=["id-1", "id-2"])

    assert sem.acquire() is True
    assert sem.identifier == "id-1"
    assert sem.acquire() is True
    assert sem.identifier == "id-2"

    assert uuid4.call_count == 2
    identifiers = [call.args[5] for call in redis.eval.call_args_list]
    assert identifiers == ["id-1", "id-2"]


# ---------------------------------------------------------------------------
# RedisSemaphore.release
# ---------------------------------------------------------------------------


def test_release_removes_identifier_and_clears_it(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    sem.identifier = "holder-1"

    sem.release()

    redis.zrem.assert_called_once_with("semaphore:job", "holder-1")
    assert sem.identifier is None


def test_release_twice_is_noop_second_time(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    sem.identifier = "holder-1"

    sem.release()
    sem.release()

    redis.zrem.assert_called_once_with("semaphore:job", "holder-1")


def test_release_without_acquire_is_noop(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)

    sem.release()

    redis.zrem.assert_not_called()
    assert sem.identifier is None


# ---------------------------------------------------------------------------
# RedisSemaphore context manager (__enter__ / __exit__)
# ---------------------------------------------------------------------------


def test_enter_returns_self_when_acquire_succeeds(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    mocker.patch.object(sem, "acquire", return_value=True)
    release = mocker.patch.object(sem, "release")

    with sem as entered:
        assert entered is sem

    release.assert_called_once_with()


def test_enter_raises_timeout_error_when_acquire_fails(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    mocker.patch.object(sem, "acquire", return_value=False)

    with pytest.raises(TimeoutError, match="semaphore:job"):
        with sem:
            pass


def test_exit_calls_release_and_returns_false(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    release = mocker.patch.object(sem, "release")

    result = sem.__exit__(None, None, None)

    assert result is False
    release.assert_called_once_with()


def test_exit_does_not_swallow_exceptions(mocker):
    redis = mocker.MagicMock()
    sem = utils_pkg.RedisSemaphore(redis, "job", 5)
    mocker.patch.object(sem, "acquire", return_value=True)
    release = mocker.patch.object(sem, "release")

    with pytest.raises(ValueError, match="boom"):
        with sem:
            raise ValueError("boom")

    release.assert_called_once_with()


# ---------------------------------------------------------------------------
# create_redlock
# ---------------------------------------------------------------------------


def _patch_redlock(mocker, *, redis=None, lock=None):
    """Wire the dependencies ``create_redlock`` touches.

    ``logging.getLogger`` is patched to a mock so the test never mutates the
    real (process-global) ``pottery`` logger level. ``pottery.Redlock`` is
    patched on the ``pottery`` module because the production code imports it
    lazily inside the function (``from pottery import Redlock``).

    Returns ``(redlock_cls, redis, lock, pottery_logger, get_logger)``.
    """
    redis = redis if redis is not None else mocker.MagicMock(name="redis")
    lock = lock if lock is not None else mocker.MagicMock(name="redlock")
    mocker.patch("osism.utils._init_redis", return_value=redis)
    redlock_cls = mocker.patch("pottery.Redlock", return_value=lock)
    pottery_logger = mocker.MagicMock(name="pottery-logger")
    get_logger = mocker.patch("logging.getLogger", return_value=pottery_logger)
    return redlock_cls, redis, lock, pottery_logger, get_logger


def test_create_redlock_returns_configured_instance(mocker):
    redlock_cls, redis, lock, _logger, _get_logger = _patch_redlock(mocker)

    result = utils_pkg.create_redlock("my-lock")

    assert result is lock
    redlock_cls.assert_called_once_with(
        key="my-lock", masters={redis}, auto_release_time=3600
    )


def test_create_redlock_custom_auto_release_time(mocker):
    redlock_cls, redis, _lock, _logger, _get_logger = _patch_redlock(mocker)

    utils_pkg.create_redlock("my-lock", auto_release_time=600)

    redlock_cls.assert_called_once_with(
        key="my-lock", masters={redis}, auto_release_time=600
    )


def test_create_redlock_sets_pottery_logger_to_critical(mocker):
    import logging

    _cls, _redis, _lock, pottery_logger, get_logger = _patch_redlock(mocker)

    utils_pkg.create_redlock("my-lock")

    get_logger.assert_called_once_with("pottery")
    pottery_logger.setLevel.assert_called_once_with(logging.CRITICAL)


def test_create_redlock_suppresses_construction_output(mocker, capsys):
    """stdout/stderr written while ``Redlock`` is constructed must be
    swallowed by the ``redirect_stdout``/``redirect_stderr`` to devnull."""
    import sys

    lock = mocker.MagicMock(name="redlock")

    def _noisy(**kwargs):
        print("stdout-noise")
        print("stderr-noise", file=sys.stderr)
        return lock

    mocker.patch("osism.utils._init_redis", return_value=mocker.MagicMock())
    mocker.patch("pottery.Redlock", side_effect=_noisy)
    mocker.patch("logging.getLogger", return_value=mocker.MagicMock())

    result = utils_pkg.create_redlock("my-lock")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert result is lock


# ---------------------------------------------------------------------------
# create_netbox_semaphore
# ---------------------------------------------------------------------------


def _expected_semaphore_key(url):
    """Mirror the key the helper builds, including RedisSemaphore's prefix."""
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"semaphore:netbox_semaphore_{url_hash}"


def test_create_netbox_semaphore_uses_settings_default(mocker):
    mocker.patch("osism.utils._init_redis", return_value=mocker.MagicMock())
    mocker.patch("osism.utils.settings.NETBOX_MAX_CONNECTIONS", 7)

    sem = utils_pkg.create_netbox_semaphore("https://nb.example")

    assert isinstance(sem, utils_pkg.RedisSemaphore)
    assert sem.maxsize == 7


def test_create_netbox_semaphore_explicit_max_connections(mocker):
    mocker.patch("osism.utils._init_redis", return_value=mocker.MagicMock())
    mocker.patch("osism.utils.settings.NETBOX_MAX_CONNECTIONS", 5)

    sem = utils_pkg.create_netbox_semaphore("https://nb.example", max_connections=20)

    assert sem.maxsize == 20


def test_create_netbox_semaphore_key_timeout_and_client(mocker):
    redis = mocker.MagicMock()
    init_redis = mocker.patch("osism.utils._init_redis", return_value=redis)
    mocker.patch("osism.utils.settings.NETBOX_MAX_CONNECTIONS", 5)
    url = "https://nb.example"

    sem = utils_pkg.create_netbox_semaphore(url)

    assert sem.key == _expected_semaphore_key(url)
    assert sem.timeout == 30
    assert sem.redis is redis
    init_redis.assert_called_once_with()


def test_create_netbox_semaphore_different_urls_differ(mocker):
    mocker.patch("osism.utils._init_redis", return_value=mocker.MagicMock())
    mocker.patch("osism.utils.settings.NETBOX_MAX_CONNECTIONS", 5)

    sem_a = utils_pkg.create_netbox_semaphore("https://a.example")
    sem_b = utils_pkg.create_netbox_semaphore("https://b.example")

    assert sem_a.key != sem_b.key


def test_create_netbox_semaphore_same_url_identical_key(mocker):
    mocker.patch("osism.utils._init_redis", return_value=mocker.MagicMock())
    mocker.patch("osism.utils.settings.NETBOX_MAX_CONNECTIONS", 5)

    sem_a = utils_pkg.create_netbox_semaphore("https://same.example")
    sem_b = utils_pkg.create_netbox_semaphore("https://same.example")

    assert sem_a.key == sem_b.key
