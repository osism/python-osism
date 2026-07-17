# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism manage amphora`` commands.

``AmphoraRestore`` and ``AmphoraRotate`` import the cloud environment helpers
inside ``take_action``, so those are patched at their source module
``osism.tasks.openstack``. The octavia wait helpers and ``sleep`` are bound at
import time and therefore patched at ``osism.commands.amphora``.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import openstack
import pytest

from osism.commands import amphora

from ._helpers import parse_args


@contextmanager
def _patched_environment(conn, setup_success=True):
    """Patch the cloud helpers and octavia wait helpers used by both commands."""
    setup_return = ("pw", [], None, True) if setup_success else (None, [], None, False)
    with patch(
        "osism.tasks.openstack.setup_cloud_environment", return_value=setup_return
    ) as setup, patch(
        "osism.tasks.openstack.get_openstack_connection", return_value=conn
    ) as getconn, patch(
        "osism.tasks.openstack.cleanup_cloud_environment"
    ) as cleanup, patch(
        "osism.commands.amphora.sleep"
    ) as mock_sleep, patch(
        "osism.commands.amphora.wait_for_amphora_boot"
    ) as boot, patch(
        "osism.commands.amphora.wait_for_amphora_delete"
    ) as delete:
        yield SimpleNamespace(
            setup=setup,
            getconn=getconn,
            cleanup=cleanup,
            sleep=mock_sleep,
            boot=boot,
            delete=delete,
        )


def _run(command_class, args, conn, setup_success=True):
    cmd, parsed_args = parse_args(command_class, args)
    with _patched_environment(conn, setup_success=setup_success) as mocks:
        result = cmd.take_action(parsed_args)
    return result, mocks


def _make_amphora(amphora_id="amp-1", loadbalancer_id="lb-1", age=timedelta(days=31)):
    amp = MagicMock()
    amp.id = amphora_id
    amp.loadbalancer_id = loadbalancer_id
    amp.created_at = (datetime.now(timezone.utc) - age).isoformat()
    return amp


# --- AmphoraRestore.take_action ---


def test_restore_returns_1_when_setup_fails():
    conn = MagicMock()

    result, mocks = _run(amphora.AmphoraRestore, [], conn, setup_success=False)

    assert result == 1
    mocks.getconn.assert_not_called()
    mocks.cleanup.assert_not_called()


def test_restore_queries_all_error_amphorae_by_default():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = []

    _run(amphora.AmphoraRestore, [], conn)

    conn.load_balancer.amphorae.assert_called_once_with(status="ERROR")


def test_restore_scopes_query_to_loadbalancer():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = []

    _run(amphora.AmphoraRestore, ["--loadbalancer", "lb-1"], conn)

    conn.load_balancer.amphorae.assert_called_once_with(
        status="ERROR", loadbalancer_id="lb-1"
    )


def test_restore_triggers_failover_and_waits_per_amphora():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [_make_amphora()]

    result, mocks = _run(amphora.AmphoraRestore, [], conn)

    conn.load_balancer.failover_amphora.assert_called_once_with("amp-1")
    mocks.boot.assert_called_once_with(conn, "lb-1")
    mocks.delete.assert_called_once_with(conn, "lb-1")
    mocks.cleanup.assert_called_once_with([], None)


def test_restore_cleans_up_when_failover_raises():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [_make_amphora()]
    conn.load_balancer.failover_amphora.side_effect = RuntimeError("boom")
    cmd, parsed_args = parse_args(amphora.AmphoraRestore, [])

    with _patched_environment(conn) as mocks, pytest.raises(RuntimeError):
        cmd.take_action(parsed_args)

    mocks.cleanup.assert_called_once_with([], None)


# --- AmphoraRotate.take_action ---


def test_rotate_returns_1_when_setup_fails():
    conn = MagicMock()

    result, mocks = _run(amphora.AmphoraRotate, [], conn, setup_success=False)

    assert result == 1
    mocks.getconn.assert_not_called()
    mocks.cleanup.assert_not_called()


def test_rotate_old_amphora_triggers_loadbalancer_failover():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [_make_amphora(age=timedelta(days=31))]

    result, mocks = _run(amphora.AmphoraRotate, [], conn)

    conn.load_balancer.amphorae.assert_called_once_with(status="ALLOCATED")
    conn.load_balancer.failover_load_balancer.assert_called_once_with("lb-1")
    mocks.boot.assert_called_once_with(conn, "lb-1")
    mocks.delete.assert_called_once_with(conn, "lb-1")
    mocks.cleanup.assert_called_once_with([], None)


def test_rotate_skips_young_amphora_without_force():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [_make_amphora(age=timedelta(days=1))]

    result, mocks = _run(amphora.AmphoraRotate, [], conn)

    conn.load_balancer.failover_load_balancer.assert_not_called()
    mocks.boot.assert_not_called()
    mocks.delete.assert_not_called()


def test_rotate_force_rotates_regardless_of_age():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [_make_amphora(age=timedelta(days=1))]

    result, mocks = _run(
        amphora.AmphoraRotate, ["--force", "--loadbalancer", "lb-1"], conn
    )

    conn.load_balancer.amphorae.assert_called_once_with(
        status="ALLOCATED", loadbalancer_id="lb-1"
    )
    conn.load_balancer.failover_load_balancer.assert_called_once_with("lb-1")


def test_rotate_handles_each_loadbalancer_once():
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [
        _make_amphora(amphora_id="amp-1"),
        _make_amphora(amphora_id="amp-2"),
    ]

    result, mocks = _run(amphora.AmphoraRotate, [], conn)

    conn.load_balancer.failover_load_balancer.assert_called_once_with("lb-1")
    mocks.boot.assert_called_once_with(conn, "lb-1")


def test_rotate_conflict_keeps_loadbalancer_out_of_done(loguru_logs):
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [
        _make_amphora(amphora_id="amp-1"),
        _make_amphora(amphora_id="amp-2"),
    ]
    conn.load_balancer.failover_load_balancer.side_effect = [
        openstack.exceptions.ConflictException,
        None,
    ]

    result, mocks = _run(amphora.AmphoraRotate, [], conn)

    # The conflict only logs a warning; the loadbalancer is not marked as
    # done, so the second amphora of the same loadbalancer retries.
    assert conn.load_balancer.failover_load_balancer.call_count == 2
    mocks.boot.assert_called_once_with(conn, "lb-1")
    warnings = [r for r in loguru_logs if r["level"] == "WARNING"]
    assert any(
        "Conflict while rotating loadbalancer lb-1" in r["message"] for r in warnings
    )
