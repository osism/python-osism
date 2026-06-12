# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.ssh`` known_hosts maintenance helpers."""

import re
import socket
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from osism.utils.ssh import (
    KNOWN_HOSTS_PATH,
    backup_known_hosts,
    cleanup_ssh_known_hosts_for_node,
    ensure_known_hosts_file,
    get_host_identifiers,
    remove_known_hosts_entries,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KNOWN_HOSTS_DIR = "/share"


def _has_log(records, level, substring):
    """Return True if any captured log record matches level and substring."""
    return any(r["level"] == level and substring in r["message"] for r in records)


def _run_result(returncode=0, stderr="", stdout=""):
    """Build a stand-in for the ``subprocess.run`` CompletedProcess result."""
    return MagicMock(returncode=returncode, stderr=stderr, stdout=stdout)


def _device(address):
    """Build a NetBox device stub whose primary_ip4.address stringifies."""
    return SimpleNamespace(primary_ip4=SimpleNamespace(address=address))


# ---------------------------------------------------------------------------
# ensure_known_hosts_file
# ---------------------------------------------------------------------------


def test_ensure_directory_and_file_exist(mocker):
    """Directory and file already exist -> True, no create/chmod calls."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    makedirs = mocker.patch("osism.utils.ssh.os.makedirs")
    chmod = mocker.patch("osism.utils.ssh.os.chmod")
    open_ = mocker.patch("builtins.open")

    assert ensure_known_hosts_file() is True
    makedirs.assert_not_called()
    open_.assert_not_called()
    chmod.assert_not_called()


def test_ensure_creates_missing_directory(mocker):
    """Directory missing -> os.makedirs invoked with mode/exist_ok."""
    mocker.patch(
        "osism.utils.ssh.os.path.exists",
        side_effect=lambda path: path != KNOWN_HOSTS_DIR,
    )
    makedirs = mocker.patch("osism.utils.ssh.os.makedirs")
    mocker.patch("osism.utils.ssh.os.chmod")
    open_ = mocker.patch("builtins.open")

    assert ensure_known_hosts_file() is True
    makedirs.assert_called_once_with(KNOWN_HOSTS_DIR, mode=0o755, exist_ok=True)
    open_.assert_not_called()


def test_ensure_creates_missing_file(mocker):
    """File missing -> open(path, "a") and os.chmod(path, 0o644), returns True."""
    mocker.patch(
        "osism.utils.ssh.os.path.exists",
        side_effect=lambda path: path == KNOWN_HOSTS_DIR,
    )
    makedirs = mocker.patch("osism.utils.ssh.os.makedirs")
    chmod = mocker.patch("osism.utils.ssh.os.chmod")
    open_ = mocker.patch("builtins.open")

    assert ensure_known_hosts_file() is True
    makedirs.assert_not_called()
    open_.assert_called_once_with(KNOWN_HOSTS_PATH, "a")
    chmod.assert_called_once_with(KNOWN_HOSTS_PATH, 0o644)


def test_ensure_makedirs_permission_error(mocker, loguru_logs):
    """os.makedirs raises PermissionError -> False, error logged."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=False)
    mocker.patch("osism.utils.ssh.os.makedirs", side_effect=PermissionError("denied"))

    assert ensure_known_hosts_file() is False
    assert _has_log(loguru_logs, "ERROR", "Permission denied creating")


def test_ensure_makedirs_os_error(mocker, loguru_logs):
    """os.makedirs raises OSError -> False, error logged."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=False)
    mocker.patch("osism.utils.ssh.os.makedirs", side_effect=OSError("disk full"))

    assert ensure_known_hosts_file() is False
    assert _has_log(loguru_logs, "ERROR", "OS error creating")


def test_ensure_open_unexpected_error(mocker, loguru_logs):
    """open raises a generic Exception (catch-all) -> False, error logged."""
    mocker.patch(
        "osism.utils.ssh.os.path.exists",
        side_effect=lambda path: path == KNOWN_HOSTS_DIR,
    )
    mocker.patch("osism.utils.ssh.os.makedirs")
    mocker.patch("osism.utils.ssh.os.chmod")
    mocker.patch("builtins.open", side_effect=RuntimeError("boom"))

    assert ensure_known_hosts_file() is False
    assert _has_log(loguru_logs, "ERROR", "Unexpected error creating")


def test_ensure_custom_path_propagates(mocker):
    """A custom path argument propagates to makedirs/open/chmod."""
    custom = "/custom/dir/known_hosts"
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=False)
    makedirs = mocker.patch("osism.utils.ssh.os.makedirs")
    chmod = mocker.patch("osism.utils.ssh.os.chmod")
    open_ = mocker.patch("builtins.open")

    assert ensure_known_hosts_file(custom) is True
    makedirs.assert_called_once_with("/custom/dir", mode=0o755, exist_ok=True)
    open_.assert_called_once_with(custom, "a")
    chmod.assert_called_once_with(custom, 0o644)


# ---------------------------------------------------------------------------
# get_host_identifiers
# ---------------------------------------------------------------------------


def test_get_identifiers_dns_unique_ip(mocker):
    """DNS resolves to a unique IP -> [hostname, ip], list starts with host."""
    mocker.patch("socket.gethostbyname", return_value="192.168.1.10")
    mocker.patch("osism.utils.ssh.utils.nb", new=None, create=True)

    result = get_host_identifiers("node01")
    assert result == ["node01", "192.168.1.10"]
    assert result[0] == "node01"


def test_get_identifiers_dns_returns_hostname(mocker):
    """DNS resolves to the hostname itself -> no duplicate added."""
    mocker.patch("socket.gethostbyname", return_value="node01")
    mocker.patch("osism.utils.ssh.utils.nb", new=None, create=True)

    assert get_host_identifiers("node01") == ["node01"]


def test_get_identifiers_dns_gaierror(mocker, loguru_logs):
    """socket.gaierror -> DNS fails silently, debug log, IP not appended."""
    mocker.patch("socket.gethostbyname", side_effect=socket.gaierror("no dns"))
    mocker.patch("osism.utils.ssh.utils.nb", new=None, create=True)

    assert get_host_identifiers("node01") == ["node01"]
    assert _has_log(loguru_logs, "DEBUG", "DNS resolution failed")


def test_get_identifiers_netbox_disabled(mocker):
    """utils.nb is None -> NetBox lookup skipped, only DNS result returned."""
    mocker.patch("socket.gethostbyname", return_value="192.168.1.10")
    mocker.patch("osism.utils.ssh.utils.nb", new=None, create=True)

    assert get_host_identifiers("node01") == ["node01", "192.168.1.10"]


def test_get_identifiers_netbox_primary_ip(mocker, loguru_logs):
    """NetBox device primary_ip4 -> IP appended with prefix stripped, logged."""
    mocker.patch("socket.gethostbyname", side_effect=socket.gaierror("no dns"))
    nb = mocker.MagicMock()
    nb.dcim.devices.get.return_value = _device("10.0.0.5/24")
    mocker.patch("osism.utils.ssh.utils.nb", new=nb, create=True)

    result = get_host_identifiers("node01")
    assert result == ["node01", "10.0.0.5"]
    nb.dcim.devices.get.assert_called_once_with(name="node01")
    assert _has_log(loguru_logs, "DEBUG", "10.0.0.5")


def test_get_identifiers_netbox_device_none(mocker):
    """nb.dcim.devices.get returns None -> no IP appended."""
    mocker.patch("socket.gethostbyname", side_effect=socket.gaierror("no dns"))
    nb = mocker.MagicMock()
    nb.dcim.devices.get.return_value = None
    mocker.patch("osism.utils.ssh.utils.nb", new=nb, create=True)

    assert get_host_identifiers("node01") == ["node01"]


def test_get_identifiers_netbox_raises(mocker, loguru_logs):
    """nb.dcim.devices.get raises -> debug log, no IP appended, no propagation."""
    mocker.patch("socket.gethostbyname", side_effect=socket.gaierror("no dns"))
    nb = mocker.MagicMock()
    nb.dcim.devices.get.side_effect = Exception("netbox down")
    mocker.patch("osism.utils.ssh.utils.nb", new=nb, create=True)

    assert get_host_identifiers("node01") == ["node01"]
    assert _has_log(loguru_logs, "DEBUG", "Error querying Netbox")


def test_get_identifiers_dns_and_netbox_same_ip(mocker):
    """Same IP from DNS and NetBox -> only one copy in result."""
    mocker.patch("socket.gethostbyname", return_value="10.0.0.5")
    nb = mocker.MagicMock()
    nb.dcim.devices.get.return_value = _device("10.0.0.5/24")
    mocker.patch("osism.utils.ssh.utils.nb", new=nb, create=True)

    result = get_host_identifiers("node01")
    assert result == ["node01", "10.0.0.5"]
    assert result.count("10.0.0.5") == 1


# ---------------------------------------------------------------------------
# remove_known_hosts_entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostname", ["", "   "])
def test_remove_empty_hostname(mocker, loguru_logs, hostname):
    """Empty / whitespace hostname -> False, warning, no subprocess call."""
    run = mocker.patch("osism.utils.ssh.subprocess.run")
    identifiers = mocker.patch("osism.utils.ssh.get_host_identifiers")

    assert remove_known_hosts_entries(hostname) is False
    run.assert_not_called()
    identifiers.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "Empty hostname")


def test_remove_path_missing(mocker, loguru_logs):
    """known_hosts_path does not exist -> True, nothing to clean."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=False)
    run = mocker.patch("osism.utils.ssh.subprocess.run")

    assert remove_known_hosts_entries("node01") is True
    run.assert_not_called()
    assert _has_log(loguru_logs, "DEBUG", "does not exist")


def test_remove_no_identifiers(mocker, loguru_logs):
    """get_host_identifiers returns [] -> False, warning."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=[])
    run = mocker.patch("osism.utils.ssh.subprocess.run")

    assert remove_known_hosts_entries("node01") is False
    run.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "No host identifiers")


def test_remove_identifiers_raises(mocker, loguru_logs):
    """get_host_identifiers raises -> False, error logged."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch(
        "osism.utils.ssh.get_host_identifiers",
        side_effect=RuntimeError("boom"),
    )
    run = mocker.patch("osism.utils.ssh.subprocess.run")

    assert remove_known_hosts_entries("node01") is False
    run.assert_not_called()
    assert _has_log(loguru_logs, "ERROR", "Error getting host identifiers")


def test_remove_single_identifier_updated(mocker, loguru_logs):
    """returncode 0 with 'updated' in stderr -> counted, debug log, True."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    run = mocker.patch(
        "osism.utils.ssh.subprocess.run",
        return_value=_run_result(stderr="# Host node01 found\nupdated"),
    )

    assert remove_known_hosts_entries("node01", KNOWN_HOSTS_PATH) is True
    run.assert_called_once_with(
        ["ssh-keygen", "-R", "node01", "-f", KNOWN_HOSTS_PATH],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert _has_log(loguru_logs, "DEBUG", "Removed SSH known_hosts entries for node01")
    assert _has_log(loguru_logs, "INFO", "Successfully cleaned 1")


def test_remove_stderr_contains_identifier(mocker, loguru_logs):
    """Stderr contains the identifier (case-insensitive) -> counted as removed."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch(
        "osism.utils.ssh.subprocess.run",
        return_value=_run_result(stderr="NODE01 entry removed"),
    )

    assert remove_known_hosts_entries("node01") is True
    assert _has_log(loguru_logs, "DEBUG", "Removed SSH known_hosts entries for node01")


def test_remove_no_entry_found(mocker, loguru_logs):
    """Stderr neither 'updated' nor identifier -> no entry, still True."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch("osism.utils.ssh.subprocess.run", return_value=_run_result(stderr=""))

    assert remove_known_hosts_entries("node01") is True
    assert _has_log(loguru_logs, "DEBUG", "No SSH known_hosts entries found for node01")
    assert _has_log(loguru_logs, "DEBUG", "No SSH known_hosts entries found to clean")


def test_remove_nonzero_returncode_continues(mocker, loguru_logs):
    """returncode != 0 -> warning, but success not flipped to False."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch(
        "osism.utils.ssh.subprocess.run",
        return_value=_run_result(returncode=1, stderr="some failure"),
    )

    assert remove_known_hosts_entries("node01") is True
    assert _has_log(loguru_logs, "WARNING", "non-zero exit code")


def test_remove_timeout(mocker, loguru_logs):
    """subprocess.run raises TimeoutExpired -> error logged, success False."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch(
        "osism.utils.ssh.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=30),
    )

    assert remove_known_hosts_entries("node01") is False
    assert _has_log(loguru_logs, "ERROR", "Timeout while removing")


def test_remove_called_process_error(mocker, loguru_logs):
    """subprocess.run raises CalledProcessError -> error logged, success False."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch(
        "osism.utils.ssh.subprocess.run",
        side_effect=subprocess.CalledProcessError(returncode=1, cmd="ssh-keygen"),
    )

    assert remove_known_hosts_entries("node01") is False
    assert _has_log(loguru_logs, "ERROR", "Error removing SSH known_hosts entries")


def test_remove_generic_exception(mocker, loguru_logs):
    """subprocess.run raises a generic Exception -> error logged, success False."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.get_host_identifiers", return_value=["node01"])
    mocker.patch("osism.utils.ssh.subprocess.run", side_effect=ValueError("weird"))

    assert remove_known_hosts_entries("node01") is False
    assert _has_log(loguru_logs, "ERROR", "Unexpected error removing")


def test_remove_multiple_one_succeeds_one_times_out(mocker, loguru_logs):
    """Multiple identifiers, one succeeds and one times out -> success False."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch(
        "osism.utils.ssh.get_host_identifiers",
        return_value=["node01", "10.0.0.5"],
    )
    run = mocker.patch(
        "osism.utils.ssh.subprocess.run",
        side_effect=[
            _run_result(stderr="updated"),
            subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=30),
        ],
    )

    assert remove_known_hosts_entries("node01") is False
    assert run.call_count == 2
    assert _has_log(loguru_logs, "INFO", "Successfully cleaned 1")


def test_remove_skips_empty_identifier(mocker, loguru_logs):
    """Empty/whitespace identifier in the list -> skipped, no subprocess call."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch(
        "osism.utils.ssh.get_host_identifiers",
        return_value=["valid-host", "", "  "],
    )
    run = mocker.patch(
        "osism.utils.ssh.subprocess.run",
        return_value=_run_result(stderr="updated"),
    )

    assert remove_known_hosts_entries("valid-host") is True
    run.assert_called_once_with(
        ["ssh-keygen", "-R", "valid-host", "-f", KNOWN_HOSTS_PATH],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert _has_log(loguru_logs, "DEBUG", "Skipping empty identifier")


# ---------------------------------------------------------------------------
# backup_known_hosts
# ---------------------------------------------------------------------------


def test_backup_empty_path(loguru_logs):
    """Empty path -> warning, returns None."""
    assert backup_known_hosts("") is None
    assert _has_log(loguru_logs, "WARNING", "Empty known_hosts path")


def test_backup_path_missing(mocker, loguru_logs):
    """Path does not exist -> debug log, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=False)

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "DEBUG", "does not exist, no backup needed")


def test_backup_not_readable(mocker, loguru_logs):
    """File not readable (R_OK false) -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=False)

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "not readable")


def test_backup_directory_missing(mocker, loguru_logs):
    """Backup directory missing -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch(
        "osism.utils.ssh.os.path.exists",
        side_effect=lambda path: path == KNOWN_HOSTS_PATH,
    )

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "Backup directory does not exist")


def test_backup_directory_not_writable(mocker, loguru_logs):
    """Backup directory not writable -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", side_effect=[True, False])

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "Backup directory is not writable")


def test_backup_happy_path(mocker, loguru_logs):
    """Happy path -> copy2(src, backup), path matches pattern, returns it."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("osism.utils.ssh.os.path.getsize", return_value=128)
    copy2 = mocker.patch("shutil.copy2")

    result = backup_known_hosts(KNOWN_HOSTS_PATH)
    assert result is not None
    assert re.fullmatch(re.escape(KNOWN_HOSTS_PATH) + r"\.backup_\d{8}_\d{6}", result)
    copy2.assert_called_once_with(KNOWN_HOSTS_PATH, result)
    assert _has_log(loguru_logs, "DEBUG", "Created SSH known_hosts backup")


def test_backup_verify_missing_after_copy(mocker, loguru_logs):
    """Backup file absent after copy -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("shutil.copy2")
    mocker.patch(
        "osism.utils.ssh.os.path.exists",
        side_effect=lambda path: not path.startswith(KNOWN_HOSTS_PATH + ".backup_"),
    )

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "was not created properly")


def test_backup_verify_empty_after_copy(mocker, loguru_logs):
    """Backup file empty (getsize 0) after copy -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("osism.utils.ssh.os.path.getsize", return_value=0)
    mocker.patch("shutil.copy2")

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "was not created properly")


def test_backup_copy_permission_error(mocker, loguru_logs):
    """shutil.copy2 raises PermissionError -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("shutil.copy2", side_effect=PermissionError("denied"))

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "Permission denied creating SSH")


def test_backup_copy_os_error(mocker, loguru_logs):
    """shutil.copy2 raises OSError -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("shutil.copy2", side_effect=OSError("io error"))

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "OS error creating SSH")


def test_backup_copy_generic_exception(mocker, loguru_logs):
    """shutil.copy2 raises a generic Exception -> warning, returns None."""
    mocker.patch("osism.utils.ssh.os.path.exists", return_value=True)
    mocker.patch("osism.utils.ssh.os.access", return_value=True)
    mocker.patch("shutil.copy2", side_effect=ValueError("weird"))

    assert backup_known_hosts(KNOWN_HOSTS_PATH) is None
    assert _has_log(loguru_logs, "WARNING", "Unexpected error creating SSH")


# ---------------------------------------------------------------------------
# cleanup_ssh_known_hosts_for_node
# ---------------------------------------------------------------------------


def test_cleanup_backup_success(mocker, loguru_logs):
    """create_backup=True, backup succeeds -> debug log, cleanup result."""
    backup = mocker.patch(
        "osism.utils.ssh.backup_known_hosts",
        return_value=f"{KNOWN_HOSTS_PATH}.backup_20260427_120000",
    )
    remove = mocker.patch(
        "osism.utils.ssh.remove_known_hosts_entries", return_value=True
    )

    assert cleanup_ssh_known_hosts_for_node("node01") is True
    backup.assert_called_once_with(KNOWN_HOSTS_PATH)
    remove.assert_called_once_with("node01", KNOWN_HOSTS_PATH)
    assert _has_log(loguru_logs, "DEBUG", "SSH known_hosts backup created")


def test_cleanup_backup_returns_none(mocker, loguru_logs):
    """create_backup=True, backup returns None -> no debug log, cleanup runs."""
    backup = mocker.patch("osism.utils.ssh.backup_known_hosts", return_value=None)
    remove = mocker.patch(
        "osism.utils.ssh.remove_known_hosts_entries", return_value=True
    )

    assert cleanup_ssh_known_hosts_for_node("node01") is True
    backup.assert_called_once_with(KNOWN_HOSTS_PATH)
    remove.assert_called_once_with("node01", KNOWN_HOSTS_PATH)
    assert not _has_log(loguru_logs, "DEBUG", "SSH known_hosts backup created")


def test_cleanup_no_backup(mocker):
    """create_backup=False -> backup_known_hosts not called."""
    backup = mocker.patch("osism.utils.ssh.backup_known_hosts")
    remove = mocker.patch(
        "osism.utils.ssh.remove_known_hosts_entries", return_value=True
    )

    assert cleanup_ssh_known_hosts_for_node("node01", create_backup=False) is True
    backup.assert_not_called()
    remove.assert_called_once_with("node01", KNOWN_HOSTS_PATH)


def test_cleanup_remove_returns_false(mocker):
    """remove_known_hosts_entries returns False -> returns False."""
    mocker.patch("osism.utils.ssh.backup_known_hosts", return_value=None)
    mocker.patch("osism.utils.ssh.remove_known_hosts_entries", return_value=False)

    assert cleanup_ssh_known_hosts_for_node("node01") is False


def test_cleanup_remove_raises(mocker, loguru_logs):
    """remove_known_hosts_entries raises -> caught, error logged, False."""
    mocker.patch("osism.utils.ssh.backup_known_hosts", return_value=None)
    mocker.patch(
        "osism.utils.ssh.remove_known_hosts_entries",
        side_effect=RuntimeError("boom"),
    )

    assert cleanup_ssh_known_hosts_for_node("node01") is False
    assert _has_log(loguru_logs, "ERROR", "Error during SSH known_hosts cleanup")
