# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the manager tasks of ``osism/tasks/openstack.py``.

Covers ``image_manager``, ``flavor_manager``, ``project_manager`` and
``project_manager_sync``.

Every external effect is mocked: the cloud environment helpers, ``run_command``
and the task-lock check are patched, and the module-level ``os`` binding comes
from the shared ``mock_os`` fixture (see ``conftest.py``) so no test touches the
real filesystem or working directory. The bound tasks (``bind=True``) are
exercised through ``task.__wrapped__(...)`` (already bound to the task instance,
so ``self.request.id`` is ``None``).
"""

import pathlib

import pytest

from osism.tasks import openstack as openstack_tasks

# ---------------------------------------------------------------------------
# image_manager
# ---------------------------------------------------------------------------


def test_image_manager_delegates_without_configs(mocker):
    """Without configs the task delegates to the generalized helper."""
    check = mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    delegate = mocker.patch(
        "osism.tasks.openstack.run_openstack_command_with_cloud", return_value="RC"
    )

    result = openstack_tasks.image_manager.__wrapped__(
        "--dry-run", cloud="admin", publish=False, locking=True, auto_release_time=60
    )

    check.assert_called_once_with()
    delegate.assert_called_once_with(
        None,
        "/usr/local/bin/openstack-image-manager",
        "admin",
        ("--dry-run",),
        publish=False,
        locking=True,
        auto_release_time=60,
    )
    assert result == "RC"


def test_image_manager_rewrites_images_arguments(mocker):
    """With configs, each config lands as a file in a temp directory, both
    ``--images=...`` and ``--images <dir>`` arguments are dropped and the
    temp directory is appended as the new ``--images`` value."""
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    setup = mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, [], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    captured = {}

    def fake_run_command(request_id, command, env, *args, **kwargs):
        # The temp directory only exists while run_command executes, so its
        # contents must be captured here.
        images_dir = pathlib.Path(args[args.index("--images") + 1])
        captured["request_id"] = request_id
        captured["command"] = command
        captured["env"] = env
        captured["args"] = args
        captured["kwargs"] = kwargs
        captured["configs"] = sorted(p.read_text() for p in images_dir.iterdir())
        return "RC"

    mocker.patch("osism.tasks.openstack.run_command", side_effect=fake_run_command)

    result = openstack_tasks.image_manager.__wrapped__(
        "--dry-run",
        "--images=inline-dir",
        "--images",
        "pair-dir",
        configs=["yaml-a", "yaml-b"],
        cloud="admin",
    )

    setup.assert_called_once_with("admin")
    assert captured["request_id"] is None
    assert captured["command"] == "/usr/local/bin/openstack-image-manager"
    assert captured["env"] == {}
    assert captured["args"][:2] == ("--dry-run", "--images")
    assert "--images=inline-dir" not in captured["args"]
    assert "pair-dir" not in captured["args"]
    assert captured["configs"] == ["yaml-a", "yaml-b"]
    assert captured["kwargs"] == {
        "publish": True,
        "locking": False,
        "auto_release_time": 3600,
        "ignore_env": True,
    }
    cleanup.assert_called_once_with([], "/orig")
    assert result == "RC"


def test_image_manager_cleans_up_on_run_command_error(mocker):
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, [], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    mocker.patch(
        "osism.tasks.openstack.run_command", side_effect=RuntimeError("worker died")
    )

    with pytest.raises(RuntimeError):
        openstack_tasks.image_manager.__wrapped__(configs=["cfg"], cloud="admin")

    cleanup.assert_called_once_with([], "/orig")


def test_image_manager_strips_trailing_images_flag(mocker):
    """A trailing ``--images`` without a value is dropped; the temp directory
    is still forced as the only ``--images`` value."""
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, [], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command", return_value="RC")

    result = openstack_tasks.image_manager.__wrapped__(
        "--dry-run", "--images", configs=["cfg"], cloud="admin"
    )

    args = run.call_args.args[3:]
    assert args[:2] == ("--dry-run", "--images")
    assert len(args) == 3  # the forced temp directory is the only --images value
    cleanup.assert_called_once_with([], "/orig")
    assert result == "RC"


def test_image_manager_aborts_on_setup_failure(mocker):
    """With configs, a failed cloud setup short-circuits before any command
    runs; cleanup still runs."""
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, [], "/orig", False),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command")

    result = openstack_tasks.image_manager.__wrapped__(configs=["cfg"], cloud="admin")

    assert result == 1
    run.assert_not_called()
    cleanup.assert_called_once_with([], "/orig")


# ---------------------------------------------------------------------------
# flavor_manager / project_manager / project_manager_sync
# ---------------------------------------------------------------------------


def test_flavor_manager_delegates(mocker):
    check = mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    delegate = mocker.patch(
        "osism.tasks.openstack.run_openstack_command_with_cloud", return_value="RC"
    )

    result = openstack_tasks.flavor_manager.__wrapped__(
        "--x", cloud="admin", publish=False, locking=True, auto_release_time=60
    )

    check.assert_called_once_with()
    delegate.assert_called_once_with(
        None,
        "/usr/local/bin/openstack-flavor-manager",
        "admin",
        ("--x",),
        publish=False,
        locking=True,
        auto_release_time=60,
    )
    assert result == "RC"


PROJECT_MANAGER_VARIANTS = [
    pytest.param(
        "project_manager",
        "/openstack-project-manager/openstack_project_manager/create.py",
        id="create",
    ),
    pytest.param(
        "project_manager_sync",
        "/openstack-project-manager/openstack_project_manager/manage.py",
        id="manage",
    ),
]


@pytest.mark.parametrize("task_name, script_path", PROJECT_MANAGER_VARIANTS)
def test_project_manager_delegates(mocker, mock_os, task_name, script_path):
    """The script path is prepended to the arguments and the command runs from
    the openstack-project-manager checkout."""
    check = mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    setup = mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=("pw", ["/tmp/clouds.yaml"], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command", return_value="RC")

    result = getattr(openstack_tasks, task_name).__wrapped__(
        "--x", cloud="admin", publish=False
    )

    check.assert_called_once_with()
    setup.assert_called_once_with("admin")
    mock_os.chdir.assert_called_once_with("/openstack-project-manager")
    run.assert_called_once_with(
        None,
        "/usr/local/bin/python3",
        {},
        script_path,
        "--x",
        publish=False,
        locking=False,
        auto_release_time=3600,
        ignore_env=True,
    )
    cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")
    assert result == "RC"


@pytest.mark.parametrize("task_name, script_path", PROJECT_MANAGER_VARIANTS)
def test_project_manager_cleans_up_on_error(mocker, mock_os, task_name, script_path):
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, ["/tmp/clouds.yaml"], "/orig", True),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command")
    mock_os.chdir.side_effect = OSError("missing directory")

    with pytest.raises(OSError):
        getattr(openstack_tasks, task_name).__wrapped__(cloud="admin")

    run.assert_not_called()
    cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")


@pytest.mark.parametrize("task_name, script_path", PROJECT_MANAGER_VARIANTS)
def test_project_manager_aborts_on_setup_failure(
    mocker, mock_os, task_name, script_path
):
    """A failed cloud setup short-circuits before the directory change."""
    mocker.patch("osism.tasks.openstack.utils.check_task_lock_and_exit")
    mocker.patch(
        "osism.tasks.openstack.setup_cloud_environment",
        return_value=(None, [], "/orig", False),
    )
    cleanup = mocker.patch("osism.tasks.openstack.cleanup_cloud_environment")
    run = mocker.patch("osism.tasks.openstack.run_command")

    result = getattr(openstack_tasks, task_name).__wrapped__(cloud="admin")

    assert result == 1
    mock_os.chdir.assert_not_called()
    run.assert_not_called()
    cleanup.assert_called_once_with([], "/orig")


MANAGER_LOCK_VARIANTS = [
    pytest.param("image_manager", {}, id="image_manager"),
    pytest.param("image_manager", {"configs": ["cfg"]}, id="image_manager_configs"),
    pytest.param("flavor_manager", {}, id="flavor_manager"),
    pytest.param("project_manager", {}, id="project_manager"),
    pytest.param("project_manager_sync", {}, id="project_manager_sync"),
]


@pytest.mark.parametrize("task_name, kwargs", MANAGER_LOCK_VARIANTS)
def test_manager_tasks_abort_when_task_lock_active(mocker, task_name, kwargs):
    """The task-lock check runs before any cloud setup or delegation."""
    mocker.patch(
        "osism.tasks.openstack.utils.check_task_lock_and_exit",
        side_effect=SystemExit(1),
    )
    delegate = mocker.patch("osism.tasks.openstack.run_openstack_command_with_cloud")
    setup = mocker.patch("osism.tasks.openstack.setup_cloud_environment")

    with pytest.raises(SystemExit):
        getattr(openstack_tasks, task_name).__wrapped__(cloud="admin", **kwargs)

    delegate.assert_not_called()
    setup.assert_not_called()
