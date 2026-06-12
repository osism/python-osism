# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the four sync orchestrators in ``conductor/ironic.py``.

The functions under test are large state machines that drive Ironic provision
state transitions from NetBox device data. The tests focus on the state
transitions and branch coverage rather than the exact ``push_task_output``
strings (those are asserted via substrings only).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from osism.tasks.conductor import ironic

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    uuid="uuid-1",
    name="node1",
    provision_state="available",
    power_state="power off",
    automated_clean=False,
    instance_uuid=None,
    is_maintenance=False,
):
    """Build an Ironic node as a plain dict (Ironic returns dict-like objects)."""
    return {
        "uuid": uuid,
        "name": name,
        "provision_state": provision_state,
        "power_state": power_state,
        "automated_clean": automated_clean,
        "instance_uuid": instance_uuid,
        "is_maintenance": is_maintenance,
    }


def _make_device(name="node1", provision_state=None, **custom_fields):
    """Build a NetBox device stand-in with a ``custom_fields`` dict."""
    fields = {"provision_state": provision_state}
    fields.update(custom_fields)
    return SimpleNamespace(name=name, custom_fields=fields)


def _validation(management=True, boot=True, mgmt_reason="", boot_reason=""):
    """Build the dict returned by ``baremetal_node_validate``.

    Each entry exposes ``.result`` and ``.reason`` like the real SDK object.
    """
    return {
        "management": SimpleNamespace(result=management, reason=mgmt_reason),
        "boot": SimpleNamespace(result=boot, reason=boot_reason),
    }


def _wire_lifecycle(openstack, power_state="power off", automated_clean=False):
    """Wire the openstack mock so provision-state calls echo the target state.

    ``baremetal_node_wait_for_nodes_provision_state(uuid, state)`` returns a
    node whose ``provision_state`` equals ``state`` -- this mirrors the real
    state machine, where the node ends up in the state it was told to wait
    for. ``power_state`` and ``automated_clean`` carry the per-test template.
    """

    def _node(provision_state):
        return _make_node(
            provision_state=provision_state,
            power_state=power_state,
            automated_clean=automated_clean,
        )

    openstack.baremetal_node_set_provision_state.side_effect = (
        lambda uuid, state: _node(state)
    )
    openstack.baremetal_node_wait_for_nodes_provision_state.side_effect = (
        lambda uuid, state: _node(state)
    )
    openstack.baremetal_node_set_power_state.side_effect = (
        lambda uuid, state, **kwargs: _make_node(
            provision_state="manageable",
            power_state=state,
            automated_clean=automated_clean,
        )
    )
    openstack.baremetal_node_update.side_effect = lambda uuid, attrs: _make_node(
        provision_state="manageable",
        power_state=power_state,
        automated_clean=attrs.get("automated_clean", automated_clean),
    )


def _messages(osism_utils):
    """Return all message strings passed to ``push_task_output``."""
    return [call.args[1] for call in osism_utils.push_task_output.call_args_list]


def _pushed(osism_utils, substring):
    """True if any ``push_task_output`` message contains ``substring``."""
    return any(substring in message for message in _messages(osism_utils))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def osism_utils(mocker):
    """Patch the module-level ``osism_utils`` import."""
    return mocker.patch("osism.tasks.conductor.ironic.osism_utils")


@pytest.fixture
def openstack(mocker):
    """Patch the module-level ``openstack`` import with sane defaults."""
    mock = mocker.patch("osism.tasks.conductor.ironic.openstack")
    mock.baremetal_port_list.return_value = []
    mock.baremetal_node_set_target_raid_config.return_value = (True, "")
    mock.baremetal_node_validate.return_value = _validation()
    _wire_lifecycle(mock)
    return mock


@pytest.fixture
def deep_compare(mocker):
    """Patch ``deep_compare``; by default it leaves ``node_updates`` empty."""
    return mocker.patch("osism.tasks.conductor.ironic.deep_compare")


@pytest.fixture
def mask_secrets(mocker):
    """Patch ``mask_secrets`` with a JSON-serialisable pass-through."""
    return mocker.patch(
        "osism.tasks.conductor.ironic.mask_secrets",
        side_effect=lambda obj, secret_values=None: obj,
    )


# ===========================================================================
# _sync_ironic_device -- node creation path
# ===========================================================================


def test_create_node_when_show_returns_none(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = None
    openstack.baremetal_node_create.return_value = _make_node(provision_state="enroll")
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    node_attributes = {"driver": "redfish"}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=False
    )

    openstack.baremetal_node_create.assert_called_once_with(
        "node1", {"automated_clean": False, "driver": "redfish"}
    )


def test_create_path_sets_target_raid_config(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = None
    openstack.baremetal_node_create.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    deep_compare.side_effect = lambda a, b, updates: updates.update(
        {"target_raid_config": {"x": 1}, "name": "node1"}
    )
    node_attributes = {"driver": "redfish", "target_raid_config": {"x": 1}}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_target_raid_config.assert_called_once_with(
        "uuid-1", {"x": 1}
    )


def test_target_raid_config_failure_raises(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = None
    openstack.baremetal_node_create.return_value = _make_node()
    openstack.baremetal_node_set_target_raid_config.return_value = (False, "error")
    deep_compare.side_effect = lambda a, b, updates: updates.update(
        {"target_raid_config": {"x": 1}}
    )
    node_attributes = {"driver": "redfish", "target_raid_config": {"x": 1}}

    with pytest.raises(Exception, match="target_raid_config"):
        ironic._sync_ironic_device(
            "req", _make_device(), node_attributes, [], adopt=False, force=False
        )


# ===========================================================================
# _sync_ironic_device -- node update path
# ===========================================================================


def test_update_called_with_full_node_attributes(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    deep_compare.side_effect = lambda a, b, updates: updates.update({"name": "changed"})
    node_attributes = {"driver": "redfish", "name": "changed"}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=False
    )

    openstack.baremetal_node_update.assert_called_once_with("uuid-1", node_attributes)


def test_driver_password_only_change_skips_update(osism_utils, openstack, deep_compare):
    # The password key is resolved via driver_params[driver]["password"] and
    # popped before evaluating the change. When it was the only driver_info
    # delta, driver_info is dropped entirely; with no other updates and
    # force=False the node is not updated at all.
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    deep_compare.side_effect = lambda a, b, updates: updates.update(
        {"driver_info": {"redfish_password": "secret"}}
    )
    node_attributes = {"driver": "redfish"}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=False
    )

    openstack.baremetal_node_update.assert_not_called()


def test_driver_info_with_other_change_still_updates(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    deep_compare.side_effect = lambda a, b, updates: updates.update(
        {"driver_info": {"redfish_password": "secret", "redfish_address": "1.2.3.4"}}
    )
    node_attributes = {"driver": "redfish"}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=False
    )

    openstack.baremetal_node_update.assert_called_once()


def test_force_update_with_no_changes_still_updates(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    node_attributes = {"driver": "redfish"}

    ironic._sync_ironic_device(
        "req", _make_device(), node_attributes, [], adopt=False, force=True
    )

    openstack.baremetal_node_update.assert_called_once()
    openstack.baremetal_node_set_target_raid_config.assert_not_called()


# ===========================================================================
# _sync_ironic_device -- port reconciliation
# ===========================================================================


def test_extra_port_deleted_and_match_is_case_insensitive(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    openstack.baremetal_port_list.return_value = [
        {"id": "p1", "address": "AA:BB:CC:DD:EE:01"},
        {"id": "p2", "address": "AA:BB:CC:DD:EE:02"},
    ]
    # Lower-case MAC matches the upper-case stored port -> only p2 is stale.
    ports_attributes = [{"address": "aa:bb:cc:dd:ee:01"}]

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, ports_attributes, False, False
    )

    openstack.baremetal_port_delete.assert_called_once_with("p2")
    openstack.baremetal_port_create.assert_not_called()


def test_new_port_created(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_node_validate.return_value = _validation(management=False)
    openstack.baremetal_port_list.return_value = []
    ports_attributes = [{"address": "aa:bb:cc:dd:ee:99"}]

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, ports_attributes, False, False
    )

    openstack.baremetal_port_create.assert_called_once()
    created = openstack.baremetal_port_create.call_args.args[0]
    assert created["node_id"] == "uuid-1"
    openstack.baremetal_port_delete.assert_not_called()


# ===========================================================================
# _sync_ironic_device -- validation + provisioning transitions
# ===========================================================================


def test_management_validation_failure_returns_early(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node(provision_state="enroll")
    openstack.baremetal_node_validate.return_value = _validation(management=False)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_not_called()
    assert _pushed(osism_utils, "Validation of management interface failed")


def test_enroll_state_transitioned_to_manageable(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node(provision_state="enroll")
    openstack.baremetal_node_validate.return_value = _validation(boot=False)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "manage"
    )
    openstack.baremetal_node_wait_for_nodes_provision_state.assert_called_once_with(
        "uuid-1", "manageable"
    )


def test_clean_failed_state_transitioned_to_manage(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="clean failed"
    )
    openstack.baremetal_node_validate.return_value = _validation(boot=False)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_any_call("uuid-1", "manage")


def test_power_state_forced_off_after_manageable(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="enroll", power_state="power on"
    )
    _wire_lifecycle(openstack, power_state="power on")
    openstack.baremetal_node_validate.return_value = _validation(boot=False)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_power_state.assert_called_once_with(
        "uuid-1", "power off", wait=True, timeout=300
    )


def test_boot_failure_on_available_demotes_to_manageable(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node(provision_state="available")
    openstack.baremetal_node_validate.return_value = _validation(boot=False)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "manage"
    )
    openstack.baremetal_node_wait_for_nodes_provision_state.assert_called_once_with(
        "uuid-1", "manageable"
    )


def test_adopt_manageable_node(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="manageable", automated_clean=True
    )
    _wire_lifecycle(openstack, automated_clean=True)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=True, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "adopt"
    )
    openstack.baremetal_node_wait_for_nodes_provision_state.assert_called_once_with(
        "uuid-1", "active"
    )


def test_adoption_derived_from_custom_field_active(
    osism_utils, openstack, deep_compare
):
    # is_adoption = adopt or custom_fields["provision_state"] == "active"
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="manageable", automated_clean=True
    )
    _wire_lifecycle(openstack, automated_clean=True)
    device = _make_device(provision_state="active")

    ironic._sync_ironic_device(
        "req", device, {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "adopt"
    )


def test_adopt_available_node_prepared_via_manageable(
    osism_utils, openstack, deep_compare
):
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="available", automated_clean=True
    )
    _wire_lifecycle(openstack, automated_clean=True)

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=True, force=False
    )

    openstack.baremetal_node_set_provision_state.assert_any_call("uuid-1", "manage")
    openstack.baremetal_node_set_provision_state.assert_any_call("uuid-1", "adopt")
    assert _pushed(osism_utils, "Prepare adoption")


def test_normal_path_manageable_to_available(osism_utils, openstack, deep_compare):
    # Start automated_clean=True so the skip-cleaning branch fires, then the
    # post-available re-enable branch sets it back to True.
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="manageable", automated_clean=True
    )

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    openstack.baremetal_node_set_boot_device.assert_called_once_with(
        "uuid-1", "cdrom", persistent=False
    )
    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "provide"
    )
    openstack.baremetal_node_wait_for_nodes_provision_state.assert_called_once_with(
        "uuid-1", "available"
    )
    update_calls = [
        call.args[1] for call in openstack.baremetal_node_update.call_args_list
    ]
    assert {"automated_clean": False} in update_calls
    assert {"automated_clean": True} in update_calls


def test_set_boot_device_failure_is_caught(osism_utils, openstack, deep_compare):
    openstack.baremetal_node_show.return_value = _make_node(
        provision_state="manageable"
    )
    openstack.baremetal_node_set_boot_device.side_effect = Exception("boom")

    ironic._sync_ironic_device(
        "req", _make_device(), {"driver": "redfish"}, [], adopt=False, force=False
    )

    assert _pushed(osism_utils, "Could not set boot device")
    # Transition continues despite the boot-device failure.
    openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "uuid-1", "provide"
    )


# ===========================================================================
# _sync_ironic_device_dry_run
# ===========================================================================


def test_dry_run_collects_secret_values(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = None
    template_vars = {
        "redfish_password": "topsecret",
        "some_secret": "abc",
        "ironic_osism_token": "tok",
        "normalkey": "plain",
        "intval": 123,
    }

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(), {"driver": "redfish"}, [], False, False, template_vars
    )

    expected = {"topsecret", "abc", "tok"}
    mask_secrets.assert_any_call({"driver": "redfish"}, secret_values=expected)
    mask_secrets.assert_any_call(template_vars, secret_values=expected)


def test_dry_run_create_branch_messages(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = None
    ports_attributes = [{"address": "AA:BB:CC:DD:EE:01"}]
    device = _make_device(provision_state="enroll")

    ironic._sync_ironic_device_dry_run(
        "req", device, {"driver": "redfish"}, ports_attributes, False, False, {}
    )

    assert _pushed(osism_utils, "Would CREATE baremetal node")
    assert _pushed(osism_utils, "Would CREATE port with MAC AA:BB:CC:DD:EE:01")
    assert _pushed(osism_utils, "Would try to transition node to `available`")


def test_dry_run_create_branch_adopt_message(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = None

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(provision_state="enroll"), {}, [], True, False, {}
    )

    assert _pushed(osism_utils, "Would try to adopt node")


def test_dry_run_create_branch_active_implies_adopt(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = None

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(provision_state="active"), {}, [], False, False, {}
    )

    assert _pushed(osism_utils, "Would try to adopt node")


def test_dry_run_update_branch_reports_update(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = _make_node(provision_state="available")
    deep_compare.side_effect = lambda a, b, updates: updates.update({"name": "changed"})

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(), {"driver": "redfish"}, [], False, False, {}
    )

    assert _pushed(osism_utils, "Would UPDATE baremetal node")
    assert _pushed(osism_utils, "Current provision_state for node1: available")


def test_dry_run_update_branch_no_update_needed(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = _make_node()

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(), {"driver": "redfish"}, [], False, False, {}
    )

    assert _pushed(osism_utils, "no update needed")


def test_dry_run_update_branch_port_reconciliation(
    osism_utils, openstack, deep_compare, mask_secrets
):
    openstack.baremetal_node_show.return_value = _make_node()
    openstack.baremetal_port_list.return_value = [
        {"id": "p1", "address": "AA:BB:CC:DD:EE:01"},
        {"id": "p2", "address": "AA:BB:CC:DD:EE:02"},
    ]
    # One existing match, one new MAC -> create; the unmatched p2 -> delete.
    ports_attributes = [
        {"address": "aa:bb:cc:dd:ee:01"},
        {"address": "aa:bb:cc:dd:ee:99"},
    ]

    ironic._sync_ironic_device_dry_run(
        "req", _make_device(), {"driver": "redfish"}, ports_attributes, False, False, {}
    )

    assert _pushed(osism_utils, "Would CREATE port with MAC aa:bb:cc:dd:ee:99")
    assert _pushed(osism_utils, "Would DELETE port with MAC AA:BB:CC:DD:EE:02")


# ===========================================================================
# sync_ironic
# ===========================================================================


@pytest.fixture
def sync_env(mocker):
    """Patch every collaborator of ``sync_ironic`` with workable defaults."""
    utils = mocker.patch("osism.tasks.conductor.ironic.osism_utils")
    openstack = mocker.patch("osism.tasks.conductor.ironic.openstack")
    netbox = mocker.patch("osism.tasks.conductor.ironic.netbox")
    prepare = mocker.patch("osism.tasks.conductor.ironic._prepare_node_attributes")
    sync_device = mocker.patch("osism.tasks.conductor.ironic._sync_ironic_device")
    sync_dry = mocker.patch("osism.tasks.conductor.ironic._sync_ironic_device_dry_run")
    query = mocker.patch("osism.tasks.conductor.ironic.get_nb_device_query_list_ironic")

    lock = MagicMock(acquire=MagicMock(return_value=True), release=MagicMock())
    utils.create_redlock.return_value = lock
    utils.nb.status.return_value = None
    openstack.baremetal_node_list.return_value = []
    openstack.baremetal_port_list.return_value = []
    netbox.get_devices.return_value = []
    netbox.get_interfaces_by_device.return_value = []
    prepare.return_value = ({"driver": "redfish"}, {})
    query.return_value = [{}]

    return SimpleNamespace(
        utils=utils,
        openstack=openstack,
        netbox=netbox,
        prepare=prepare,
        sync_device=sync_device,
        sync_dry=sync_dry,
        query=query,
        lock=lock,
    )


def test_sync_ironic_netbox_unreachable(sync_env):
    sync_env.utils.nb.status.side_effect = Exception("down")

    ironic.sync_ironic("req", MagicMock())

    assert _pushed(sync_env.utils, "NetBox API is not reachable")
    sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)
    sync_env.netbox.get_devices.assert_not_called()


def test_sync_ironic_ironic_unreachable(sync_env):
    sync_env.utils.get_openstack_connection.return_value.baremetal.nodes.side_effect = (
        Exception("down")
    )

    ironic.sync_ironic("req", MagicMock())

    assert _pushed(sync_env.utils, "Ironic API is not reachable")
    sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_sync_ironic_node_name_not_in_netbox(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device(name="other")]

    ironic.sync_ironic("req", MagicMock(), node_name="node1")

    assert _pushed(sync_env.utils, "Node node1 not found in NetBox")
    sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_sync_ironic_dry_run_uses_dry_run_path(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device()]

    ironic.sync_ironic("req", MagicMock(), dry_run=True)

    sync_env.sync_dry.assert_called_once()
    sync_env.sync_device.assert_not_called()
    sync_env.utils.create_redlock.assert_not_called()
    assert _pushed(sync_env.utils, "[DRY RUN] ")
    sync_env.utils.finish_task_output.assert_called_once_with("req", rc=0)


def test_sync_ironic_lock_acquired_calls_device_and_releases(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device()]
    sync_env.sync_device.side_effect = Exception("boom")

    ironic.sync_ironic("req", MagicMock())

    sync_env.sync_device.assert_called_once()
    sync_env.lock.release.assert_called_once()
    assert _pushed(sync_env.utils, "Could not fully synchronize device")


def test_sync_ironic_lock_not_acquired(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device()]
    sync_env.lock.acquire.return_value = False

    ironic.sync_ironic("req", MagicMock())

    sync_env.sync_device.assert_not_called()
    assert _pushed(sync_env.utils, "Could not acquire lock for node node1")


def test_sync_ironic_stale_node_deleted(sync_env):
    sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(name="stale", uuid="u-stale", provision_state="available")
    ]

    ironic.sync_ironic("req", MagicMock())

    sync_env.openstack.baremetal_node_delete.assert_called_once_with("u-stale")


def test_sync_ironic_stale_node_dry_run_not_deleted(sync_env):
    sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(name="stale", uuid="u-stale", provision_state="available")
    ]

    ironic.sync_ironic("req", MagicMock(), dry_run=True)

    assert _pushed(sync_env.utils, "Would delete stale baremetal node: stale")
    sync_env.openstack.baremetal_node_delete.assert_not_called()


def test_sync_ironic_stale_clean_failed_moved_to_manageable(sync_env):
    sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(name="stale", uuid="u-stale", provision_state="clean failed")
    ]
    sync_env.openstack.baremetal_port_list.return_value = [SimpleNamespace(id="p1")]

    ironic.sync_ironic("req", MagicMock())

    sync_env.openstack.baremetal_node_set_provision_state.assert_called_once_with(
        "u-stale", "manage"
    )
    sync_env.openstack.baremetal_port_delete.assert_called_once_with("p1")
    sync_env.openstack.baremetal_node_delete.assert_called_once()


def test_sync_ironic_stale_node_not_eligible(sync_env):
    sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(
            name="stale",
            uuid="u-stale",
            provision_state="active",
            instance_uuid="i-1",
        )
    ]

    ironic.sync_ironic("req", MagicMock())

    assert _pushed(sync_env.utils, "Cannot remove baremetal node")
    sync_env.openstack.baremetal_node_delete.assert_not_called()


def test_sync_ironic_kernel_params_propagated(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device()]

    ironic.sync_ironic(
        "req",
        MagicMock(),
        skip_kernel_params=["nofb"],
        extra_kernel_params=["debug"],
    )

    assert sync_env.prepare.call_args.kwargs["skip_kernel_params"] == ["nofb"]
    assert sync_env.prepare.call_args.kwargs["extra_kernel_params"] == ["debug"]
    assert _pushed(sync_env.utils, "Skipping kernel append parameters: nofb")
    assert _pushed(sync_env.utils, "Adding extra kernel append parameters: debug")


def test_sync_ironic_ports_attributes_filtering(sync_env):
    sync_env.netbox.get_devices.return_value = [_make_device()]
    sync_env.netbox.get_interfaces_by_device.return_value = [
        SimpleNamespace(enabled=True, mgmt_only=False, mac_address="AA:BB:CC:DD:EE:01"),
        SimpleNamespace(
            enabled=False, mgmt_only=False, mac_address="AA:BB:CC:DD:EE:02"
        ),
        SimpleNamespace(enabled=True, mgmt_only=True, mac_address="AA:BB:CC:DD:EE:03"),
        SimpleNamespace(enabled=True, mgmt_only=False, mac_address=None),
    ]

    ironic.sync_ironic("req", MagicMock())

    ports_attributes = sync_env.sync_device.call_args.args[3]
    assert ports_attributes == [{"address": "AA:BB:CC:DD:EE:01"}]


# ===========================================================================
# sync_netbox_from_ironic
# ===========================================================================


@pytest.fixture
def netbox_sync_env(mocker):
    """Patch every collaborator of ``sync_netbox_from_ironic``."""
    utils = mocker.patch("osism.tasks.conductor.ironic.osism_utils")
    openstack = mocker.patch("osism.tasks.conductor.ironic.openstack")
    netbox = mocker.patch("osism.tasks.conductor.ironic.netbox")
    matches = mocker.patch("osism.tasks.conductor.ironic._matches_netbox_filter")

    utils.secondary_nb_list = []
    utils.nb.status.return_value = None
    openstack.baremetal_node_list.return_value = []
    netbox.set_provision_state.return_value = True
    netbox.set_power_state.return_value = True
    netbox.set_maintenance.return_value = True
    matches.return_value = True

    return SimpleNamespace(
        utils=utils, openstack=openstack, netbox=netbox, matches=matches
    )


def test_netbox_sync_filter_primary_match(netbox_sync_env):
    netbox_sync_env.matches.side_effect = lambda nb, flt, is_primary: is_primary
    netbox_sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(power_state="power on")
    ]

    ironic.sync_netbox_from_ironic("req", netbox_filter="primary")

    netbox_sync_env.netbox.set_provision_state.assert_called_once_with(
        "node1", "available", netbox_filter="primary", secondary_nb_list=[]
    )


def test_netbox_sync_filter_secondary_fallback(netbox_sync_env):
    secondary = MagicMock()
    secondary.status.return_value = None
    netbox_sync_env.utils.secondary_nb_list = [secondary]
    netbox_sync_env.utils.nb.status.side_effect = Exception("primary down")
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]

    ironic.sync_netbox_from_ironic("req", netbox_filter="any")

    assert netbox_sync_env.netbox.set_provision_state.call_args.kwargs[
        "secondary_nb_list"
    ] == [secondary]


def test_netbox_sync_filter_no_match(netbox_sync_env):
    netbox_sync_env.matches.return_value = False

    ironic.sync_netbox_from_ironic("req", netbox_filter="nope")

    assert _pushed(netbox_sync_env.utils, "No NetBox instances match filter")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_netbox_sync_filter_all_unreachable(netbox_sync_env):
    netbox_sync_env.matches.side_effect = lambda nb, flt, is_primary: is_primary
    netbox_sync_env.utils.nb.status.side_effect = Exception("down")

    ironic.sync_netbox_from_ironic("req", netbox_filter="primary")

    assert _pushed(netbox_sync_env.utils, "are reachable")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_netbox_sync_primary_unreachable_no_filter(netbox_sync_env):
    netbox_sync_env.utils.nb.status.side_effect = Exception("down")

    ironic.sync_netbox_from_ironic("req")

    assert _pushed(netbox_sync_env.utils, "NetBox API is not reachable")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_netbox_sync_all_secondaries_reachable(netbox_sync_env):
    s1, s2 = MagicMock(), MagicMock()
    s1.status.return_value = None
    s2.status.return_value = None
    netbox_sync_env.utils.secondary_nb_list = [s1, s2]
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]

    ironic.sync_netbox_from_ironic("req")

    assert netbox_sync_env.netbox.set_provision_state.call_args.kwargs[
        "secondary_nb_list"
    ] == [s1, s2]
    assert _pushed(netbox_sync_env.utils, "(including secondaries)")


def test_netbox_sync_one_secondary_unreachable(netbox_sync_env):
    s1, s2 = MagicMock(), MagicMock()
    s1.status.return_value = None
    s2.status.side_effect = Exception("down")
    netbox_sync_env.utils.secondary_nb_list = [s1, s2]
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]

    ironic.sync_netbox_from_ironic("req")

    assert netbox_sync_env.netbox.set_provision_state.call_args.kwargs[
        "secondary_nb_list"
    ] == [s1]


def test_netbox_sync_no_secondaries_message(netbox_sync_env):
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]

    ironic.sync_netbox_from_ironic("req")

    assert _pushed(netbox_sync_env.utils, "to NetBox")
    assert not _pushed(netbox_sync_env.utils, "(including secondaries)")


def test_netbox_sync_node_name_not_in_ironic(netbox_sync_env):
    netbox_sync_env.openstack.baremetal_node_list.return_value = [
        _make_node(name="other")
    ]

    ironic.sync_netbox_from_ironic("req", node_name="node1")

    assert _pushed(netbox_sync_env.utils, "Node node1 not found in Ironic")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)


def test_netbox_sync_failed_device_reported(netbox_sync_env):
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]
    netbox_sync_env.netbox.set_provision_state.return_value = False

    ironic.sync_netbox_from_ironic("req")

    assert _pushed(netbox_sync_env.utils, "Failed to sync 1 device(s)")


def test_netbox_sync_all_success_no_warning(netbox_sync_env):
    netbox_sync_env.openstack.baremetal_node_list.return_value = [_make_node()]

    ironic.sync_netbox_from_ironic("req")

    assert not _pushed(netbox_sync_env.utils, "Failed to sync")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=0)


def test_netbox_sync_ironic_unreachable(netbox_sync_env):
    netbox_sync_env.utils.get_openstack_connection.return_value.baremetal.nodes.side_effect = Exception(
        "down"
    )

    ironic.sync_netbox_from_ironic("req")

    assert _pushed(netbox_sync_env.utils, "Ironic API is not reachable")
    netbox_sync_env.utils.finish_task_output.assert_called_once_with("req", rc=1)
