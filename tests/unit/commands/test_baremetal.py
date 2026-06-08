# SPDX-License-Identifier: Apache-2.0

from unittest.mock import MagicMock, patch

import pytest

from osism.commands import baremetal

# Each of these command classes follows the identical pattern: when the
# requested node cannot be found, the command logs a warning and must return
# a non-zero exit code so a failed lookup is not reported as success.
NOT_FOUND_COMMANDS = [
    baremetal.BaremetalDeploy,
    baremetal.BaremetalUndeploy,
    baremetal.BaremetalBurnIn,
    baremetal.BaremetalClean,
    baremetal.BaremetalProvide,
    baremetal.BaremetalMaintenanceSet,
    baremetal.BaremetalMaintenanceUnset,
    baremetal.BaremetalPowerOn,
    baremetal.BaremetalPowerOff,
    baremetal.BaremetalDelete,
]


def _run_not_found(cls):
    cmd = cls(MagicMock(), MagicMock())
    # Select the single-node path by naming one node (and not using --all).
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    conn = MagicMock()
    conn.baremetal.find_node.return_value = None

    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


@pytest.mark.parametrize("cls", NOT_FOUND_COMMANDS)
def test_node_not_found_returns_1(cls):
    assert _run_not_found(cls) == 1
