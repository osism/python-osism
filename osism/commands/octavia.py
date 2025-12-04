# SPDX-License-Identifier: Apache-2.0

"""Common utilities for Octavia loadbalancer and amphora management."""

from time import sleep

from loguru import logger

# Timing constants for waiting on amphora operations
SLEEP_WAIT_FOR_AMPHORA_BOOT = 5
TIMEOUT_WAIT_FOR_AMPHORA_BOOT = 120

SLEEP_WAIT_FOR_AMPHORA_DELETE = 5
TIMEOUT_WAIT_FOR_AMPHORA_DELETE = 60


def wait_for_amphora_boot(conn, loadbalancer_id):
    """Wait for all amphorae of a loadbalancer to finish booting.

    Args:
        conn: OpenStack connection object
        loadbalancer_id: ID of the loadbalancer to wait for
    """
    logger.info(
        f"Wait up to {TIMEOUT_WAIT_FOR_AMPHORA_BOOT} seconds for amphora boot of loadbalancer {loadbalancer_id}"
    )

    iterations = TIMEOUT_WAIT_FOR_AMPHORA_BOOT / SLEEP_WAIT_FOR_AMPHORA_BOOT

    while iterations > 0:
        amphorae = conn.load_balancer.amphorae(
            loadbalancer_id=loadbalancer_id, status="BOOTING"
        )
        if not list(amphorae):
            break
        iterations -= 1
        sleep(SLEEP_WAIT_FOR_AMPHORA_BOOT)


def wait_for_amphora_delete(conn, loadbalancer_id):
    """Wait for all amphorae of a loadbalancer to finish deletion.

    Args:
        conn: OpenStack connection object
        loadbalancer_id: ID of the loadbalancer to wait for
    """
    logger.info(
        f"Wait up to {TIMEOUT_WAIT_FOR_AMPHORA_DELETE} seconds for amphora delete of loadbalancer {loadbalancer_id}"
    )

    iterations = TIMEOUT_WAIT_FOR_AMPHORA_DELETE / SLEEP_WAIT_FOR_AMPHORA_DELETE

    while iterations > 0:
        amphorae = conn.load_balancer.amphorae(
            loadbalancer_id=loadbalancer_id, status="PENDING_DELETE"
        )
        if not list(amphorae):
            break
        iterations -= 1
        sleep(SLEEP_WAIT_FOR_AMPHORA_DELETE)
