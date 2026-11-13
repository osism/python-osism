# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.collect``.

The remote execution is replaced by a function with the signature of
``osism.utils.ssh.run_remote``, so no SSH process is started.
"""

import argparse
import json
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from osism.utils.hardware.collect import (
    CollectError,
    Request,
    add_collection_arguments,
    collect,
    collect_one,
    collector_script,
    dump_raw,
    remote_command,
)
from osism.utils.hardware.selection import KIND_NODE, KIND_SWITCH, Target

REQUESTS = {
    KIND_NODE: Request(sections=["ports", "lldp"], sudo=True),
    KIND_SWITCH: Request(sections=["ports"]),
}


def _target(name, kind=KIND_NODE, address="192.0.2.1", user="dragon"):
    return Target(name=name, hostname=name, kind=kind, address=address, user=user)


def _result(stdout="{}", returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_collection_arguments():
    parser = argparse.ArgumentParser()
    add_collection_arguments(parser)

    args = parser.parse_args([])
    assert (args.parallel, args.timeout, args.dump_raw) == (10, 60, None)

    args = parser.parse_args(
        ["--parallel", "4", "--timeout", "2.5", "--dump-raw", "/tmp/capture"]
    )
    assert (args.parallel, args.timeout, args.dump_raw) == (4, 2.5, "/tmp/capture")


def test_remote_command_quotes_arguments_and_adds_sudo():
    assert remote_command(Request(sections=["ports"])) == "python3 - --sections ports"
    assert (
        remote_command(
            Request(sections=["ports", "lldp"], options=["--include-vf"], sudo=True)
        )
        == "sudo -n python3 - --sections ports,lldp --include-vf"
    )
    assert "'a b'" in remote_command(Request(sections=["ports"], options=["a b"]))


@pytest.mark.parametrize("kind", [KIND_NODE, KIND_SWITCH])
def test_collector_script_is_self_contained_python(kind):
    source = collector_script(kind)

    compile(source, f"<{kind} collector>", "exec")
    assert "import osism" not in source and "from osism" not in source


def test_collect_one_pipes_the_collector_and_returns_the_document():
    calls = []

    def run(host, user, command, stdin=None, timeout=None):
        calls.append((host, user, command, stdin, timeout))
        return _result(stdout=json.dumps({"collector": "linux"}))

    document = collect_one(
        _target("node-a", address="192.0.2.7"), REQUESTS[KIND_NODE], 42, run
    )

    assert document == {"collector": "linux"}
    host, user, command, stdin, timeout = calls[0]
    assert (host, user, timeout) == ("192.0.2.7", "dragon", 42)
    assert command == "sudo -n python3 - --sections ports,lldp"
    assert stdin == collector_script(KIND_NODE)


def test_collect_one_uses_the_collector_of_the_device_kind():
    seen = {}

    def run(host, user, command, stdin=None, timeout=None):
        seen["stdin"] = stdin
        return _result()

    collect_one(_target("leaf", kind=KIND_SWITCH), REQUESTS[KIND_SWITCH], 5, run)

    assert seen["stdin"] == collector_script(KIND_SWITCH)


@pytest.mark.parametrize(
    "outcome,message",
    [
        (
            _result(returncode=255, stderr="Permission denied (publickey)."),
            "Permission denied (publickey).",
        ),
        (
            _result(
                returncode=1, stderr="warning\ncannot read CONFIG_DB PORT: denied\n"
            ),
            "cannot read CONFIG_DB PORT: denied",
        ),
        (_result(returncode=3, stderr=""), "exit code 3"),
        (_result(stdout="not json"), "unparsable collector output"),
        (_result(stdout="[1, 2]"), "unparsable collector output"),
        (subprocess.TimeoutExpired(cmd="ssh", timeout=5), "timeout"),
    ],
)
def test_collect_one_failures(outcome, message):
    def run(host, user, command, stdin=None, timeout=None):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with pytest.raises(CollectError) as excinfo:
        collect_one(_target("node-a"), REQUESTS[KIND_NODE], 5, run)

    assert str(excinfo.value) == message


def test_collect_one_without_address_does_not_connect():
    def run(*args, **kwargs):
        raise AssertionError("must not connect")

    with pytest.raises(CollectError, match="no management address"):
        collect_one(_target("leaf", address=""), REQUESTS[KIND_NODE], 5, run)


def test_collect_reports_failed_devices_and_keeps_the_others():
    def run(host, user, command, stdin=None, timeout=None):
        if host == "bad":
            raise subprocess.TimeoutExpired(cmd="ssh", timeout=timeout)
        if host == "broken":
            raise OSError("ssh binary missing")
        return _result(stdout=json.dumps({"host": host}))

    targets = [
        _target("node-a", address="a"),
        _target("node-b", address="bad"),
        _target("leaf-1", kind=KIND_SWITCH, address="c", user="admin"),
        _target("node-c", address="broken"),
    ]

    collection = collect(targets, REQUESTS, parallel=2, timeout=5, run=run)

    assert collection.documents == {"node-a": {"host": "a"}, "leaf-1": {"host": "c"}}
    assert collection.failed == [
        {"name": "node-b", "error": "timeout"},
        {"name": "node-c", "error": "OSError: ssh binary missing"},
    ]


def test_collect_queries_devices_in_parallel():
    """A slow device must not hold up the others.

    All four calls have to be in flight at the same time before any of them
    is released. With serial execution the barrier would never fill and the
    calls would fail with ``BrokenBarrierError``.
    """
    barrier = threading.Barrier(4, timeout=5)

    def run(host, user, command, stdin=None, timeout=None):
        barrier.wait()
        return _result(stdout=json.dumps({"host": host}))

    targets = [_target(f"node-{i}", address=str(i)) for i in range(4)]

    collection = collect(targets, REQUESTS, parallel=4, timeout=5, run=run)

    assert sorted(collection.documents) == ["node-0", "node-1", "node-2", "node-3"]
    assert collection.failed == []


def test_collect_honours_the_parallel_limit():
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def run(host, user, command, stdin=None, timeout=None):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.02)
        with lock:
            state["running"] -= 1
        return _result()

    targets = [_target(f"node-{i}", address=str(i)) for i in range(6)]

    collect(targets, REQUESTS, parallel=2, timeout=5, run=run)

    assert state["peak"] <= 2


def test_dump_raw_writes_one_file_per_device(tmp_path):
    def run(host, user, command, stdin=None, timeout=None):
        return _result(stdout=json.dumps({"host": host}))

    collection = collect(
        [_target("node-a", address="a"), _target("rack/1", address="b")],
        REQUESTS,
        run=run,
    )

    paths = dump_raw(collection, str(tmp_path / "capture"))

    assert [p.rsplit("/", 1)[1] for p in paths] == ["node-a.json", "rack_1.json"]
    assert json.loads((tmp_path / "capture" / "node-a.json").read_text()) == {
        "host": "a"
    }
