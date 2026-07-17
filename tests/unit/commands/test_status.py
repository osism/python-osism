# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism status`` commands.

Covers the ``display_time`` helper, the Celery worker overview (``Run``), the
MariaDB Galera cluster validation (``Database``) and the RabbitMQ cluster
validation (``Messaging``). All external services are replaced by mocks: the
MariaDB connection object, the RabbitMQ management API (``requests.get``) and
the inventory/password helpers from ``osism.utils.rabbitmq``. The commands
must return non-zero whenever a prerequisite (configuration, password,
connectivity) is missing or a health check fails, and zero only for a clean
cluster.
"""

import argparse
from unittest.mock import MagicMock, mock_open, patch

import pymysql
import pytest
import requests

from osism.commands import status


def test_run_returns_1_for_unknown_resource_type():
    cmd = status.Run(MagicMock(), MagicMock())
    parsed_args = argparse.Namespace(type=["bogus"])

    with patch("celery.Celery"):
        result = cmd.take_action(parsed_args)

    assert result == 1


# --- display_time ---


@pytest.mark.parametrize(
    ("seconds", "granularity", "expected"),
    [
        (0, 2, ""),
        (1, 2, "1 second"),
        (90061, 2, "1 day, 1 hour"),
        (90061, 5, "1 day, 1 hour, 1 minute, 1 second"),
        (604800, 2, "1 week"),
    ],
)
def test_display_time(seconds, granularity, expected):
    assert status.display_time(seconds, granularity) == expected


# --- Run (workers) ---


def test_run_workers_reports_uptime_and_reachability(capsys):
    cmd = status.Run(MagicMock(), MagicMock())
    parsed_args = argparse.Namespace(type=["workers"])

    inspector = MagicMock()
    inspector.stats.return_value = {
        "worker-b": {"uptime": 90061},
        "worker-a": {"uptime": 1},
    }
    inspector.ping.side_effect = lambda destination: (
        [{"worker-a": {"ok": "pong"}}] if destination == ["worker-a"] else None
    )

    with patch("celery.Celery") as celery_cls:
        celery_cls.return_value.control.inspect.return_value = inspector
        result = cmd.take_action(parsed_args)

    assert not result
    lines = capsys.readouterr().out.splitlines()
    line_a = next(line for line in lines if "worker-a" in line)
    line_b = next(line for line in lines if "worker-b" in line)
    assert "1 second" in line_a
    assert "REACHABLE" in line_a
    assert "NOT REACHABLE" not in line_a
    assert "1 day, 1 hour" in line_b
    assert "NOT REACHABLE" in line_b


# --- Database helpers ---


def _database(format="log"):
    cmd = status.Database(MagicMock(), MagicMock())
    return cmd, cmd.get_parser("test").parse_args(["--format", format])


HEALTHY_WSREP_ROWS = [
    ("wsrep_cluster_status", "Primary"),
    ("wsrep_connected", "ON"),
    ("wsrep_ready", "ON"),
    ("wsrep_cluster_size", "3"),
    ("wsrep_local_state_comment", "Synced"),
]

GENERAL_ROWS = [
    ("Uptime", "90061"),
    ("Threads_connected", "5"),
    ("Threads_running", "1"),
    ("Questions", "1000"),
    ("Slow_queries", "0"),
    ("Aborted_connects", "0"),
]


def _galera_connection(wsrep_rows, general_rows=GENERAL_ROWS):
    """Mock a PyMySQL connection serving the two SHOW STATUS queries."""
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [list(wsrep_rows), list(general_rows)]
    return connection


def _override(rows, name, value):
    return [(n, value if n == name else v) for n, v in rows]


# --- Database._load_kolla_configuration ---


def test_load_kolla_configuration_returns_none_when_file_missing(loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=False):
        assert cmd._load_kolla_configuration() is None

    assert any(
        "Configuration file not found" in record["message"] for record in loguru_logs
    )


def test_load_kolla_configuration_parses_yaml():
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "builtins.open",
        mock_open(read_data="kolla_internal_vip_address: 192.168.16.9\n"),
    ):
        config = cmd._load_kolla_configuration()

    assert config == {"kolla_internal_vip_address": "192.168.16.9"}


def test_load_kolla_configuration_returns_none_on_read_error(loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "builtins.open", side_effect=OSError("permission denied")
    ):
        assert cmd._load_kolla_configuration() is None

    assert any(
        "Failed to load configuration" in record["message"] for record in loguru_logs
    )


# --- Database._load_database_password ---


def test_load_database_password_returns_none_when_secrets_file_missing(loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=False):
        assert cmd._load_database_password() is None

    assert any("Secrets file not found" in record["message"] for record in loguru_logs)


@pytest.mark.parametrize("secrets", [None, {}, "not-a-mapping", ["a", "b"]])
def test_load_database_password_rejects_invalid_secrets(secrets, loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file", return_value=secrets
    ):
        assert cmd._load_database_password() is None

    assert any(
        "Empty or invalid secrets file" in record["message"] for record in loguru_logs
    )


def test_load_database_password_requires_database_password_key(loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file",
        return_value={"another_password": "x"},
    ):
        assert cmd._load_database_password() is None

    assert any(
        "database_password not found" in record["message"] for record in loguru_logs
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(12345, "12345"), ("  s3cret\n", "s3cret")],
)
def test_load_database_password_coerces_and_strips(raw, expected):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file",
        return_value={"database_password": raw},
    ):
        assert cmd._load_database_password() == expected


def test_load_database_password_returns_none_when_loader_raises(loguru_logs):
    cmd, _ = _database()

    with patch("osism.commands.status.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file",
        side_effect=RuntimeError("vault broken"),
    ):
        assert cmd._load_database_password() is None

    assert any(
        "Failed to load database password" in record["message"]
        for record in loguru_logs
    )


# --- Database._check_galera_status ---


def test_check_galera_status_healthy_cluster_has_no_findings():
    cmd, _ = _database()
    connection = _galera_connection(HEALTHY_WSREP_ROWS)

    results, errors, warnings = cmd._check_galera_status(connection)

    assert errors == []
    assert warnings == []
    assert results["cluster_status"] == "Primary"
    assert results["connected"] == "ON"
    assert results["ready"] == "ON"
    assert results["cluster_size"] == "3"
    assert results["local_state"] == "Synced"
    assert results["uptime"] == "90061"
    assert results["threads_connected"] == "5"


@pytest.mark.parametrize(
    ("name", "value", "fragment"),
    [
        ("wsrep_cluster_status", "non-Primary", "expected 'Primary'"),
        ("wsrep_connected", "OFF", "Cluster connected is 'OFF'"),
        ("wsrep_ready", "OFF", "Cluster ready is 'OFF'"),
        ("wsrep_cluster_size", "0", "Cluster size is 0"),
        ("wsrep_cluster_size", "many", "Invalid cluster size: many"),
        ("wsrep_local_state_comment", "Donor/Desynced", "expected 'Synced'"),
    ],
)
def test_check_galera_status_reports_each_failing_check(name, value, fragment):
    cmd, _ = _database()
    connection = _galera_connection(_override(HEALTHY_WSREP_ROWS, name, value))

    _, errors, _ = cmd._check_galera_status(connection)

    assert len(errors) == 1
    assert fragment in errors[0]


@pytest.mark.parametrize(
    ("name", "value", "fragment"),
    [
        ("wsrep_flow_control_paused", "0.10", "Flow control paused"),
        ("wsrep_local_recv_queue_avg", "0.75", "receive queue average"),
        ("wsrep_local_cert_failures", "2", "Certification failures: 2"),
    ],
)
def test_check_galera_status_warns_on_replication_pressure(name, value, fragment):
    cmd, _ = _database()
    connection = _galera_connection(HEALTHY_WSREP_ROWS + [(name, value)])

    _, errors, warnings = cmd._check_galera_status(connection)

    assert errors == []
    assert len(warnings) == 1
    assert fragment in warnings[0]


def test_check_galera_status_ignores_non_numeric_metrics():
    cmd, _ = _database()
    connection = _galera_connection(
        HEALTHY_WSREP_ROWS
        + [
            ("wsrep_flow_control_paused", "unknown"),
            ("wsrep_local_recv_queue_avg", "unknown"),
            ("wsrep_local_cert_failures", "unknown"),
        ]
    )

    _, errors, warnings = cmd._check_galera_status(connection)

    assert errors == []
    assert warnings == []


def test_check_galera_status_reports_query_failure_once():
    cmd, _ = _database()
    connection = MagicMock()
    connection.cursor.side_effect = RuntimeError("connection lost")

    _, errors, warnings = cmd._check_galera_status(connection)

    assert errors == ["Failed to query Galera status: connection lost"]
    assert warnings == []


# --- Database.take_action ---


def test_database_returns_1_when_configuration_missing():
    cmd, parsed_args = _database()

    with patch.object(status.Database, "_load_kolla_configuration", return_value=None):
        assert cmd.take_action(parsed_args) == 1


def test_database_returns_1_without_vip_address():
    cmd, parsed_args = _database()

    with patch.object(status.Database, "_load_kolla_configuration", return_value={}):
        assert cmd.take_action(parsed_args) == 1


def test_database_returns_1_when_password_unavailable():
    cmd, parsed_args = _database()

    with patch.object(
        status.Database,
        "_load_kolla_configuration",
        return_value={"kolla_internal_vip_address": "192.168.16.9"},
    ), patch.object(status.Database, "_load_database_password", return_value=None):
        assert cmd.take_action(parsed_args) == 1


@pytest.mark.parametrize("format", ["log", "script"])
def test_database_returns_1_on_connection_error(format, capsys, loguru_logs):
    cmd, parsed_args = _database(format)

    with patch.object(
        status.Database,
        "_load_kolla_configuration",
        return_value={"kolla_internal_vip_address": "192.168.16.9"},
    ), patch.object(
        status.Database, "_load_database_password", return_value="s3cret"
    ), patch(
        "osism.utils.mariadb.connect", side_effect=pymysql.Error("vip unreachable")
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
    if format == "script":
        assert "FAILED: Connection error - vip unreachable" in capsys.readouterr().out
    else:
        assert any(
            "Failed to connect to MariaDB" in record["message"]
            for record in loguru_logs
        )


@pytest.mark.parametrize("format", ["log", "script"])
def test_database_passes_on_healthy_cluster(format, capsys, loguru_logs):
    cmd, parsed_args = _database(format)
    connection = _galera_connection(HEALTHY_WSREP_ROWS)

    with patch.object(
        status.Database,
        "_load_kolla_configuration",
        return_value={"kolla_internal_vip_address": "192.168.16.9"},
    ), patch.object(
        status.Database, "_load_database_password", return_value="s3cret"
    ), patch(
        "osism.utils.mariadb.connect", return_value=connection
    ) as connect_mock:
        result = cmd.take_action(parsed_args)

    assert result == 0
    connect_mock.assert_called_once_with(
        "192.168.16.9", "root", "s3cret", port=3306, connect_timeout=10
    )
    connection.close.assert_called_once_with()
    if format == "script":
        assert "PASSED" in capsys.readouterr().out
    else:
        assert any(
            "MariaDB Galera Cluster validation PASSED" in record["message"]
            for record in loguru_logs
        )


@pytest.mark.parametrize("format", ["log", "script"])
def test_database_fails_on_unhealthy_cluster(format, capsys, loguru_logs):
    cmd, parsed_args = _database(format)
    connection = _galera_connection(
        _override(HEALTHY_WSREP_ROWS, "wsrep_cluster_status", "non-Primary")
    )

    with patch.object(
        status.Database,
        "_load_kolla_configuration",
        return_value={"kolla_internal_vip_address": "192.168.16.9"},
    ), patch.object(
        status.Database, "_load_database_password", return_value="s3cret"
    ), patch(
        "osism.utils.mariadb.connect", return_value=connection
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
    connection.close.assert_called_once_with()
    if format == "script":
        out = capsys.readouterr().out
        assert "FAILED" in out
        assert "- Cluster status is 'non-Primary'" in out
    else:
        assert any(
            "MariaDB Galera Cluster validation FAILED" in record["message"]
            for record in loguru_logs
        )


# --- Messaging helpers ---


def _messaging(argv=None):
    cmd = status.Messaging(MagicMock(), MagicMock())
    return cmd, cmd.get_parser("test").parse_args(argv or [])


def _response(payload):
    response = MagicMock()
    response.json.return_value = payload
    return response


OVERVIEW = {
    "rabbitmq_version": "3.13.7",
    "erlang_version": "26.2.5",
    "cluster_name": "rabbit@testbed",
    "object_totals": {"connections": 10, "channels": 20, "queues": 30},
    "queue_totals": {
        "messages": 6,
        "messages_ready": 4,
        "messages_unacknowledged": 2,
    },
    "message_stats": {
        "publish_details": {"rate": 1.5},
        "deliver_get_details": {"rate": 2.5},
    },
}


def _node(name, **overrides):
    node = {
        "name": name,
        "running": True,
        "mem_alarm": False,
        "disk_free_alarm": False,
        "partitions": [],
        "disk_free": 50 * 1024**3,
        "disk_free_limit": 10 * 1024**3,
        "mem_used": 2 * 1024**3,
        "mem_limit": 8 * 1024**3,
        "fd_used": 100,
        "fd_total": 1048576,
        "sockets_used": 10,
        "sockets_total": 943626,
    }
    node.update(overrides)
    return node


def _rabbitmq_api(nodes, overview=OVERVIEW, alarms=None):
    """Responses for the three management API calls, in request order."""
    return [
        _response(overview),
        _response(nodes),
        _response(alarms or {"status": "ok"}),
    ]


def _node_results(**overrides):
    """A fully healthy per-node result dict, as the log format consumes it."""
    results = {
        "cluster_name": "rabbit@testbed",
        "rabbitmq_version": "3.13.7",
        "erlang_version": "26.2.5",
        "nodes": ["rabbit@node-a"],
        "running_nodes": ["rabbit@node-a"],
        "partitioned_nodes": [],
        "alarms": [],
        "cluster_size": 1,
        "total_connections": 10,
        "total_channels": 20,
        "total_queues": 30,
        "total_messages": 6,
        "messages_ready": 4,
        "messages_unacked": 2,
        "publish_rate": 1.5,
        "deliver_rate": 2.5,
        "disk_free": 50 * 1024**3,
        "disk_free_limit": 10 * 1024**3,
        "mem_used": 2 * 1024**3,
        "mem_limit": 8 * 1024**3,
        "fd_used": 100,
        "fd_total": 1048576,
        "sockets_used": 10,
        "sockets_total": 943626,
    }
    results.update(overrides)
    return results


# --- Messaging._check_rabbitmq_status ---


def test_check_rabbitmq_status_parses_overview():
    cmd, _ = _messaging()

    with patch("requests.get", side_effect=_rabbitmq_api([_node("rabbit@node-a")])):
        results, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert errors == []
    assert results["rabbitmq_version"] == "3.13.7"
    assert results["erlang_version"] == "26.2.5"
    assert results["cluster_name"] == "rabbit@testbed"
    assert results["total_connections"] == 10
    assert results["total_channels"] == 20
    assert results["total_queues"] == 30
    assert results["total_messages"] == 6
    assert results["messages_ready"] == 4
    assert results["messages_unacked"] == 2
    assert results["publish_rate"] == 1.5
    assert results["deliver_rate"] == 2.5
    assert results["cluster_size"] == 1
    assert results["running_nodes"] == ["rabbit@node-a"]


def test_check_rabbitmq_status_flags_stopped_node():
    cmd, _ = _messaging()
    nodes = [_node("rabbit@node-a"), _node("rabbit@node-b", running=False)]

    with patch("requests.get", side_effect=_rabbitmq_api(nodes)):
        results, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert errors == ["Node 'rabbit@node-b' is not running"]
    assert results["nodes"] == ["rabbit@node-a", "rabbit@node-b"]
    assert results["running_nodes"] == ["rabbit@node-a"]


def test_check_rabbitmq_status_flags_resource_alarms():
    cmd, _ = _messaging()
    nodes = [_node("rabbit@node-a", mem_alarm=True, disk_free_alarm=True)]

    with patch("requests.get", side_effect=_rabbitmq_api(nodes)):
        _, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert "Memory alarm on node 'rabbit@node-a'" in errors
    assert "Disk free alarm on node 'rabbit@node-a'" in errors


def test_check_rabbitmq_status_treats_partitions_as_critical():
    cmd, _ = _messaging()
    nodes = [_node("rabbit@node-a", partitions=["rabbit@node-b"])]

    with patch("requests.get", side_effect=_rabbitmq_api(nodes)):
        results, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert results["partitioned_nodes"] == ["rabbit@node-a"]
    assert len(errors) == 1
    assert errors[0].startswith("CRITICAL: Node 'rabbit@node-a' has partitions")


def test_check_rabbitmq_status_reads_resources_from_target_node():
    cmd, _ = _messaging()
    nodes = [
        _node("rabbit@node-a", disk_free=111),
        _node("rabbit@node-b", disk_free=222),
    ]

    with patch("requests.get", side_effect=_rabbitmq_api(nodes)):
        results, errors = cmd._check_rabbitmq_status(
            "10.0.0.5", "openstack", "pw", target_host="node-b"
        )

    assert errors == []
    assert results["disk_free"] == 222


def test_check_rabbitmq_status_defaults_resources_to_first_node():
    cmd, _ = _messaging()
    nodes = [
        _node("rabbit@node-a", disk_free=111),
        _node("rabbit@node-b", disk_free=222),
    ]

    with patch("requests.get", side_effect=_rabbitmq_api(nodes)):
        results, _ = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert results["disk_free"] == 111


def test_check_rabbitmq_status_collects_all_endpoint_failures():
    cmd, _ = _messaging()

    with patch(
        "requests.get",
        side_effect=[
            requests.exceptions.RequestException("overview down"),
            requests.exceptions.RequestException("nodes down"),
            requests.exceptions.RequestException("alarms down"),
        ],
    ):
        _, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert len(errors) == 3
    assert "Failed to get overview: overview down" in errors
    assert "Failed to get nodes information: nodes down" in errors
    assert "Failed to check health alarms: alarms down" in errors


def test_check_rabbitmq_status_reports_health_alarms():
    cmd, _ = _messaging()
    api = _rabbitmq_api(
        [_node("rabbit@node-a")],
        alarms={"status": "failed", "alarms": ["file_descriptor_limit"]},
    )

    with patch("requests.get", side_effect=api):
        results, errors = cmd._check_rabbitmq_status("10.0.0.5", "openstack", "pw")

    assert results["alarms"] == ["file_descriptor_limit"]
    assert "Alarm: file_descriptor_limit" in errors


# --- Messaging.take_action ---


def test_messaging_returns_1_without_node_addresses(loguru_logs):
    cmd, parsed_args = _messaging()

    with patch("osism.utils.rabbitmq.get_rabbitmq_node_addresses", return_value=None):
        assert cmd.take_action(parsed_args) == 1

    assert any(
        "Failed to get RabbitMQ node addresses" in record["message"]
        for record in loguru_logs
    )


def test_messaging_warns_about_unknown_filter_host(loguru_logs):
    cmd, parsed_args = _messaging(["node-a", "ghost"])

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch(
        "osism.utils.rabbitmq.load_rabbitmq_password", return_value="pw"
    ), patch.object(
        status.Messaging, "_check_rabbitmq_status", return_value=(_node_results(), [])
    ):
        result = cmd.take_action(parsed_args)

    assert result == 0
    assert any(
        "Host 'ghost' not found in rabbitmq group" in record["message"]
        for record in loguru_logs
    )


def test_messaging_returns_1_when_no_filter_host_matches(loguru_logs):
    cmd, parsed_args = _messaging(["ghost"])

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ):
        assert cmd.take_action(parsed_args) == 1

    assert any(
        "None of the specified hosts found" in record["message"]
        for record in loguru_logs
    )


def test_messaging_returns_1_without_password(loguru_logs):
    cmd, parsed_args = _messaging()

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch("osism.utils.rabbitmq.load_rabbitmq_password", return_value=None):
        assert cmd.take_action(parsed_args) == 1

    assert any(
        "Failed to load RabbitMQ password" in record["message"]
        for record in loguru_logs
    )


def test_messaging_script_format_lists_node_errors(capsys):
    cmd, parsed_args = _messaging(["--format", "script"])

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch(
        "osism.utils.rabbitmq.load_rabbitmq_password", return_value="pw"
    ), patch.object(
        status.Messaging,
        "_check_rabbitmq_status",
        return_value=(_node_results(), ["Node 'rabbit@node-a' is not running"]),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "- [node-a] Node 'rabbit@node-a' is not running" in out


def test_messaging_script_format_passes_when_clean(capsys):
    cmd, parsed_args = _messaging(["--format", "script"])

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch(
        "osism.utils.rabbitmq.load_rabbitmq_password", return_value="pw"
    ), patch.object(
        status.Messaging, "_check_rabbitmq_status", return_value=(_node_results(), [])
    ):
        result = cmd.take_action(parsed_args)

    assert result == 0
    assert "PASSED" in capsys.readouterr().out


def test_messaging_log_format_passes_when_clean(loguru_logs):
    cmd, parsed_args = _messaging()

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch(
        "osism.utils.rabbitmq.load_rabbitmq_password", return_value="pw"
    ), patch.object(
        status.Messaging, "_check_rabbitmq_status", return_value=(_node_results(), [])
    ):
        result = cmd.take_action(parsed_args)

    assert result == 0
    assert any(
        "RabbitMQ Cluster validation PASSED" in record["message"]
        for record in loguru_logs
    )


def test_messaging_log_format_fails_on_node_errors(loguru_logs):
    cmd, parsed_args = _messaging()
    results = _node_results(
        partitioned_nodes=["rabbit@node-a"], alarms=["file_descriptor_limit"]
    )

    with patch(
        "osism.utils.rabbitmq.get_rabbitmq_node_addresses",
        return_value=[("10.0.0.5", "node-a")],
    ), patch(
        "osism.utils.rabbitmq.load_rabbitmq_password", return_value="pw"
    ), patch.object(
        status.Messaging,
        "_check_rabbitmq_status",
        return_value=(results, ["CRITICAL: Node 'rabbit@node-a' has partitions"]),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
    messages = [record["message"] for record in loguru_logs]
    assert any("Partitioned Nodes: rabbit@node-a" in message for message in messages)
    assert any(
        "[node-a] CRITICAL: Node 'rabbit@node-a' has partitions" in message
        for message in messages
    )
    assert any("RabbitMQ Cluster validation FAILED" in message for message in messages)
