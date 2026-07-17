# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism compose`` command.

``Run`` wraps a remote ``docker compose`` invocation in an SSH call to the
operator user on the target host. These tests pin the exact command string
that is executed - including the ``UserKnownHostsFile`` option and the
``/opt/<environment>`` project directory. A strict xfail pins the corrected
space-separated joining of multi-token remainder arguments, which is
currently mangled by ``"".join`` (``up -d`` becomes ``up-d``). A failed
known_hosts initialization must only warn; the SSH attempt is still made.
"""

from unittest.mock import patch

import pytest

from osism import settings
from osism.commands import compose
from osism.commands.compose import KNOWN_HOSTS_PATH

from ._helpers import parse_args


def _run_compose(args, *, known_hosts=True):
    cmd, parsed_args = parse_args(compose.Run, args)

    with patch("osism.commands.compose.subprocess.call") as mock_call, patch(
        "osism.commands.compose.ensure_known_hosts_file", return_value=known_hosts
    ):
        cmd.take_action(parsed_args)

    return mock_call


def test_run_builds_ssh_docker_compose_command():
    mock_call = _run_compose(["testhost", "production", "ps"])

    expected = (
        "/usr/bin/ssh -i /ansible/secrets/id_rsa.operator "
        "-o StrictHostKeyChecking=no -o LogLevel=ERROR "
        f"-o UserKnownHostsFile={KNOWN_HOSTS_PATH} "
        f"{settings.OPERATOR_USER}@testhost "
        "'docker compose --project-directory=/opt/production ps'"
    )
    mock_call.assert_called_once_with(expected, shell=True)


@pytest.mark.xfail(
    strict=True,
    reason="compose.py joins the remainder arguments with '\"\".join', so any "
    "multi-token subcommand is mangled into an unrunnable command ('up -d' "
    "becomes 'up-d'); needs '\" \".join'",
)
def test_run_joins_remainder_arguments_with_spaces():
    mock_call = _run_compose(["testhost", "production", "up", "-d"])

    command = mock_call.call_args[0][0]
    assert "'docker compose --project-directory=/opt/production up -d'" in command


def test_run_warns_but_still_connects_when_known_hosts_init_fails(loguru_logs):
    mock_call = _run_compose(["testhost", "production", "ps"], known_hosts=False)

    mock_call.assert_called_once()
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any(f"Could not initialize {KNOWN_HOSTS_PATH}" in m for m in warnings)
