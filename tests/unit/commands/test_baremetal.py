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


# --- BaremetalDump failure paths ---


def test_dump_ironic_node_not_found_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1", "--ironic"])

    conn = MagicMock()
    conn.baremetal.find_node.return_value = None

    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        assert cmd.take_action(parsed_args) == 1


def test_dump_netbox_unavailable_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        assert cmd.take_action(parsed_args) == 1


def test_dump_device_not_found_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None
    fake_nb.dcim.devices.filter.return_value = []

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1


# --- BaremetalPing failure paths ---


def test_ping_netbox_unavailable_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        assert cmd.take_action(parsed_args) == 1


def test_ping_device_not_found_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1


def test_ping_exception_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.side_effect = Exception("boom")

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1
