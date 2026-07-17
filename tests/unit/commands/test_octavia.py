# SPDX-License-Identifier: Apache-2.0

"""Tests for the amphora wait helpers in ``osism.commands.octavia``.

Both helpers poll the load-balancer API until no amphora is left in the
transitional state, sleeping between polls and giving up after a fixed
timeout. ``sleep`` is patched so the timeout paths run instantly.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from osism.commands import octavia

# (wait helper, transitional status queried, timeout / sleep iterations)
WAIT_CASES = [
    pytest.param(octavia.wait_for_amphora_boot, "BOOTING", 24, id="boot"),
    pytest.param(octavia.wait_for_amphora_delete, "PENDING_DELETE", 12, id="delete"),
]


@pytest.mark.parametrize("wait, status, max_iterations", WAIT_CASES)
def test_returns_without_sleeping_when_no_amphorae(wait, status, max_iterations):
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = []

    with patch("osism.commands.octavia.sleep") as mock_sleep:
        wait(conn, "lb-1")

    conn.load_balancer.amphorae.assert_called_once_with(
        loadbalancer_id="lb-1", status=status
    )
    mock_sleep.assert_not_called()


@pytest.mark.parametrize("wait, status, max_iterations", WAIT_CASES)
def test_polls_until_no_amphorae_remain(wait, status, max_iterations):
    conn = MagicMock()
    amphora = MagicMock()
    conn.load_balancer.amphorae.side_effect = [[amphora], [amphora], []]

    with patch("osism.commands.octavia.sleep") as mock_sleep:
        wait(conn, "lb-1")

    assert (
        conn.load_balancer.amphorae.call_args_list
        == [call(loadbalancer_id="lb-1", status=status)] * 3
    )
    assert mock_sleep.call_args_list == [call(5), call(5)]


@pytest.mark.parametrize("wait, status, max_iterations", WAIT_CASES)
def test_gives_up_after_timeout(wait, status, max_iterations):
    conn = MagicMock()
    conn.load_balancer.amphorae.return_value = [MagicMock()]

    with patch("osism.commands.octavia.sleep") as mock_sleep:
        wait(conn, "lb-1")

    assert conn.load_balancer.amphorae.call_count == max_iterations
    assert mock_sleep.call_count == max_iterations
