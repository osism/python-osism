# SPDX-License-Identifier: Apache-2.0

"""Argument-assembly wiring tests for the ``osism manage`` commands.

Each command builds a Celery task signature via ``.si(...)`` and hands the
resulting task to ``handle_task``. These tests parse a real argument vector,
patch the task modules and assert on the exact argument list the signature
receives - no broker is involved. Validator wiring to ``fetch_text`` is
covered separately in ``test_manage_wiring.py``.
"""

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import manage

from ._helpers import assert_not_called_before_lock_check, parse_args


def _run_image_command(command_class, argv, fetch_bodies):
    """Drive an Image* command with mocked fetch and task plumbing.

    Returns ``(mock_fetch, mock_manager, mock_handle)``; the image-manager
    signature call is reachable via ``mock_manager.si.call_args``.
    """
    cmd, parsed_args = parse_args(command_class, argv)

    with patch.object(manage.utils, "check_task_lock_and_exit") as mock_check, patch(
        "osism.commands.manage.fetch_text"
    ) as mock_fetch, patch("osism.tasks.openstack.image_manager") as mock_im, patch(
        "osism.tasks.handle_task"
    ) as mock_handle:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_im.si)
        mock_fetch.side_effect = fetch_bodies
        mock_im.si.return_value.apply_async.return_value = MagicMock(task_id="x")
        mock_handle.return_value = 0
        cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    return mock_fetch, mock_im, mock_handle


def _run_task_command(command_class, argv, task_target):
    """Drive a command whose take_action only schedules a Celery task.

    Returns ``(mock_task, mock_handle, task)`` where ``task`` is the object
    ``apply_async`` produced and ``handle_task`` received.
    """
    cmd, parsed_args = parse_args(command_class, argv)

    with patch.object(manage.utils, "check_task_lock_and_exit") as mock_check, patch(
        task_target
    ) as mock_task, patch("osism.tasks.handle_task") as mock_handle:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_task.si)
        task = MagicMock(task_id="x")
        mock_task.si.return_value.apply_async.return_value = task
        mock_handle.return_value = 0
        cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    return mock_task, mock_handle, task


# --- ImageClusterapi.take_action ---


def test_clusterapi_default_iterates_all_supported_releases():
    fetch_bodies = []
    for release in manage.SUPPORTED_CLUSTERAPI_K8S_IMAGES:
        fetch_bodies.append(f"2026-04-12 ubuntu-2404-kube-v{release}.5.qcow2")
        fetch_bodies.append("a" * 64)

    mock_fetch, mock_im, _ = _run_image_command(
        manage.ImageClusterapi,
        ["--no-wait", "--base-url", "https://example.com/capi/"],
        fetch_bodies,
    )

    assert mock_fetch.call_count == 6
    marker_urls = [call.args[0] for call in mock_fetch.call_args_list[::2]]
    assert marker_urls == [
        f"https://example.com/capi/last-{release}"
        for release in manage.SUPPORTED_CLUSTERAPI_K8S_IMAGES
    ]
    configs = mock_im.si.call_args.kwargs["configs"]
    assert len(configs) == len(manage.SUPPORTED_CLUSTERAPI_K8S_IMAGES)


@pytest.mark.parametrize(
    "extra_argv, expected_tail",
    [
        ([], ()),
        (["--tag", "stable"], ("--tag", "stable")),
        (["--dry-run"], ("--dry-run",)),
        (["--tag", "stable", "--dry-run"], ("--tag", "stable", "--dry-run")),
    ],
    ids=["defaults", "tag", "dry-run", "tag-and-dry-run"],
)
def test_clusterapi_builds_image_manager_arguments(extra_argv, expected_tail):
    fetch_bodies = ["2026-04-12 ubuntu-2404-kube-v1.33.1.qcow2", "a" * 64]

    _, mock_im, _ = _run_image_command(
        manage.ImageClusterapi,
        ["--no-wait", "--filter", "1.33"] + extra_argv,
        fetch_bodies,
    )

    expected = (
        "--cloud",
        "admin",
        "--filter",
        "ubuntu-capi-image",
        "--stuck-retry",
        "1",
    ) + expected_tail
    assert mock_im.si.call_args.args == expected
    assert mock_im.si.call_args.kwargs["cloud"] == "admin"


def test_clusterapi_extracts_version_from_image_name():
    fetch_bodies = ["2026-04-12 ubuntu-2404-kube-v1.33.1.qcow2", "a" * 64]

    _, mock_im, _ = _run_image_command(
        manage.ImageClusterapi,
        ["--no-wait", "--filter", "1.33"],
        fetch_bodies,
    )

    (config,) = mock_im.si.call_args.kwargs["configs"]
    assert 'version: "v1.33.1"' in config
    assert f"checksum: \"sha256:{'a' * 64}\"" in config
    assert "build_date: 2026-04-12" in config


# --- ImageGardenlinux.take_action ---


def test_gardenlinux_filter_uses_unknown_builddate_placeholder():
    _, mock_im, _ = _run_image_command(
        manage.ImageGardenlinux,
        [
            "--no-wait",
            "--base-url",
            "https://example.com/gardenlinux/",
            "--filter",
            "1877.2",
        ],
        ["a" * 64],
    )

    (config,) = mock_im.si.call_args.kwargs["configs"]
    assert 'version: "1877.2"' in config
    assert "build_date: unknown" in config


def test_gardenlinux_default_uses_supported_versions_builddate():
    mock_fetch, mock_im, _ = _run_image_command(
        manage.ImageGardenlinux,
        ["--no-wait", "--base-url", "https://example.com/gardenlinux/"],
        ["a" * 64] * len(manage.SUPPORTED_GARDENLINUX_VERSIONS),
    )

    assert mock_fetch.call_args.args[0] == (
        "https://example.com/gardenlinux/1877.7/"
        "openstack-gardener_prod-amd64-1877.7.qcow2.sha256"
    )
    (config,) = mock_im.si.call_args.kwargs["configs"]
    assert 'version: "1877.7"' in config
    assert "build_date: 2025-11-14" in config


# --- Images.take_action ---


@pytest.mark.parametrize(
    "argv, expected",
    [
        (
            ["--no-wait"],
            (
                "--cloud",
                "admin",
                "--hide",
                "--images",
                "/etc/images",
                "--stuck-retry",
                "1",
            ),
        ),
        (
            ["--no-wait", "--delete"],
            (
                "--cloud",
                "admin",
                "--delete",
                "--yes-i-really-know-what-i-do",
                "--hide",
                "--images",
                "/etc/images",
                "--stuck-retry",
                "1",
            ),
        ),
        (
            ["--no-wait", "--images", "/srv/images"],
            (
                "--cloud",
                "admin",
                "--hide",
                "--images",
                "/srv/images",
                "--stuck-retry",
                "1",
            ),
        ),
    ],
    ids=["defaults", "delete", "custom-images-path"],
)
def test_images_builds_image_manager_arguments(argv, expected):
    mock_im, _, _ = _run_task_command(
        manage.Images, argv, "osism.tasks.openstack.image_manager"
    )

    assert mock_im.si.call_args.args == expected
    assert mock_im.si.call_args.kwargs == {"cloud": "admin"}


# --- Flavors.take_action ---


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--no-wait"], ("--name", "local", "--cloud", "admin")),
        (
            ["--no-wait", "--recommended"],
            ("--name", "local", "--cloud", "admin", "--recommended"),
        ),
        (
            ["--no-wait", "--name", "url", "--url", "https://example.com/flavors.yml"],
            (
                "--name",
                "url",
                "--cloud",
                "admin",
                "--url",
                "https://example.com/flavors.yml",
            ),
        ),
    ],
    ids=["defaults", "recommended", "name-and-url"],
)
def test_flavors_builds_flavor_manager_arguments(argv, expected):
    mock_fm, _, _ = _run_task_command(
        manage.Flavors, argv, "osism.tasks.openstack.flavor_manager"
    )

    assert mock_fm.si.call_args.args == expected
    assert mock_fm.si.call_args.kwargs == {"cloud": "admin"}


# --- Dnsmasq.take_action ---


@pytest.mark.parametrize(
    "argv, expected_wait",
    [([], True), (["--no-wait"], False)],
    ids=["wait", "no-wait"],
)
def test_dnsmasq_runs_infrastructure_playbook(argv, expected_wait):
    mock_run, mock_handle, task = _run_task_command(
        manage.Dnsmasq, argv, "osism.tasks.ansible.run"
    )

    mock_run.si.assert_called_once_with("infrastructure", "dnsmasq", [])
    mock_handle.assert_called_once_with(task, expected_wait, format="log", timeout=300)


# --- ProjectCreate.take_action ---

PROJECT_CREATE_DEFAULT_ARGUMENTS = (
    "--assign-admin-user",
    "--create-admin-user",
    "--nocreate-domain",
    "--nocreate-user",
    "--nocreate-application-credential",
    "--domain-name-prefix",
    "--nohas-service-network",
    "--has-public-network",
    "--has-shared-images",
    "--norandom",
    "--nomanaged-network-resources",
    "--password-length",
    "16",
    "--quota-multiplier",
    "1",
    "--quota-router",
    "1",
    "--admin-domain",
    "default",
    "--cloud",
    "admin",
    "--domain",
    "default",
    "--name",
    "sandbox",
    "--public-network",
    "public",
    "--quota-class",
    "basic",
)


def test_project_create_defaults_render_flag_pairs():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectCreate, ["--no-wait"], "osism.tasks.openstack.project_manager"
    )

    assert mock_pm.si.call_args.args == PROJECT_CREATE_DEFAULT_ARGUMENTS
    assert mock_pm.si.call_args.kwargs == {"cloud": "admin"}


def test_project_create_negative_flags_flip_defaults():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectCreate,
        ["--no-wait", "--nocreate-admin-user", "--create-domain"],
        "osism.tasks.openstack.project_manager",
    )

    args = mock_pm.si.call_args.args
    assert "--nocreate-admin-user" in args
    assert "--create-admin-user" not in args
    assert "--create-domain" in args
    assert "--nocreate-domain" not in args


def test_project_create_includes_optional_arguments_only_when_set():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectCreate,
        [
            "--no-wait",
            "--quota-multiplier-compute",
            "2",
            "--quota-multiplier-network",
            "3",
            "--quota-multiplier-storage",
            "4",
            "--internal-id",
            "b1a2",
            "--owner",
            "operations",
            "--password",
            "s3cret",
            "--service-network-cidr",
            "192.168.0.0/24",
        ],
        "osism.tasks.openstack.project_manager",
    )

    # The quota-multiplier options are inserted right after "--quota-router 1"
    # (index 17 in the default tuple), before the string arguments.
    expected = (
        PROJECT_CREATE_DEFAULT_ARGUMENTS[:17]
        + (
            "--quota-multiplier-compute",
            "2",
            "--quota-multiplier-network",
            "3",
            "--quota-multiplier-storage",
            "4",
        )
        + PROJECT_CREATE_DEFAULT_ARGUMENTS[17:]
        + (
            "--internal-id",
            "b1a2",
            "--owner",
            "operations",
            "--password",
            "s3cret",
            "--service-network-cidr",
            "192.168.0.0/24",
        )
    )
    assert mock_pm.si.call_args.args == expected


# --- ProjectSync.take_action ---

PROJECT_SYNC_DEFAULT_ARGUMENTS = (
    "--noassign-admin-user",
    "--nodry-run",
    "--nomanage-endpoints",
    "--nomanage-homeprojects",
    "--manage-privatevolumetypes",
    "--manage-privateflavors",
    "--admin-domain",
    "default",
    "--classes",
    "etc/classes.yml",
    "--endpoints",
    "etc/endpoints.yml",
    "--cloud",
    "admin",
)


def test_project_sync_defaults_render_flag_pairs():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectSync, ["--no-wait"], "osism.tasks.openstack.project_manager_sync"
    )

    assert mock_pm.si.call_args.args == PROJECT_SYNC_DEFAULT_ARGUMENTS
    assert mock_pm.si.call_args.kwargs == {"cloud": "admin"}


def test_project_sync_appends_domain_and_name_only_when_given():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectSync,
        ["--no-wait", "--domain", "d1", "--name", "p1"],
        "osism.tasks.openstack.project_manager_sync",
    )

    assert mock_pm.si.call_args.args == PROJECT_SYNC_DEFAULT_ARGUMENTS + (
        "--domain",
        "d1",
        "--name",
        "p1",
    )


def test_project_sync_positive_flags_flip_defaults():
    mock_pm, _, _ = _run_task_command(
        manage.ProjectSync,
        ["--no-wait", "--assign-admin-user", "--dry-run", "--nomanage-privateflavors"],
        "osism.tasks.openstack.project_manager_sync",
    )

    args = mock_pm.si.call_args.args
    assert "--assign-admin-user" in args
    assert "--noassign-admin-user" not in args
    assert "--dry-run" in args
    assert "--nodry-run" not in args
    assert "--nomanage-privateflavors" in args
    assert "--manage-privateflavors" not in args
