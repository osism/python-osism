# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``osism.utils.hardware.selection``.

NetBox is replaced by a ``MagicMock`` whose ``dcim.devices.filter`` returns
plain dicts. That is the shape ``dict(record)`` produces for a pynetbox
record, which is all the selection ever reads.
"""

import argparse
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from osism.utils.hardware import selection
from osism.utils.hardware.selection import (
    KIND_NODE,
    KIND_SWITCH,
    SelectionError,
    Target,
    add_selection_arguments,
    build_netbox_query,
    load_inventory_hosts,
    managed_switch_ids,
    resolve_addresses,
    select_targets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(*argv):
    parser = argparse.ArgumentParser()
    add_selection_arguments(parser)
    return parser.parse_args(list(argv))


def _device(device_id, name, role, **extra):
    device = {
        "id": device_id,
        "name": name,
        "role": {"slug": role},
        "custom_fields": {},
    }
    device.update(extra)
    return device


LEAF_A = _device(1, "leaf-1a", "leaf")
LEAF_B = _device(2, "leaf-1b", "leaf")
SPINE = _device(3, "spine-1", "spine")
COMPUTE = _device(10, "compute-041", "compute")
STORAGE = _device(
    11, "sto-1", "storage", custom_fields={"inventory_hostname": "storage-001"}
)
PDU = _device(20, "pdu-1", "pdu")

ALL_DEVICES = [LEAF_A, LEAF_B, SPINE, COMPUTE, STORAGE, PDU]
INVENTORY = ["compute-041", "storage-001", "manager-1"]


def _nb(devices=None):
    nb = MagicMock()
    nb.dcim.devices.filter.return_value = list(
        ALL_DEVICES if devices is None else devices
    )
    return nb


@pytest.fixture
def inventory():
    with patch.object(
        selection, "load_inventory_hosts", return_value=list(INVENTORY)
    ) as load:
        yield load


@pytest.fixture
def managed():
    """Treat leaf-1a and spine-1 as matching NETBOX_FILTER_CONDUCTOR_SONIC."""
    with patch.object(selection, "managed_switch_ids", return_value={1, 3}) as ids:
        yield ids


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _names(targets):
    return [(target.name, target.kind) for target in targets]


# ---------------------------------------------------------------------------
# Arguments and NetBox query
# ---------------------------------------------------------------------------


def test_arguments_are_repeatable_and_default_to_everything():
    args = _args()
    assert args.names == []
    assert args.type == "all"
    assert args.include_unmanaged is False
    assert args.limit is None

    args = _args(
        "leaf-*",
        "spine-*",
        "--site",
        "fra1",
        "--site",
        "fra2",
        "--role",
        "leaf",
        "--rack",
        "R12",
        "--location",
        "Hall 1",
        "--region",
        "eu",
        "--site-group",
        "prod",
        "--tenant",
        "t1",
        "--tag",
        "x",
        "--manufacturer",
        "dell",
        "--device-type",
        "s5248f-on",
        "--platform",
        "sonic",
        "--status",
        "planned",
        "--filter",
        "cf_maintenance=false",
        "--type",
        "switch",
        "--include-unmanaged",
        "-l",
        "compute",
    )
    assert args.names == ["leaf-*", "spine-*"]
    assert args.site == ["fra1", "fra2"]
    assert args.site_group == ["prod"]
    assert args.device_type == ["s5248f-on"]
    assert args.netbox_filter == ["cf_maintenance=false"]
    assert args.limit == "compute"


def test_query_defaults_to_active_devices():
    assert build_netbox_query(_args(), MagicMock()) == {"status": ["active"]}


def test_query_combines_repeated_and_different_options():
    query = build_netbox_query(
        _args("--site", "fra1", "--site", "fra2", "--role", "leaf", "--tag", "x"),
        MagicMock(),
    )

    assert query == {
        "site": ["fra1", "fra2"],
        "role": ["leaf"],
        "tag": ["x"],
        "status": ["active"],
    }


def test_query_status_option_replaces_the_default():
    query = build_netbox_query(
        _args("--status", "planned", "--status", "staged"), MagicMock()
    )

    assert query["status"] == ["planned", "staged"]


def test_query_resolves_rack_and_location_names_to_ids():
    nb = MagicMock()
    nb.dcim.racks.filter.side_effect = lambda name: {
        "R12": [SimpleNamespace(id=7), SimpleNamespace(id=8)],
        "R13": [SimpleNamespace(id=9)],
    }[name]
    nb.dcim.locations.filter.return_value = [SimpleNamespace(id=3)]

    query = build_netbox_query(
        _args("--rack", "R12", "--rack", "R13", "--location", "Hall 1"), nb
    )

    assert query["rack_id"] == [7, 8, 9]
    assert query["location_id"] == [3]
    assert "rack" not in query and "location" not in query
    nb.dcim.locations.filter.assert_called_once_with(name="Hall 1")


def test_query_rejects_unknown_rack_name():
    nb = MagicMock()
    nb.dcim.racks.filter.return_value = []

    with pytest.raises(SelectionError, match="No rack named R99"):
        build_netbox_query(_args("--rack", "R99"), nb)


def test_query_reports_a_failing_rack_lookup():
    nb = MagicMock()
    nb.dcim.racks.filter.side_effect = RuntimeError("connection refused")

    with pytest.raises(SelectionError, match="NetBox rack query failed: connection"):
        build_netbox_query(_args("--rack", "R12"), nb)


def test_query_passes_generic_filters_through():
    query = build_netbox_query(
        _args(
            "--filter",
            "cf_maintenance=false",
            "--filter",
            "has_primary_ip=true",
            "--site",
            "fra1",
            "--filter",
            "site=fra2",
            "--filter",
            "status=planned",
        ),
        MagicMock(),
    )

    assert query["cf_maintenance"] == ["false"]
    assert query["has_primary_ip"] == ["true"]
    assert query["site"] == ["fra1", "fra2"]
    assert query["status"] == ["planned"]


@pytest.mark.parametrize("value", ["novalue", "=x"])
def test_query_rejects_malformed_generic_filter(value):
    with pytest.raises(SelectionError, match="expected KEY=VALUE"):
        build_netbox_query(_args("--filter", value), MagicMock())


# ---------------------------------------------------------------------------
# Selection without NetBox
# ---------------------------------------------------------------------------


def test_without_netbox_nodes_come_from_the_inventory(inventory):
    targets = select_targets(_args(), None)

    assert _names(targets) == [
        ("compute-041", KIND_NODE),
        ("manager-1", KIND_NODE),
        ("storage-001", KIND_NODE),
    ]
    assert all(target.device_id is None for target in targets)
    inventory.assert_called_once_with(None)


def test_without_netbox_names_and_limit_narrow_the_nodes(inventory):
    targets = select_targets(_args("compute-*", "-l", "compute"), None)

    assert _names(targets) == [("compute-041", KIND_NODE)]
    inventory.assert_called_once_with("compute")


@pytest.mark.parametrize(
    "argv",
    [
        ["--site", "fra1"],
        ["--rack", "R12"],
        ["--status", "active"],
        ["--filter", "cf_x=1"],
    ],
)
def test_without_netbox_filters_are_rejected(inventory, argv):
    with pytest.raises(SelectionError, match="NetBox is not configured"):
        select_targets(_args(*argv), None)

    inventory.assert_not_called()


def test_without_netbox_switches_cannot_be_selected(inventory):
    with pytest.raises(SelectionError, match="SONiC switches cannot be discovered"):
        select_targets(_args("--type", "switch"), None)


# ---------------------------------------------------------------------------
# Selection with NetBox
# ---------------------------------------------------------------------------


def test_classifies_nodes_and_switches_and_skips_the_rest(inventory, managed):
    nb = _nb()

    targets = select_targets(_args("--include-unmanaged"), nb)

    assert _names(targets) == [
        ("compute-041", KIND_NODE),
        ("leaf-1a", KIND_SWITCH),
        ("leaf-1b", KIND_SWITCH),
        ("spine-1", KIND_SWITCH),
        ("sto-1", KIND_NODE),
    ]
    nb.dcim.devices.filter.assert_called_once_with(status=["active"])
    storage = targets[-1]
    assert storage.hostname == "storage-001"
    assert storage.device_id == 11
    assert storage.device == STORAGE


def test_filters_are_passed_to_netbox(inventory, managed):
    nb = _nb([LEAF_A])

    select_targets(_args("--site", "fra1", "--role", "leaf"), nb)

    nb.dcim.devices.filter.assert_called_once_with(
        site=["fra1"], role=["leaf"], status=["active"]
    )


def test_role_is_read_from_device_role_on_old_netbox(inventory, managed):
    old = {
        "id": 1,
        "name": "leaf-1a",
        "device_role": {"slug": "leaf"},
        "custom_fields": {},
    }

    targets = select_targets(_args(), _nb([old]))

    assert _names(targets) == [("leaf-1a", KIND_SWITCH)]


def test_name_patterns_match_device_name_or_inventory_hostname(inventory, managed):
    targets = select_targets(_args("storage-*", "leaf-1a"), _nb())

    assert _names(targets) == [("leaf-1a", KIND_SWITCH), ("sto-1", KIND_NODE)]


def test_type_restricts_to_nodes(inventory, managed):
    targets = select_targets(_args("--type", "node"), _nb())

    assert _names(targets) == [("compute-041", KIND_NODE), ("sto-1", KIND_NODE)]
    managed.assert_not_called()


def test_type_switch_does_not_need_the_inventory(inventory, managed):
    targets = select_targets(_args("--type", "switch"), _nb())

    assert _names(targets) == [("leaf-1a", KIND_SWITCH), ("spine-1", KIND_SWITCH)]
    inventory.assert_not_called()


def test_limit_selects_nodes_only(managed):
    with patch.object(
        selection, "load_inventory_hosts", return_value=["compute-041"]
    ) as load:
        targets = select_targets(_args("-l", "compute"), _nb())

    assert _names(targets) == [("compute-041", KIND_NODE)]
    load.assert_called_once_with("compute")
    managed.assert_not_called()


def test_unmanaged_switch_is_skipped_with_a_warning(inventory, managed, loguru_logs):
    targets = select_targets(_args("--type", "switch"), _nb())

    assert ("leaf-1b", KIND_SWITCH) not in _names(targets)
    assert _has_log(loguru_logs, "WARNING", "Skipping 1 SONiC switch(es)")
    assert _has_log(loguru_logs, "WARNING", "leaf-1b")
    assert _has_log(loguru_logs, "WARNING", "--include-unmanaged")


def test_unmanaged_switch_is_skipped_even_when_named(inventory, managed, loguru_logs):
    with pytest.raises(SelectionError, match="No devices matched"):
        select_targets(_args("leaf-1b"), _nb())

    assert _has_log(loguru_logs, "WARNING", "leaf-1b")


def test_include_unmanaged_queries_every_sonic_role_switch(inventory, managed):
    targets = select_targets(_args("leaf-1b", "--include-unmanaged"), _nb())

    assert _names(targets) == [("leaf-1b", KIND_SWITCH)]
    managed.assert_not_called()


def test_managed_filter_failure_is_a_selection_error(inventory):
    with patch.object(
        selection, "managed_switch_ids", side_effect=ValueError("bad setting")
    ):
        with pytest.raises(SelectionError, match="NETBOX_FILTER_CONDUCTOR_SONIC"):
            select_targets(_args(), _nb())


def test_no_match_is_a_selection_error(inventory, managed):
    with pytest.raises(SelectionError, match="No devices matched"):
        select_targets(_args("does-not-exist"), _nb())


def test_netbox_query_failure_is_a_selection_error(inventory, managed):
    nb = MagicMock()
    nb.dcim.devices.filter.side_effect = RuntimeError("400 Bad Request")

    with pytest.raises(SelectionError, match="NetBox device query failed: 400"):
        select_targets(_args("--role", "nope"), nb)


def test_inventory_hosts_missing_in_netbox_are_reported(
    inventory, managed, loguru_logs
):
    select_targets(_args(), _nb())

    assert _has_log(
        loguru_logs,
        "WARNING",
        "Skipping 1 inventory host(s) without an active NetBox device: manager-1",
    )


def test_missing_hosts_are_not_reported_for_a_narrowed_selection(
    inventory, managed, loguru_logs
):
    select_targets(_args("compute-*"), _nb())
    select_targets(_args("--site", "fra1"), _nb())

    assert not _has_log(loguru_logs, "WARNING", "inventory host(s)")


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------


def _switch(**device):
    data = {"id": 1, "name": "leaf-1a"}
    data.update(device)
    return Target(
        name="leaf-1a", hostname="leaf-1a", kind=KIND_SWITCH, device_id=1, device=data
    )


def test_node_address_comes_from_the_resolver():
    node = Target(name="sto-1", hostname="storage-001", kind=KIND_NODE)
    resolver = MagicMock(return_value="192.0.2.10")

    resolve_addresses([node], resolver)

    resolver.assert_called_once_with("storage-001")
    assert node.address == "192.0.2.10"
    assert node.user == selection.settings.OPERATOR_USER


def test_switch_prefers_the_management_ip_of_the_config_context():
    switch = _switch(
        local_context_data={"management": {"ip": "10.0.0.1", "username": "ops"}},
        oob_ip={"address": "10.0.0.2/24"},
    )

    resolve_addresses([switch], MagicMock())

    assert (switch.address, switch.user) == ("10.0.0.1", "ops")


def test_switch_falls_back_to_the_oob_ip_and_the_admin_user():
    switch = _switch(
        local_context_data=None,
        oob_ip={"address": "10.0.0.2/24"},
        primary_ip4={"address": "10.0.0.3/24"},
    )

    resolve_addresses([switch], MagicMock())

    assert (switch.address, switch.user) == ("10.0.0.2", "admin")


def test_switch_uses_the_management_interface_ip_before_the_primary_ip():
    switch = _switch(primary_ip4={"address": "10.0.0.3/24"})

    with patch(
        "osism.tasks.conductor.netbox.get_device_oob_ip",
        return_value=("10.0.0.4", 24),
    ) as oob:
        resolve_addresses([switch], MagicMock())

    assert switch.address == "10.0.0.4"
    assert oob.call_args.args[0].id == 1


def test_switch_falls_back_to_the_primary_ip():
    switch = _switch(primary_ip4={"address": "10.0.0.3/24"})

    with patch("osism.tasks.conductor.netbox.get_device_oob_ip", return_value=None):
        resolve_addresses([switch], MagicMock())

    assert switch.address == "10.0.0.3"


def test_switch_without_any_address_keeps_it_empty():
    switch = _switch()

    with patch("osism.tasks.conductor.netbox.get_device_oob_ip", return_value=None):
        resolve_addresses([switch], MagicMock())

    assert switch.address == ""


# ---------------------------------------------------------------------------
# Inventory, managed switches, target attributes
# ---------------------------------------------------------------------------


def _proc(returncode=0, stdout=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr="")


def test_load_inventory_hosts_passes_the_limit():
    data = {"_meta": {"hostvars": {}}, "compute": {"hosts": ["c1", "c2"]}}

    with patch.object(
        selection, "get_inventory_path", return_value="/inv/hosts.yml"
    ), patch.object(
        selection.subprocess, "run", return_value=_proc(stdout=json.dumps(data))
    ) as run:
        hosts = load_inventory_hosts("compute")

    assert hosts == ["c1", "c2"]
    assert run.call_args.args[0] == [
        "ansible-inventory",
        "-i",
        "/inv/hosts.yml",
        "--list",
        "--limit",
        "compute",
    ]


@pytest.mark.parametrize(
    "result,message",
    [
        (_proc(returncode=1), "Error loading inventory."),
        (_proc(stdout="not json"), "Could not parse inventory."),
        (
            subprocess.TimeoutExpired(cmd="ansible-inventory", timeout=30),
            "Timeout loading inventory.",
        ),
    ],
)
def test_load_inventory_hosts_failures(result, message):
    with patch.object(
        selection, "get_inventory_path", return_value="/inv/hosts.yml"
    ), patch.object(selection.subprocess, "run", side_effect=[result]):
        with pytest.raises(SelectionError, match=message):
            load_inventory_hosts()


def test_managed_switch_ids_unions_all_configured_queries():
    nb = MagicMock()
    nb.dcim.devices.filter.side_effect = [
        [SimpleNamespace(id=1), SimpleNamespace(id=2)],
        [SimpleNamespace(id=2), SimpleNamespace(id=5)],
    ]
    queries = [{"status": "active", "tag": ["a"]}, {"site": "fra1"}]

    with patch(
        "osism.tasks.conductor.netbox.get_nb_device_query_list_sonic",
        return_value=queries,
    ):
        ids = managed_switch_ids(nb)

    assert ids == {1, 2, 5}
    assert [call.kwargs for call in nb.dcim.devices.filter.call_args_list] == queries


def test_target_describes_the_netbox_device():
    target = Target(
        name="leaf-1a",
        hostname="leaf-1a",
        kind=KIND_SWITCH,
        address="10.0.0.1",
        device_id=1,
        device={
            "site": {"slug": "fra1"},
            "rack": {"name": "R12"},
            "role": {"slug": "leaf"},
            "device_type": {"model": "S5248F-ON", "manufacturer": {"name": "Dell"}},
            "serial": "ABC123",
            "custom_fields": {"sonic_parameters": {"hwsku": "DellEMC-S5248f-P-25G"}},
        },
    )

    assert target.hwsku == "DellEMC-S5248f-P-25G"
    assert target.describe() == {
        "name": "leaf-1a",
        "inventory_hostname": "leaf-1a",
        "kind": "switch",
        "address": "10.0.0.1",
        "site": "fra1",
        "rack": "R12",
        "role": "leaf",
        "device_type": "S5248F-ON",
        "manufacturer": "Dell",
        "serial": "ABC123",
    }


def test_target_without_netbox_data_describes_itself():
    target = Target(name="compute-041", hostname="compute-041", kind=KIND_NODE)

    assert target.hwsku is None
    assert target.describe()["site"] is None
    assert target.describe()["serial"] is None
