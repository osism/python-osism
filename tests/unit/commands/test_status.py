# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism status`` commands.

A request for an unknown resource type is invalid input and must yield a
non-zero exit status rather than falling through to an implicit success.
"""

import argparse
from unittest.mock import MagicMock, patch

from osism.commands import status


def test_run_returns_1_for_unknown_resource_type():
    cmd = status.Run(MagicMock(), MagicMock())
    parsed_args = argparse.Namespace(type=["bogus"])

    with patch("celery.Celery"):
        result = cmd.take_action(parsed_args)

    assert result == 1
