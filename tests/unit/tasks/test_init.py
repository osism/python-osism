# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the module-level helpers in :mod:`osism.tasks`.

Covers the shared Celery-worker foundation: the ``HOST_PATTERN`` regex, the
Celery ``Config`` class, ``get_container_version``, ``log_play_execution`` and
the two subprocess runners ``run_ansible_in_environment`` / ``run_command``,
plus the CLI-side ``handle_task`` wait/revoke helper. None of these are Celery
tasks, so they are called directly without a broker.

``Config.broker_url`` / ``Config.result_backend`` precedence and
``task_track_started`` are already pinned by ``test_config.py`` (which reloads
``osism.settings`` / ``osism.tasks`` to exercise the import-time resolution);
this module deliberately does not duplicate them and covers only the
environment-independent ``Config`` attributes. ``Config.enable_ironic`` is
likewise resolved from ``os.environ`` at import time, so asserting it here
would depend on the environment of the first import; that reload-based
pattern lives in ``test_config.py``.

Everything under test is accessed as a module attribute (``tasks.Config``,
``tasks.get_container_version``, ...) rather than imported by name, because
``test_config.py`` reloads ``osism.tasks`` and a name bound at import time could
otherwise go stale depending on test order.

Loguru output is invisible to pytest's ``caplog``; the ``loguru_logs`` fixture
from ``tests/conftest.py`` is used for every "warning/error logged" assertion.
"""

import json
import subprocess
from pathlib import Path as RealPath
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import osism.utils as utils_pkg
from osism import tasks


def make_process(lines, rc=0):
    """Return a fake ``subprocess.Popen`` driving the runner output loop.

    ``poll`` yields ``None`` once per line and then ``rc`` so the
    ``while p.poll() is None`` loop reads every line exactly once before it
    exits; ``wait`` returns the same code.
    """
    p = MagicMock()
    p.poll.side_effect = [None] * len(lines) + [rc]
    p.stdout.readline.side_effect = [line.encode() for line in lines]
    p.wait.return_value = rc
    return p


# ---------------------------------------------------------------------------
# HOST_PATTERN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line, host",
    [
        ("ok: [node-1]", "node-1"),
        ("changed: [host.example.com]", "host.example.com"),
        ("failed: [x]", "x"),
        ("skipping: [x]", "x"),
        ("unreachable: [x]", "x"),
        # Delegation: [^\]]+ captures the whole "src -> dst" string (pinned).
        ("ok: [node-1 -> 192.168.0.5]", "node-1 -> 192.168.0.5"),
    ],
)
def test_host_pattern_matches(line, host):
    match = tasks.HOST_PATTERN.match(line)
    assert match is not None
    assert match.group(2) == host


@pytest.mark.parametrize(
    "line",
    [
        # Ansible reports task failures as "fatal:", which the pattern does not
        # list -- documenting the known gap.
        "fatal: [node-1]: FAILED!",
        "TASK [Gathering Facts]",
        "ok:",
        "",
        # Leading whitespace: pattern is ^-anchored and the caller strips first.
        "  ok: [node-1]",
    ],
)
def test_host_pattern_no_match(line):
    assert tasks.HOST_PATTERN.match(line) is None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_static_flags():
    assert tasks.Config.task_default_queue == "default"
    assert tasks.Config.task_create_missing_queues is True
    assert tasks.Config.broker_connection_retry_on_startup is True
    assert tasks.Config.enable_utc is True


def test_config_task_routes_complete_mapping():
    assert tasks.Config.task_routes == {
        "osism.tasks.ansible.*": {"queue": "osism-ansible"},
        "osism.tasks.ceph.*": {"queue": "ceph-ansible"},
        "osism.tasks.conductor.*": {"queue": "conductor"},
        "osism.tasks.kolla.*": {"queue": "kolla-ansible"},
        "osism.tasks.kubernetes.*": {"queue": "kubernetes"},
        "osism.tasks.netbox.*": {"queue": "netbox"},
        "osism.tasks.openstack.*": {"queue": "openstack"},
        "osism.tasks.reconciler.*": {"queue": "reconciler"},
    }


# ---------------------------------------------------------------------------
# get_container_version
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_path(mocker, tmp_path):
    """Redirect the hardcoded absolute paths in ``osism.tasks`` into tmp_path.

    Both ``get_container_version`` (``/interface/versions/{worker}.yml``) and
    ``log_play_execution`` (``/share/ansible-execution-history.json``) build a
    ``Path`` from a literal path; keeping only the basename under ``tmp_path``
    lets the real YAML / JSON / ``fcntl`` code run against real temp files.
    """
    mocker.patch("osism.tasks.Path", new=lambda p: tmp_path / RealPath(p).name)
    return tmp_path


def test_get_container_version_missing_file_returns_unknown(patched_path, loguru_logs):
    assert tasks.get_container_version("osism-ansible") == "unknown"
    assert any(
        r["level"] == "DEBUG" and "Version file not found" in r["message"]
        for r in loguru_logs
    )


def test_get_container_version_reads_version(patched_path):
    (patched_path / "osism-ansible.yml").write_text('osism_ansible_version: "7.0.5a"\n')
    assert tasks.get_container_version("osism-ansible") == "7.0.5a"


@pytest.mark.parametrize(
    "worker, key",
    [
        ("kolla-ansible", "kolla_ansible_version"),
        ("ceph-ansible", "ceph_ansible_version"),
        ("osism-kubernetes", "osism_kubernetes_version"),
    ],
)
def test_get_container_version_key_derivation(patched_path, worker, key):
    (patched_path / f"{worker}.yml").write_text(f'{key}: "1.2.3"\n')
    assert tasks.get_container_version(worker) == "1.2.3"


def test_get_container_version_empty_string_returns_latest(patched_path):
    (patched_path / "osism-ansible.yml").write_text('osism_ansible_version: ""\n')
    assert tasks.get_container_version("osism-ansible") == "latest"


def test_get_container_version_key_missing_returns_unknown(patched_path):
    (patched_path / "osism-ansible.yml").write_text("some_other_key: 1\n")
    assert tasks.get_container_version("osism-ansible") == "unknown"


def test_get_container_version_empty_yaml_returns_unknown_and_warns(
    patched_path, loguru_logs
):
    # yaml.safe_load("") -> None, then None.get(...) raises AttributeError,
    # which the broad except catches.
    (patched_path / "osism-ansible.yml").write_text("")
    assert tasks.get_container_version("osism-ansible") == "unknown"
    assert any(r["level"] == "WARNING" for r in loguru_logs)


def test_get_container_version_invalid_yaml_returns_unknown_and_warns(
    patched_path, loguru_logs
):
    # An unterminated flow sequence raises yaml.YAMLError.
    (patched_path / "osism-ansible.yml").write_text("key: [unclosed\n")
    assert tasks.get_container_version("osism-ansible") == "unknown"
    assert any(r["level"] == "WARNING" for r in loguru_logs)


# ---------------------------------------------------------------------------
# log_play_execution
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_version(mocker):
    """Patch ``get_container_version`` (covered separately) to a fixed value."""
    return mocker.patch("osism.tasks.get_container_version", return_value="9.9.9")


def test_log_play_execution_appends_json_record(patched_path, patched_version):
    tasks.log_play_execution(
        request_id="req-1",
        worker="osism-ansible",
        environment="testbed",
        role="dummy-role",
        hosts=["node-1"],
        arguments="-l all",
        result="success",
    )

    log_file = patched_path / "ansible-execution-history.json"
    records = [json.loads(line) for line in log_file.read_text().splitlines()]
    assert len(records) == 1

    record = records[0]
    assert record["request_id"] == "req-1"
    assert record["worker"] == "osism-ansible"
    assert record["worker_version"] == "9.9.9"
    assert record["environment"] == "testbed"
    assert record["role"] == "dummy-role"
    assert record["hosts"] == ["node-1"]
    assert record["arguments"] == "-l all"
    assert record["result"] == "success"
    assert record["timestamp"].endswith("Z")


@pytest.mark.parametrize("arguments", [None, ""])
def test_log_play_execution_normalizes_hosts_and_arguments(
    patched_path, patched_version, arguments
):
    tasks.log_play_execution(
        request_id="req-1",
        worker="osism-ansible",
        environment="testbed",
        role="dummy-role",
        hosts=None,
        arguments=arguments,
        result="started",
    )

    log_file = patched_path / "ansible-execution-history.json"
    record = json.loads(log_file.read_text())
    assert record["hosts"] == []
    assert record["arguments"] == ""


def test_log_play_execution_two_calls_append_two_lines(patched_path, patched_version):
    for _ in range(2):
        tasks.log_play_execution(
            request_id="req-1",
            worker="osism-ansible",
            environment="testbed",
            role="dummy-role",
        )

    log_file = patched_path / "ansible-execution-history.json"
    assert len(log_file.read_text().splitlines()) == 2


def test_log_play_execution_creates_parent_directory(mocker, tmp_path, patched_version):
    mocker.patch(
        "osism.tasks.Path",
        new=lambda p: tmp_path / "history" / RealPath(p).name,
    )

    tasks.log_play_execution(
        request_id="req-1",
        worker="osism-ansible",
        environment="testbed",
        role="dummy-role",
    )

    log_file = tmp_path / "history" / "ansible-execution-history.json"
    assert log_file.exists()
    assert len(log_file.read_text().splitlines()) == 1


def test_log_play_execution_write_failure_warns_without_raising(
    patched_path, patched_version, mocker, loguru_logs
):
    mocker.patch("builtins.open", side_effect=OSError("read-only"))

    # No exception propagates.
    tasks.log_play_execution(
        request_id="req-1",
        worker="osism-ansible",
        environment="testbed",
        role="dummy-role",
    )

    assert any(
        r["level"] == "WARNING" and "Failed to log play execution" in r["message"]
        for r in loguru_logs
    )


# ---------------------------------------------------------------------------
# run_ansible_in_environment
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis(mocker):
    """Provide a fake ``utils.redis`` without opening a real connection.

    ``osism.utils.redis`` is a lazy attribute created by ``__getattr__`` on
    first access (which constructs a real ``Redis`` and pings it), so it is set
    directly in the module dict rather than via ``mocker.patch(..., create=True)``
    -- the latter would trigger ``__getattr__`` during mock setup.
    """
    redis = MagicMock()
    redis.get.return_value = None
    mocker.patch.dict(utils_pkg.__dict__, {"redis": redis})
    return redis


@pytest.fixture
def runner_mocks(mocker, tmp_path, mock_redis, monkeypatch):
    """Patch every external touchpoint of ``run_ansible_in_environment``."""
    monkeypatch.delenv("ANSIBLE_SSH_RETRIES", raising=False)
    monkeypatch.delenv("VAULT", raising=False)

    popen = mocker.patch("osism.tasks.subprocess.Popen")
    popen.return_value = make_process(["ok: [node-1]\n"])

    return SimpleNamespace(
        popen=popen,
        create_redlock=mocker.patch("osism.tasks.utils.create_redlock"),
        push=mocker.patch("osism.tasks.utils.push_task_output"),
        finish=mocker.patch("osism.tasks.utils.finish_task_output"),
        log_play=mocker.patch("osism.tasks.log_play_execution"),
        mkdtemp=mocker.patch(
            "osism.tasks.tempfile.mkdtemp", return_value=str(tmp_path / "ssh")
        ),
        rmtree=mocker.patch("osism.tasks.shutil.rmtree"),
        redis=mock_redis,
    )


def run_ansible(**kwargs):
    """Call ``run_ansible_in_environment`` with sensible test defaults."""
    params = {
        "request_id": "req-1",
        "worker": "osism-ansible",
        "environment": "testbed",
        "role": "dummy-role",
        "arguments": "-l all",
    }
    params.update(kwargs)
    return tasks.run_ansible_in_environment(**params)


# -- argument handling --


def test_run_ansible_list_arguments_joined(runner_mocks):
    run_ansible(arguments=["-e", "a=b", "-l", "all"])
    command = runner_mocks.popen.call_args.args[0]
    assert command.endswith("-e a=b -l all")


def test_run_ansible_string_arguments_passed_through(runner_mocks):
    run_ansible(arguments="-e a=b")
    command = runner_mocks.popen.call_args.args[0]
    assert command.endswith("-e a=b")


def test_run_ansible_tuple_arguments_not_joined(runner_mocks):
    # type(...) == list is an exact-type check: a tuple is not joined but
    # interpolated via its repr into the command string (pinned behavior).
    run_ansible(arguments=("-e", "a=b"))
    command = runner_mocks.popen.call_args.args[0]
    assert "('-e', 'a=b')" in command


def test_run_ansible_kolla_stop_appends_ignore_missing(runner_mocks):
    run_ansible(worker="kolla-ansible", arguments="-e kolla_action=stop")
    command = runner_mocks.popen.call_args.args[0]
    assert "-e kolla_action_stop_ignore_missing=true" in command


def test_run_ansible_kolla_stop_ignore_missing_not_duplicated(runner_mocks):
    args = "-e kolla_action=stop -e kolla_action_stop_ignore_missing=true"
    run_ansible(worker="kolla-ansible", arguments=args)
    command = runner_mocks.popen.call_args.args[0]
    assert command.count("kolla_action_stop_ignore_missing=true") == 1


def test_run_ansible_non_kolla_worker_stop_not_appended(runner_mocks):
    run_ansible(worker="osism-ansible", arguments="-e kolla_action=stop")
    command = runner_mocks.popen.call_args.args[0]
    assert "kolla_action_stop_ignore_missing" not in command


# -- environment construction --


def test_run_ansible_env_static_flags(runner_mocks):
    run_ansible()
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["ANSIBLE_FORCE_COLOR"] == "1"
    assert env["PY_COLORS"] == "1"
    assert env["PYTHONUNBUFFERED"] == "1"


def test_run_ansible_ssh_control_path_dir(runner_mocks, tmp_path):
    run_ansible()
    runner_mocks.mkdtemp.assert_called_once_with(prefix=".ansible-ssh-req-1-")
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["ANSIBLE_SSH_CONTROL_PATH_DIR"] == str(tmp_path / "ssh")


def test_run_ansible_ssh_retries_default(runner_mocks):
    run_ansible()
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["ANSIBLE_SSH_RETRIES"] == "3"


def test_run_ansible_ssh_retries_preset_not_overridden(runner_mocks, monkeypatch):
    monkeypatch.setenv("ANSIBLE_SSH_RETRIES", "7")
    run_ansible()
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["ANSIBLE_SSH_RETRIES"] == "7"


def test_run_ansible_sub_environment(runner_mocks):
    run_ansible(environment="manager.sub1")
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["SUB"] == "manager.sub1"
    assert env["ENVIRONMENT"] == "manager"
    assert "/run-manager.sh" in runner_mocks.popen.call_args.args[0]


def test_run_ansible_vault_env_set_when_password_present(runner_mocks):
    runner_mocks.redis.get.return_value = b"secret"
    run_ansible()
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert env["VAULT"] == "/ansible-vault.py"


def test_run_ansible_vault_env_absent_without_password(runner_mocks):
    runner_mocks.redis.get.return_value = None
    run_ansible()
    env = runner_mocks.popen.call_args.kwargs["env"]
    assert "VAULT" not in env


# -- worker dispatch --


def test_run_ansible_kolla_command(runner_mocks):
    run_ansible(worker="kolla-ansible", role="glance", arguments="-e x=y")
    call = runner_mocks.popen.call_args
    assert call.args[0] == "stdbuf -oL /run.sh deploy glance -e x=y"
    assert call.kwargs["shell"] is True


@pytest.mark.parametrize("role", ["mariadb-backup", "mariadb_backup"])
def test_run_ansible_kolla_mariadb_backup_rewrite(runner_mocks, role):
    run_ansible(worker="kolla-ansible", role=role, arguments="-e kolla_action=deploy")
    command = runner_mocks.popen.call_args.args[0]
    assert command == "stdbuf -oL /run.sh backup mariadb -e kolla_action=backup"


@pytest.mark.parametrize("worker", ["osism-kubernetes", "ceph-ansible"])
def test_run_ansible_run_sh_workers(runner_mocks, worker):
    run_ansible(worker=worker, role="site", arguments="-l all")
    command = runner_mocks.popen.call_args.args[0]
    assert command == "stdbuf -oL /run.sh site -l all"


def test_run_ansible_default_worker_uses_environment_script(runner_mocks):
    run_ansible(worker="osism-ansible", environment="testbed", role="site")
    command = runner_mocks.popen.call_args.args[0]
    assert command == "stdbuf -oL /run-testbed.sh site -l all"


# -- output loop, host extraction, logging --


def test_run_ansible_collects_output_and_streams_lines(runner_mocks):
    runner_mocks.popen.return_value = make_process(
        ["ok: [node-2]\n", "ok: [node-1]\n"], rc=0
    )
    result = run_ansible()
    assert result == "ok: [node-2]\nok: [node-1]\n"
    assert runner_mocks.push.call_count == 2
    runner_mocks.finish.assert_called_once_with("req-1", rc=0)


def test_run_ansible_logs_start_then_success_with_sorted_hosts(runner_mocks):
    runner_mocks.popen.return_value = make_process(
        ["ok: [node-2]\n", "ok: [node-1]\n"], rc=0
    )
    run_ansible()
    calls = runner_mocks.log_play.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["result"] == "started"
    assert calls[0].kwargs["hosts"] is None
    assert calls[1].kwargs["result"] == "success"
    assert calls[1].kwargs["hosts"] == ["node-1", "node-2"]


def test_run_ansible_nonzero_rc_logs_failure(runner_mocks):
    runner_mocks.popen.return_value = make_process(["ok: [node-1]\n"], rc=1)
    run_ansible()
    calls = runner_mocks.log_play.call_args_list
    assert calls[1].kwargs["result"] == "failure"
    runner_mocks.finish.assert_called_once_with("req-1", rc=1)


def test_run_ansible_duplicate_hosts_deduplicated(runner_mocks):
    runner_mocks.popen.return_value = make_process(
        ["ok: [node-1]\n", "changed: [node-1]\n"], rc=0
    )
    run_ansible()
    calls = runner_mocks.log_play.call_args_list
    assert calls[1].kwargs["hosts"] == ["node-1"]


def test_run_ansible_publish_false_suppresses_streaming(runner_mocks):
    run_ansible(publish=False)
    runner_mocks.push.assert_not_called()
    runner_mocks.finish.assert_not_called()


# -- locking & cleanup --


def test_run_ansible_locking_lifecycle(runner_mocks):
    run_ansible(locking=True, auto_release_time=1234)
    runner_mocks.create_redlock.assert_called_once_with(
        key="lock-ansible-testbed-dummy-role", auto_release_time=1234
    )
    lock = runner_mocks.create_redlock.return_value
    lock.acquire.assert_called_once()
    lock.release.assert_called_once()


def test_run_ansible_lock_released_when_wait_raises(runner_mocks):
    proc = make_process(["ok: [node-1]\n"])
    proc.wait.side_effect = RuntimeError("boom")
    runner_mocks.popen.return_value = proc

    with pytest.raises(RuntimeError):
        run_ansible(locking=True)

    lock = runner_mocks.create_redlock.return_value
    lock.release.assert_called_once()
    runner_mocks.rmtree.assert_called_once()


def test_run_ansible_lock_release_failure_warns(runner_mocks, loguru_logs):
    runner_mocks.create_redlock.return_value.release.side_effect = RuntimeError("x")
    result = run_ansible(locking=True)
    assert result == "ok: [node-1]\n"
    assert any(
        r["level"] == "WARNING" and "Failed to release lock" in r["message"]
        for r in loguru_logs
    )


def test_run_ansible_locking_false_no_redlock(runner_mocks):
    run_ansible(locking=False)
    runner_mocks.create_redlock.assert_not_called()


def test_run_ansible_ssh_dir_cleanup(runner_mocks, tmp_path):
    run_ansible()
    runner_mocks.rmtree.assert_called_once_with(str(tmp_path / "ssh"))


def test_run_ansible_ssh_dir_cleanup_when_popen_raises(runner_mocks, tmp_path):
    runner_mocks.popen.side_effect = OSError("boom")
    with pytest.raises(OSError):
        run_ansible()
    runner_mocks.rmtree.assert_called_once_with(str(tmp_path / "ssh"))


def test_run_ansible_rmtree_failure_warns(runner_mocks, loguru_logs):
    runner_mocks.rmtree.side_effect = OSError("busy")
    result = run_ansible()
    assert result == "ok: [node-1]\n"
    assert any(
        r["level"] == "WARNING"
        and "Failed to clean up SSH ControlPath directory" in r["message"]
        for r in loguru_logs
    )


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


@pytest.fixture
def command_mocks(mocker):
    popen = mocker.patch("osism.tasks.subprocess.Popen")
    popen.return_value = make_process(["line-1\n"])
    return SimpleNamespace(
        popen=popen,
        push=mocker.patch("osism.tasks.utils.push_task_output"),
        finish=mocker.patch("osism.tasks.utils.finish_task_output"),
        create_redlock=mocker.patch("osism.tasks.utils.create_redlock"),
    )


def test_run_command_popen_argv_no_shell(command_mocks):
    tasks.run_command("req-1", "echo", {}, "a", "b")
    args, kwargs = command_mocks.popen.call_args
    assert args[0] == ["echo", "a", "b"]
    assert kwargs["stderr"] == subprocess.STDOUT
    assert "shell" not in kwargs


def test_run_command_ignore_env_passes_env_verbatim(command_mocks):
    env = {"FOO": "bar"}
    tasks.run_command("req-1", "echo", env, ignore_env=True)
    assert command_mocks.popen.call_args.kwargs["env"] is env


def test_run_command_merges_env_with_os_environ(command_mocks, monkeypatch):
    monkeypatch.setenv("INHERITED_KEY", "inherited")
    env = {"INJECTED_KEY": "injected"}
    tasks.run_command("req-1", "echo", env, ignore_env=False)
    passed = command_mocks.popen.call_args.kwargs["env"]
    assert passed["INJECTED_KEY"] == "injected"
    assert passed["INHERITED_KEY"] == "inherited"
    assert passed is not env


def test_run_command_accumulates_output_and_publishes(command_mocks):
    command_mocks.popen.return_value = make_process(["out-1\n", "out-2\n"], rc=0)
    result = tasks.run_command("req-1", "echo", {})
    assert result == "out-1\nout-2\n"
    assert command_mocks.push.call_count == 2
    command_mocks.finish.assert_called_once_with("req-1", rc=0)


def test_run_command_nonzero_rc_aggregates_output_and_finishes(command_mocks):
    command_mocks.popen.return_value = make_process(["err-1\n", "err-2\n"], rc=1)
    result = tasks.run_command("req-1", "echo", {})
    assert result == "err-1\nerr-2\n"
    assert command_mocks.push.call_count == 2
    command_mocks.finish.assert_called_once_with("req-1", rc=1)


def test_run_command_publish_false_no_streaming(command_mocks):
    tasks.run_command("req-1", "echo", {}, publish=False)
    command_mocks.push.assert_not_called()
    command_mocks.finish.assert_not_called()


def test_run_command_locking_never_acquires(command_mocks):
    # Pinned quirk: with locking=True a redlock is created and released but
    # acquire() is never called in the current implementation.
    tasks.run_command("req-1", "echo", {}, locking=True)
    command_mocks.create_redlock.assert_called_once_with(
        key="lock-echo", auto_release_time=3600
    )
    lock = command_mocks.create_redlock.return_value
    lock.acquire.assert_not_called()
    lock.release.assert_called_once()


def test_run_command_locking_false_no_redlock(command_mocks):
    tasks.run_command("req-1", "echo", {}, locking=False)
    command_mocks.create_redlock.assert_not_called()


# ---------------------------------------------------------------------------
# handle_task
# ---------------------------------------------------------------------------


@pytest.fixture
def task():
    """A fake task exposing both ``id`` (for fetch) and ``task_id`` (for logs)."""
    t = MagicMock()
    t.id = "id-1"
    t.task_id = "task-1"
    return t


def test_handle_task_wait_returns_fetch_result(task, mocker):
    fetch = mocker.patch("osism.tasks.utils.fetch_task_output", return_value="OUTPUT")
    result = tasks.handle_task(task, wait=True, timeout=42)
    assert result == "OUTPUT"
    fetch.assert_called_once_with("id-1", timeout=42)


def test_handle_task_timeout_returns_1_and_logs_hint(task, mocker, loguru_logs):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=TimeoutError)
    result = tasks.handle_task(task, wait=True, timeout=5)
    assert result == 1
    messages = [r["message"] for r in loguru_logs]
    assert any("no output from the task task-1" in m for m in messages)
    assert any("osism wait --output --live --delay 2 task-1" in m for m in messages)


@pytest.mark.parametrize("answer", ["y", "yes"])
def test_handle_task_interrupt_revoke_confirmed(task, mocker, loguru_logs, answer):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=KeyboardInterrupt)
    revoke = mocker.patch("osism.tasks.utils.revoke_task", return_value=True)
    mocker.patch("prompt_toolkit.prompt", return_value=answer)

    result = tasks.handle_task(task)

    assert result == 1
    revoke.assert_called_once_with("task-1")
    assert any("has been revoked" in r["message"] for r in loguru_logs)


def test_handle_task_interrupt_revoke_failure_logged(task, mocker, loguru_logs):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=KeyboardInterrupt)
    mocker.patch("osism.tasks.utils.revoke_task", return_value=False)
    mocker.patch("prompt_toolkit.prompt", return_value="y")

    result = tasks.handle_task(task)

    assert result == 1
    assert any(
        r["level"] == "ERROR" and "Failed to revoke task task-1" in r["message"]
        for r in loguru_logs
    )


@pytest.mark.parametrize("answer", ["n", "no", ""])
def test_handle_task_interrupt_declined(task, mocker, loguru_logs, answer):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=KeyboardInterrupt)
    revoke = mocker.patch("osism.tasks.utils.revoke_task")
    mocker.patch("prompt_toolkit.prompt", return_value=answer)

    result = tasks.handle_task(task)

    assert result == 1
    revoke.assert_not_called()
    assert any("continues running" in r["message"] for r in loguru_logs)


def test_handle_task_interrupt_prompt_keyboard_interrupt(task, mocker, loguru_logs):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=KeyboardInterrupt)
    revoke = mocker.patch("osism.tasks.utils.revoke_task")
    mocker.patch("prompt_toolkit.prompt", side_effect=KeyboardInterrupt)

    result = tasks.handle_task(task)

    assert result == 1
    revoke.assert_not_called()
    assert any("continues running" in r["message"] for r in loguru_logs)


def test_handle_task_interrupt_prompt_eof(task, mocker, loguru_logs):
    mocker.patch("osism.tasks.utils.fetch_task_output", side_effect=KeyboardInterrupt)
    revoke = mocker.patch("osism.tasks.utils.revoke_task")
    mocker.patch("prompt_toolkit.prompt", side_effect=EOFError)

    result = tasks.handle_task(task)

    assert result == 1
    revoke.assert_not_called()
    assert any("continues running" in r["message"] for r in loguru_logs)


def test_handle_task_no_wait_log_format(task, mocker, loguru_logs):
    fetch = mocker.patch("osism.tasks.utils.fetch_task_output")
    result = tasks.handle_task(task, wait=False, format="log")
    assert result == 0
    fetch.assert_not_called()
    assert any("running in background" in r["message"] for r in loguru_logs)


def test_handle_task_no_wait_script_format_prints_task_id(task, mocker, capsys):
    mocker.patch("osism.tasks.utils.fetch_task_output")
    result = tasks.handle_task(task, wait=False, format="script")
    assert result == 0
    assert capsys.readouterr().out == "task-1\n"
