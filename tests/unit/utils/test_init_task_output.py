# SPDX-License-Identifier: Apache-2.0

"""Unit tests for task-output streaming, task revocation, the ansible-vault
password helper, the ansible-facts freshness check, and the ``first`` iterator
helper from :mod:`osism.utils`.

Companion to ``test_init_connections.py``. ``_init_redis`` is the single
dependency most helpers share — it is patched per-test to return a
``MagicMock`` redis client.
"""

from unittest.mock import call, mock_open

import pytest

import osism.utils as utils_pkg

# ---------------------------------------------------------------------------
# first
# ---------------------------------------------------------------------------


def test_first_returns_first_matching_item():
    assert utils_pkg.first((1, 2, 3), condition=lambda x: x % 2 == 0) == 2


def test_first_default_condition_returns_first_item():
    assert utils_pkg.first(range(3, 100)) == 3


def test_first_empty_iterable_raises_stop_iteration():
    with pytest.raises(StopIteration):
        utils_pkg.first(())


def test_first_no_match_raises_stop_iteration():
    with pytest.raises(StopIteration):
        utils_pkg.first([1, 3, 5], condition=lambda x: x % 2 == 0)


def test_first_consumes_generator_lazily():
    """``first`` must stop iterating as soon as a match is found.

    A generator that records how many items it produced lets us verify that
    items past the first match are not pulled.
    """
    pulled = []

    def gen():
        for i in range(10):
            pulled.append(i)
            yield i

    g = gen()
    result = utils_pkg.first(g, condition=lambda x: x == 2)

    assert result == 2
    # Items 0, 1, 2 are pulled; 3+ must remain untouched.
    assert pulled == [0, 1, 2]
    # The generator is still alive and yields the next item on demand.
    assert next(g) == 3


# ---------------------------------------------------------------------------
# fetch_task_output
# ---------------------------------------------------------------------------


def _xread_payload(message_id: bytes, msg_type: bytes, content: bytes):
    """Build an ``xread`` return value matching the production unpacking."""
    return [(b"task-id", [(message_id, {b"type": msg_type, b"content": content})])]


def test_fetch_task_output_stdout_then_rc_then_quit(mocker, capsys):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"hello"),
        _xread_payload(b"2-0", b"rc", b"7"),
        _xread_payload(b"3-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    result = utils_pkg.fetch_task_output("task-1", timeout=5)

    assert result == 7
    captured = capsys.readouterr()
    assert captured.out == "hello"
    mock_r.close.assert_called_once_with()


def test_fetch_task_output_default_rc_when_no_rc_message(mocker, capsys):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"line\n"),
        _xread_payload(b"2-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    result = utils_pkg.fetch_task_output("task-1", timeout=5)

    assert result == 0
    assert capsys.readouterr().out == "line\n"


def test_fetch_task_output_play_recap_log_when_enabled(mocker, capsys, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"PLAY RECAP **********\n"),
        _xread_payload(b"2-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.fetch_task_output("task-1", timeout=5, enable_play_recap=True)

    info_messages = [r["message"] for r in loguru_logs if r["level"] == "INFO"]
    assert any("Play has been completed" in m for m in info_messages)
    assert any("do not abort execution" in m for m in info_messages)
    assert "PLAY RECAP **********\n" in capsys.readouterr().out


def test_fetch_task_output_play_recap_no_log_when_disabled(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"PLAY RECAP **********\n"),
        _xread_payload(b"2-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.fetch_task_output("task-1", timeout=5, enable_play_recap=False)

    info_messages = [r["message"] for r in loguru_logs if r["level"] == "INFO"]
    assert not any("Play has been completed" in m for m in info_messages)


def test_fetch_task_output_xdel_called_per_message(mocker):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"a"),
        _xread_payload(b"2-0", b"stdout", b"b"),
        _xread_payload(b"3-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.fetch_task_output("task-1", timeout=5)

    assert mock_r.xdel.call_args_list == [
        call("task-1", "1-0"),
        call("task-1", "2-0"),
        call("task-1", "3-0"),
    ]


def test_fetch_task_output_last_id_threaded_through_xread(mocker):
    """After processing a batch the next ``xread`` must reference the most
    recently consumed message id, so Redis doesn't re-deliver it."""
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"42-0", b"stdout", b"a"),
        _xread_payload(b"99-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.fetch_task_output("task-1", timeout=5)

    first_call_args, _ = mock_r.xread.call_args_list[0]
    second_call_args, _ = mock_r.xread.call_args_list[1]
    assert first_call_args[0] == {"task-1": 0}
    assert second_call_args[0] == {"task-1": "42-0"}


def test_fetch_task_output_timeout_when_xread_returns_none(mocker):
    mock_r = mocker.MagicMock()
    mock_r.xread.return_value = None
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    # time.time() is called once to compute ``stoptime`` and once per loop
    # iteration. Returning a value past the deadline on the second poll exits
    # the loop and raises ``TimeoutError``.
    time_values = iter([0.0, 0.0, 100.0])
    mocker.patch("osism.utils.time.time", side_effect=lambda: next(time_values))

    with pytest.raises(TimeoutError):
        utils_pkg.fetch_task_output("task-1", timeout=10)


def test_fetch_task_output_data_resets_deadline(mocker):
    """When ``xread`` returns data the loop must reset its deadline.

    We assert this indirectly: the function reads ``time.time()`` once
    before the loop (set initial ``stoptime``), once per loop check, and
    once again inside the ``if data:`` branch to reset the deadline.
    Three iterations that all return data therefore consume exactly seven
    ``time.time()`` calls (1 initial + 3 loop checks + 3 deadline resets).
    """
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"stdout", b"a"),
        _xread_payload(b"2-0", b"stdout", b"b"),
        _xread_payload(b"3-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    time_calls = []

    def fake_time():
        time_calls.append(len(time_calls))
        return 0.0

    mocker.patch("osism.utils.time.time", side_effect=fake_time)

    utils_pkg.fetch_task_output("task-1", timeout=5)

    # 1 initial + 3 loop-check entries + 3 in-branch resets.
    assert len(time_calls) == 7


def test_fetch_task_output_quit_closes_redis_and_returns_rc(mocker):
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [
        _xread_payload(b"1-0", b"rc", b"3"),
        _xread_payload(b"2-0", b"action", b"quit"),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    result = utils_pkg.fetch_task_output("task-1", timeout=5)

    assert result == 3
    mock_r.close.assert_called_once_with()


def test_fetch_task_output_honours_explicit_timeout_kwarg(mocker):
    """``timeout=`` propagates into the ``xread`` ``block`` parameter
    (milliseconds)."""
    mock_r = mocker.MagicMock()
    mock_r.xread.side_effect = [_xread_payload(b"1-0", b"action", b"quit")]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.fetch_task_output("task-1", timeout=42)

    _args, kwargs = mock_r.xread.call_args
    assert kwargs.get("block") == 42 * 1000


# ---------------------------------------------------------------------------
# push_task_output
# ---------------------------------------------------------------------------


def test_push_task_output_xadds_stdout_once(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.push_task_output("task-1", "hello\n")

    mock_r.xadd.assert_called_once_with(
        "task-1", {"type": "stdout", "content": "hello\n"}
    )


# ---------------------------------------------------------------------------
# finish_task_output
# ---------------------------------------------------------------------------


def test_finish_task_output_rc_none_publishes_only_quit(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.finish_task_output("task-1", rc=None)

    mock_r.xadd.assert_called_once_with("task-1", {"type": "action", "content": "quit"})


def test_finish_task_output_rc_zero_publishes_only_quit(mocker):
    """``if rc:`` is intentionally truthy — rc=0 must be treated like rc=None."""
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.finish_task_output("task-1", rc=0)

    mock_r.xadd.assert_called_once_with("task-1", {"type": "action", "content": "quit"})


def test_finish_task_output_nonzero_rc_publishes_rc_then_quit(mocker):
    mock_r = mocker.MagicMock()
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.finish_task_output("task-1", rc=1)

    assert mock_r.xadd.call_args_list == [
        call("task-1", {"type": "rc", "content": 1}),
        call("task-1", {"type": "action", "content": "quit"}),
    ]


# ---------------------------------------------------------------------------
# revoke_task
# ---------------------------------------------------------------------------


def test_revoke_task_happy_path(mocker):
    app = mocker.MagicMock()
    celery_cls = mocker.patch("celery.Celery", return_value=app)
    config_sentinel = mocker.MagicMock(name="Config")
    mocker.patch("osism.tasks.Config", config_sentinel)

    result = utils_pkg.revoke_task("task-1")

    assert result is True
    celery_cls.assert_called_once_with("task")
    app.config_from_object.assert_called_once_with(config_sentinel)
    app.control.revoke.assert_called_once_with("task-1", terminate=True)


def test_revoke_task_celery_construction_fails(mocker, loguru_logs):
    mocker.patch("celery.Celery", side_effect=RuntimeError("boom"))

    result = utils_pkg.revoke_task("task-1")

    assert result is False
    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to revoke task task-1" in m for m in error_messages)


def test_revoke_task_revoke_call_fails(mocker, loguru_logs):
    app = mocker.MagicMock()
    app.control.revoke.side_effect = RuntimeError("nope")
    mocker.patch("celery.Celery", return_value=app)
    mocker.patch("osism.tasks.Config", mocker.MagicMock())

    result = utils_pkg.revoke_task("task-1")

    assert result is False
    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to revoke task task-1" in m for m in error_messages)
    assert any("nope" in m for m in error_messages)


# ---------------------------------------------------------------------------
# get_ansible_vault_password
# ---------------------------------------------------------------------------


def _patch_vault_chain(mocker, *, redis_value, fernet_decrypted):
    """Wire the open/Fernet/redis chain used by ``get_ansible_vault_password``.

    Returns the ``Fernet`` class mock so callers can assert how it was called.
    """
    mocker.patch("builtins.open", mock_open(read_data="fernet-key"))
    fernet_instance = mocker.MagicMock()
    fernet_instance.decrypt.return_value = fernet_decrypted
    fernet_cls = mocker.patch(
        "cryptography.fernet.Fernet", return_value=fernet_instance
    )
    mock_r = mocker.MagicMock()
    mock_r.get.return_value = redis_value
    mocker.patch("osism.utils._init_redis", return_value=mock_r)
    return fernet_cls, fernet_instance, mock_r


def test_get_ansible_vault_password_happy_path(mocker):
    fernet_cls, fernet_instance, mock_r = _patch_vault_chain(
        mocker,
        redis_value=b"encrypted-blob",
        fernet_decrypted=b"my-secret",
    )

    result = utils_pkg.get_ansible_vault_password()

    # The production code does NOT strip — verify the raw decoded text is
    # returned (the strip check only guards the empty-string branch).
    assert result == "my-secret"
    fernet_cls.assert_called_once_with("fernet-key")
    fernet_instance.decrypt.assert_called_once_with(b"encrypted-blob")
    mock_r.get.assert_called_once_with("ansible_vault_password")


def test_get_ansible_vault_password_redis_returns_none(mocker, loguru_logs):
    _patch_vault_chain(mocker, redis_value=None, fernet_decrypted=b"unused")

    with pytest.raises(ValueError, match="not set in Redis"):
        utils_pkg.get_ansible_vault_password()

    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Unable to get ansible vault password" in m for m in error_messages)


def test_get_ansible_vault_password_empty_decrypted(mocker, loguru_logs):
    _patch_vault_chain(mocker, redis_value=b"enc", fernet_decrypted=b"")

    with pytest.raises(ValueError, match="empty or contains only whitespace"):
        utils_pkg.get_ansible_vault_password()

    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Unable to get ansible vault password" in m for m in error_messages)


def test_get_ansible_vault_password_whitespace_decrypted(mocker):
    _patch_vault_chain(mocker, redis_value=b"enc", fernet_decrypted=b"   \n\t")

    with pytest.raises(ValueError, match="empty or contains only whitespace"):
        utils_pkg.get_ansible_vault_password()


def test_get_ansible_vault_password_keyfile_missing(mocker, loguru_logs):
    mocker.patch("builtins.open", side_effect=FileNotFoundError("no key"))

    with pytest.raises(FileNotFoundError, match="no key"):
        utils_pkg.get_ansible_vault_password()

    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Unable to get ansible vault password" in m for m in error_messages)


def test_get_ansible_vault_password_fernet_decrypt_raises(mocker, loguru_logs):
    mocker.patch("builtins.open", mock_open(read_data="fernet-key"))
    fernet_instance = mocker.MagicMock()
    fernet_instance.decrypt.side_effect = RuntimeError("bad token")
    mocker.patch("cryptography.fernet.Fernet", return_value=fernet_instance)
    mock_r = mocker.MagicMock()
    mock_r.get.return_value = b"enc"
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    with pytest.raises(RuntimeError, match="bad token"):
        utils_pkg.get_ansible_vault_password()

    error_messages = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Unable to get ansible vault password" in m for m in error_messages)


# ---------------------------------------------------------------------------
# check_ansible_facts
# ---------------------------------------------------------------------------


def _facts_payload(epoch):
    """Return JSON bytes shaped like an ansible facts blob."""
    import json

    return json.dumps({"ansible_date_time": {"epoch": epoch}}).encode("utf-8")


def test_check_ansible_facts_scan_raises_logs_warning(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.scan.side_effect = RuntimeError("redis down")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("Could not check Ansible facts freshness" in m for m in warnings)
    assert any("redis down" in m for m in warnings)
    # No further work after the scan failed.
    mock_r.get.assert_not_called()


def test_check_ansible_facts_no_keys_logs_warning(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [])
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("No Ansible facts found in Redis cache" in m for m in warnings)


def test_check_ansible_facts_one_stale_host(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = _facts_payload(now - 9999)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("stale for 1 host(s)" in m for m in warnings)
    assert any("host-a" in m and "seconds old" in m for m in warnings)


def test_check_ansible_facts_one_fresh_host_no_warning(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = _facts_payload(now - 1)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert not any("stale" in m for m in warnings)


def test_check_ansible_facts_mix_of_fresh_and_stale(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (
        0,
        [b"ansible_factsfresh-host", b"ansible_factsstale-host"],
    )
    mock_r.get.side_effect = [
        _facts_payload(now - 1),
        _facts_payload(now - 9999),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("stale for 1 host(s)" in m for m in warnings)
    assert any("stale-host" in m for m in warnings)
    assert not any("fresh-host" in m for m in warnings)


def test_check_ansible_facts_hostname_prefix_stripped(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factsmy.host.example"])
    mock_r.get.return_value = _facts_payload(now - 9999)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("my.host.example" in m for m in warnings)
    # The literal "ansible_facts" prefix must not appear in the hostname
    # surfaced in the per-host warning line.
    per_host = [m for m in warnings if "seconds old" in m]
    assert per_host
    for line in per_host:
        assert "ansible_factsmy.host.example" not in line


@pytest.mark.parametrize(
    "key",
    [b"ansible_factshost-a", "ansible_factshost-a"],
    ids=["bytes", "str"],
)
def test_check_ansible_facts_bytes_or_str_keys(mocker, loguru_logs, key):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [key])
    mock_r.get.return_value = _facts_payload(now - 9999)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("host-a" in m for m in warnings)


def test_check_ansible_facts_get_returns_none_host_skipped(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = None
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    # No keys-found warning (a key was found) and no stale warning either.
    assert not any("stale" in m for m in warnings)
    assert not any("No Ansible facts found" in m for m in warnings)


def test_check_ansible_facts_malformed_json_skipped(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = b"not-json"
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    debug_messages = [r["message"] for r in loguru_logs if r["level"] == "DEBUG"]
    assert any("Skipping malformed ansible_facts entry" in m for m in debug_messages)
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert not any("stale" in m for m in warnings)


def test_check_ansible_facts_missing_epoch_skipped(mocker, loguru_logs):
    import json

    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = json.dumps({"ansible_date_time": {}}).encode("utf-8")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    debug_messages = [r["message"] for r in loguru_logs if r["level"] == "DEBUG"]
    assert any("facts missing ansible_date_time.epoch" in m for m in debug_messages)
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert not any("stale" in m for m in warnings)


def test_check_ansible_facts_non_numeric_epoch_skipped(mocker, loguru_logs):
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    mock_r.get.return_value = _facts_payload("foo")
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    debug_messages = [r["message"] for r in loguru_logs if r["level"] == "DEBUG"]
    assert any("Skipping malformed ansible_facts entry" in m for m in debug_messages)
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert not any("stale" in m for m in warnings)


def test_check_ansible_facts_scan_paginates(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mock_r = mocker.MagicMock()
    # First scan returns a non-zero cursor + one key; second scan returns
    # cursor 0 + another key. Both must be processed.
    mock_r.scan.side_effect = [
        (42, [b"ansible_factshost-a"]),
        (0, [b"ansible_factshost-b"]),
    ]
    mock_r.get.side_effect = [
        _facts_payload(now - 9999),
        _facts_payload(now - 9999),
    ]
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    assert mock_r.scan.call_count == 2
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("stale for 2 host(s)" in m for m in warnings)
    assert any("host-a" in m for m in warnings)
    assert any("host-b" in m for m in warnings)


def test_check_ansible_facts_max_age_none_uses_settings(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mocker.patch("osism.utils.settings.FACTS_MAX_AGE", 10)
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    # Age = 9999s, threshold = 10s → stale.
    mock_r.get.return_value = _facts_payload(now - 9999)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=None)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("older than 10 seconds" in m for m in warnings)


def test_check_ansible_facts_explicit_max_age_overrides_settings(mocker, loguru_logs):
    import time as time_mod

    now = time_mod.time()
    mocker.patch("osism.utils.settings.FACTS_MAX_AGE", 99999)
    mock_r = mocker.MagicMock()
    mock_r.scan.return_value = (0, [b"ansible_factshost-a"])
    # Age = 50s. With settings.FACTS_MAX_AGE=99999 it would be fresh; with
    # max_age=10 it is stale — proving the kwarg overrides settings.
    mock_r.get.return_value = _facts_payload(now - 50)
    mocker.patch("osism.utils._init_redis", return_value=mock_r)

    utils_pkg.check_ansible_facts(max_age=10)

    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any("older than 10 seconds" in m for m in warnings)
