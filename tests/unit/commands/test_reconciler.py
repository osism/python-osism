# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism reconciler`` commands.

These focus on the exit-code contract: a command must return a non-zero exit
status when it gives up waiting for a task (a timeout is an operational
failure), rather than falling through to an implicit success.
"""

from unittest.mock import MagicMock, patch

from osism.commands import reconciler


def test_task_timeout_help_describes_output_inactivity():
    cmd = reconciler.Sync(MagicMock(), MagicMock())
    parser = cmd.get_parser("test")
    help_text = next(
        action.help
        for action in parser._actions
        if "--task-timeout" in action.option_strings
    )

    # The value bounds how long the client waits for further task output. Time
    # a task spends queued produces no output, so it counts against the
    # timeout rather than being excluded from it.
    assert "output" in help_text.lower()
    assert "scheduled task that has not been executed" not in help_text.lower()
    assert "queued" in help_text.lower()


def test_sync_returns_nonzero_on_task_timeout():
    cmd = reconciler.Sync(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch("osism.commands.reconciler.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.reconciler.run.delay", return_value=MagicMock()
    ), patch(
        "osism.commands.reconciler.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1
