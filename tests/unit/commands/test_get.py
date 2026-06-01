# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism get`` commands.

These focus on the exit-code contract: a command must return a non-zero exit
status when the underlying query cannot be run (e.g. the inventory cannot be
loaded), but must keep returning success when the query runs fine and simply
yields an empty result.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

from osism.commands import get


def _make(cls):
    return cls(MagicMock(), MagicMock())


# --- Hosts.take_action ---


def test_hosts_returns_nonzero_when_inventory_cannot_be_loaded():
    cmd = _make(get.Hosts)
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ansible-inventory"),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_hosts_returns_success_for_empty_inventory():
    cmd = _make(get.Hosts)
    parsed_args = cmd.get_parser("test").parse_args([])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"_meta": {"hostvars": {}}}).encode(),
    ), patch(
        "osism.commands.get.get_hosts_from_inventory", return_value=[]
    ):
        result = cmd.take_action(parsed_args)

    assert not result


# --- Hostvars.take_action ---


def test_hostvars_returns_nonzero_when_inventory_query_fails():
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        side_effect=subprocess.CalledProcessError(1, "ansible-inventory"),
    ):
        result = cmd.take_action(parsed_args)

    assert result == 1


def test_hostvars_returns_success_when_variable_absent_from_result():
    cmd = _make(get.Hostvars)
    parsed_args = cmd.get_parser("test").parse_args(["somehost", "missingvar"])

    with patch(
        "osism.commands.get.get_inventory_path",
        return_value="/ansible/inventory/hosts.yml",
    ), patch(
        "osism.commands.get.subprocess.check_output",
        return_value=json.dumps({"present": "value"}).encode(),
    ):
        result = cmd.take_action(parsed_args)

    assert not result
