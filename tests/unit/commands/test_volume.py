# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism volume list`` and ``osism volume repair`` commands.

``VolumeList`` must return a non-zero exit status when a requested domain or
project cannot be found, report volumes stuck in transitional states for more
than two hours, and list volumes per project when filtering by domain.
``VolumeRepair`` must only touch volumes that are actually stuck and honor the
confirmation prompts.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

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


# ---------------------------------------------------------------------------
# Shared helpers for the stuck-volume tests
# ---------------------------------------------------------------------------

STUCK_STATUSES = ["detaching", "creating", "error_deleting", "deleting", "error"]


def _created_at(hours_ago):
    # The command parses ``created_at`` with dateutil and localizes it via
    # ``pytz.utc``, so the timestamp must be a naive ISO string.
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )


def _volume(volume_id, status, hours_ago, name="vol", volume_type="ssd"):
    vol = MagicMock()
    vol.id = volume_id
    vol.name = name
    vol.volume_type = volume_type
    vol.status = status
    vol.created_at = _created_at(hours_ago)
    return vol


def _volumes_by_status(mapping):
    def side_effect(all_projects=True, status=None, **kwargs):
        return mapping.get(status, [])

    return side_effect


def _run_repair(args, conn, prompt_mock=None, sleep_mock=None):
    cmd = volume.VolumeRepair(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    if prompt_mock is None:
        prompt_mock = MagicMock(return_value="yes")
    if sleep_mock is None:
        sleep_mock = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ), patch("osism.commands.volume.prompt", prompt_mock), patch(
        "osism.commands.volume.sleep", sleep_mock
    ):
        return cmd.take_action(parsed_args)


# ---------------------------------------------------------------------------
# VolumeList
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", STUCK_STATUSES)
def test_list_reports_only_stuck_volumes(capsys, status):
    conn = MagicMock()
    stuck = _volume("stuckvol", status, hours_ago=3)
    fresh = _volume("freshvol", status, hours_ago=1)
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {status: [stuck, fresh]}
    )
    result = _run([], conn)
    assert result is None
    queried = {c.kwargs["status"] for c in conn.block_storage.volumes.call_args_list}
    assert queried == set(STUCK_STATUSES)
    out = capsys.readouterr().out
    assert "stuckvol" in out
    assert "freshvol" not in out


def test_list_domain_lists_volumes_per_project(capsys):
    conn = MagicMock()
    domain = MagicMock()
    domain.id = "domainid"
    conn.identity.find_domain.return_value = domain

    project1 = MagicMock()
    project1.id = "projectid1"
    project1.name = "project1"
    project2 = MagicMock()
    project2.id = "projectid2"
    project2.name = "project2"
    conn.identity.projects.return_value = [project1, project2]

    volumes = {
        "projectid1": [_volume("volid1", "available", hours_ago=1)],
        "projectid2": [_volume("volid2", "in-use", hours_ago=1)],
    }

    def volumes_by_project(all_projects=True, project_id=None, **kwargs):
        return volumes[project_id]

    conn.block_storage.volumes.side_effect = volumes_by_project

    result = _run(["--domain", "somedomain"], conn)
    assert result is None
    conn.identity.projects.assert_called_once_with(domain_id="domainid")
    out = capsys.readouterr().out
    assert "project1" in out
    assert "volid1" in out
    assert "project2" in out
    assert "volid2" in out


# ---------------------------------------------------------------------------
# VolumeRepair
# ---------------------------------------------------------------------------


def test_repair_aborts_stuck_detaching_without_prompt():
    conn = MagicMock()
    stuck = _volume("stuckvol", "detaching", hours_ago=3)
    fresh = _volume("freshvol", "detaching", hours_ago=1)
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {"detaching": [stuck, fresh]}
    )
    prompt_mock = MagicMock(return_value="yes")
    result = _run_repair([], conn, prompt_mock=prompt_mock)
    assert result is None
    conn.block_storage.abort_volume_detaching.assert_called_once_with("stuckvol")
    prompt_mock.assert_not_called()
    conn.block_storage.delete_volume.assert_not_called()


def test_repair_deletes_stuck_creating_with_yes():
    conn = MagicMock()
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {"creating": [_volume("stuckvol", "creating", hours_ago=3)]}
    )
    prompt_mock = MagicMock(return_value="no")
    result = _run_repair(["--yes"], conn, prompt_mock=prompt_mock)
    assert result is None
    prompt_mock.assert_not_called()
    conn.block_storage.delete_volume.assert_called_once_with("stuckvol", force=True)


def test_repair_stuck_creating_prompt_no_skips_delete():
    conn = MagicMock()
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {"creating": [_volume("stuckvol", "creating", hours_ago=3)]}
    )
    prompt_mock = MagicMock(return_value="no")
    result = _run_repair([], conn, prompt_mock=prompt_mock)
    assert result is None
    prompt_mock.assert_called_once()
    conn.block_storage.delete_volume.assert_not_called()


def test_repair_error_deleting_prompted_regardless_of_age():
    conn = MagicMock()
    # A fresh volume: ERROR_DELETING is handled without an age threshold.
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {"error_deleting": [_volume("brokenvol", "error_deleting", hours_ago=1)]}
    )
    prompt_mock = MagicMock(return_value="yes")
    result = _run_repair([], conn, prompt_mock=prompt_mock)
    assert result is None
    prompt_mock.assert_called_once()
    conn.block_storage.delete_volume.assert_called_once_with("brokenvol", force=True)


def test_repair_stuck_deleting_resets_then_deletes():
    conn = MagicMock()
    conn.block_storage.volumes.side_effect = _volumes_by_status(
        {"deleting": [_volume("stuckvol", "deleting", hours_ago=3)]}
    )
    sleep_mock = MagicMock()
    manager = MagicMock()
    manager.attach_mock(conn.block_storage.reset_volume_status, "reset")
    manager.attach_mock(sleep_mock, "sleep")
    manager.attach_mock(conn.block_storage.delete_volume, "delete")
    result = _run_repair([], conn, sleep_mock=sleep_mock)
    assert result is None
    assert manager.mock_calls == [
        call.reset(
            "stuckvol", status="available", attach_status=None, migration_status=None
        ),
        call.sleep(volume.SLEEP_WAIT_FOR_API),
        call.delete("stuckvol", force=True),
    ]
