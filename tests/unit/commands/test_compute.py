# SPDX-License-Identifier: Apache-2.0

import datetime
from unittest.mock import MagicMock, call, patch

import openstack
import pytest

from osism.commands import compute


def _run(args, conn):
    cmd = compute.ComputeMigrationList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


def test_no_user_domain_returns_1():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--user", "u", "--user-domain", "d"], conn)
    assert result == 1


def test_no_user_returns_1():
    conn = MagicMock()
    conn.identity.find_user.return_value = None
    result = _run(["--user", "u"], conn)
    assert result == 1


def test_no_project_domain_returns_1():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--project", "p", "--project-domain", "d"], conn)
    assert result == 1


def test_no_project_returns_1():
    conn = MagicMock()
    conn.identity.find_project.return_value = None
    result = _run(["--project", "p"], conn)
    assert result == 1


def test_multiple_servers_returns_1():
    conn = MagicMock()
    conn.compute.find_server.side_effect = openstack.exceptions.DuplicateResource
    result = _run(["--server", "s"], conn)
    assert result == 1


def test_no_server_returns_1():
    conn = MagicMock()
    conn.compute.find_server.return_value = None
    result = _run(["--server", "s"], conn)
    assert result == 1


def _run_enable(args, conn):
    cmd = compute.ComputeEnable(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


def test_enable_returns_1_when_force_up_rejected():
    # A service that is forced_down, where clearing force-down is rejected
    # because `done` evacuation records remain.
    conn = MagicMock()
    service = MagicMock()
    service.__getitem__.return_value = True  # service["forced_down"] is True
    conn.compute.services.return_value = iter([service])
    conn.compute.update_service_forced_down.side_effect = (
        openstack.exceptions.BadRequestException
    )
    result = _run_enable(["somehost"], conn)
    assert result == 1


def test_migration_list_rejects_changes_since_after_changes_before():
    # changes-since must be <= changes-before; this is invalid input and the
    # check runs before any cloud setup is reached.
    result = _run(
        [
            "--changes-since",
            "2025-01-02T00:00:00",
            "--changes-before",
            "2025-01-01T00:00:00",
        ],
        MagicMock(),
    )
    assert result == 1


# ---------------------------------------------------------------------------
# Shared helpers for the remaining compute commands
# ---------------------------------------------------------------------------


def _run_command(command_class, args, conn, setup_success=True, prompt_mock=None):
    """Run any compute command with mocked cloud helpers, prompt and sleep."""
    cmd = command_class(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, setup_success))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    if prompt_mock is None:
        prompt_mock = MagicMock(return_value="yes")
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ), patch("osism.commands.compute.prompt", prompt_mock), patch(
        "osism.commands.compute.time.sleep", MagicMock()
    ):
        return cmd.take_action(parsed_args)


def _service(forced_down=False):
    service = MagicMock()
    service.__getitem__.return_value = forced_down  # service["forced_down"]
    return service


def _server(server_id, name, status, project_id="project-1"):
    server = MagicMock()
    server.id = server_id
    server.name = name
    server.status = status
    server.project_id = project_id
    return server


def _hypervisor(hypervisor_id, name, status="enabled", state="up", uptime=None):
    hypervisor = MagicMock()
    data = {
        "id": hypervisor_id,
        "status": status,
        "state": state,
        "uptime": uptime,
    }
    hypervisor.get.side_effect = lambda key, default=None: data.get(key, default)
    hypervisor.name = name
    return hypervisor


def _polled_server(status):
    server = MagicMock()
    server.status = status
    return server


# ---------------------------------------------------------------------------
# ComputeEnable
# ---------------------------------------------------------------------------


def test_enable_service_not_forced_down_only_enables():
    conn = MagicMock()
    service = _service(forced_down=False)
    conn.compute.services.return_value = iter([service])
    result = _run_command(compute.ComputeEnable, ["somehost"], conn)
    assert result is None
    conn.compute.update_service_forced_down.assert_not_called()
    conn.compute.enable_service.assert_called_once_with(
        service=service.id, host="somehost", binary="nova-compute"
    )


def test_enable_forced_down_service_is_forced_up_then_enabled():
    conn = MagicMock()
    service = _service(forced_down=True)
    conn.compute.services.return_value = iter([service])
    result = _run_command(compute.ComputeEnable, ["somehost"], conn)
    assert result is None
    conn.compute.update_service_forced_down.assert_called_once_with(
        service=service.id, host="somehost", binary="nova-compute", forced=False
    )
    conn.compute.enable_service.assert_called_once_with(
        service=service.id, host="somehost", binary="nova-compute"
    )


def test_enable_returns_1_when_setup_fails():
    conn = MagicMock()
    result = _run_command(
        compute.ComputeEnable, ["somehost"], conn, setup_success=False
    )
    assert result == 1
    conn.compute.enable_service.assert_not_called()


# ---------------------------------------------------------------------------
# ComputeDisable
# ---------------------------------------------------------------------------


def test_disable_uses_maintenance_reason():
    conn = MagicMock()
    service = _service()
    conn.compute.services.return_value = iter([service])
    result = _run_command(compute.ComputeDisable, ["somehost"], conn)
    assert result is None
    conn.compute.disable_service.assert_called_once_with(
        service=service.id,
        host="somehost",
        binary="nova-compute",
        disabled_reason="MAINTENANCE",
    )


# ---------------------------------------------------------------------------
# ComputeList
# ---------------------------------------------------------------------------


def test_list_host_with_project_filter(capsys):
    conn = MagicMock()
    server = _server("id1", "srv1", "ACTIVE", project_id="project-1")
    conn.compute.servers.return_value = [server]
    result = _run_command(
        compute.ComputeList, ["--project", "project-1", "somehost"], conn
    )
    assert result is None
    conn.compute.servers.assert_called_once_with(all_projects=True, node="somehost")
    # A server matching the project filter is listed without a domain lookup.
    conn.identity.get_project.assert_not_called()
    out = capsys.readouterr().out
    assert "id1" in out
    assert "srv1" in out


def test_list_host_with_domain_filter(capsys):
    conn = MagicMock()
    matching = _server("id1", "srv1", "ACTIVE", project_id="project-1")
    other = _server("id2", "srv2", "ACTIVE", project_id="project-2")
    conn.compute.servers.return_value = [matching, other]

    def get_project(project_id):
        project = MagicMock()
        project.domain_id = "domain-1" if project_id == "project-1" else "domain-2"
        return project

    conn.identity.get_project.side_effect = get_project
    result = _run_command(
        compute.ComputeList, ["--domain", "domain-1", "somehost"], conn
    )
    assert result is None
    assert conn.identity.get_project.call_count == 2
    out = capsys.readouterr().out
    assert "id1" in out
    assert "id2" not in out


def test_list_host_unfiltered(capsys):
    conn = MagicMock()
    conn.compute.servers.return_value = [
        _server("id1", "srv1", "ACTIVE"),
        _server("id2", "srv2", "SHUTOFF"),
    ]
    result = _run_command(compute.ComputeList, ["somehost"], conn)
    assert result is None
    out = capsys.readouterr().out
    assert "id1" in out
    assert "id2" in out


def test_list_details_parses_uptime(capsys):
    conn = MagicMock()
    conn.compute.hypervisors.return_value = [
        _hypervisor(
            "hv1",
            "node001",
            uptime=" 16:41:00 up 5 days,  3:02,  2 users,  load average: 0.98, 1.10, 1.00",
        )
    ]
    result = _run_command(compute.ComputeList, ["--details"], conn)
    assert result is None
    conn.compute.hypervisors.assert_called_once_with(details=True)
    out = capsys.readouterr().out
    assert "5 days, 3:02" in out
    assert "0.98" in out


@pytest.mark.parametrize("uptime", [None, "garbage"])
def test_list_details_missing_or_unparsable_uptime(capsys, uptime):
    conn = MagicMock()
    conn.compute.hypervisors.return_value = [
        _hypervisor("hv1", "node001", uptime=uptime)
    ]
    result = _run_command(compute.ComputeList, ["--details"], conn)
    assert result is None
    out = capsys.readouterr().out
    row = next(line for line in out.splitlines() if "hv1" in line)
    # Uptime, Load 1, Load 5 and Load 15 all fall back to the "-" placeholder.
    assert row.count("-") == 4


def test_list_hypervisors_without_details(capsys):
    conn = MagicMock()
    conn.compute.hypervisors.return_value = [_hypervisor("hv1", "node001")]
    result = _run_command(compute.ComputeList, [], conn)
    assert result is None
    out = capsys.readouterr().out
    assert "Uptime" not in out
    assert "hv1" in out
    assert "node001" in out
    assert "enabled" in out


# ---------------------------------------------------------------------------
# ComputeMigrate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["ACTIVE", "PAUSED"])
def test_migrate_live_migrates_active_and_paused(status):
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", status)]
    result = _run_command(
        compute.ComputeMigrate,
        ["--yes", "--no-wait", "--target", "target1", "--force", "somehost"],
        conn,
    )
    assert result is None
    conn.compute.live_migrate_server.assert_called_once_with(
        "id1", host="target1", block_migration="auto", force=True
    )
    conn.compute.migrate_server.assert_not_called()
    # --no-wait skips the status polling loop.
    conn.compute.get_server.assert_not_called()


def test_migrate_cold_migrates_shutoff():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "SHUTOFF")]
    result = _run_command(
        compute.ComputeMigrate,
        ["--yes", "--no-wait", "--target", "target1", "somehost"],
        conn,
    )
    assert result is None
    conn.compute.migrate_server.assert_called_once_with("id1", host="target1")
    conn.compute.live_migrate_server.assert_not_called()
    conn.compute.get_server.assert_not_called()


def test_migrate_shutoff_skipped_with_no_cold_migration(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "SHUTOFF")]
    result = _run_command(
        compute.ComputeMigrate, ["--yes", "--no-cold-migration", "somehost"], conn
    )
    assert result is None
    conn.compute.migrate_server.assert_not_called()
    conn.compute.live_migrate_server.assert_not_called()
    assert any("cannot be migrated" in r["message"] for r in loguru_logs)


def test_migrate_other_status_skipped(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "ERROR")]
    result = _run_command(compute.ComputeMigrate, ["--yes", "somehost"], conn)
    assert result is None
    conn.compute.migrate_server.assert_not_called()
    conn.compute.live_migrate_server.assert_not_called()
    assert any("cannot be migrated" in r["message"] for r in loguru_logs)


def test_migrate_prompt_no_skips_migration():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "ACTIVE")]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeMigrate, ["somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    prompt_mock.assert_called_once()
    conn.compute.live_migrate_server.assert_not_called()
    conn.compute.migrate_server.assert_not_called()


def test_migrate_cold_wait_confirms_verify_resize():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "SHUTOFF")]
    polled = _polled_server("VERIFY_RESIZE")
    conn.compute.get_server.return_value = polled
    result = _run_command(compute.ComputeMigrate, ["--yes", "somehost"], conn)
    assert result is None
    conn.compute.confirm_server_resize.assert_called_once_with(polled)


def test_migrate_confirm_failure_reraises():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "SHUTOFF")]
    conn.compute.get_server.return_value = _polled_server("VERIFY_RESIZE")
    conn.compute.confirm_server_resize.side_effect = RuntimeError("confirm failed")
    with pytest.raises(RuntimeError):
        _run_command(compute.ComputeMigrate, ["--yes", "somehost"], conn)


def test_migrate_live_wait_until_migration_completes(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "ACTIVE")]
    conn.compute.get_server.side_effect = [
        _polled_server("MIGRATING"),
        _polled_server("ACTIVE"),
    ]
    result = _run_command(compute.ComputeMigrate, ["--yes", "somehost"], conn)
    assert result is None
    assert conn.compute.get_server.call_count == 2
    messages = [r["message"] for r in loguru_logs]
    assert any("still in progress" in m for m in messages)
    assert any("completed with status ACTIVE" in m for m in messages)


def test_migrate_no_instances_found(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = []
    result = _run_command(compute.ComputeMigrate, ["--yes", "somehost"], conn)
    assert result is None
    assert any("No migratable instances found" in r["message"] for r in loguru_logs)


# ---------------------------------------------------------------------------
# ComputeMigrationList (happy path)
# ---------------------------------------------------------------------------


def test_migration_list_passes_resolved_filters_to_query():
    conn = MagicMock()

    domain = MagicMock()
    domain.__contains__.return_value = True  # "id" in domain
    domain.id = "domain-id"
    conn.identity.find_domain.return_value = domain

    user = MagicMock()
    user.__contains__.return_value = True
    user.id = "user-id"
    conn.identity.find_user.return_value = user

    project = MagicMock()
    project.__contains__.return_value = True
    project.id = "project-id"
    conn.identity.find_project.return_value = project

    server = MagicMock()
    server.__contains__.return_value = True
    server.id = "instance-uuid"
    conn.compute.find_server.return_value = server

    conn.compute.migrations.return_value = []

    result = _run(
        [
            "--host",
            "somehost",
            "--server",
            "srv1",
            "--user",
            "alice",
            "--user-domain",
            "somedomain",
            "--project",
            "someproject",
            "--project-domain",
            "somedomain",
            "--status",
            "running",
            "--type",
            "live-migration",
            "--changes-since",
            "2025-01-01T00:00:00",
            "--changes-before",
            "2025-01-02T00:00:00",
        ],
        conn,
    )
    assert result is None
    conn.identity.find_user.assert_called_once_with(
        "alice", ignore_missing=True, domain_id="domain-id"
    )
    conn.identity.find_project.assert_called_once_with(
        "someproject", ignore_missing=True, domain_id="domain-id"
    )
    conn.compute.find_server.assert_called_once_with(
        "srv1", details=False, ignore_missing=False, all_projects=True
    )
    conn.compute.migrations.assert_called_once_with(
        host="somehost",
        instance_uuid="instance-uuid",
        status="running",
        migration_type="live-migration",
        user_id="user-id",
        project_id="project-id",
        changes_since=datetime.datetime(2025, 1, 1, 0, 0, 0),
        changes_before=datetime.datetime(2025, 1, 2, 0, 0, 0),
    )


# ---------------------------------------------------------------------------
# ComputeStart / ComputeStop
# ---------------------------------------------------------------------------


def test_start_starts_only_shutoff_servers(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [
        _server("id1", "srv1", "SHUTOFF"),
        _server("id2", "srv2", "ACTIVE"),
    ]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeStart, ["--yes", "somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    # --yes starts without consulting the prompt.
    prompt_mock.assert_not_called()
    conn.compute.start_server.assert_called_once_with("id1")
    assert any("cannot be started" in r["message"] for r in loguru_logs)


def test_start_prompt_no_skips():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "SHUTOFF")]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeStart, ["somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    prompt_mock.assert_called_once()
    conn.compute.start_server.assert_not_called()


def test_stop_stops_only_active_and_paused_servers(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [
        _server("id1", "srv1", "ACTIVE"),
        _server("id2", "srv2", "PAUSED"),
        _server("id3", "srv3", "SHUTOFF"),
    ]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeStop, ["--yes", "somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    # --yes stops without consulting the prompt.
    prompt_mock.assert_not_called()
    assert conn.compute.stop_server.call_args_list == [call("id1"), call("id2")]
    assert any("cannot be stopped" in r["message"] for r in loguru_logs)


def test_stop_prompt_no_skips():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "ACTIVE")]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeStop, ["somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    prompt_mock.assert_called_once()
    conn.compute.stop_server.assert_not_called()


# ---------------------------------------------------------------------------
# ComputeEvacuate
# ---------------------------------------------------------------------------


def test_evacuate_prompt_no_makes_no_changes():
    conn = MagicMock()
    conn.compute.servers.return_value = [_server("id1", "srv1", "ACTIVE")]
    prompt_mock = MagicMock(return_value="no")
    result = _run_command(
        compute.ComputeEvacuate, ["somehost"], conn, prompt_mock=prompt_mock
    )
    assert result is None
    prompt_mock.assert_called_once()
    conn.compute.stop_server.assert_not_called()
    conn.compute.update_service_forced_down.assert_not_called()
    conn.compute.evacuate_server.assert_not_called()
    conn.compute.disable_service.assert_not_called()


def test_evacuate_full_flow(loguru_logs):
    conn = MagicMock()
    conn.compute.servers.return_value = [
        _server("id1", "srv1", "ACTIVE"),
        _server("id2", "srv2", "SHUTOFF"),
        _server("id3", "srv3", "ERROR"),
    ]
    service = _service()
    conn.compute.services.return_value = iter([service])
    # First poll: the stopped server reached SHUTOFF; second poll: the
    # restarted server reached ACTIVE.
    conn.compute.get_server.side_effect = [
        _polled_server("SHUTOFF"),
        _polled_server("ACTIVE"),
    ]

    result = _run_command(
        compute.ComputeEvacuate, ["--yes", "--target", "target1", "somehost"], conn
    )
    assert result is None

    # The ACTIVE server is stopped first and recorded for restart.
    conn.compute.stop_server.assert_called_once_with("id1")
    conn.compute.start_server.assert_called_once_with("id1")

    conn.compute.update_service_forced_down.assert_called_once_with(
        service=service.id, host="somehost", binary="nova-compute", forced=True
    )
    assert conn.compute.evacuate_server.call_args_list == [
        call("id1", host="target1"),
        call("id2", host="target1"),
    ]
    conn.compute.disable_service.assert_called_once_with(
        service=service.id,
        host="somehost",
        binary="nova-compute",
        disabled_reason="EVACUATE",
    )

    # The service is forced down before any server is evacuated.
    method_calls = [name for name, _args, _kwargs in conn.mock_calls]
    assert method_calls.index(
        "compute.update_service_forced_down"
    ) < method_calls.index("compute.evacuate_server")

    assert any(
        "srv3" in r["message"] and "cannot be evacuated" in r["message"]
        for r in loguru_logs
    )
