# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.tasks.conductor.sonic.exporter``.

Covers ``save_config_to_netbox`` (NetBox local-context persistence with diff
checking + journal logging) and ``export_config_to_file`` (on-disk export with
diff checking, filename selection, and the serial-number→hostname symlink).

``save_config_to_netbox`` reuses the shared ``mock_nb`` fixture (it patches
``osism.utils.nb``, which ``exporter.utils.nb`` resolves to). The file-export
tests drive a real filesystem under ``tmp_path`` where that reads more clearly
than asserting on mocked ``os`` calls, and fall back to patching ``os.*`` only
to inject the two error paths (symlink / makedirs failures).
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from osism.tasks.conductor.sonic.exporter import (
    export_config_to_file,
    save_config_to_netbox,
)


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


# ---------------------------------------------------------------------------
# save_config_to_netbox
# ---------------------------------------------------------------------------


def _make_save_device(local_context_data=None, device_id=1, name="sw-1"):
    """Build a NetBox-shaped device whose ``save`` is observable."""
    return SimpleNamespace(
        id=device_id,
        name=name,
        local_context_data=local_context_data,
        save=MagicMock(),
    )


def test_save_config_first_time_saves_and_returns_true(mock_nb):
    """No existing local context → first-time path saves and reports change."""
    device = _make_save_device(local_context_data=None)

    result = save_config_to_netbox(device, {"PORT": {"Ethernet0": {}}})

    assert result is True
    device.save.assert_called_once_with()
    assert device.local_context_data == {"sonic_config": {"PORT": {"Ethernet0": {}}}}
    # First-time configuration creates no journal entry.
    mock_nb.extras.journal_entries.create.assert_not_called()


def test_save_config_first_time_return_diff_tuple(mock_nb):
    """``return_diff=True`` on the first-time path yields ``(True, None)``."""
    device = _make_save_device(local_context_data=None)

    result = save_config_to_netbox(device, {"PORT": {}}, return_diff=True)

    assert result == (True, None)


def test_save_config_no_change_skips_save(mock_nb):
    """Identical existing context → ``DeepDiff`` empty, no save, returns False."""
    config = {"PORT": {"Ethernet0": {}}}
    device = _make_save_device(local_context_data={"sonic_config": config})

    result = save_config_to_netbox(device, config)

    assert result is False
    device.save.assert_not_called()


def test_save_config_no_change_return_diff_tuple(mock_nb):
    config = {"PORT": {"Ethernet0": {}}}
    device = _make_save_device(local_context_data={"sonic_config": config})

    result = save_config_to_netbox(device, config, return_diff=True)

    assert result == (False, None)


def test_save_config_change_writes_journal_and_saves(mock_nb):
    """A changed config generates a diff, a journal entry, and a save."""
    device = _make_save_device(
        local_context_data={"sonic_config": {"PORT": {"Ethernet0": {}}}}
    )

    changed, diff_text = save_config_to_netbox(
        device, {"PORT": {"Ethernet1": {}}}, return_diff=True
    )

    assert changed is True
    # The unified diff names both the removed and the added port.
    assert "Ethernet0" in diff_text
    assert "Ethernet1" in diff_text
    device.save.assert_called_once_with()
    mock_nb.extras.journal_entries.create.assert_called_once()
    kwargs = mock_nb.extras.journal_entries.create.call_args.kwargs
    assert kwargs["assigned_object_type"] == "dcim.device"
    assert kwargs["assigned_object_id"] == device.id
    assert kwargs["kind"] == "info"
    assert "```diff" in kwargs["comments"]


def test_save_config_change_bool_form(mock_nb):
    """Without ``return_diff`` the changed path returns a bare ``True``."""
    device = _make_save_device(
        local_context_data={"sonic_config": {"PORT": {"Ethernet0": {}}}}
    )

    result = save_config_to_netbox(device, {"PORT": {"Ethernet1": {}}})

    assert result is True


def test_save_config_preserves_sibling_context_keys(mock_nb):
    """Only the ``sonic_config`` key is owned — sibling keys like
    ``frr_parameters`` must survive a config update untouched."""
    frr = {"asn": 4200000001, "loopback": "10.0.0.1"}
    device = _make_save_device(
        local_context_data={
            "frr_parameters": frr,
            "sonic_config": {"PORT": {"Ethernet0": {}}},
        }
    )

    result = save_config_to_netbox(device, {"PORT": {"Ethernet1": {}}})

    assert result is True
    device.save.assert_called_once_with()
    assert device.local_context_data == {
        "frr_parameters": frr,
        "sonic_config": {"PORT": {"Ethernet1": {}}},
    }


def test_save_config_sibling_only_context_is_first_time(mock_nb):
    """A context holding only sibling keys has no ``sonic_config`` to diff:
    the first-time path adds the key and keeps the siblings."""
    frr = {"asn": 4200000001}
    device = _make_save_device(local_context_data={"frr_parameters": frr})

    result = save_config_to_netbox(device, {"PORT": {}}, return_diff=True)

    assert result == (True, None)
    device.save.assert_called_once_with()
    assert device.local_context_data == {
        "frr_parameters": frr,
        "sonic_config": {"PORT": {}},
    }
    # First-time configuration creates no journal entry.
    mock_nb.extras.journal_entries.create.assert_not_called()


def test_save_config_sibling_keys_do_not_trigger_change(mock_nb):
    """Diffing covers only ``sonic_config`` — sibling keys must not register
    as removals and force a save when the SONiC config itself is unchanged."""
    config = {"PORT": {"Ethernet0": {}}}
    device = _make_save_device(
        local_context_data={"frr_parameters": {"asn": 1}, "sonic_config": config}
    )

    result = save_config_to_netbox(device, config)

    assert result is False
    device.save.assert_not_called()


def test_save_config_journal_failure_still_saves(mock_nb, loguru_logs):
    """A failing journal create is logged but must not block the save."""
    mock_nb.extras.journal_entries.create.side_effect = RuntimeError("journal down")
    device = _make_save_device(
        local_context_data={"sonic_config": {"PORT": {"Ethernet0": {}}}}
    )

    changed, diff_text = save_config_to_netbox(
        device, {"PORT": {"Ethernet1": {}}}, return_diff=True
    )

    assert changed is True
    assert diff_text is not None
    device.save.assert_called_once_with()
    assert _has_log(loguru_logs, "ERROR", "Failed to save diff to journal")


def test_save_config_save_failure_raises(mock_nb, loguru_logs):
    """A raising ``device.save()`` is logged and re-raised so a failed save
    stays distinguishable from "no changes" at the task layer."""
    device = _make_save_device(local_context_data=None)
    device.save.side_effect = RuntimeError("netbox write failed")

    with pytest.raises(RuntimeError, match="netbox write failed"):
        save_config_to_netbox(device, {"PORT": {}}, return_diff=True)

    assert _has_log(loguru_logs, "ERROR", "Failed to save local context")


def test_save_config_changed_path_save_failure_creates_no_journal(mock_nb, loguru_logs):
    """A failed save on the changed path must not leave an orphaned journal
    entry claiming the update succeeded — journal creation follows the save."""
    device = _make_save_device(
        local_context_data={"sonic_config": {"PORT": {"Ethernet0": {}}}}
    )
    device.save.side_effect = RuntimeError("netbox write failed")

    with pytest.raises(RuntimeError, match="netbox write failed"):
        save_config_to_netbox(device, {"PORT": {"Ethernet1": {}}}, return_diff=True)

    mock_nb.extras.journal_entries.create.assert_not_called()
    assert _has_log(loguru_logs, "ERROR", "Failed to save local context")


# ---------------------------------------------------------------------------
# export_config_to_file
# ---------------------------------------------------------------------------


@pytest.fixture
def export_settings(mocker):
    """Patch the four ``SONIC_EXPORT_*`` settings exporter reads at call time."""

    def _set(
        export_dir,
        identifier="serial-number",
        prefix="osism_",
        suffix="_config_db.json",
    ):
        mocker.patch(
            "osism.tasks.conductor.sonic.exporter.settings.SONIC_EXPORT_DIR",
            str(export_dir),
        )
        mocker.patch(
            "osism.tasks.conductor.sonic.exporter.settings.SONIC_EXPORT_PREFIX",
            prefix,
        )
        mocker.patch(
            "osism.tasks.conductor.sonic.exporter.settings.SONIC_EXPORT_SUFFIX",
            suffix,
        )
        mocker.patch(
            "osism.tasks.conductor.sonic.exporter.settings.SONIC_EXPORT_IDENTIFIER",
            identifier,
        )

    return _set


@pytest.fixture
def patch_hostname(mocker):
    """Pin ``get_device_hostname`` so filenames are deterministic."""
    return mocker.patch(
        "osism.tasks.conductor.sonic.exporter.get_device_hostname",
        return_value="sw-1",
    )


# --- filename selection -----------------------------------------------------


def test_export_hostname_identifier_uses_hostname(
    tmp_path, export_settings, patch_hostname
):
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    config = {"PORT": {"Ethernet0": {}}}

    assert export_config_to_file(device, config) is True

    target = tmp_path / "osism_sw-1_config_db.json"
    assert target.exists()
    assert json.loads(target.read_text()) == config


def test_export_serial_identifier_uses_serial(
    tmp_path, export_settings, patch_hostname
):
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")

    assert export_config_to_file(device, {"PORT": {}}) is True

    assert (tmp_path / "osism_ABC123_config_db.json").exists()


@pytest.mark.parametrize("serial", ["", None])
def test_export_serial_missing_falls_back_to_hostname(
    tmp_path, export_settings, patch_hostname, loguru_logs, serial
):
    """An empty or absent serial in serial-number mode warns and uses hostname,
    and the symlink branch is skipped entirely (debug logged)."""
    export_settings(tmp_path, identifier="serial-number")
    device = (
        SimpleNamespace(name="sw-1", serial=serial)
        if serial is not None
        else SimpleNamespace(name="sw-1")
    )

    assert export_config_to_file(device, {"PORT": {}}) is True

    target = tmp_path / "osism_sw-1_config_db.json"
    assert target.exists()
    assert not target.is_symlink()
    assert _has_log(loguru_logs, "WARNING", "Serial number not found")
    assert _has_log(loguru_logs, "DEBUG", "Symlink conditions not met")


# --- diff handling ----------------------------------------------------------


def test_export_no_change_returns_false(tmp_path, export_settings, patch_hostname):
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    config = {"PORT": {"Ethernet0": {}}}
    (tmp_path / "osism_sw-1_config_db.json").write_text(json.dumps(config))

    assert export_config_to_file(device, config) is False


def test_export_changed_content_rewrites_file(
    tmp_path, export_settings, patch_hostname
):
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    target = tmp_path / "osism_sw-1_config_db.json"
    target.write_text(json.dumps({"PORT": {"Ethernet9": {}}}))
    new_config = {"PORT": {"Ethernet0": {}}}

    assert export_config_to_file(device, new_config) is True
    assert json.loads(target.read_text()) == new_config


def test_export_unreadable_file_is_overwritten(
    tmp_path, export_settings, patch_hostname, loguru_logs
):
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    target = tmp_path / "osism_sw-1_config_db.json"
    target.write_text("not valid json {")
    new_config = {"PORT": {"Ethernet0": {}}}

    assert export_config_to_file(device, new_config) is True
    assert json.loads(target.read_text()) == new_config
    assert _has_log(loguru_logs, "WARNING", "Could not read existing config file")


def test_export_write_failure_preserves_previous_export(
    tmp_path, export_settings, patch_hostname, mocker, loguru_logs
):
    """The export is written atomically: a mid-write failure must leave the
    previous export intact instead of truncating it, and not leak a temp file."""
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    target = tmp_path / "osism_sw-1_config_db.json"
    old_config = {"PORT": {"Ethernet9": {}}}
    target.write_text(json.dumps(old_config))
    mocker.patch(
        "osism.tasks.conductor.sonic.exporter.json.dump",
        side_effect=OSError("no space left on device"),
    )

    with pytest.raises(OSError, match="no space left on device"):
        export_config_to_file(device, {"PORT": {"Ethernet0": {}}})

    assert json.loads(target.read_text()) == old_config
    assert not (tmp_path / "osism_sw-1_config_db.json.tmp").exists()
    assert _has_log(loguru_logs, "ERROR", "Failed to export config")


# --- symlink handling -------------------------------------------------------


def test_export_creates_symlink_when_hostname_absent(
    tmp_path, export_settings, patch_hostname
):
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")

    assert export_config_to_file(device, {"PORT": {}}) is True

    link = tmp_path / "osism_sw-1_config_db.json"
    assert link.is_symlink()
    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_replaces_existing_regular_file_with_symlink(
    tmp_path, export_settings, patch_hostname
):
    """A regular file at the hostname path is removed before the symlink is
    created — observable because the path ends up as a symlink, not a file."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    link = tmp_path / "osism_sw-1_config_db.json"
    link.write_text("stale regular file")

    assert export_config_to_file(device, {"PORT": {}}) is True

    assert link.is_symlink()
    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_replaces_dangling_symlink(tmp_path, export_settings, patch_hostname):
    """A dangling symlink (``exists`` False, ``islink`` True) is removed and
    repointed at the serial-number file."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    link = tmp_path / "osism_sw-1_config_db.json"
    link.symlink_to("does_not_exist_target")
    assert not os.path.exists(link) and os.path.islink(link)

    assert export_config_to_file(device, {"PORT": {}}) is True

    assert link.is_symlink()
    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_unchanged_config_repairs_missing_symlink(
    tmp_path, export_settings, patch_hostname
):
    """Symlink reconciliation is independent of a content change: an unchanged
    config with a missing hostname link still gets the link created."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    config = {"PORT": {"Ethernet0": {}}}
    (tmp_path / "osism_ABC123_config_db.json").write_text(json.dumps(config))

    assert export_config_to_file(device, config) is False

    link = tmp_path / "osism_sw-1_config_db.json"
    assert link.is_symlink()
    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_unchanged_config_repoints_stale_symlink(
    tmp_path, export_settings, patch_hostname
):
    """A hostname link pointing at the wrong target is repointed even when
    the exported content is unchanged."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    config = {"PORT": {"Ethernet0": {}}}
    (tmp_path / "osism_ABC123_config_db.json").write_text(json.dumps(config))
    link = tmp_path / "osism_sw-1_config_db.json"
    link.symlink_to("osism_OTHER_config_db.json")

    assert export_config_to_file(device, config) is False

    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_existing_correct_symlink_left_untouched(
    tmp_path, export_settings, patch_hostname, mocker
):
    """A link that already points at the config file is not removed and
    recreated on every run."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="ABC123")
    config = {"PORT": {"Ethernet0": {}}}
    (tmp_path / "osism_ABC123_config_db.json").write_text(json.dumps(config))
    link = tmp_path / "osism_sw-1_config_db.json"
    link.symlink_to("osism_ABC123_config_db.json")
    remove_spy = mocker.spy(os, "remove")
    symlink_spy = mocker.spy(os, "symlink")

    assert export_config_to_file(device, config) is False

    remove_spy.assert_not_called()
    symlink_spy.assert_not_called()
    assert os.readlink(link) == "osism_ABC123_config_db.json"


def test_export_hostname_equals_serial_keeps_config_file(
    tmp_path, export_settings, patch_hostname
):
    """When the serial equals the hostname the config file already lives at
    the hostname path — no self-referential symlink may replace it."""
    export_settings(tmp_path, identifier="serial-number")
    device = SimpleNamespace(name="sw-1", serial="sw-1")
    config = {"PORT": {"Ethernet0": {}}}

    assert export_config_to_file(device, config) is True

    target = tmp_path / "osism_sw-1_config_db.json"
    assert target.exists()
    assert not target.is_symlink()
    assert json.loads(target.read_text()) == config


def test_export_symlink_failure_still_returns_true(
    tmp_path, export_settings, patch_hostname, mocker, loguru_logs
):
    """A failing ``os.symlink`` is logged but the written config still counts
    as a change (the file was exported successfully)."""
    export_settings(tmp_path, identifier="serial-number")
    mocker.patch(
        "osism.tasks.conductor.sonic.exporter.os.symlink",
        side_effect=OSError("permission denied"),
    )
    device = SimpleNamespace(name="sw-1", serial="ABC123")

    assert export_config_to_file(device, {"PORT": {}}) is True

    assert (tmp_path / "osism_ABC123_config_db.json").exists()
    assert _has_log(loguru_logs, "ERROR", "Failed to create hostname symlink")


def test_export_hostname_mode_makes_no_symlink(
    tmp_path, export_settings, patch_hostname
):
    export_settings(tmp_path, identifier="hostname")
    device = SimpleNamespace(name="sw-1", serial="ABC123")

    assert export_config_to_file(device, {"PORT": {}}) is True

    target = tmp_path / "osism_sw-1_config_db.json"
    assert target.exists()
    assert not target.is_symlink()


# --- error handling ---------------------------------------------------------


def test_export_makedirs_failure_raises(
    tmp_path, export_settings, patch_hostname, mocker, loguru_logs
):
    export_settings(tmp_path, identifier="hostname")
    mocker.patch(
        "osism.tasks.conductor.sonic.exporter.os.makedirs",
        side_effect=OSError("read-only filesystem"),
    )
    device = SimpleNamespace(name="sw-1", serial="ABC123")

    with pytest.raises(OSError, match="read-only filesystem"):
        export_config_to_file(device, {"PORT": {}})

    assert _has_log(loguru_logs, "ERROR", "Failed to export config")
