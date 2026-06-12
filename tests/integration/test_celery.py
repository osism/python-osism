# SPDX-License-Identifier: Apache-2.0

"""Celery round-trip and worker-visibility integration tests.

These validate the broker, queue routing (``osism-ansible``), worker and result
backend end-to-end against a live Redis and a worker started from the same
virtualenv.
"""

import pytest

pytestmark = pytest.mark.integration


def test_noop_round_trip(celery_worker):
    """Dispatching ``noop`` returns ``True`` through the result backend.

    A single round-trip exercises the broker, the ``osism-ansible`` queue
    routing, the worker and the result backend.
    """
    from osism.tasks import ansible

    result = ansible.noop.delay()

    assert result.get(timeout=60) is True


def test_worker_is_visible(celery_worker):
    """``app.control.inspect().ping()`` sees the running worker.

    This is the mechanism behind ``osism get status workers``: a fresh Celery
    client configured from ``Config`` inspects the worker over the broker. The
    ``celery_worker`` fixture starts it as ``ci-worker@<hostname>``.
    """
    from celery import Celery

    from osism.tasks import Config

    app = Celery("status")
    app.config_from_object(Config)

    replies = app.control.inspect().ping()

    assert replies
    assert any(name.startswith("ci-worker@") for name in replies)
