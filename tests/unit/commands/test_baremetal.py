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


# --- Argument-validation failure paths ---
#
# These commands validate their arguments at the very top of take_action,
# before any cloud setup. When neither a node name nor --all is given (or, for
# the power commands, when no node name is given) the command must report a
# non-zero exit code rather than silently succeeding. No mocking is required
# because the validation branch returns before any infrastructure access.
MISSING_NODE_COMMANDS = [
    baremetal.BaremetalDeploy,
    baremetal.BaremetalUndeploy,
    baremetal.BaremetalBurnIn,
    baremetal.BaremetalClean,
    baremetal.BaremetalProvide,
    baremetal.BaremetalPowerOn,
    baremetal.BaremetalPowerOff,
    baremetal.BaremetalDelete,
]


@pytest.mark.parametrize("cls", MISSING_NODE_COMMANDS)
def test_missing_node_argument_returns_1(cls):
    cmd = cls(MagicMock(), MagicMock())
    # Neither a node name nor --all: the argument-validation branch fires.
    parsed_args = cmd.get_parser("test").parse_args([])
    assert cmd.take_action(parsed_args) == 1


def test_burnin_no_stressor_returns_1():
    cmd = baremetal.BaremetalBurnIn(MagicMock(), MagicMock())
    # Select a node so the node check passes, but disable every stressor so the
    # "at least one stressor" validation branch fires before any cloud setup.
    parsed_args = cmd.get_parser("test").parse_args(
        ["node1", "--no-cpu", "--no-memory", "--no-disk"]
    )
    assert cmd.take_action(parsed_args) == 1


# When --all is requested for a destructive operation without the
# --yes-i-really-really-mean-it confirmation, the command refuses to proceed
# and must return a non-zero exit code rather than reporting success. The
# confirmation guard runs before any cloud setup, so no mocking is needed.


def test_deploy_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalDeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all", "--rebuild"])
    assert cmd.take_action(parsed_args) == 1


def test_undeploy_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalUndeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1


def test_clean_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalClean(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1


def test_delete_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalDelete(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1
