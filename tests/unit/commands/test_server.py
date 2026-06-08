from unittest.mock import MagicMock, patch

from osism.commands import server


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
