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


def test_acquire_succeeds_on_first_try_when_below_maxsize(mocker):
    redis = mocker.MagicMock()
    redis.zcard.return_value = 0
    sem = utils_pkg.RedisSemaphore(redis, "job", 2, timeout=10)
    mocker.patch("osism.utils.time.time", return_value=100.0)
    sleep = mocker.patch("osism.utils.time.sleep")
    uuid4 = mocker.patch("osism.utils.uuid.uuid4", return_value="fixed-id")

    assert sem.acquire() is True

    redis.zadd.assert_called_once_with("semaphore:job", {"fixed-id": 100.0})
    assert sem.identifier == "fixed-id"
    uuid4.assert_called_once_with()
    sleep.assert_not_called()


def test_acquire_returns_false_when_full_for_whole_window(mocker):
    redis = mocker.MagicMock()
    redis.zcard.return_value = 5  # always at capacity (maxsize=5)
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    # now=0 (call 1); loop check 0.001 < 10 enters one iteration; 11 < 10 exits.
    mocker.patch("osism.utils.time.time", side_effect=[0, 0.001, 11])
    sleep = mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    redis.zadd.assert_not_called()
    assert sem.identifier is None
    sleep.assert_called_once_with(0.01)


def test_acquire_cleans_up_expired_holders_each_iteration(mocker):
    """``zremrangebyscore`` runs once per loop iteration to evict holders
    whose score is older than 60 seconds (``now - 60``)."""
    redis = mocker.MagicMock()
    redis.zcard.return_value = 5
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    # now=0; loop checks 1 and 2 enter (two iterations); 11 exits.
    mocker.patch("osism.utils.time.time", side_effect=[0, 1, 2, 11])
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    assert redis.zremrangebyscore.call_count == 2
    redis.zremrangebyscore.assert_called_with("semaphore:job", 0, -60)


def test_acquire_default_timeout_is_ten_seconds(mocker):
    """With both the call and instance timeout unset the loop deadline is
    ``now + 10``. Probing the boundary at 9.5/10.5 proves the fallback: one
    iteration runs (9.5 < 10) and the next check exits (10.5 < 10)."""
    redis = mocker.MagicMock()
    redis.zcard.return_value = 5  # full → never acquires, loop runs to deadline
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=None)
    mocker.patch("osism.utils.time.time", side_effect=[0, 9.5, 10.5])
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire() is False

    assert redis.zremrangebyscore.call_count == 1


def test_acquire_explicit_timeout_overrides_instance(mocker):
    """An explicit ``timeout=5`` wins over the instance's ``timeout=999``.
    The deadline is ``now + 5``; the side_effect supplies exactly the values
    one short window consumes. Had the instance value been used, the loop
    would request a fourth ``time.time`` value and raise ``StopIteration``."""
    redis = mocker.MagicMock()
    redis.zcard.return_value = 5
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=999)
    mocker.patch("osism.utils.time.time", side_effect=[0, 4.5, 5.5])
    mocker.patch("osism.utils.time.sleep")

    assert sem.acquire(timeout=5) is False

    assert redis.zremrangebyscore.call_count == 1


def test_acquire_uses_fresh_uuid_per_call(mocker):
    redis = mocker.MagicMock()
    redis.zcard.return_value = 0
    sem = utils_pkg.RedisSemaphore(redis, "job", 5, timeout=10)
    mocker.patch("osism.utils.time.time", return_value=50.0)
    mocker.patch("osism.utils.time.sleep")
    uuid4 = mocker.patch("osism.utils.uuid.uuid4", side_effect=["id-1", "id-2"])

    assert sem.acquire() is True
    assert sem.identifier == "id-1"
    assert sem.acquire() is True
    assert sem.identifier == "id-2"

    assert uuid4.call_count == 2
    zadd_payloads = [c.args[1] for c in redis.zadd.call_args_list]
    assert zadd_payloads == [{"id-1": 50.0}, {"id-2": 50.0}]


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
