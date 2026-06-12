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


# ---------------------------------------------------------------------------
# set_task_lock
# ---------------------------------------------------------------------------

_TASK_LOCK_KEY = "osism:task_lock"
_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _captured_lock_payload(mock_r):
    """Return the JSON payload ``set_task_lock`` wrote to redis as a dict."""
    mock_r.set.assert_called_once()
    args = mock_r.set.call_args.args
    assert args[0] == _TASK_LOCK_KEY
    return json.loads(args[1])


def test_set_task_lock_user_none_falls_back_to_operator_user(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    mocker.patch("osism.utils.settings.OPERATOR_USER", "operator-x")

    assert utils_pkg.set_task_lock(user=None) is True

    assert _captured_lock_payload(mock_r)["user"] == "operator-x"


def test_set_task_lock_explicit_user_used_directly(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    mocker.patch("osism.utils.settings.OPERATOR_USER", "operator-x")

    assert utils_pkg.set_task_lock(user="alice") is True

    assert _captured_lock_payload(mock_r)["user"] == "alice"


def test_set_task_lock_reason_none_stored_as_null(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    mocker.patch("osism.utils.settings.OPERATOR_USER", "operator-x")

    utils_pkg.set_task_lock(reason=None)

    assert _captured_lock_payload(mock_r)["reason"] is None


def test_set_task_lock_payload_contents(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    mocker.patch("osism.utils.settings.OPERATOR_USER", "operator-x")

    utils_pkg.set_task_lock(user="alice", reason="maintenance")

    payload = _captured_lock_payload(mock_r)
    assert payload["locked"] is True
    assert payload["user"] == "alice"
    assert payload["reason"] == "maintenance"
    assert _ISO_TIMESTAMP_RE.match(payload["timestamp"])


def test_set_task_lock_redis_failure_returns_false(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.set.side_effect = RuntimeError("redis down")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    mocker.patch("osism.utils.settings.OPERATOR_USER", "operator-x")

    assert utils_pkg.set_task_lock(user="alice") is False

    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to set task lock" in m for m in errors)
    assert any("redis down" in m for m in errors)


# ---------------------------------------------------------------------------
# remove_task_lock
# ---------------------------------------------------------------------------


def test_remove_task_lock_deletes_key_returns_true(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    assert utils_pkg.remove_task_lock() is True

    mock_r.delete.assert_called_once_with(_TASK_LOCK_KEY)


def test_remove_task_lock_failure_returns_false(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.delete.side_effect = RuntimeError("redis down")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    assert utils_pkg.remove_task_lock() is False

    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to remove task lock" in m for m in errors)


# ---------------------------------------------------------------------------
# is_task_locked
# ---------------------------------------------------------------------------


def test_is_task_locked_returns_none_when_unset(mocker):
    mock_r = mocker.MagicMock()
    mock_r.get.return_value = None
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    assert utils_pkg.is_task_locked() is None

    mock_r.get.assert_called_once_with(_TASK_LOCK_KEY)


def test_is_task_locked_decodes_and_parses_json(mocker):
    """The raw redis value is byte-decoded via ``.decode("utf-8")`` before
    being parsed; a mock value lets us assert the decode call explicitly."""
    raw = mocker.MagicMock(name="lock-bytes")
    raw.decode.return_value = '{"locked": true, "user": "alice"}'
    mock_r = mocker.MagicMock()
    mock_r.get.return_value = raw
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    result = utils_pkg.is_task_locked()

    raw.decode.assert_called_once_with("utf-8")
    assert result == {"locked": True, "user": "alice"}


def test_is_task_locked_get_failure_returns_none(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.get.side_effect = RuntimeError("redis down")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    assert utils_pkg.is_task_locked() is None

    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to check task lock status" in m for m in errors)


def test_is_task_locked_invalid_json_returns_none(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.get.return_value = b"not-json"
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    assert utils_pkg.is_task_locked() is None

    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to check task lock status" in m for m in errors)


# ---------------------------------------------------------------------------
# check_task_lock_and_exit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lock_info",
    [None, {"locked": False}],
    ids=["no_lock", "locked_false"],
)
def test_check_task_lock_and_exit_no_lock_does_not_exit(mocker, lock_info):
    mocker.patch("osism.utils.is_task_locked", return_value=lock_info)
    exit_mock = mocker.patch("builtins.exit")

    assert utils_pkg.check_task_lock_and_exit() is None

    exit_mock.assert_not_called()


def test_check_task_lock_and_exit_locked_logs_and_exits(mocker, loguru_logs):
    mocker.patch(
        "osism.utils.is_task_locked",
        return_value={
            "locked": True,
            "user": "alice",
            "timestamp": "2026-01-02T03:04:05",
            "reason": "maintenance",
        },
    )
    exit_mock = mocker.patch("builtins.exit")

    utils_pkg.check_task_lock_and_exit()

    exit_mock.assert_called_once_with(1)
    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("locked by alice at 2026-01-02T03:04:05" in m for m in errors)
    assert any("Reason: maintenance" in m for m in errors)
    assert any("osism unlock" in m for m in errors)


def test_check_task_lock_and_exit_no_reason_skips_reason_line(mocker, loguru_logs):
    mocker.patch(
        "osism.utils.is_task_locked",
        return_value={
            "locked": True,
            "user": "alice",
            "timestamp": "2026-01-02T03:04:05",
            "reason": None,
        },
    )
    mocker.patch("builtins.exit")

    utils_pkg.check_task_lock_and_exit()

    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert not any(m.startswith("Reason:") for m in errors)


def test_check_task_lock_and_exit_missing_fields_default_unknown(mocker, loguru_logs):
    mocker.patch("osism.utils.is_task_locked", return_value={"locked": True})
    exit_mock = mocker.patch("builtins.exit")

    utils_pkg.check_task_lock_and_exit()

    exit_mock.assert_called_once_with(1)
    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("locked by unknown at unknown" in m for m in errors)
    assert not any(m.startswith("Reason:") for m in errors)
