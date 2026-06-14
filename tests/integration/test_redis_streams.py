# SPDX-License-Identifier: Apache-2.0

"""Redis-streams task-output integration tests.

``push_task_output`` / ``finish_task_output`` / ``fetch_task_output`` are the
mechanism ``osism apply`` uses to stream task logs; they round-trip through a
Redis stream keyed by the task id and are testable with Redis alone.
"""

import uuid

import pytest

from osism import utils

pytestmark = pytest.mark.integration


def test_task_output_round_trip(capsys):
    """Output pushed to a task stream is read back with its return code."""
    task_id = f"itest-{uuid.uuid4()}"

    utils.push_task_output(task_id, "first line\n")
    utils.push_task_output(task_id, "second line\n")
    utils.finish_task_output(task_id, rc=3)

    rc = utils.fetch_task_output(task_id, timeout=10)

    assert rc == 3
    assert capsys.readouterr().out == "first line\nsecond line\n"
