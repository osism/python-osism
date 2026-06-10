# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.tasks.conductor.sonic.sync.sync_sonic``.

``sync_sonic`` is the orchestration entry point: it manages the cache
lifecycle, resolves the device set (single-device or NetBox-filtered),
computes spine/superspine AS mappings, and drives config generation, NetBox
persistence, and file export per device. Every heavy collaborator is stubbed
at its import site in ``sync`` so only the orchestration glue is exercised
here — ``find_interconnected_devices`` and ``generate_sonic_config`` have their
own coverage (see #2199) and are intentionally mocked.

``utils.nb`` is supplied by the shared ``mock_nb`` fixture (it patches
``osism.utils.nb``, which ``sync.utils.nb`` resolves to).
"""

from types import SimpleNamespace
from unittest.mock import call

import pytest

from osism.tasks.conductor.sonic.sync import sync_sonic


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def make_device(
    name="sw-1",
    device_id=1,
    role_slug="leaf",
    hwsku="Accton-AS7326-56X",
    config_version=None,
):
    """Build a NetBox-shaped device the orchestrator can consume.

    ``role_slug=None`` yields ``role=None``; ``hwsku=None`` yields an empty
    ``sonic_parameters`` so the HWSKU-missing branch is reachable.
    """
    params = {}
    if hwsku is not None:
        params["hwsku"] = hwsku
    if config_version is not None:
        params["config_version"] = config_version
    role = SimpleNamespace(slug=role_slug) if role_slug is not None else None
    return SimpleNamespace(
        id=device_id,
        name=name,
        serial="ABC",
        role=role,
        local_context_data=None,
        custom_fields={"sonic_parameters": params},
        config_context={},
    )


@pytest.fixture
def patch_sync_deps(mocker):
    """Stub every heavy collaborator ``sync_sonic`` imports.

    Returns a ``SimpleNamespace`` of the mocks so tests can tune individual
    return values / side effects. Each name is patched at its ``sync`` import
    site, not at its source module, so the rebound reference is the one that
    gets replaced.
    """

    def patch(name, **kw):
        return mocker.patch(f"osism.tasks.conductor.sonic.sync.{name}", **kw)

    return SimpleNamespace(
        get_nb_device_query_list_sonic=patch(
            "get_nb_device_query_list_sonic", return_value=[]
        ),
        find_interconnected_devices=patch(
            "find_interconnected_devices", return_value=[]
        ),
        calculate_minimum_as_for_group=patch(
            "calculate_minimum_as_for_group", return_value=None
        ),
        generate_sonic_config=patch(
            "generate_sonic_config", return_value={"PORT": {"Ethernet0": {}}}
        ),
        save_config_to_netbox=patch("save_config_to_netbox", return_value=(True, None)),
        export_config_to_file=patch("export_config_to_file", return_value=False),
        clear_interface_cache=patch("clear_interface_cache"),
        clear_all_caches=patch("clear_all_caches"),
        clear_vip_addresses_cache=patch("clear_vip_addresses_cache"),
        _load_metalbox_devices_cache=patch("_load_metalbox_devices_cache"),
        load_vip_addresses_cache=patch("load_vip_addresses_cache"),
        get_interface_cache_stats=patch("get_interface_cache_stats", return_value={}),
        push_task_output=patch("utils.push_task_output"),
        finish_task_output=patch("utils.finish_task_output"),
    )


# ---------------------------------------------------------------------------
# Cache lifecycle
# ---------------------------------------------------------------------------


def test_cache_lifecycle_clears_in_order(mock_nb, patch_sync_deps, mocker):
    """Caches are cleared at start (interface, all) and end (interface, all,
    vip), with the two cache loads in between — pinned as an exact sequence."""
    deps = patch_sync_deps
    manager = mocker.Mock()
    manager.attach_mock(deps.clear_interface_cache, "clear_interface_cache")
    manager.attach_mock(deps.clear_all_caches, "clear_all_caches")
    manager.attach_mock(deps.clear_vip_addresses_cache, "clear_vip_addresses_cache")
    manager.attach_mock(deps._load_metalbox_devices_cache, "load_metalbox")
    manager.attach_mock(deps.load_vip_addresses_cache, "load_vip")

    sync_sonic()

    assert manager.mock_calls == [
        call.clear_interface_cache(),
        call.clear_all_caches(),
        call.load_metalbox(),
        call.load_vip(),
        call.clear_interface_cache(),
        call.clear_all_caches(),
        call.clear_vip_addresses_cache(),
    ]


def test_caches_loaded_once_per_invocation(mock_nb, patch_sync_deps):
    deps = patch_sync_deps

    sync_sonic()

    deps._load_metalbox_devices_cache.assert_called_once_with()
    deps.load_vip_addresses_cache.assert_called_once_with()


# ---------------------------------------------------------------------------
# Single-device path
# ---------------------------------------------------------------------------


def test_single_device_allowed_role_is_processed(mock_nb, patch_sync_deps):
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    assert result == {"sw-1": {"PORT": {"Ethernet0": {}}}}


def test_single_device_disallowed_role_returns_empty(
    mock_nb, patch_sync_deps, loguru_logs
):
    device = make_device(name="sw-1", role_slug="router")
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    assert result == {}
    patch_sync_deps.generate_sonic_config.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "not in allowed SONiC roles")


def test_single_device_role_none_returns_empty(mock_nb, patch_sync_deps, loguru_logs):
    device = make_device(name="sw-1", role_slug=None)
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    assert result == {}
    assert _has_log(loguru_logs, "WARNING", "role 'None'")


def test_single_device_not_found_returns_empty(mock_nb, patch_sync_deps, loguru_logs):
    mock_nb.dcim.devices.get.return_value = None

    result = sync_sonic(device_name="missing")

    assert result == {}
    assert _has_log(loguru_logs, "ERROR", "not found in NetBox")


def test_single_device_lookup_raises_returns_empty(
    mock_nb, patch_sync_deps, loguru_logs
):
    mock_nb.dcim.devices.get.side_effect = RuntimeError("netbox down")

    result = sync_sonic(device_name="sw-1")

    assert result == {}
    assert _has_log(loguru_logs, "ERROR", "Error fetching device")


def test_single_spine_fetches_all_spine_devices(mock_nb, patch_sync_deps):
    """A single spine triggers a full spine/superspine fetch for group
    detection, so ``nb.dcim.devices.filter`` runs via the query list."""
    deps = patch_sync_deps
    device = make_device(name="spine-1", role_slug="spine")
    mock_nb.dcim.devices.get.return_value = device
    deps.get_nb_device_query_list_sonic.return_value = [{"status": "active"}]
    mock_nb.dcim.devices.filter.return_value = [device]

    sync_sonic(device_name="spine-1")

    mock_nb.dcim.devices.filter.assert_called_once_with(status="active")
    deps.find_interconnected_devices.assert_called_once_with(
        [device], ["spine", "superspine"]
    )


def test_single_leaf_uses_device_list_without_extra_fetch(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="leaf-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device

    sync_sonic(device_name="leaf-1")

    mock_nb.dcim.devices.filter.assert_not_called()
    deps.find_interconnected_devices.assert_called_once_with(
        [device], ["spine", "superspine"]
    )


# ---------------------------------------------------------------------------
# Multi-device path
# ---------------------------------------------------------------------------


def test_multi_device_keeps_only_allowed_roles(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    leaf = make_device(name="leaf-1", device_id=1, role_slug="leaf")
    router = make_device(name="router-1", device_id=2, role_slug="router")
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [leaf, router]

    result = sync_sonic()

    assert "leaf-1" in result
    assert "router-1" not in result


def test_multi_device_skips_devices_without_role(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    leaf = make_device(name="leaf-1", device_id=1, role_slug="leaf")
    norole = make_device(name="x-1", device_id=2, role_slug=None)
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [norole, leaf]

    result = sync_sonic()

    assert set(result) == {"leaf-1"}


# ---------------------------------------------------------------------------
# Per-device processing
# ---------------------------------------------------------------------------


def test_hwsku_missing_skips_device(mock_nb, patch_sync_deps, loguru_logs):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf", hwsku=None)
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    assert result == {}
    deps.generate_sonic_config.assert_not_called()
    assert _has_log(loguru_logs, "DEBUG", "no HWSKU configured")


def test_hwsku_unsupported_skips_device(mock_nb, patch_sync_deps, loguru_logs):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf", hwsku="Bogus-HWSKU")
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    assert result == {}
    deps.generate_sonic_config.assert_not_called()
    assert _has_log(loguru_logs, "WARNING", "unsupported HWSKU")


def test_hwsku_valid_generates_and_stores_config(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device

    result = sync_sonic(device_name="sw-1")

    deps.generate_sonic_config.assert_called_once_with(
        device, "Accton-AS7326-56X", {}, None
    )
    assert result == {"sw-1": {"PORT": {"Ethernet0": {}}}}


def test_config_version_read_from_custom_fields(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf", config_version="4_2_0")
    mock_nb.dcim.devices.get.return_value = device

    sync_sonic(device_name="sw-1")

    assert deps.generate_sonic_config.call_args.args[3] == "4_2_0"


# ---------------------------------------------------------------------------
# AS mapping
# ---------------------------------------------------------------------------


def test_as_mapping_calculated_per_spine_group(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    g1 = make_device(name="spine-1", device_id=1, role_slug="spine")
    g2 = make_device(name="spine-2", device_id=2, role_slug="spine")
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [g1, g2]
    deps.find_interconnected_devices.return_value = [[g1], [g2]]
    deps.calculate_minimum_as_for_group.side_effect = [4200000001, 4200000002]

    sync_sonic()

    assert deps.calculate_minimum_as_for_group.call_count == 2
    # The full mapping is handed to every per-device generation call.
    assert deps.generate_sonic_config.call_args_list[0].args[2] == {
        1: 4200000001,
        2: 4200000002,
    }


def test_as_mapping_passed_into_generate(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="leaf-1", device_id=7, role_slug="leaf")
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [device]
    deps.find_interconnected_devices.return_value = [[device]]
    deps.calculate_minimum_as_for_group.return_value = 4200000001

    sync_sonic()

    assert deps.generate_sonic_config.call_args.args == (
        device,
        "Accton-AS7326-56X",
        {7: 4200000001},
        None,
    )


def test_group_with_none_min_as_not_propagated(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="leaf-1", device_id=7, role_slug="leaf")
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [device]
    deps.find_interconnected_devices.return_value = [[device]]
    deps.calculate_minimum_as_for_group.return_value = None

    sync_sonic()

    assert deps.generate_sonic_config.call_args.args[2] == {}


# ---------------------------------------------------------------------------
# Diff handling
# ---------------------------------------------------------------------------


def test_diff_streamed_to_task_output(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.save_config_to_netbox.return_value = (True, "the-diff")

    sync_sonic(device_name="sw-1", task_id="t")

    deps.save_config_to_netbox.assert_called_once_with(
        device, {"PORT": {"Ethernet0": {}}}, return_diff=True
    )
    assert call("t", "the-diff\n") in deps.push_task_output.call_args_list


def test_first_time_configuration_message(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.save_config_to_netbox.return_value = (True, None)

    sync_sonic(device_name="sw-1", task_id="t")

    assert (
        call("t", "First-time configuration created for sw-1\n")
        in deps.push_task_output.call_args_list
    )


def test_no_change_skips_diff_output_but_still_exports(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.save_config_to_netbox.return_value = (False, None)

    sync_sonic(device_name="sw-1", task_id="t")

    deps.export_config_to_file.assert_called_once_with(
        device, {"PORT": {"Ethernet0": {}}}
    )
    # Only the "Processing device" line is pushed — no diff / first-time lines.
    assert deps.push_task_output.call_args_list == [
        call("t", "Processing device: sw-1\n")
    ]


def test_show_diff_false_calls_save_without_return_diff(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.save_config_to_netbox.return_value = True

    sync_sonic(device_name="sw-1", show_diff=False)

    deps.save_config_to_netbox.assert_called_once_with(
        device, {"PORT": {"Ethernet0": {}}}
    )


# ---------------------------------------------------------------------------
# Task output
# ---------------------------------------------------------------------------


def test_task_id_pushes_per_device_and_finishes(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device

    sync_sonic(device_name="sw-1", task_id="t")

    assert (
        call("t", "Processing device: sw-1\n") in deps.push_task_output.call_args_list
    )
    deps.finish_task_output.assert_called_once_with("t", rc=0)


def test_no_task_id_suppresses_task_output(mock_nb, patch_sync_deps):
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device

    sync_sonic(device_name="sw-1")

    deps.push_task_output.assert_not_called()
    deps.finish_task_output.assert_not_called()


# ---------------------------------------------------------------------------
# Failure handling and cleanup
# ---------------------------------------------------------------------------


def _assert_caches_cleaned(deps):
    """The end-of-run cleanup must have run: interface and generator caches
    are cleared a second time (after the initial clear) and the VIP cache once."""
    assert deps.clear_interface_cache.call_count == 2
    assert deps.clear_all_caches.call_count == 2
    deps.clear_vip_addresses_cache.assert_called_once_with()


@pytest.mark.parametrize("path", ["disallowed_role", "not_found", "lookup_raises"])
def test_early_return_cleans_caches_and_reports_failure(mock_nb, patch_sync_deps, path):
    """Single-device early returns happen after the module-level caches are
    loaded — cleanup and task finalization must still run, with rc=1."""
    deps = patch_sync_deps
    if path == "disallowed_role":
        mock_nb.dcim.devices.get.return_value = make_device(
            name="sw-1", role_slug="router"
        )
    elif path == "not_found":
        mock_nb.dcim.devices.get.return_value = None
    else:
        mock_nb.dcim.devices.get.side_effect = RuntimeError("netbox down")

    result = sync_sonic(device_name="sw-1", task_id="t")

    assert result == {}
    _assert_caches_cleaned(deps)
    deps.finish_task_output.assert_called_once_with("t", rc=1)


def test_mid_loop_exception_continues_and_reports_failure(
    mock_nb, patch_sync_deps, loguru_logs
):
    """A device failing mid-loop must not abort the remaining devices, must
    not leak the module-level caches, and must surface as rc=1."""
    deps = patch_sync_deps
    bad = make_device(name="bad-1", device_id=1, role_slug="leaf")
    good = make_device(name="good-1", device_id=2, role_slug="leaf")
    deps.get_nb_device_query_list_sonic.return_value = [{}]
    mock_nb.dcim.devices.filter.return_value = [bad, good]
    deps.generate_sonic_config.side_effect = [
        RuntimeError("generation failed"),
        {"PORT": {"Ethernet0": {}}},
    ]

    result = sync_sonic(task_id="t")

    assert result == {"good-1": {"PORT": {"Ethernet0": {}}}}
    _assert_caches_cleaned(deps)
    deps.finish_task_output.assert_called_once_with("t", rc=1)
    assert _has_log(
        loguru_logs, "ERROR", "Failed to sync SONiC configuration for device bad-1"
    )


def test_netbox_save_failure_reports_nonzero_rc(mock_nb, patch_sync_deps, loguru_logs):
    """A raising ``save_config_to_netbox`` must not finish the task as rc=0
    — a failed write is not "no changes"."""
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.save_config_to_netbox.side_effect = RuntimeError("netbox write failed")

    sync_sonic(device_name="sw-1", task_id="t")

    deps.export_config_to_file.assert_not_called()
    _assert_caches_cleaned(deps)
    deps.finish_task_output.assert_called_once_with("t", rc=1)
    assert _has_log(
        loguru_logs, "ERROR", "Failed to sync SONiC configuration for device sw-1"
    )


def test_file_export_failure_reports_nonzero_rc(mock_nb, patch_sync_deps, loguru_logs):
    """A raising ``export_config_to_file`` surfaces as rc=1 as well."""
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.export_config_to_file.side_effect = OSError("disk full")

    sync_sonic(device_name="sw-1", task_id="t")

    _assert_caches_cleaned(deps)
    deps.finish_task_output.assert_called_once_with("t", rc=1)
    assert _has_log(
        loguru_logs, "ERROR", "Failed to sync SONiC configuration for device sw-1"
    )


def test_config_without_port_section_is_handled(mock_nb, patch_sync_deps, loguru_logs):
    """A config lacking the PORT section must not raise in the summary log."""
    deps = patch_sync_deps
    device = make_device(name="sw-1", role_slug="leaf")
    mock_nb.dcim.devices.get.return_value = device
    deps.generate_sonic_config.return_value = {"VLAN": {}}

    result = sync_sonic(device_name="sw-1", task_id="t")

    assert result == {"sw-1": {"VLAN": {}}}
    deps.finish_task_output.assert_called_once_with("t", rc=0)
    assert _has_log(loguru_logs, "INFO", "with 0 ports")


# ---------------------------------------------------------------------------
# Cache stats
# ---------------------------------------------------------------------------


def test_cache_stats_logged_when_present(mock_nb, patch_sync_deps, loguru_logs):
    patch_sync_deps.get_interface_cache_stats.return_value = {
        "cached_devices": 2,
        "total_interfaces": 10,
    }

    sync_sonic()

    assert _has_log(
        loguru_logs, "DEBUG", "Interface cache stats: 2 devices, 10 interfaces"
    )


def test_cache_stats_not_logged_when_empty(mock_nb, patch_sync_deps, loguru_logs):
    patch_sync_deps.get_interface_cache_stats.return_value = {}

    sync_sonic()

    assert not _has_log(loguru_logs, "DEBUG", "Interface cache stats")
