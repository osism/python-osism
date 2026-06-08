# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism report`` commands.

These focus on the exit-code contract when loading the Ansible inventory: a
command must return a non-zero exit status when the inventory query itself
cannot be run (a non-zero ansible-inventory return code, or a timeout), but
must keep returning success when the query runs fine and simply yields no
hosts.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import report

COMMANDS = [report.Memory, report.Lldp, report.Bgp, report.Status]

# Status requires a positional "type"; the others take no required args.
ARGS = {report.Status: ["bootstrap"]}


def _make(cls):
    cmd = cls(MagicMock(), MagicMock())
    return cmd, cmd.get_parser("test").parse_args(ARGS.get(cls, []))


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_nonzero_when_inventory_load_fails(cls):
    cmd, parsed_args = _make(cls)
    failed = MagicMock()
    failed.returncode = 1

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run", return_value=failed
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_nonzero_when_inventory_load_times_out(cls):
    cmd, parsed_args = _make(cls)

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run",
        side_effect=subprocess.TimeoutExpired("ansible-inventory", 30),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


@pytest.mark.parametrize("cls", COMMANDS)
def test_returns_success_when_inventory_is_empty(cls):
    cmd, parsed_args = _make(cls)
    ok = MagicMock()
    ok.returncode = 0
    ok.stdout = "{}"

    with patch(
        "osism.commands.report.ensure_known_hosts_file", return_value=True
    ), patch(
        "osism.commands.report.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.report.subprocess.run", return_value=ok
    ), patch(
        "osism.commands.report.get_hosts_from_inventory", return_value=[]
    ):
        result = cmd.take_action(parsed_args)

    assert not result
