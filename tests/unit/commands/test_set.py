# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism set`` commands.

``Maintenance`` and ``Bootstrap`` schedule the corresponding state playbook
with ``status=True`` for a single host; they differ only in the playbook
name.
"""

from unittest.mock import patch

import pytest

from osism.commands import set as set_cmd

from ._helpers import assert_not_called_before_lock_check, parse_args


@pytest.mark.parametrize(
    "command_class, playbook",
    [
        (set_cmd.Maintenance, "state-maintenance"),
        (set_cmd.Bootstrap, "state-bootstrap"),
    ],
)
def test_take_action_schedules_state_playbook(command_class, playbook):
    cmd, parsed_args = parse_args(command_class, ["node1"])

    with patch(
        "osism.commands.set.utils.check_task_lock_and_exit"
    ) as mock_check, patch("osism.tasks.ansible.run.delay") as mock_delay:
        mock_check.side_effect = assert_not_called_before_lock_check(mock_delay)
        cmd.take_action(parsed_args)

    mock_check.assert_called_once()
    mock_delay.assert_called_once_with(
        "generic", playbook, ["-e status=True", "-l node1"]
    )
