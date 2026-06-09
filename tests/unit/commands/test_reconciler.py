# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism reconciler`` commands."""

from unittest.mock import MagicMock, patch

from osism.commands import reconciler


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
