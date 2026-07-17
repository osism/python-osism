# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism log`` commands.

``Ansible`` shells out to ``ara``, ``Container`` wraps ``docker logs`` in an
SSH call, and ``File`` tails a file below ``/var/log`` either via clush (for
inventory groups with multiple hosts) or via a direct SSH connection. These
tests pin the constructed command lines, the path-traversal guard and its
exit code, the shell quoting of the resolved path, and the pass-through of
non-zero clush/ssh return codes. ``Opensearch`` runs an interactive query
loop against the OpenSearch SQL plugin; its output formats (payload-only,
verbose with ``@timestamp`` fallback, raw response without hits) are pinned
via ``capsys``.
"""

import json
from unittest.mock import patch

from osism import settings
from osism.commands import log
from osism.commands.log import KNOWN_HOSTS_PATH

from ._helpers import parse_args

# --- Ansible.take_action ---


def test_ansible_appends_joined_parameters_to_ara():
    cmd, parsed_args = parse_args(log.Ansible, ["result", "list"])

    with patch("osism.commands.log.subprocess.call") as mock_call:
        cmd.take_action(parsed_args)

    mock_call.assert_called_once_with("/usr/local/bin/ara result list", shell=True)


# --- Container.take_action ---


def _run_container(args, *, known_hosts=True):
    cmd, parsed_args = parse_args(log.Container, args)

    with patch("osism.commands.log.subprocess.call") as mock_call, patch(
        "osism.commands.log.ensure_known_hosts_file", return_value=known_hosts
    ):
        cmd.take_action(parsed_args)

    return mock_call


def test_container_builds_docker_logs_ssh_command():
    mock_call = _run_container(["testhost", "nova_compute", "--tail", "50"])

    command = mock_call.call_args[0][0]
    assert mock_call.call_args.kwargs == {"shell": True}
    assert f"{settings.OPERATOR_USER}@testhost" in command
    assert f"UserKnownHostsFile={KNOWN_HOSTS_PATH}" in command
    assert command.endswith("docker logs --tail 50 nova_compute")


def test_container_warns_but_still_connects_when_known_hosts_init_fails(loguru_logs):
    mock_call = _run_container(["testhost", "nova_compute"], known_hosts=False)

    mock_call.assert_called_once()
    warnings = [r["message"] for r in loguru_logs if r["level"] == "WARNING"]
    assert any(f"Could not initialize {KNOWN_HOSTS_PATH}" in m for m in warnings)


# --- File.take_action ---


def _run_file(args, *, group_hosts, call_rc=0, resolved="192.0.2.1"):
    cmd, parsed_args = parse_args(log.File, args)

    with patch(
        "osism.commands.log.get_hosts_from_group", return_value=group_hosts
    ), patch(
        "osism.commands.log.resolve_host_with_fallback", return_value=resolved
    ) as mock_resolve, patch(
        "osism.commands.log.subprocess.call", return_value=call_rc
    ) as mock_call, patch(
        "osism.commands.log.ensure_known_hosts_file", return_value=True
    ):
        result = cmd.take_action(parsed_args)

    return result, mock_call, mock_resolve


def test_file_rejects_path_traversal_outside_var_log(loguru_logs):
    result, mock_call, _ = _run_file(["testhost", "../../etc/passwd"], group_hosts=[])

    assert result == 1
    mock_call.assert_not_called()
    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("must stay within /var/log" in m for m in errors)


def test_file_accepts_nested_path_below_var_log():
    result, mock_call, _ = _run_file(
        ["testhost", "kolla/nova/nova-compute.log"], group_hosts=[]
    )

    assert result == 0
    tail_command = mock_call.call_args[0][0][-1]
    assert tail_command == "tail -n 100 /var/log/kolla/nova/nova-compute.log"


def test_file_tail_command_includes_lines_and_follow_flag():
    _, mock_call, _ = _run_file(
        ["testhost", "syslog", "--follow", "--lines", "500"], group_hosts=[]
    )

    tail_command = mock_call.call_args[0][0][-1]
    assert tail_command == "tail -n 500 -f /var/log/syslog"


def test_file_shell_quotes_resolved_path():
    _, mock_call, _ = _run_file(["testhost", "nova/instance name.log"], group_hosts=[])

    tail_command = mock_call.call_args[0][0][-1]
    assert tail_command == "tail -n 100 '/var/log/nova/instance name.log'"


def test_file_uses_clush_for_group_with_multiple_hosts():
    result, mock_call, mock_resolve = _run_file(
        ["ctl", "syslog"], group_hosts=["host1", "host2"]
    )

    assert result == 0
    mock_resolve.assert_not_called()
    mock_call.assert_called_once_with(
        [
            "/usr/local/bin/clush",
            "-l",
            settings.OPERATOR_USER,
            "-w",
            "host1,host2",
            "tail -n 100 /var/log/syslog",
        ]
    )


def test_file_passes_through_clush_return_code(loguru_logs):
    result, _, _ = _run_file(
        ["ctl", "syslog"], group_hosts=["host1", "host2"], call_rc=3
    )

    assert result == 3
    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("clush log tailing failed" in m for m in errors)


def test_file_substitutes_single_group_host_and_uses_ssh():
    result, mock_call, mock_resolve = _run_file(
        ["ctl", "syslog"], group_hosts=["ctl001"]
    )

    assert result == 0
    mock_resolve.assert_called_once_with("ctl001")
    assert mock_call.call_args[0][0][0] == "/usr/bin/ssh"


def test_file_resolves_non_group_host_for_ssh():
    result, mock_call, mock_resolve = _run_file(
        ["testhost", "syslog"], group_hosts=[], resolved="192.0.2.10"
    )

    assert result == 0
    mock_resolve.assert_called_once_with("testhost")
    mock_call.assert_called_once_with(
        [
            "/usr/bin/ssh",
            "-i",
            "/ansible/secrets/id_rsa.operator",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "LogLevel=ERROR",
            "-o",
            f"UserKnownHostsFile={KNOWN_HOSTS_PATH}",
            f"{settings.OPERATOR_USER}@192.0.2.10",
            "tail -n 100 /var/log/syslog",
        ]
    )


def test_file_passes_through_ssh_return_code(loguru_logs):
    result, _, _ = _run_file(["testhost", "syslog"], group_hosts=[], call_rc=5)

    assert result == 5
    errors = [r["message"] for r in loguru_logs if r["level"] == "ERROR"]
    assert any("ssh log tailing failed" in m for m in errors)


# --- Opensearch.take_action ---


def _run_opensearch(args, prompts, response_data=None):
    cmd, parsed_args = parse_args(log.Opensearch, args)

    with patch("osism.commands.log.PromptSession") as mock_session_cls, patch(
        "osism.commands.log.requests.post"
    ) as mock_post:
        mock_session_cls.return_value.prompt.side_effect = prompts
        if response_data is not None:
            mock_post.return_value.json.return_value = response_data
        cmd.take_action(parsed_args)

    return mock_post


def test_opensearch_exit_breaks_loop_without_query():
    mock_post = _run_opensearch([], ["exit"])

    mock_post.assert_not_called()


def test_opensearch_prints_payload_for_each_hit(capsys):
    data = {
        "hits": {
            "hits": [
                {"_source": {"Payload": "line one"}},
                {"_source": {"Payload": "line two"}},
            ]
        }
    }

    mock_post = _run_opensearch([], ["SELECT * FROM logs", "exit"], data)

    assert capsys.readouterr().out == "line one\nline two\n"
    request_body = json.loads(mock_post.call_args.kwargs["data"])
    assert request_body == {"query": "SELECT * FROM logs"}
    assert mock_post.call_args.kwargs["verify"] is False


def test_opensearch_verbose_prints_metadata_with_timestamp_fallback(capsys):
    data = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "timestamp": "2026-01-01T00:00:00",
                        "Hostname": "ctl001",
                        "programname": "nova-api",
                        "Payload": "request done",
                    }
                },
                {
                    "_source": {
                        "@timestamp": "2026-01-02T00:00:00",
                        "Hostname": "ctl002",
                        "Payload": "booted",
                    }
                },
            ]
        }
    }

    _run_opensearch(["--verbose"], ["SELECT * FROM logs", "exit"], data)

    assert capsys.readouterr().out == (
        "2026-01-01T00:00:00 | ctl001 | nova-api | request done\n"
        "2026-01-02T00:00:00 | ctl002 | booted\n"
    )


def test_opensearch_prints_raw_response_without_hits(capsys):
    data = {"error": "no permissions"}

    _run_opensearch([], ["SELECT 1", "exit"], data)

    assert capsys.readouterr().out == "{'error': 'no permissions'}\n"
