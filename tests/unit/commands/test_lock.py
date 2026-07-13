# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism lock`` / ``unlock`` / ``lock status`` commands.

The commands manage the Redis-backed task lock via ``osism.utils``; the lock
logic itself is covered by the ``osism.utils`` tests, so everything is mocked
at the command module here.
"""

from unittest.mock import patch

import pytest

from osism.commands import lock

from ._helpers import make_command, parse_args


def _lock(args, *, lock_info, set_result=True):
    cmd, parsed_args = parse_args(lock.Lock, args)

    with patch(
        "osism.commands.lock.utils.is_task_locked", return_value=lock_info
    ), patch(
        "osism.commands.lock.utils.set_task_lock", return_value=set_result
    ) as mock_set:
        result = cmd.take_action(parsed_args)

    return result, mock_set


def _unlock(*, lock_info, remove_result=True):
    cmd, parsed_args = parse_args(lock.Unlock, [])

    with patch(
        "osism.commands.lock.utils.is_task_locked", return_value=lock_info
    ), patch(
        "osism.commands.lock.utils.remove_task_lock", return_value=remove_result
    ) as mock_remove:
        result = cmd.take_action(parsed_args)

    return result, mock_remove


def _status(lock_info):
    cmd, parsed_args = parse_args(lock.LockStatus, [])

    with patch("osism.commands.lock.utils.is_task_locked", return_value=lock_info):
        return cmd.take_action(parsed_args)


def test_lock_warns_when_already_locked(loguru_logs):
    result, mock_set = _lock(
        [], lock_info={"locked": True, "user": "alice", "timestamp": "2026-01-01"}
    )

    assert result is None
    mock_set.assert_not_called()
    assert any(
        record["level"] == "WARNING"
        and "already locked by alice at 2026-01-01" in record["message"]
        for record in loguru_logs
    )
    assert not any("Existing reason" in record["message"] for record in loguru_logs)


def test_lock_warns_with_existing_reason(loguru_logs):
    _lock(
        [],
        lock_info={
            "locked": True,
            "user": "alice",
            "timestamp": "2026-01-01",
            "reason": "upgrade",
        },
    )

    assert any(
        record["level"] == "WARNING" and "Existing reason: upgrade" in record["message"]
        for record in loguru_logs
    )


@pytest.mark.parametrize("lock_info", [None, {"locked": False}])
def test_lock_passes_user_and_reason_through(lock_info):
    result, mock_set = _lock(
        ["--user", "bob", "--reason", "maintenance"], lock_info=lock_info
    )

    assert result is None
    mock_set.assert_called_once_with("bob", "maintenance")


def test_lock_user_defaults_to_operator_user():
    with patch("osism.commands.lock.settings.OPERATOR_USER", "testuser"):
        result, mock_set = _lock([], lock_info=None)

    assert result is None
    mock_set.assert_called_once_with("testuser", None)


def test_lock_user_help_bakes_in_operator_user_at_parser_build_time():
    with patch("osism.commands.lock.settings.OPERATOR_USER", "testuser"):
        parser = make_command(lock.Lock).get_parser("test")

    # The default operator user is interpolated into the ``--user`` help text
    # when the parser is built, not when the command runs; the rendered help
    # is the public surface that exposes it.
    assert "testuser" in parser.format_help()


def test_lock_returns_nonzero_when_setting_lock_fails(loguru_logs):
    result, _ = _lock([], lock_info=None, set_result=False)

    assert result == 1
    assert any(
        record["level"] == "ERROR" and "Failed to set task lock" in record["message"]
        for record in loguru_logs
    )


@pytest.mark.parametrize("lock_info", [None, {"locked": False}])
def test_unlock_is_a_noop_when_not_locked(loguru_logs, lock_info):
    result, mock_remove = _unlock(lock_info=lock_info)

    assert result is None
    mock_remove.assert_not_called()
    assert any(
        "Tasks are not currently locked" in record["message"] for record in loguru_logs
    )


def test_unlock_removes_lock_and_logs_previous_owner(loguru_logs):
    result, mock_remove = _unlock(
        lock_info={"locked": True, "user": "alice", "timestamp": "2026-01-01"}
    )

    assert result is None
    mock_remove.assert_called_once_with()
    assert any(
        "was set by alice at 2026-01-01" in record["message"] for record in loguru_logs
    )
    assert not any("Previous reason" in record["message"] for record in loguru_logs)


def test_unlock_logs_previous_reason_when_present(loguru_logs):
    _unlock(
        lock_info={
            "locked": True,
            "user": "alice",
            "timestamp": "2026-01-01",
            "reason": "upgrade",
        }
    )

    assert any(
        "Previous reason: upgrade" in record["message"] for record in loguru_logs
    )


def test_unlock_returns_nonzero_when_removing_lock_fails(loguru_logs):
    result, _ = _unlock(
        lock_info={"locked": True, "user": "alice", "timestamp": "2026-01-01"},
        remove_result=False,
    )

    assert result == 1
    assert any(
        record["level"] == "ERROR" and "Failed to remove task lock" in record["message"]
        for record in loguru_logs
    )


def test_status_locked_with_reason(loguru_logs):
    _status(
        {
            "locked": True,
            "user": "alice",
            "timestamp": "2026-01-01",
            "reason": "upgrade",
        }
    )

    assert any(
        "Tasks are LOCKED by alice at 2026-01-01" in record["message"]
        for record in loguru_logs
    )
    assert any("Reason: upgrade" in record["message"] for record in loguru_logs)


def test_status_locked_falls_back_to_unknown(loguru_logs):
    _status({"locked": True})

    assert any(
        "Tasks are LOCKED by unknown at unknown" in record["message"]
        for record in loguru_logs
    )
    assert not any("Reason:" in record["message"] for record in loguru_logs)


@pytest.mark.parametrize("lock_info", [None, {"locked": False}])
def test_status_unlocked(loguru_logs, lock_info):
    _status(lock_info)

    assert any("Tasks are UNLOCKED" in record["message"] for record in loguru_logs)
