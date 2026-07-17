# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``osism check`` commands.

``check mount`` verifies bind-mount integrity by comparing the container's
view of /opt/configuration with the view from a freshly started container;
``check inode`` prints a lightweight inode snapshot without spawning one.
These tests cover:

- the pure helpers ``get_file_info``, ``collect_file_info`` and
  ``parse_stat_output`` on real temporary trees;
- the ``Mount`` helpers ``_compare_file_info`` (mismatch classification) and
  ``_get_container_id`` / ``_get_mount_source`` (procfs parsing);
- the ``Mount.take_action`` guard rails (missing path, missing Docker,
  undeterminable mount source) and its exit-code / script-output contract;
- ``Inode.take_action`` for explicit file lists and random sampling.
"""

import hashlib
import io
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from osism.commands import check

from ._helpers import make_command, parse_args


def _fake_open(payloads):
    """Return an ``open`` replacement serving per-path text payloads.

    Paths missing from ``payloads`` raise ``IOError``, emulating procfs files
    that are absent or unreadable outside a container.
    """

    def _open(path, *args, **kwargs):
        if path in payloads:
            return io.StringIO(payloads[path])
        raise IOError(f"unreadable: {path}")

    return _open


# --- get_file_info ---


def test_get_file_info_small_file_includes_metadata_and_hash(tmp_path):
    filepath = tmp_path / "small.txt"
    filepath.write_bytes(b"hello osism")

    info = check.get_file_info(str(filepath))

    st = os.stat(filepath)
    assert info["inode"] == st.st_ino
    assert info["mtime"] == st.st_mtime
    assert info["size"] == len(b"hello osism")
    assert info["mode"] == st.st_mode
    assert info["uid"] == st.st_uid
    assert info["gid"] == st.st_gid
    assert info["is_link"] is False
    assert info["hash"] == hashlib.md5(b"hello osism").hexdigest()


def test_get_file_info_large_file_has_no_hash(tmp_path):
    filepath = tmp_path / "large.bin"
    filepath.write_bytes(b"\0" * 1024 * 1024)

    info = check.get_file_info(str(filepath))

    assert info["size"] == 1024 * 1024
    assert info["hash"] is None


def test_get_file_info_directory_has_no_hash(tmp_path):
    info = check.get_file_info(str(tmp_path))

    assert info["hash"] is None
    assert info["is_link"] is False
    assert "error" not in info


def test_get_file_info_unreadable_file_omits_hash_only(tmp_path):
    filepath = tmp_path / "secret.txt"
    filepath.write_bytes(b"data")

    with patch("builtins.open", side_effect=IOError("denied")):
        info = check.get_file_info(str(filepath))

    assert info["hash"] is None
    assert info["size"] == 4
    assert "error" not in info


def test_get_file_info_nonexistent_path_returns_error(tmp_path):
    info = check.get_file_info(str(tmp_path / "missing.txt"))

    assert set(info) == {"error"}
    assert "missing.txt" in info["error"]


# --- collect_file_info ---


def test_collect_file_info_walks_files_and_dirs_and_skips_noise(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    for skip in [".git", "venv", "__pycache__"]:
        skip_dir = tmp_path / skip
        skip_dir.mkdir()
        (skip_dir / "inner.txt").write_text("x")
    (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")

    result = check.collect_file_info(str(tmp_path))

    assert set(result) == {"a.txt", "sub", "sub/b.txt"}
    assert result["a.txt"]["hash"] == hashlib.md5(b"a").hexdigest()
    assert result["sub"]["hash"] is None


def test_collect_file_info_stops_at_max_files_and_warns(tmp_path, loguru_logs):
    for name in ["a.txt", "b.txt", "c.txt", "d.txt"]:
        (tmp_path / name).write_text(name)

    result = check.collect_file_info(str(tmp_path), max_files=2)

    assert len(result) == 2
    assert set(result) <= {"a.txt", "b.txt", "c.txt", "d.txt"}
    assert any(
        r["level"] == "WARNING"
        and r["message"] == "Reached max file limit (2), stopping scan"
        for r in loguru_logs
    )


# --- parse_stat_output ---


def test_parse_stat_output_parses_typed_fields():
    output = "\n".join(
        [
            "FILE:environments/kolla/configuration.yml",
            "INODE:12345",
            "SIZE:678",
            "MTIME:1700000000",
            "HASH:d41d8cd98f00b204e9800998ecf8427e",
        ]
    )

    result = check.parse_stat_output(output)

    info = result["environments/kolla/configuration.yml"]
    assert info == {
        "inode": 12345,
        "size": 678,
        "mtime": 1700000000.0,
        "hash": "d41d8cd98f00b204e9800998ecf8427e",
    }
    assert isinstance(info["inode"], int)
    assert isinstance(info["size"], int)
    assert isinstance(info["mtime"], float)


def test_parse_stat_output_maps_hash_none_to_none():
    result = check.parse_stat_output("FILE:a.txt\nHASH:NONE\n")

    assert result == {"a.txt": {"hash": None}}


def test_parse_stat_output_captures_error_lines():
    result = check.parse_stat_output("FILE:a.txt\nERROR:Permission denied\n")

    assert result == {"a.txt": {"error": "Permission denied"}}


def test_parse_stat_output_ignores_noise_lines():
    output = "\n".join(
        [
            "INODE:99",
            "",
            "FILE:a.txt",
            "INODE:1",
            "line without a colon",
            "UNKNOWN:value",
        ]
    )

    result = check.parse_stat_output(output)

    assert result == {"a.txt": {"inode": 1}}


def test_parse_stat_output_parses_multiple_files_independently():
    output = "\n".join(
        [
            "FILE:a.txt",
            "INODE:1",
            "HASH:aaa",
            "FILE:b.txt",
            "INODE:2",
            "HASH:NONE",
        ]
    )

    result = check.parse_stat_output(output)

    assert result == {
        "a.txt": {"inode": 1, "hash": "aaa"},
        "b.txt": {"inode": 2, "hash": None},
    }


def test_parse_stat_output_returns_empty_dict_for_empty_output():
    assert check.parse_stat_output("") == {}


# --- Mount._compare_file_info ---


def _compare(local, fresh, check_content=False):
    cmd = make_command(check.Mount)
    return cmd._compare_file_info(local, fresh, check_content)


def test_compare_file_info_reports_inode_mismatches():
    inode, content, missing_local, missing_fresh = _compare(
        {"a": {"inode": 1}}, {"a": {"inode": 2}}
    )

    assert inode == [{"file": "a", "local_inode": 1, "fresh_inode": 2}]
    assert content == []
    assert missing_local == []
    assert missing_fresh == []


def test_compare_file_info_reports_content_mismatches_only_when_enabled():
    local = {"a": {"inode": 1, "hash": "aaa"}}
    fresh = {"a": {"inode": 1, "hash": "bbb"}}

    _, content, _, _ = _compare(local, fresh, check_content=True)
    assert content == [{"file": "a", "local_hash": "aaa", "fresh_hash": "bbb"}]

    assert _compare(local, fresh, check_content=False) == ([], [], [], [])


def test_compare_file_info_reports_files_missing_on_either_side():
    inode, content, missing_local, missing_fresh = _compare(
        {"only-local": {"inode": 1}}, {"only-fresh": {"inode": 2}}
    )

    assert missing_local == ["only-fresh"]
    assert missing_fresh == ["only-local"]
    assert inode == []
    assert content == []


def test_compare_file_info_skips_entries_with_errors():
    result = _compare(
        {"a": {"error": "denied"}, "b": {"inode": 1}},
        {"a": {"inode": 99}, "b": {"error": "gone"}},
        check_content=True,
    )

    assert result == ([], [], [], [])


def test_compare_file_info_ignores_falsy_inodes():
    result = _compare(
        {"a": {"inode": None}, "b": {"inode": 0}, "c": {"inode": 3}},
        {"a": {"inode": 1}, "b": {"inode": 2}, "c": {"inode": None}},
    )

    assert result == ([], [], [], [])


def test_compare_file_info_ignores_missing_hashes():
    result = _compare(
        {"a": {"inode": 1, "hash": None}},
        {"a": {"inode": 1, "hash": "bbb"}},
        check_content=True,
    )

    assert result == ([], [], [], [])


def test_compare_file_info_sorts_results_by_file_path():
    local = {
        "z": {"inode": 1},
        "a": {"inode": 1},
        "n": {"inode": 5},
        "b": {"inode": 5},
    }
    fresh = {
        "z": {"inode": 2},
        "a": {"inode": 2},
        "y": {"inode": 7},
        "c": {"inode": 7},
    }

    inode, _, missing_local, missing_fresh = _compare(local, fresh)

    assert [m["file"] for m in inode] == ["a", "z"]
    assert missing_local == ["c", "y"]
    assert missing_fresh == ["b", "n"]


# --- Mount._get_container_id ---


def test_get_container_id_truncates_64_char_cgroup_id():
    payloads = {"/proc/self/cgroup": "12:memory:/docker/" + "a" * 64 + "\n"}
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open(payloads)):
        assert cmd._get_container_id() == "a" * 12


def test_get_container_id_returns_12_char_cgroup_id_as_is():
    payloads = {"/proc/self/cgroup": "12:cpu:/docker/abcdef123456\n"}
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open(payloads)):
        assert cmd._get_container_id() == "abcdef123456"


def test_get_container_id_falls_back_to_12_char_hostname():
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open({})), patch(
        "osism.commands.check.os.uname",
        return_value=SimpleNamespace(nodename="abcdef123456"),
    ):
        assert cmd._get_container_id() == "abcdef123456"


def test_get_container_id_falls_back_to_mountinfo():
    payloads = {
        "/proc/self/mountinfo": (
            "1443 1442 8:1 /var/lib/docker/containers/"
            + "b" * 64
            + "/resolv.conf /etc/resolv.conf rw - ext4 /dev/sda1 rw\n"
        )
    }
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open(payloads)), patch(
        "osism.commands.check.os.uname",
        return_value=SimpleNamespace(nodename="not-a-container-id"),
    ):
        assert cmd._get_container_id() == "b" * 12


def test_get_container_id_returns_none_when_undetectable():
    payloads = {
        "/proc/self/cgroup": "0::/init.scope\n",
        "/proc/self/mountinfo": "36 35 98:0 / / rw - ext4 /dev/sda1 rw\n",
    }
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open(payloads)), patch(
        "osism.commands.check.os.uname",
        return_value=SimpleNamespace(nodename="host"),
    ):
        assert cmd._get_container_id() is None


# --- Mount._get_mount_source ---


def test_get_mount_source_returns_absolute_source_after_separator():
    payloads = {
        "/proc/self/mountinfo": (
            "543 481 254:1 /cfg /opt/configuration rw,relatime - ext4 /dev/vda1 rw\n"
        )
    }
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open(payloads)):
        assert cmd._get_mount_source("/opt/configuration") == "/dev/vda1"


@pytest.mark.parametrize(
    "line",
    [
        # no " - " separator at all
        "543 481 254:1 /cfg /opt/configuration rw,relatime\n",
        # separator present but no source field after the fstype
        "543 481 254:1 /cfg /opt/configuration rw - ext4\n",
        # source is not an absolute path (e.g. overlayfs)
        "543 481 254:1 /cfg /opt/configuration rw - overlay overlay rw\n",
        # no entry for the requested mount point
        "543 481 254:1 /cfg /other rw - ext4 /dev/vda1 rw\n",
    ],
)
def test_get_mount_source_returns_none_for_unusable_lines(line):
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open({"/proc/self/mountinfo": line})):
        assert cmd._get_mount_source("/opt/configuration") is None


def test_get_mount_source_returns_none_when_mountinfo_unreadable():
    cmd = make_command(check.Mount)

    with patch("builtins.open", side_effect=_fake_open({})):
        assert cmd._get_mount_source("/opt/configuration") is None


# --- Mount.take_action ---


def _run_mount(
    argv,
    *,
    docker_available=True,
    path_exists=True,
    socket_exists=True,
    docker_mock=None,
    container_id=None,
    mount_info=None,
    mountinfo_source=None,
    local_info=None,
    fresh_output="",
    fresh_error=None,
):
    """Drive ``Mount.take_action`` with all environment probes patched out.

    The instance helpers that talk to procfs and Docker are replaced with
    mocks so the tests steer the control flow purely through return values.
    Returns the ``(exit_code, command)`` pair; the command exposes the helper
    mocks for call assertions.
    """
    cmd, parsed_args = parse_args(check.Mount, argv)
    cmd._get_container_id = MagicMock(return_value=container_id)
    cmd._get_volume_mount_info = MagicMock(return_value=mount_info)
    cmd._get_mount_source = MagicMock(return_value=mountinfo_source)
    cmd._run_fresh_container = MagicMock(
        return_value=fresh_output, side_effect=fresh_error
    )

    if docker_mock is None:
        docker_mock = MagicMock()

    def fake_exists(path):
        if path == check.DOCKER_SOCKET_PATH:
            return socket_exists
        return path_exists

    with patch("osism.commands.check.DOCKER_AVAILABLE", docker_available), patch(
        "osism.commands.check.docker", docker_mock, create=True
    ), patch("osism.commands.check.os.path.exists", side_effect=fake_exists), patch(
        "osism.commands.check.collect_file_info", return_value=local_info or {}
    ):
        return cmd.take_action(parsed_args), cmd


def test_mount_fails_when_path_missing(capsys):
    result, _ = _run_mount(["--format", "script"], path_exists=False)

    assert result == 1
    assert "FAILED: Path does not exist: /opt/configuration" in capsys.readouterr().out


def test_mount_fails_without_docker_library(capsys):
    result, _ = _run_mount(["--format", "script"], docker_available=False)

    assert result == 1
    assert "FAILED: Docker Python library not available" in capsys.readouterr().out


def test_mount_fails_without_docker_socket(capsys):
    result, _ = _run_mount(["--format", "script"], socket_exists=False)

    assert result == 1
    out = capsys.readouterr().out
    assert "FAILED: Docker socket not found at /var/run/docker.sock" in out


def test_mount_fails_when_docker_connection_fails(capsys):
    docker_mock = MagicMock()
    docker_mock.from_env.side_effect = Exception("cannot connect")

    result, _ = _run_mount(["--format", "script"], docker_mock=docker_mock)

    assert result == 1
    out = capsys.readouterr().out
    assert "FAILED: Failed to connect to Docker: cannot connect" in out


def test_mount_fails_when_mount_source_undeterminable(capsys):
    result, cmd = _run_mount(["--format", "script"])

    assert result == 1
    out = capsys.readouterr().out
    assert "FAILED: Could not determine mount source for /opt/configuration" in out
    # Without a container ID the Docker API is never queried.
    cmd._get_volume_mount_info.assert_not_called()
    cmd._get_mount_source.assert_called_once_with("/opt/configuration")
    cmd._run_fresh_container.assert_not_called()


def test_mount_uses_bind_mount_source_and_passes(capsys):
    result, cmd = _run_mount(
        ["--format", "script"],
        container_id="abcdef123456",
        mount_info={
            "type": "bind",
            "source": "/host/configuration",
            "name": None,
            "driver": None,
        },
    )

    assert result == 0
    assert "PASSED" in capsys.readouterr().out
    args = cmd._run_fresh_container.call_args[0]
    assert args[1] == "registry.osism.cloud/dockerhub/alpine:latest"
    assert args[2] == "/host/configuration"
    assert args[3] == "/opt/configuration"


def test_mount_volume_name_overrides_detected_volume():
    result, cmd = _run_mount(
        ["--format", "script", "--volume-name", "configuration"],
        container_id="abcdef123456",
        mount_info={
            "type": "volume",
            "source": "/var/lib/docker/volumes/auto/_data",
            "name": "auto",
            "driver": "local",
        },
    )

    assert result == 0
    assert cmd._run_fresh_container.call_args[0][2] == "configuration"


def test_mount_volume_uses_detected_name_without_override():
    result, cmd = _run_mount(
        ["--format", "script"],
        container_id="abcdef123456",
        mount_info={
            "type": "volume",
            "source": "/var/lib/docker/volumes/auto/_data",
            "name": "auto",
            "driver": "local",
        },
    )

    assert result == 0
    assert cmd._run_fresh_container.call_args[0][2] == "auto"


def test_mount_fails_when_fresh_container_fails(capsys):
    result, _ = _run_mount(
        ["--format", "script"],
        container_id="abcdef123456",
        mount_info={"type": "bind", "source": "/host/configuration"},
        fresh_error=RuntimeError("Failed to run fresh container: boom"),
    )

    assert result == 1
    assert "FAILED: Failed to run fresh container: boom" in capsys.readouterr().out


def test_mount_reports_inode_mismatches_in_script_format(capsys):
    fresh_output = "\n".join(
        ["FILE:a.txt", "INODE:2", "SIZE:5", "MTIME:1.0", "HASH:NONE"]
    )

    result, _ = _run_mount(
        ["--format", "script"],
        container_id="abcdef123456",
        mount_info={"type": "bind", "source": "/host/configuration"},
        local_info={"a.txt": {"inode": 1, "size": 5, "hash": None}},
        fresh_output=fresh_output,
    )

    assert result == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "INODE_MISMATCHES:1" in out


def test_mount_passes_in_log_format_with_mountinfo_fallback(loguru_logs):
    result, cmd = _run_mount([], mountinfo_source="/host/configuration")

    assert result == 0
    messages = [r["message"] for r in loguru_logs]
    assert "Could not determine current container ID" in messages
    assert "Using mount source: /host/configuration" in messages
    assert "Mount integrity check PASSED" in messages


# --- Inode.take_action ---


def test_inode_script_reports_explicit_files_and_skips_symlinks(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("content")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")

    cmd, parsed_args = parse_args(
        check.Inode,
        [
            "a.txt",
            "subdir",
            "link.txt",
            "ghost.txt",
            "--path",
            str(tmp_path),
            "--format",
            "script",
        ],
    )
    result = cmd.take_action(parsed_args)

    assert result == 0
    inode_file = os.stat(tmp_path / "a.txt").st_ino
    inode_dir = os.stat(tmp_path / "subdir").st_ino
    assert capsys.readouterr().out.splitlines() == [
        f"File:a.txt:{inode_file}",
        f"Dir:subdir:{inode_dir}",
    ]


def test_inode_table_format_prints_snapshot(tmp_path, capsys):
    (tmp_path / "a.txt").write_text("content")

    cmd, parsed_args = parse_args(check.Inode, ["a.txt", "--path", str(tmp_path)])
    result = cmd.take_action(parsed_args)

    assert result == 0
    out = capsys.readouterr().out
    assert "Inode snapshot of random files" in out
    for header in ["Path", "Type", "Inode", "Size"]:
        assert header in out
    assert "a.txt" in out


def test_inode_log_format_logs_rows(tmp_path, loguru_logs):
    (tmp_path / "a.txt").write_text("content")

    cmd, parsed_args = parse_args(
        check.Inode, ["a.txt", "--path", str(tmp_path), "--format", "log"]
    )
    result = cmd.take_action(parsed_args)

    assert result == 0
    st = os.stat(tmp_path / "a.txt")
    assert any(
        r["message"] == f"a.txt: type=File, inode={st.st_ino}, size={st.st_size}"
        for r in loguru_logs
    )


def test_inode_samples_random_entries_when_no_files_given(tmp_path, capsys):
    env_sub = tmp_path / "environments" / "kolla"
    env_sub.mkdir(parents=True)
    for name in ["a.yml", "b.yml", "c.yml"]:
        (env_sub / name).write_text(name)
    (tmp_path / "environments" / "site.yml").write_text("site")
    # Symlinked subdirectories are skipped by the sampling.
    (tmp_path / "environments" / "linked").symlink_to(env_sub)

    inv_sub = tmp_path / "inventory" / "group_vars"
    inv_sub.mkdir(parents=True)
    (inv_sub / "all.yml").write_text("all")

    cmd, parsed_args = parse_args(
        check.Inode, ["--path", str(tmp_path), "--format", "script"]
    )
    with patch(
        "osism.commands.check.random.sample",
        side_effect=lambda population, k: sorted(population)[:k],
    ):
        result = cmd.take_action(parsed_args)

    assert result == 0
    lines = capsys.readouterr().out.splitlines()
    reported = {":".join(line.split(":")[:2]) for line in lines}
    assert reported == {
        "Dir:environments/kolla",
        "File:environments/kolla/a.yml",
        "File:environments/site.yml",
        "Dir:inventory/group_vars",
        "File:inventory/group_vars/all.yml",
    }


def test_inode_returns_zero_without_configuration_directories(tmp_path, capsys):
    cmd, parsed_args = parse_args(
        check.Inode, ["--path", str(tmp_path), "--format", "script"]
    )
    result = cmd.take_action(parsed_args)

    assert result == 0
    assert capsys.readouterr().out == ""
