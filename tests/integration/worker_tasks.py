# SPDX-License-Identifier: Apache-2.0

"""Test-only Celery tasks registered on the ``ansible`` app.

None of the production tasks on the ``ansible`` app raises deliberately or
blocks, so the lifecycle tests (failure propagation, ``STARTED`` tracking,
revocation) register their own tasks here. The ``celery_worker`` fixture
starts the worker with ``--include=tests.integration.worker_tasks`` so the
worker process knows them; a task defined inside a test file would only exist
in the pytest process.

The explicit ``osism.tasks.ansible.*`` names matter: ``Config.task_routes``
routes by that pattern onto the ``osism-ansible`` queue the worker consumes.
With their auto-generated names (``tests.integration.worker_tasks.*``) the
tasks would land on the ``default`` queue and never run.
"""

import time

from osism.tasks.ansible import app

# Hard time limit for ``itest_block``, in seconds. The revoke test dispatches it
# with a duration long enough to never race the task's natural end; should that
# test fail before issuing the revoke, this bound keeps the blocked task from
# occupying the single-concurrency worker for the rest of the session. Chosen
# well above the time a test may wait for a state transition, so it never
# preempts a revoke.
BLOCK_TIME_LIMIT = 60


@app.task(name="osism.tasks.ansible.itest_fail")
def itest_fail(message):
    raise RuntimeError(message)


@app.task(name="osism.tasks.ansible.itest_block", time_limit=BLOCK_TIME_LIMIT)
def itest_block(seconds):
    time.sleep(seconds)
    return seconds
