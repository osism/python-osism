# SPDX-License-Identifier: Apache-2.0

"""Fixtures and skip logic shared by the Celery/Redis integration tests.

These tests exercise the real task-processing core (broker, queue routing,
worker, result backend, Redis streams and distributed locks) against a live
Redis. They are skipped automatically when Redis is not reachable -- for
example during a local ``pytest`` run without the service -- so the suite stays
green outside the dedicated CI job.
"""

import os
import subprocess
import time

import pytest

from osism import settings

# Only the ``ansible`` Celery app is used as worker: it has no import-time
# dependency on NetBox, OpenStack or ansible-core, unlike the other task
# modules. ``osism.tasks.ansible.*`` is routed to the ``osism-ansible`` queue.
WORKER_APP = "osism.tasks.ansible"
WORKER_QUEUE = "osism-ansible"
# Celery treats a ``-n`` value without ``@`` as the host part (yielding
# ``celery@ci-worker``), so the node name must be given explicitly.
WORKER_NAME = "ci-worker@%h"
# Node-name prefix the worker registers under (``ci-worker@<hostname>``). Used
# to gate readiness on *this* worker rather than any worker on the broker.
WORKER_NODE_PREFIX = WORKER_NAME.split("@", 1)[0] + "@"
WORKER_BOOT_TIMEOUT = 60


def _require_redis():
    """Return ``True`` when an unreachable Redis must fail the session.

    Set ``OSISM_REQUIRE_REDIS=1`` (as the CI job does) to turn the
    skip-when-unreachable behaviour into a hard failure, so a Redis-startup
    problem surfaces as a red job instead of an all-skipped green one. Left
    unset locally, the suite keeps skipping when Redis is not running.
    """
    return os.environ.get("OSISM_REQUIRE_REDIS", "").lower() not in (
        "",
        "0",
        "false",
        "no",
    )


def _redis_reachable():
    """Return ``True`` when the configured Redis answers a ping."""
    try:
        from redis import Redis

        client = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_connect_timeout=1,
        )
        try:
            client.ping()
        finally:
            client.close()
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Skip integration-marked tests when Redis is not reachable.

    With ``OSISM_REQUIRE_REDIS`` set, an unreachable Redis fails the session
    instead -- otherwise an all-skipped run exits 0 and a broken Redis would
    pass the CI gate green.
    """
    if _redis_reachable():
        return
    reason = f"Redis is not reachable on {settings.REDIS_HOST}:{settings.REDIS_PORT}"
    if _require_redis():
        pytest.exit(f"{reason} but OSISM_REQUIRE_REDIS is set", returncode=1)
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def celery_app():
    """The ``ansible`` Celery app, configured from the live broker URL."""
    from osism.tasks import ansible

    return ansible.app


@pytest.fixture(scope="session")
def celery_worker(celery_app):
    """Start a Celery worker for the ``osism-ansible`` queue for the session.

    The worker runs from the same virtualenv as the tests.
    ``GATHER_FACTS_SCHEDULE=0`` prevents registration of the periodic
    ``gather_facts`` task, which would try to run ``/run.sh`` in containers that
    do not exist in CI.
    """
    proc = subprocess.Popen(
        [
            "celery",
            "-A",
            WORKER_APP,
            "worker",
            "-n",
            WORKER_NAME,
            "-Q",
            WORKER_QUEUE,
            "-c",
            "1",
        ],
        env={**os.environ, "GATHER_FACTS_SCHEDULE": "0"},
    )

    try:
        deadline = time.time() + WORKER_BOOT_TIMEOUT
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"Celery worker exited early with code {proc.returncode}"
                )
            # Gate on *this* worker, not any worker answering on the broker, so a
            # shared local broker cannot let the fixture pass before it is up.
            replies = celery_app.control.inspect().ping() or {}
            if any(name.startswith(WORKER_NODE_PREFIX) for name in replies):
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                f"Celery worker did not become ready within {WORKER_BOOT_TIMEOUT}s"
            )
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
