# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for the ``osism.commands`` unit tests.

The command tests all instantiate a cliff command, parse a small argument
vector and - for the scheduling and service commands - assert that the task
lock is consulted before any work is dispatched. These helpers centralize
those recurring steps so the individual tests stay focused on behavior.
"""

from unittest.mock import MagicMock


def make_command(command_class):
    """Instantiate a cliff command with a mocked app and command namespace."""
    return command_class(MagicMock(), MagicMock())


def parse_args(command_class, args):
    """Build ``command_class`` and parse ``args`` with its own parser.

    Returns the ``(command, parsed_args)`` pair; parser-only tests discard the
    command, while ``take_action`` tests drive it afterwards.
    """
    cmd = make_command(command_class)
    return cmd, cmd.get_parser("test").parse_args(args)


def assert_not_called_before_lock_check(guarded_mock):
    """Return a ``check_task_lock_and_exit`` side effect that enforces ordering.

    Scheduling and service commands must consult the task lock *before* they
    schedule a Celery task or spawn a subprocess. Install the returned callable
    as the mocked ``check_task_lock_and_exit`` side effect; it fails the test if
    ``guarded_mock`` has already run by the time the lock is checked.
    """
    return lambda *args, **kwargs: guarded_mock.assert_not_called()
