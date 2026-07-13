# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism task revoke`` command.

``Revoke`` is a thin wrapper around the Celery control API: it builds an app
from ``osism.tasks.Config`` and revokes the given task with termination.
"""

from unittest.mock import patch

from osism.commands import task

from ._helpers import parse_args


def test_parser_task_is_a_one_element_list():
    _, parsed_args = parse_args(task.Revoke, ["abc"])
    assert parsed_args.task == ["abc"]


def test_revoke_terminates_task_by_id():
    from osism.tasks import Config

    cmd, parsed_args = parse_args(task.Revoke, ["abc"])

    with patch("celery.Celery") as mock_celery:
        cmd.take_action(parsed_args)

    mock_celery.assert_called_once_with("task")
    app = mock_celery.return_value
    app.config_from_object.assert_called_once_with(Config)
    app.control.revoke.assert_called_once_with("abc", terminate=True)
