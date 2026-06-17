# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism reset facts`` command.

These cover the two reset paths and their edge cases: flushing the whole
``ansible_facts*`` cache (including the empty-cache no-op), restricting the
reset to the hosts a ``--limit`` pattern resolves to, and the error contracts
for a failed inventory load and an unreachable Redis.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import RedisError

from osism.commands import reset


def _make():
    return reset.Facts(MagicMock(), MagicMock())


def _parse(*args):
    return _make().get_parser("test").parse_args(list(args))


@pytest.fixture
def mock_redis():
    """Provide a mock Redis client wherever the command resolves it.

    ``osism.utils.redis`` is a lazily-initialised module attribute that opens
    a real connection on first access, so patch both the attribute and its
    initialiser to keep the test offline.
    """
    client = MagicMock()
    with patch("osism.utils._init_redis", return_value=client), patch(
        "osism.commands.reset.utils.redis", client, create=True
    ):
        yield client


# --- flush-all path ---


def test_facts_flushes_all_keys_when_no_limit(mock_redis, loguru_logs):
    mock_redis.scan.return_value = (
        0,
        [b"ansible_factsnode1", b"ansible_factsnode2"],
    )

    rc = _make().take_action(_parse())

    assert rc == 0
    mock_redis.scan.assert_called_once_with(0, match="ansible_facts*", count=100)
    mock_redis.delete.assert_called_once_with(
        b"ansible_factsnode1", b"ansible_factsnode2"
    )
    assert any("2 host(s)" in r["message"] for r in loguru_logs)


def test_facts_succeeds_and_skips_delete_when_cache_empty(mock_redis, loguru_logs):
    mock_redis.scan.return_value = (0, [])

    rc = _make().take_action(_parse())

    assert rc == 0
    mock_redis.delete.assert_not_called()
    infos = [r for r in loguru_logs if r["level"] == "INFO"]
    assert any("0 host(s)" in r["message"] for r in infos)


def test_facts_returns_nonzero_on_redis_error(mock_redis, loguru_logs):
    mock_redis.scan.side_effect = RedisError("connection refused")

    rc = _make().take_action(_parse())

    assert rc == 1
    mock_redis.delete.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to reset Ansible fact cache" in r["message"] for r in errors)


# --- limited path ---


def test_facts_limit_deletes_only_selected_hosts(mock_redis):
    mock_redis.delete.return_value = 1
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{}"

    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch("osism.commands.reset.subprocess.run", return_value=ok), patch(
        "osism.commands.reset.get_hosts_from_inventory",
        return_value=["node1", "node2"],
    ):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 0
    mock_redis.scan.assert_not_called()
    mock_redis.delete.assert_called_once_with(
        "ansible_factsnode1", "ansible_factsnode2"
    )


def test_facts_limit_returns_nonzero_when_inventory_fails(mock_redis, loguru_logs):
    failed = MagicMock()
    failed.returncode = 1
    failed.stderr = "boom"

    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch("osism.commands.reset.subprocess.run", return_value=failed):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 1
    mock_redis.delete.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Error loading inventory" in r["message"] for r in errors)
    assert any("boom" in r["message"] for r in errors)


def test_facts_limit_returns_nonzero_on_invalid_inventory_json(mock_redis, loguru_logs):
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{not valid json"

    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch("osism.commands.reset.subprocess.run", return_value=ok):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 1
    mock_redis.delete.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to parse inventory output" in r["message"] for r in errors)


def test_facts_limit_returns_nonzero_when_inventory_times_out(mock_redis, loguru_logs):
    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.reset.subprocess.run",
        side_effect=subprocess.TimeoutExpired("ansible-inventory", 30),
    ):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 1
    mock_redis.delete.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Timeout loading inventory." in r["message"] for r in errors)


def test_facts_limit_warns_and_succeeds_when_no_hosts_match(mock_redis, loguru_logs):
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{}"

    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch("osism.commands.reset.subprocess.run", return_value=ok), patch(
        "osism.commands.reset.get_hosts_from_inventory", return_value=[]
    ):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 0
    mock_redis.delete.assert_not_called()
    warnings = [r for r in loguru_logs if r["level"] == "WARNING"]
    assert any("No hosts matched the given limit." in r["message"] for r in warnings)


def test_facts_limit_returns_nonzero_on_redis_error(mock_redis, loguru_logs):
    mock_redis.delete.side_effect = RedisError("connection refused")
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{}"

    with patch(
        "osism.commands.reset.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch("osism.commands.reset.subprocess.run", return_value=ok), patch(
        "osism.commands.reset.get_hosts_from_inventory",
        return_value=["node1", "node2"],
    ):
        rc = _make().take_action(_parse("-l", "control"))

    assert rc == 1
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to reset Ansible fact cache" in r["message"] for r in errors)
