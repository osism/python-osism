from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from osism.commands import server


def _obj(**attrs):
    """Build a MagicMock with real attribute values (incl. ``name``)."""
    obj = MagicMock()
    for key, value in attrs.items():
        setattr(obj, key, value)
    return obj


def _created_at(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _run(args, conn):
    cmd = server.ServerList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


def test_no_domain_found_for_user_domain_returns_1():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--user", "u", "--user-domain", "d"], conn)
    assert result == 1


def test_no_user_found_returns_1():
    conn = MagicMock()
    conn.identity.find_user.return_value = None
    result = _run(["--user", "u"], conn)
    assert result == 1


def test_domain_not_found_returns_1():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--domain", "d"], conn)
    assert result == 1


def test_project_domain_not_found_returns_1():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--project", "p", "--project-domain", "d"], conn)
    assert result == 1


def test_project_not_found_returns_1():
    conn = MagicMock()
    conn.identity.find_project.return_value = None
    result = _run(["--project", "p"], conn)
    assert result == 1


def _run_migrate(args, conn):
    cmd = server.ServerMigrate(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


def test_migrate_returns_1_when_server_not_active_or_paused():
    conn = MagicMock()
    conn.compute.get_server.return_value = MagicMock(
        id="i1", name="n1", status="SHUTOFF"
    )
    result = _run_migrate(["someinstance"], conn)
    assert result == 1


def _run_migrate_interactive(args, conn, prompt_return="yes"):
    """Run ServerMigrate with prompt and time.sleep mocked out."""
    cmd = server.ServerMigrate(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    prompt_mock = MagicMock(return_value=prompt_return)
    sleep_mock = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ), patch("osism.commands.server.prompt", prompt_mock), patch(
        "osism.commands.server.time.sleep", sleep_mock
    ):
        rc = cmd.take_action(parsed_args)
    return rc, prompt_mock, sleep_mock


def test_migrate_active_with_yes_uses_defaults():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    conn.compute.get_server.side_effect = [active, active]

    _, prompt_mock, _ = _run_migrate_interactive(["--yes", "s1"], conn)

    conn.compute.live_migrate_server.assert_called_once_with(
        "s1", host=None, block_migration="auto", force=False
    )
    prompt_mock.assert_not_called()


def test_migrate_target_and_force_passed_through():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    conn.compute.get_server.side_effect = [active, active]

    _run_migrate_interactive(["--yes", "--target", "host1", "--force", "s1"], conn)

    conn.compute.live_migrate_server.assert_called_once_with(
        "s1", host="host1", block_migration="auto", force=True
    )


def test_migrate_prompt_no_skips_migration():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    conn.compute.get_server.return_value = active

    _, prompt_mock, _ = _run_migrate_interactive(["s1"], conn, prompt_return="no")

    prompt_mock.assert_called_once()
    conn.compute.live_migrate_server.assert_not_called()


def test_migrate_prompt_y_accepted():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    conn.compute.get_server.side_effect = [active, active]

    _run_migrate_interactive(["s1"], conn, prompt_return="y")

    conn.compute.live_migrate_server.assert_called_once()


def test_migrate_waits_until_no_longer_migrating():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    migrating = _obj(id="s1", name="srv1", status="MIGRATING")
    conn.compute.get_server.side_effect = [active, migrating, migrating, active]

    _, _, sleep_mock = _run_migrate_interactive(["--yes", "s1"], conn)

    assert conn.compute.get_server.call_count == 4
    assert sleep_mock.call_count == 3


def test_migrate_no_wait_skips_polling():
    conn = MagicMock()
    active = _obj(id="s1", name="srv1", status="ACTIVE")
    conn.compute.get_server.side_effect = [active]

    _, _, sleep_mock = _run_migrate_interactive(["--yes", "--no-wait", "s1"], conn)

    assert conn.compute.get_server.call_count == 1
    sleep_mock.assert_not_called()
    conn.compute.live_migrate_server.assert_called_once()


def test_migrate_paused_server_allowed():
    conn = MagicMock()
    paused = _obj(id="s1", name="srv1", status="PAUSED")
    conn.compute.get_server.side_effect = [paused]

    rc, _, _ = _run_migrate_interactive(["--yes", "--no-wait", "s1"], conn)

    assert rc is None
    conn.compute.live_migrate_server.assert_called_once()


# --- ServerList happy paths ---


def test_list_domain_happy_path(capsys):
    conn = MagicMock()
    domain = _obj(id="d1", name="dom1")
    conn.identity.find_domain.return_value = domain
    project = _obj(id="p1", name="proj1")
    conn.identity.projects.return_value = [project]
    srv = _obj(
        id="s1",
        name="vm1",
        status="ACTIVE",
        user_id="u1",
        flavor={"original_name": "m1.small"},
    )
    conn.compute.servers.return_value = [srv]

    _run(["--domain", "dom1"], conn)

    conn.identity.projects.assert_called_once_with(domain_id="d1")
    conn.compute.servers.assert_called_once_with(all_projects=True, project_id="p1")
    out = capsys.readouterr().out
    for header in ["Project", "Project ID", "User ID", "ID", "Name", "Flavor"]:
        assert header in out
    assert "proj1" in out
    assert "vm1" in out
    assert "m1.small" in out


def test_list_project_with_project_domain(capsys):
    conn = MagicMock()
    project_domain = _obj(id="pd1")
    conn.identity.find_domain.return_value = project_domain
    project = _obj(id="p1", name="proj1", domain_id="pd1")
    conn.identity.find_project.return_value = project
    resolved_domain = _obj(name="domname")
    conn.identity.get_domain.return_value = resolved_domain
    srv = _obj(
        id="s1",
        name="vm1",
        status="ACTIVE",
        user_id="u1",
        flavor={"original_name": "f1"},
    )
    conn.compute.servers.return_value = [srv]

    _run(["--project", "proj1", "--project-domain", "pd"], conn)

    conn.identity.find_project.assert_called_once_with("proj1", domain_id="pd1")
    out = capsys.readouterr().out
    assert "domname" in out
    assert "vm1" in out


def test_list_project_get_domain_failure_falls_back_to_id(capsys):
    conn = MagicMock()
    project = _obj(id="p1", name="proj1", domain_id="pd1")
    conn.identity.find_project.return_value = project
    conn.identity.get_domain.side_effect = RuntimeError("keystone down")
    srv = _obj(
        id="s1",
        name="vm1",
        status="ACTIVE",
        user_id="u1",
        flavor={"original_name": "f1"},
    )
    conn.compute.servers.return_value = [srv]

    _run(["--project", "proj1"], conn)

    out = capsys.readouterr().out
    assert "pd1" in out


def test_list_user_happy_path(capsys):
    conn = MagicMock()
    user = MagicMock()
    user.id = "u1"
    user.__contains__.return_value = True
    conn.identity.find_user.return_value = user
    srv = _obj(
        id="s1",
        name="vm1",
        status="ACTIVE",
        project_id="p1",
        flavor={"original_name": "f1"},
    )
    conn.compute.servers.return_value = [srv]
    project = _obj(id="p1", domain_id="d1")
    conn.identity.get_project.return_value = project
    domain = _obj(name="domname")
    conn.identity.get_domain.return_value = domain

    _run(["--user", "alice"], conn)

    conn.compute.servers.assert_called_once_with(all_projects=True, user_id="u1")
    out = capsys.readouterr().out
    assert "domname" in out
    assert "vm1" in out
    assert "p1" in out


def test_list_user_domain_resolution_failure_leaves_domain_empty(capsys):
    conn = MagicMock()
    user = MagicMock()
    user.id = "u1"
    user.__contains__.return_value = True
    conn.identity.find_user.return_value = user
    srv = _obj(
        id="s1",
        name="vm1",
        status="ACTIVE",
        project_id="p1",
        flavor={"original_name": "f1"},
    )
    conn.compute.servers.return_value = [srv]
    conn.identity.get_project.side_effect = RuntimeError("keystone down")

    _run(["--user", "alice"], conn)

    out = capsys.readouterr().out
    assert "vm1" in out
    assert "domname" not in out


def test_list_default_only_reports_old_build_and_error_servers(capsys):
    conn = MagicMock()
    old_build = _obj(
        id="old-build-id",
        name="ob",
        status="BUILD",
        flavor={"original_name": "f"},
        created_at=_created_at(8000),
    )
    fresh_build = _obj(
        id="fresh-build-id",
        name="fb",
        status="BUILD",
        flavor={"original_name": "f"},
        created_at=_created_at(60),
    )
    old_error = _obj(
        id="old-error-id",
        name="oe",
        status="ERROR",
        flavor={"original_name": "f"},
        created_at=_created_at(8000),
    )

    def servers(all_projects=True, status=None, **kwargs):
        return {"build": [old_build, fresh_build], "error": [old_error]}[status]

    conn.compute.servers.side_effect = servers

    _run([], conn)

    out = capsys.readouterr().out
    assert "old-build-id" in out
    assert "old-error-id" in out
    assert "fresh-build-id" not in out


# --- ServerClean ---


def _run_clean(args, conn, prompt_return="yes"):
    cmd = server.ServerClean(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    prompt_mock = MagicMock(return_value=prompt_return)
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ), patch("osism.commands.server.prompt", prompt_mock):
        rc = cmd.take_action(parsed_args)
    return rc, prompt_mock, cleanup


def _clean_conn(build=None, error=None):
    conn = MagicMock()

    def servers(all_projects=True, status=None, **kwargs):
        return {"build": build or [], "error": error or []}[status]

    conn.compute.servers.side_effect = servers
    return conn


def test_clean_deletes_old_build_server_with_yes():
    stuck = _obj(id="s1", name="vm1", created_at=_created_at(8000))
    conn = _clean_conn(build=[stuck])

    _, prompt_mock, _ = _run_clean(["--yes"], conn)

    conn.compute.delete_server.assert_called_once_with("s1", force=True)
    prompt_mock.assert_not_called()


def test_clean_skips_young_build_server():
    fresh = _obj(id="s1", name="vm1", created_at=_created_at(60))
    conn = _clean_conn(build=[fresh])

    _, prompt_mock, _ = _run_clean(["--yes"], conn)

    conn.compute.delete_server.assert_not_called()
    prompt_mock.assert_not_called()


def test_clean_honors_custom_build_timeout():
    stuck = _obj(id="s1", name="vm1", created_at=_created_at(120))
    conn = _clean_conn(build=[stuck])

    _run_clean(["--yes", "--build-timeout", "60"], conn)

    conn.compute.delete_server.assert_called_once_with("s1", force=True)


def test_clean_prompt_no_skips_deletion():
    stuck = _obj(id="s1", name="vm1", created_at=_created_at(8000))
    conn = _clean_conn(build=[stuck])

    _, prompt_mock, _ = _run_clean([], conn, prompt_return="no")

    prompt_mock.assert_called_once()
    conn.compute.delete_server.assert_not_called()


def test_clean_error_server_deleted_regardless_of_age():
    broken = _obj(id="s2", name="vm2", created_at=_created_at(60))
    conn = _clean_conn(error=[broken])

    _run_clean(["--yes"], conn)

    conn.compute.delete_server.assert_called_once_with("s2", force=True)


def test_clean_cleanup_called_in_finally():
    conn = _clean_conn()

    _, _, cleanup = _run_clean(["--yes"], conn)

    cleanup.assert_called_once_with([], None)
