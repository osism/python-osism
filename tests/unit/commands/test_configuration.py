# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism configuration sync`` command.

``Sync`` schedules the ``configuration`` playbook on the manager environment
and returns the task's exit code via ``handle_task``.
"""

from unittest.mock import patch

import pytest

from osism.commands import configuration

from ._helpers import assert_not_called_before_lock_check, parse_args


def test_parser_forwards_mixed_positional_and_option_arguments():
    _, parsed_args = parse_args(configuration.Sync, ["playbook", "-e", "foo=1"])
    assert parsed_args.arguments == ["playbook", "-e", "foo=1"]


def test_parser_forwards_leading_option_arguments():
    # The parser delegates to ``parse_known_args`` (see ``_PassthroughParser``),
    # so option-like tokens (``-e``, ``--limit``, ...) are forwarded verbatim
    # even without a leading positional.
    _, parsed_args = parse_args(configuration.Sync, ["-e", "foo=1"])
    assert parsed_args.arguments == ["-e", "foo=1"]


@pytest.mark.parametrize("rc", [0, 2])
def test_take_action_schedules_configuration_sync_and_returns_rc(rc):
    cmd, parsed_args = parse_args(configuration.Sync, ["playbook", "-e", "foo=1"])

    with patch(
        "osism.commands.configuration.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.tasks.ansible.run.delay") as mock_delay, patch(
        "osism.tasks.handle_task", return_value=rc
    ):
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        result = cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with(
        "manager",
        "configuration",
        ["playbook", "-e", "foo=1"],
        auto_release_time=60,
    )
    assert result == rc


def test_take_action_waits_with_log_format():
    cmd, parsed_args = parse_args(configuration.Sync, [])

    with patch("osism.commands.configuration.utils.check_task_lock_and_exit"), patch(
        "osism.tasks.ansible.run.delay"
    ) as mock_delay, patch("osism.tasks.handle_task", return_value=0) as mock_handle:
        cmd.take_action(parsed_args)

    mock_handle.assert_called_once_with(mock_delay.return_value, True, "log", 60)
