# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism container`` command.

``Run`` executes ``docker`` commands on a remote host via SSH, either from
the command line (one-shot) or from an interactive prompt loop.
"""

from unittest.mock import patch

import pytest

from osism.commands import container

from ._helpers import parse_args


def _run(args, *, prompt_side_effect=None, known_hosts=True):
    cmd, parsed_args = parse_args(container.Run, args)

    with patch("osism.commands.container.subprocess.call") as mock_call, patch(
        "osism.commands.container.ensure_known_hosts_file", return_value=known_hosts
    ), patch(
        "osism.commands.container.prompt", side_effect=prompt_side_effect
    ) as mock_prompt, patch(
        "osism.commands.container.settings.OPERATOR_USER", "testuser"
    ):
        cmd.take_action(parsed_args)

    return mock_call, mock_prompt


def _ssh_command(mock_call):
    """Flatten the ``subprocess.call`` invocation to a single command string.

    The tests assert only the observable contract (ssh target and docker
    command), so they hold whether the command is passed as a shell string or
    as an argv vector.
    """
    command = mock_call.call_args[0][0]
    return command if isinstance(command, str) else " ".join(command)


def test_parser_splits_host_and_remainder_command():
    _, parsed_args = parse_args(container.Run, ["node1", "ps", "-a"])
    assert parsed_args.host == ["node1"]
    assert parsed_args.command == ["ps", "-a"]


def test_one_shot_command_runs_docker_via_ssh():
    mock_call, mock_prompt = _run(["node1", "ps", "-a"])

    mock_prompt.assert_not_called()
    mock_call.assert_called_once()
    ssh_command = _ssh_command(mock_call)
    assert "testuser@node1" in ssh_command
    assert ssh_command.endswith("docker ps -a")


def test_known_hosts_failure_warns_but_still_connects(loguru_logs):
    mock_call, _ = _run(["node1", "ps"], known_hosts=False)

    assert any(
        record["level"] == "WARNING" and "/share/known_hosts" in record["message"]
        for record in loguru_logs
    )
    mock_call.assert_called_once()


def test_interactive_prompt_runs_commands_until_exit():
    mock_call, mock_prompt = _run(["node1"], prompt_side_effect=["ps", "exit"])

    assert mock_prompt.call_count == 2
    mock_call.assert_called_once()
    ssh_command = _ssh_command(mock_call)
    assert "testuser@node1" in ssh_command
    assert ssh_command.endswith("docker ps")


@pytest.mark.parametrize("keyword", ["Exit", "exit", "EXIT"])
def test_interactive_exit_keywords_break_immediately(keyword):
    mock_call, mock_prompt = _run(["node1"], prompt_side_effect=[keyword])

    mock_prompt.assert_called_once()
    mock_call.assert_not_called()
