# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism manage loadbalancer`` commands and their helpers.

The module-level helpers load the kolla configuration and the octavia
database password and open a MariaDB connection; the commands combine those
with the OpenStack cloud helpers. The database connection helper delegates to
``osism.utils.mariadb.connect`` (which handles the ProxySQL sharded user), so
that module is patched as a whole here.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, call, mock_open, patch

import pymysql
import pytest

from osism.commands import loadbalancer

from ._helpers import parse_args


# --- _load_kolla_configuration ---


def test_load_kolla_configuration_returns_none_when_file_missing(loguru_logs):
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=False):
        assert loadbalancer._load_kolla_configuration() is None

    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Configuration file not found" in r["message"] for r in errors)


def test_load_kolla_configuration_returns_none_on_load_error(loguru_logs):
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data="key: value\n")
    ), patch(
        "osism.commands.loadbalancer.yaml.safe_load", side_effect=Exception("boom")
    ):
        assert loadbalancer._load_kolla_configuration() is None

    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to load configuration" in r["message"] for r in errors)


def test_load_kolla_configuration_returns_parsed_yaml():
    open_mock = mock_open(read_data="kolla_internal_vip_address: 192.0.2.10\n")
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=True), patch(
        "builtins.open", open_mock
    ):
        config = loadbalancer._load_kolla_configuration()

    assert config == {"kolla_internal_vip_address": "192.0.2.10"}
    open_mock.assert_called_once_with(
        "/opt/configuration/environments/kolla/configuration.yml", "r"
    )


# --- _load_octavia_database_password ---


def test_load_octavia_password_returns_none_when_file_missing(loguru_logs):
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=False):
        assert loadbalancer._load_octavia_database_password() is None

    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Secrets file not found" in r["message"] for r in errors)


@pytest.mark.parametrize(
    "secrets, expected",
    [
        pytest.param(None, None, id="loader-returns-none"),
        pytest.param(["not", "a", "dict"], None, id="not-a-dict"),
        pytest.param(
            {
                "octavia_database_password": "octavia-pw",
                "database_password": "general-pw",
            },
            "octavia-pw",
            id="octavia-password-preferred",
        ),
        pytest.param(
            {"database_password": "general-pw"},
            "general-pw",
            id="fallback-to-database-password",
        ),
        pytest.param({"other_key": "value"}, None, id="no-password-keys"),
        pytest.param(
            {"octavia_database_password": " padded \n"}, "padded", id="stripped"
        ),
        pytest.param(
            {"octavia_database_password": 123456}, "123456", id="coerced-to-str"
        ),
    ],
)
def test_load_octavia_password_variants(secrets, expected):
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file", return_value=secrets
    ):
        assert loadbalancer._load_octavia_database_password() == expected


def test_load_octavia_password_returns_none_on_loader_error(loguru_logs):
    with patch("osism.commands.loadbalancer.os.path.exists", return_value=True), patch(
        "osism.tasks.conductor.utils.load_yaml_file", side_effect=Exception("boom")
    ):
        assert loadbalancer._load_octavia_database_password() is None

    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any(
        "Failed to load octavia database password" in r["message"] for r in errors
    )


# --- _get_octavia_database_connection ---


@contextmanager
def _database_environment(config, password):
    with patch(
        "osism.commands.loadbalancer._load_kolla_configuration", return_value=config
    ), patch(
        "osism.commands.loadbalancer._load_octavia_database_password",
        return_value=password,
    ), patch(
        "osism.commands.loadbalancer.mariadb"
    ) as mariadb:
        yield mariadb


def test_get_database_connection_returns_none_without_config():
    with _database_environment(None, "secret") as mariadb:
        assert loadbalancer._get_octavia_database_connection() is None

    mariadb.connect.assert_not_called()


def test_get_database_connection_returns_none_without_vip_address(loguru_logs):
    with _database_environment({}, "secret") as mariadb:
        assert loadbalancer._get_octavia_database_connection() is None

    mariadb.connect.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("kolla_internal_vip_address not found" in r["message"] for r in errors)


def test_get_database_connection_returns_none_without_password():
    with _database_environment(
        {"kolla_internal_vip_address": "192.0.2.10"}, None
    ) as mariadb:
        assert loadbalancer._get_octavia_database_connection() is None

    mariadb.connect.assert_not_called()


def test_get_database_connection_happy_path():
    with _database_environment(
        {"kolla_internal_vip_address": "192.0.2.10"}, "secret"
    ) as mariadb:
        connection = loadbalancer._get_octavia_database_connection()

    assert connection is mariadb.connect.return_value
    mariadb.connect.assert_called_once_with(
        "192.0.2.10",
        "octavia",
        "secret",
        port=3306,
        database="octavia",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


def test_get_database_connection_returns_none_on_pymysql_error(loguru_logs):
    with _database_environment(
        {"kolla_internal_vip_address": "192.0.2.10"}, "secret"
    ) as mariadb:
        mariadb.connect.side_effect = pymysql.Error("boom")
        assert loadbalancer._get_octavia_database_connection() is None

    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to connect to Octavia database" in r["message"] for r in errors)


# --- _reset_provisioning_status / _reset_operating_status ---

RESET_STATUS_CASES = [
    pytest.param(
        loadbalancer._reset_provisioning_status,
        "provisioning_status",
        "ACTIVE",
        id="provisioning",
    ),
    pytest.param(
        loadbalancer._reset_operating_status,
        "operating_status",
        "ONLINE",
        id="operating",
    ),
]


@pytest.mark.parametrize("reset, column, default_status", RESET_STATUS_CASES)
def test_reset_status_executes_update_with_default_status(
    reset, column, default_status
):
    database = MagicMock()
    cursor = database.cursor.return_value.__enter__.return_value

    reset(database, "lb-1")

    cursor.execute.assert_called_once_with(
        f"UPDATE load_balancer SET {column} = '{default_status}' WHERE id = 'lb-1';"
    )
    database.commit.assert_called_once_with()


@pytest.mark.parametrize("reset, column, default_status", RESET_STATUS_CASES)
def test_reset_status_interpolates_custom_status(reset, column, default_status):
    database = MagicMock()
    cursor = database.cursor.return_value.__enter__.return_value

    reset(database, "lb-1", status="ERROR")

    cursor.execute.assert_called_once_with(
        f"UPDATE load_balancer SET {column} = 'ERROR' WHERE id = 'lb-1';"
    )
    database.commit.assert_called_once_with()


# --- LoadbalancerList.take_action ---


def _make_loadbalancer(provisioning_status="ACTIVE", operating_status="ONLINE"):
    lb = MagicMock()
    lb.id = "lb-1"
    lb.name = "web"
    lb.provisioning_status = provisioning_status
    lb.operating_status = operating_status
    lb.project_id = "project-1"
    return lb


def _run_list(args, conn, setup_success=True):
    cmd, parsed_args = parse_args(loadbalancer.LoadbalancerList, args)
    setup_return = ("pw", [], None, True) if setup_success else (None, [], None, False)
    setup = MagicMock(return_value=setup_return)
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        result = cmd.take_action(parsed_args)
    return result, cleanup


def test_list_returns_1_when_setup_fails():
    result, cleanup = _run_list([], MagicMock(), setup_success=False)

    assert result == 1
    cleanup.assert_not_called()


def test_list_provisioning_status_queries_three_statuses(capsys):
    conn = MagicMock()
    conn.load_balancer.load_balancers.return_value = [_make_loadbalancer("ERROR")]

    result, cleanup = _run_list([], conn)

    assert conn.load_balancer.load_balancers.call_args_list == [
        call(provisioning_status="PENDING_CREATE"),
        call(provisioning_status="PENDING_UPDATE"),
        call(provisioning_status="ERROR"),
    ]
    assert "lb-1" in capsys.readouterr().out
    cleanup.assert_called_once_with([], None)


def test_list_operating_status_queries_error_only(capsys):
    conn = MagicMock()
    conn.load_balancer.load_balancers.return_value = [
        _make_loadbalancer(operating_status="ERROR")
    ]

    _run_list(["--status-type", "operating_status"], conn)

    conn.load_balancer.load_balancers.assert_called_once_with(operating_status="ERROR")
    assert "lb-1" in capsys.readouterr().out


def test_list_without_results_logs_message(capsys, loguru_logs):
    conn = MagicMock()
    conn.load_balancer.load_balancers.return_value = []

    _run_list([], conn)

    assert capsys.readouterr().out == ""
    assert any(
        "No loadbalancers with problematic status found" in r["message"]
        for r in loguru_logs
    )


# --- LoadbalancerReset / LoadbalancerDelete ---


@contextmanager
def _command_environment(conn, db=None, prompt_answer="yes", setup_success=True):
    """Patch everything ``LoadbalancerReset``/``LoadbalancerDelete`` touch."""
    setup_return = ("pw", [], None, True) if setup_success else (None, [], None, False)
    setup = MagicMock(return_value=setup_return)
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ), patch(
        "osism.commands.loadbalancer.prompt", return_value=prompt_answer
    ) as prompt_mock, patch(
        "osism.commands.loadbalancer._get_octavia_database_connection",
        return_value=db,
    ) as get_db, patch(
        "osism.commands.loadbalancer._reset_provisioning_status"
    ) as reset_provisioning, patch(
        "osism.commands.loadbalancer._reset_operating_status"
    ) as reset_operating, patch(
        "osism.commands.loadbalancer.wait_for_amphora_boot"
    ) as boot, patch(
        "osism.commands.loadbalancer.sleep"
    ):
        yield SimpleNamespace(
            getconn=getconn,
            cleanup=cleanup,
            prompt=prompt_mock,
            get_db=get_db,
            reset_provisioning=reset_provisioning,
            reset_operating=reset_operating,
            boot=boot,
        )


def _run_command(command_class, args, conn, **kwargs):
    cmd, parsed_args = parse_args(command_class, args)
    with _command_environment(conn, **kwargs) as mocks:
        result = cmd.take_action(parsed_args)
    return result, mocks


def _conn_for(lb):
    conn = MagicMock()
    conn.load_balancer.get_load_balancer.return_value = lb
    return conn


# --- LoadbalancerReset.take_action ---


def test_reset_returns_1_when_setup_fails():
    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset, ["lb-1"], MagicMock(), setup_success=False
    )

    assert result == 1
    mocks.getconn.assert_not_called()


def test_reset_returns_1_when_loadbalancer_lookup_fails(loguru_logs):
    conn = MagicMock()
    conn.load_balancer.get_load_balancer.side_effect = Exception("boom")

    result, mocks = _run_command(loadbalancer.LoadbalancerReset, ["lb-1"], conn)

    assert result == 1
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to get loadbalancer lb-1" in r["message"] for r in errors)


def test_reset_provisioning_rejects_pending_create(loguru_logs):
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))

    result, mocks = _run_command(loadbalancer.LoadbalancerReset, ["lb-1"], conn)

    assert result == 1
    mocks.get_db.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("manage loadbalancer delete" in r["message"] for r in errors)


def test_reset_operating_requires_error_operating_status():
    conn = _conn_for(_make_loadbalancer("ACTIVE", "ONLINE"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset,
        ["lb-1", "--status-type", "operating_status"],
        conn,
    )

    assert result == 1
    mocks.get_db.assert_not_called()


def test_reset_operating_requires_active_provisioning_status():
    conn = _conn_for(_make_loadbalancer("PENDING_UPDATE", "ERROR"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset,
        ["lb-1", "--status-type", "operating_status"],
        conn,
    )

    assert result == 1
    mocks.get_db.assert_not_called()


def test_reset_aborts_when_prompt_declined(loguru_logs):
    conn = _conn_for(_make_loadbalancer("ERROR"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset, ["lb-1"], conn, prompt_answer="no"
    )

    assert result == 0
    mocks.get_db.assert_not_called()
    mocks.reset_provisioning.assert_not_called()
    assert any("Aborted" in r["message"] for r in loguru_logs)


def test_reset_returns_1_without_database_connection():
    conn = _conn_for(_make_loadbalancer("ERROR"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset, ["lb-1", "--yes"], conn, db=None
    )

    assert result == 1
    mocks.reset_provisioning.assert_not_called()


def test_reset_prompts_before_reset():
    conn = _conn_for(_make_loadbalancer("PENDING_UPDATE"))
    db = MagicMock()

    result, mocks = _run_command(loadbalancer.LoadbalancerReset, ["lb-1"], conn, db=db)

    mocks.prompt.assert_called_once()
    mocks.reset_provisioning.assert_called_once_with(db, "lb-1")


def test_reset_provisioning_happy_path():
    conn = _conn_for(_make_loadbalancer("ERROR"))
    db = MagicMock()

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset, ["lb-1", "--yes"], conn, db=db
    )

    assert result is None
    mocks.prompt.assert_not_called()
    mocks.reset_provisioning.assert_called_once_with(db, "lb-1")
    mocks.reset_operating.assert_not_called()
    conn.load_balancer.failover_load_balancer.assert_called_once_with("lb-1")
    mocks.boot.assert_called_once_with(conn, "lb-1")
    db.close.assert_called_once_with()
    mocks.cleanup.assert_called_once_with([], None)


def test_reset_operating_happy_path():
    conn = _conn_for(_make_loadbalancer("ACTIVE", "ERROR"))
    db = MagicMock()

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset,
        ["lb-1", "--yes", "--status-type", "operating_status"],
        conn,
        db=db,
    )

    assert result is None
    mocks.reset_operating.assert_called_once_with(db, "lb-1")
    mocks.reset_provisioning.assert_not_called()
    db.close.assert_called_once_with()


def test_reset_no_failover_skips_failover():
    conn = _conn_for(_make_loadbalancer("ERROR"))
    db = MagicMock()

    result, mocks = _run_command(
        loadbalancer.LoadbalancerReset, ["lb-1", "--yes", "--no-failover"], conn, db=db
    )

    conn.load_balancer.failover_load_balancer.assert_not_called()
    mocks.boot.assert_not_called()
    mocks.reset_provisioning.assert_called_once_with(db, "lb-1")
    db.close.assert_called_once_with()


def test_reset_closes_database_when_failover_raises():
    conn = _conn_for(_make_loadbalancer("ERROR"))
    conn.load_balancer.failover_load_balancer.side_effect = RuntimeError("boom")
    db = MagicMock()
    cmd, parsed_args = parse_args(loadbalancer.LoadbalancerReset, ["lb-1", "--yes"])

    with _command_environment(conn, db=db) as mocks, pytest.raises(RuntimeError):
        cmd.take_action(parsed_args)

    db.close.assert_called_once_with()
    mocks.cleanup.assert_called_once_with([], None)


# --- LoadbalancerDelete.take_action ---


def test_delete_returns_1_when_loadbalancer_lookup_fails(loguru_logs):
    conn = MagicMock()
    conn.load_balancer.get_load_balancer.side_effect = Exception("boom")

    result, mocks = _run_command(loadbalancer.LoadbalancerDelete, ["lb-1"], conn)

    assert result == 1
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("Failed to get loadbalancer lb-1" in r["message"] for r in errors)


def test_delete_rejects_non_pending_create_status(loguru_logs):
    conn = _conn_for(_make_loadbalancer("ERROR"))

    result, mocks = _run_command(loadbalancer.LoadbalancerDelete, ["lb-1"], conn)

    assert result == 1
    mocks.get_db.assert_not_called()
    errors = [r for r in loguru_logs if r["level"] == "ERROR"]
    assert any("manage loadbalancer reset" in r["message"] for r in errors)


def test_delete_aborts_when_prompt_declined(loguru_logs):
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerDelete, ["lb-1"], conn, prompt_answer="no"
    )

    assert result == 0
    conn.load_balancer.delete_load_balancer.assert_not_called()
    assert any("Aborted" in r["message"] for r in loguru_logs)


def test_delete_yes_skips_prompt():
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))
    db = MagicMock()

    result, mocks = _run_command(
        loadbalancer.LoadbalancerDelete, ["lb-1", "--yes"], conn, db=db
    )

    mocks.prompt.assert_not_called()
    conn.load_balancer.delete_load_balancer.assert_called_once_with("lb-1")


def test_delete_returns_1_without_database_connection():
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))

    result, mocks = _run_command(
        loadbalancer.LoadbalancerDelete, ["lb-1", "--yes"], conn, db=None
    )

    assert result == 1
    conn.load_balancer.delete_load_balancer.assert_not_called()


def test_delete_sets_error_status_before_deleting():
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))
    db = MagicMock()
    cmd, parsed_args = parse_args(loadbalancer.LoadbalancerDelete, ["lb-1", "--yes"])

    with _command_environment(conn, db=db) as mocks:
        # The provisioning status must be set to ERROR before the delete call.
        mocks.reset_provisioning.side_effect = (
            lambda *args, **kwargs: conn.load_balancer.delete_load_balancer.assert_not_called()
        )
        result = cmd.take_action(parsed_args)

    assert result is None
    mocks.reset_provisioning.assert_called_once_with(db, "lb-1", status="ERROR")
    conn.load_balancer.delete_load_balancer.assert_called_once_with("lb-1")
    db.close.assert_called_once_with()
    mocks.cleanup.assert_called_once_with([], None)


def test_delete_closes_database_when_delete_raises():
    conn = _conn_for(_make_loadbalancer("PENDING_CREATE"))
    conn.load_balancer.delete_load_balancer.side_effect = RuntimeError("boom")
    db = MagicMock()
    cmd, parsed_args = parse_args(loadbalancer.LoadbalancerDelete, ["lb-1", "--yes"])

    with _command_environment(conn, db=db) as mocks, pytest.raises(RuntimeError):
        cmd.take_action(parsed_args)

    db.close.assert_called_once_with()
    mocks.cleanup.assert_called_once_with([], None)
