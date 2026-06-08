# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import openstack

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
