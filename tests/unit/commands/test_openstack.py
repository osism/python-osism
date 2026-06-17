# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism openstack`` passthrough command.

These cover the wrapper contract:

- subcommands and parameters are passed straight through to the
  ``openstack`` CLI, defaulting to the ``admin`` cloud;
- OpenStack global options that precede the subcommand (e.g.
  ``--os-interface``, ``--os-region-name``) are forwarded verbatim
  rather than rejected;
- ``--cloud`` selects a different cloud profile;
- passing ``--os-cloud`` through is rejected in favour of ``--cloud``;
- a failed cloud setup short-circuits before the CLI is invoked but
  still cleans up the (possibly partial) cloud environment;
- the CLI's exit code is propagated as the command's return code;
- registering ``openstack`` alongside ``openstack stress`` does not
  shadow the existing stress subcommand (cliff longest-prefix routing).
"""

from unittest.mock import MagicMock, patch

from osism.commands import openstack


def _run(args, *, setup_return, run_returncode=0):
    cmd = openstack.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)

    setup = MagicMock(return_value=setup_return)
    cleanup = MagicMock()
    run = MagicMock()
    run.return_value.returncode = run_returncode

    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, MagicMock(), cleanup),
    ), patch("osism.commands.openstack.subprocess.run", run):
        result = cmd.take_action(parsed_args)

    return result, setup, cleanup, run


def test_passes_arguments_through_with_default_cloud():
    result, setup, cleanup, run = _run(
        ["server", "list", "-f", "json"],
        setup_return=(None, ["/tmp/clouds.yaml"], "/orig", True),
    )

    assert result == 0
    setup.assert_called_once_with("admin")
    run.assert_called_once()
    assert run.call_args.args[0] == [
        "openstack",
        "--os-cloud",
        "admin",
        "server",
        "list",
        "-f",
        "json",
    ]
    cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")


def test_forwards_leading_global_options():
    # Regression test for the passthrough contract: OpenStack global options
    # placed *before* the subcommand must be forwarded verbatim, not rejected.
    # argparse.REMAINDER captures only from the first positional token, so the
    # parser delegates to parse_known_args to keep these intact.
    #
    # cliff's *app-level* parser consumes its own globals (--debug, -v/-q,
    # --log-file) before this command's parser runs, so those never reach the
    # passthrough and are intentionally not exercised here; --os-interface /
    # --os-region-name are forwarded because the app parser does not know them.
    result, setup, cleanup, run = _run(
        ["--os-interface", "public", "--os-region-name", "RegionOne", "server", "list"],
        setup_return=(None, [], "/orig", True),
    )

    assert result == 0
    setup.assert_called_once_with("admin")
    assert run.call_args.args[0] == [
        "openstack",
        "--os-cloud",
        "admin",
        "--os-interface",
        "public",
        "--os-region-name",
        "RegionOne",
        "server",
        "list",
    ]


def test_cloud_option_selects_cloud():
    result, setup, cleanup, run = _run(
        ["--cloud", "octavia", "image", "list"],
        setup_return=(None, [], "/orig", True),
    )

    assert result == 0
    setup.assert_called_once_with("octavia")
    assert run.call_args.args[0][:5] == [
        "openstack",
        "--os-cloud",
        "octavia",
        "image",
        "list",
    ]


def test_returns_one_when_cloud_setup_fails():
    result, setup, cleanup, run = _run(
        ["server", "list"],
        setup_return=(None, ["/tmp/clouds.yaml"], "/orig", False),
    )

    assert result == 1
    run.assert_not_called()
    # setup may have copied temp files / changed cwd before failing, so the
    # environment is still cleaned up.
    cleanup.assert_called_once_with(["/tmp/clouds.yaml"], "/orig")


def test_rejects_passed_through_os_cloud():
    for args in (
        ["server", "list", "--os-cloud", "other"],
        ["server", "list", "--os-cloud=other"],
    ):
        result, setup, cleanup, run = _run(
            args,
            setup_return=(None, [], "/orig", True),
        )

        assert result == 1
        setup.assert_not_called()
        run.assert_not_called()
        cleanup.assert_not_called()


def test_propagates_openstack_exit_code():
    result, setup, cleanup, run = _run(
        ["server", "show", "missing"],
        setup_return=(None, [], "/orig", True),
        run_returncode=2,
    )

    assert result == 2
    cleanup.assert_called_once()


def test_returns_one_when_openstack_binary_missing():
    cmd = openstack.Run(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["server", "list"])

    setup = MagicMock(return_value=(None, [], "/orig", True))
    cleanup = MagicMock()

    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, MagicMock(), cleanup),
    ), patch(
        "osism.commands.openstack.subprocess.run",
        side_effect=FileNotFoundError,
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
    cleanup.assert_called_once_with([], "/orig")


def test_openstack_subcommands_route_correctly():
    from cliff.commandmanager import CommandManager

    # CommandManager reads *installed* entry-point metadata, not the source
    # tree, so this assertion depends on a current editable install. After
    # editing setup.cfg without reinstalling, stale egg-info makes this fail
    # with a misleading "Unknown command ..."; it is green in CI (fresh
    # install) and after `pip install -e .` locally.
    manager = CommandManager("osism.commands")

    _, stress_name, _ = manager.find_command(["openstack", "stress"])
    assert stress_name == "openstack stress"

    _, name, remainder = manager.find_command(["openstack", "server", "list"])
    assert name == "openstack"
    assert remainder == ["server", "list"]
