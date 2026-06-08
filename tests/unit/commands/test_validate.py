# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism validate`` commands.

These focus on the exit-code contract: ``_handle_task`` is what ``take_action``
returns, so a timeout while waiting for task output must yield a non-zero exit
status rather than an implicit ``None`` (exit 0).
"""

from unittest.mock import MagicMock, patch

from osism.commands import validate


def test_handle_task_returns_nonzero_on_timeout():
    cmd = validate.Run(MagicMock(), MagicMock())
    task = MagicMock()

    with patch(
        "osism.commands.validate.utils.fetch_task_output",
        side_effect=TimeoutError,
    ):
        result = cmd._handle_task(
            task, wait=True, format="log", timeout=1, playbook="validate-x"
        )

    assert result == 1
