# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism volume list`` command.

These focus on the exit-code contract: ``VolumeList.take_action`` must return a
non-zero exit status when a requested domain or project cannot be found, so a
failed lookup does not look like success.
"""

from unittest.mock import MagicMock, patch

from osism.commands import volume


def _run(args, conn):
    cmd = volume.VolumeList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


def test_returns_nonzero_when_domain_not_found():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--domain", "d"], conn)
    assert result == 1


def test_returns_nonzero_when_project_domain_not_found():
    conn = MagicMock()
    conn.identity.find_domain.return_value = None
    result = _run(["--project", "p", "--project-domain", "d"], conn)
    assert result == 1


def test_returns_nonzero_when_project_not_found():
    conn = MagicMock()
    conn.identity.find_project.return_value = None
    result = _run(["--project", "p"], conn)
    assert result == 1
