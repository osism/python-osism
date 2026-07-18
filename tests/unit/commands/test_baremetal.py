# SPDX-License-Identifier: Apache-2.0

import json
import os
import subprocess
from unittest.mock import MagicMock, call, patch

import openstack.exceptions
import pytest
import yaml

from osism import settings
from osism.commands import baremetal

# Each of these command classes follows the identical pattern: when the
# requested node cannot be found, the command logs a warning and must return
# a non-zero exit code so a failed lookup is not reported as success.
NOT_FOUND_COMMANDS = [
    baremetal.BaremetalDeploy,
    baremetal.BaremetalUndeploy,
    baremetal.BaremetalBurnIn,
    baremetal.BaremetalClean,
    baremetal.BaremetalProvide,
    baremetal.BaremetalMaintenanceSet,
    baremetal.BaremetalMaintenanceUnset,
    baremetal.BaremetalPowerOn,
    baremetal.BaremetalPowerOff,
    baremetal.BaremetalDelete,
]


def _run_not_found(cls):
    cmd = cls(MagicMock(), MagicMock())
    # Select the single-node path by naming one node (and not using --all).
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    conn = MagicMock()
    conn.baremetal.find_node.return_value = None

    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        return cmd.take_action(parsed_args)


@pytest.mark.parametrize("cls", NOT_FOUND_COMMANDS)
def test_node_not_found_returns_1(cls):
    assert _run_not_found(cls) == 1


# --- BaremetalList output ---


def test_list_includes_uuid_column(capsys):
    # The node UUID must be shown so it can be cross-referenced with Ironic logs.
    cmd = baremetal.BaremetalList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    node = {
        "name": "node1",
        "id": "11111111-2222-3333-4444-555555555555",
        "power_state": "power on",
        "provision_state": "active",
        "maintenance": False,
    }
    conn = MagicMock()
    conn.baremetal.nodes.return_value = [node]

    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        cmd.take_action(parsed_args)

    out = capsys.readouterr().out
    assert "UUID" in out
    assert node["id"] in out


# --- BaremetalDump failure paths ---


def test_dump_ironic_node_not_found_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1", "--ironic"])

    conn = MagicMock()
    conn.baremetal.find_node.return_value = None

    setup = MagicMock(return_value=("pw", [], None, True))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    with patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    ):
        assert cmd.take_action(parsed_args) == 1


def test_dump_netbox_unavailable_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        assert cmd.take_action(parsed_args) == 1


def test_dump_device_not_found_returns_1():
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None
    fake_nb.dcim.devices.filter.return_value = []

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1


# --- BaremetalPing failure paths ---


def test_ping_netbox_unavailable_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    with patch.dict("osism.utils.__dict__", {"nb": None}):
        assert cmd.take_action(parsed_args) == 1


def test_ping_device_not_found_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.return_value = None

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1


def test_ping_exception_returns_1():
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["node1"])

    fake_nb = MagicMock()
    fake_nb.dcim.devices.get.side_effect = Exception("boom")

    with patch.dict("osism.utils.__dict__", {"nb": fake_nb}):
        assert cmd.take_action(parsed_args) == 1


# --- Argument-validation failure paths ---
#
# These commands validate their arguments at the very top of take_action,
# before any cloud setup. When neither a node name nor --all is given (or, for
# the power commands, when no node name is given) the command must report a
# non-zero exit code rather than silently succeeding. No mocking is required
# because the validation branch returns before any infrastructure access.
MISSING_NODE_COMMANDS = [
    baremetal.BaremetalDeploy,
    baremetal.BaremetalUndeploy,
    baremetal.BaremetalBurnIn,
    baremetal.BaremetalClean,
    baremetal.BaremetalProvide,
    baremetal.BaremetalPowerOn,
    baremetal.BaremetalPowerOff,
    baremetal.BaremetalDelete,
]


@pytest.mark.parametrize("cls", MISSING_NODE_COMMANDS)
def test_missing_node_argument_returns_1(cls):
    cmd = cls(MagicMock(), MagicMock())
    # Neither a node name nor --all: the argument-validation branch fires.
    parsed_args = cmd.get_parser("test").parse_args([])
    assert cmd.take_action(parsed_args) == 1


def test_burnin_no_stressor_returns_1():
    cmd = baremetal.BaremetalBurnIn(MagicMock(), MagicMock())
    # Select a node so the node check passes, but disable every stressor so the
    # "at least one stressor" validation branch fires before any cloud setup.
    parsed_args = cmd.get_parser("test").parse_args(
        ["node1", "--no-cpu", "--no-memory", "--no-disk"]
    )
    assert cmd.take_action(parsed_args) == 1


# When --all is requested for a destructive operation without the
# --yes-i-really-really-mean-it confirmation, the command refuses to proceed
# and must return a non-zero exit code rather than reporting success. The
# confirmation guard runs before any cloud setup, so no mocking is needed.


def test_deploy_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalDeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all", "--rebuild"])
    assert cmd.take_action(parsed_args) == 1


def test_undeploy_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalUndeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1


def test_clean_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalClean(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1


def test_delete_all_without_confirmation_returns_1():
    cmd = baremetal.BaremetalDelete(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(["--all"])
    assert cmd.take_action(parsed_args) == 1


# --- Test doubles for the behavior tests below ---


class FakeNode:
    """Ironic node double.

    The commands mix attribute access (``node.provision_state``), item access
    (``node["maintenance"]``), membership tests (``"instance_info" in node``)
    and ``node.get(...)``, which a plain MagicMock does not support well.
    """

    def __init__(self, **fields):
        defaults = {
            "id": "uuid-1",
            "name": "node1",
            "provision_state": "available",
            "maintenance": False,
            "instance_info": {"image_source": "image"},
            "extra": {},
            "target_raid_config": None,
            "properties": {},
            "power_state": "power on",
        }
        defaults.update(fields)
        self._fields = defaults

    def __getattr__(self, item):
        fields = self.__dict__.get("_fields", {})
        if item in fields:
            return fields[item]
        raise AttributeError(item)

    def __getitem__(self, item):
        return self._fields[item]

    def __contains__(self, item):
        return item in self._fields

    def get(self, item, default=None):
        return self._fields.get(item, default)


def _cloud_helpers(conn, success=True):
    setup = MagicMock(return_value=("pw", ["tempfile"], "/cwd", success))
    getconn = MagicMock(return_value=conn)
    cleanup = MagicMock()
    return setup, getconn, cleanup


def _patch_cloud(setup, getconn, cleanup):
    return patch(
        "osism.tasks.openstack.get_cloud_helpers",
        return_value=(setup, getconn, cleanup),
    )


# --- _apply_metalbox_vars ---


def test_apply_metalbox_vars_sets_entries_when_ip_found():
    play_vars = {}
    with patch(
        "osism.commands.baremetal._get_metalbox_primary_ip4",
        return_value="192.168.30.1",
    ):
        baremetal._apply_metalbox_vars(play_vars, MagicMock())

    assert play_vars["hosts_additional_entries"] == {
        "metalbox.osism.xyz": "192.168.30.1"
    }
    assert play_vars["docker_insecure_registries"] == ["metalbox:5001"]


def test_apply_metalbox_vars_leaves_vars_untouched_without_ip():
    play_vars = {"existing": True}
    with patch("osism.commands.baremetal._get_metalbox_primary_ip4", return_value=None):
        baremetal._apply_metalbox_vars(play_vars, MagicMock())

    assert play_vars == {"existing": True}


# --- Cloud setup failure guard (identical in every command of the module) ---

SETUP_FAILURE_COMMANDS = [
    (baremetal.BaremetalList, []),
    (baremetal.BaremetalDeploy, ["node1"]),
    (baremetal.BaremetalDump, ["node1", "--ironic"]),
    (baremetal.BaremetalUndeploy, ["node1"]),
    (baremetal.BaremetalBurnIn, ["node1"]),
    (baremetal.BaremetalClean, ["node1"]),
    (baremetal.BaremetalProvide, ["node1"]),
    (baremetal.BaremetalMaintenanceSet, ["node1"]),
    (baremetal.BaremetalMaintenanceUnset, ["node1"]),
    (baremetal.BaremetalPowerOn, ["node1"]),
    (baremetal.BaremetalPowerOff, ["node1"]),
    (baremetal.BaremetalDelete, ["node1"]),
]


@pytest.mark.parametrize("cls,args", SETUP_FAILURE_COMMANDS)
def test_setup_failure_returns_1_without_connection(cls, args):
    cmd = cls(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(MagicMock(), success=False)
    with _patch_cloud(setup, getconn, cleanup):
        assert cmd.take_action(parsed_args) == 1
    getconn.assert_not_called()


# --- BaremetalList ---


def _list_node(name, power_state="power on"):
    return {
        "name": name,
        "id": f"uuid-{name}",
        "power_state": power_state,
        "provision_state": "active",
        "maintenance": False,
    }


def _run_list(args, conn, nb=None, info_mock=None):
    cmd = baremetal.BaremetalList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    if info_mock is None:
        info_mock = MagicMock(return_value={})
    with _patch_cloud(setup, getconn, cleanup), patch(
        "osism.tasks.openstack.get_baremetal_node_netbox_info", info_mock
    ), patch.dict("osism.utils.__dict__", {"nb": nb}):
        rc = cmd.take_action(parsed_args)
    return rc, info_mock


def test_list_rows_sorted_and_power_state_placeholder(capsys):
    conn = MagicMock()
    conn.baremetal.nodes.return_value = [
        _list_node("node-b", power_state=None),
        _list_node("node-a"),
    ]

    _run_list([], conn)

    out = capsys.readouterr().out
    assert out.index("node-a") < out.index("node-b")
    assert "n/a" in out


def test_list_query_flags_forwarded():
    conn = MagicMock()
    conn.baremetal.nodes.return_value = []

    _run_list(["--provision-state", "active", "--maintenance"], conn)

    conn.baremetal.nodes.assert_called_once_with(
        provision_state="active", maintenance=True
    )


def test_list_without_flags_queries_without_kwargs():
    conn = MagicMock()
    conn.baremetal.nodes.return_value = []

    _run_list([], conn)

    conn.baremetal.nodes.assert_called_once_with()


def test_list_netbox_adds_device_role_column(capsys):
    conn = MagicMock()
    conn.baremetal.nodes.return_value = [
        _list_node("node-b"),
        _list_node("node-a"),
    ]
    info_mock = MagicMock(
        side_effect=[{"device_role": "compute"}, {"device_role": None}]
    )

    _run_list(["--netbox"], conn, nb=MagicMock(), info_mock=info_mock)

    out = capsys.readouterr().out
    assert "Device Role" in out
    assert "compute" in out
    assert "N/A" in out
    # Rows are sorted before the NetBox lookups run.
    assert info_mock.call_args_list == [call("node-a"), call("node-b")]


def test_list_netbox_without_connection_skips_extra_column(capsys):
    conn = MagicMock()
    conn.baremetal.nodes.return_value = [_list_node("node-a")]

    _, info_mock = _run_list(["--netbox"], conn, nb=None)

    info_mock.assert_not_called()
    assert "Device Role" not in capsys.readouterr().out


def test_list_cleanup_called_when_listing_fails():
    cmd = baremetal.BaremetalList(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])
    conn = MagicMock()
    conn.baremetal.nodes.side_effect = RuntimeError("boom")
    setup, getconn, cleanup = _cloud_helpers(conn)

    with _patch_cloud(setup, getconn, cleanup):
        with pytest.raises(RuntimeError):
            cmd.take_action(parsed_args)

    cleanup.assert_called_once_with(["tempfile"], "/cwd")


# --- BaremetalDeploy ---


def _run_deploy(args, conn, nb=None, pack_side_effect=None):
    cmd = baremetal.BaremetalDeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    vault = MagicMock()
    captured = {}

    def fake_pack(tmp_dir):
        with open(os.path.join(tmp_dir, "playbook.yml")) as handle:
            captured["playbook"] = yaml.safe_load(handle)
        return "config-drive"

    with _patch_cloud(setup, getconn, cleanup), patch(
        "osism.tasks.conductor.utils.get_vault", return_value=vault
    ), patch("osism.tasks.conductor.utils.deep_decrypt") as deep_decrypt, patch(
        "openstack.baremetal.configdrive.pack",
        side_effect=pack_side_effect or fake_pack,
    ), patch(
        "osism.commands.baremetal._get_metalbox_primary_ip4", return_value=None
    ), patch.dict(
        "osism.utils.__dict__", {"nb": nb}
    ):
        rc = cmd.take_action(parsed_args)
    return rc, captured, deep_decrypt, vault


@pytest.mark.parametrize(
    "provision_state,maintenance,rebuild,expected_target",
    [
        ("available", False, False, "active"),
        ("deploy failed", False, False, "active"),
        ("error", False, False, "rebuild"),
        ("active", False, True, "rebuild"),
        ("active", False, False, None),
        ("available", True, False, None),
    ],
)
def test_deploy_provision_state_decision(
    provision_state, maintenance, rebuild, expected_target
):
    node = FakeNode(provision_state=provision_state, maintenance=maintenance)
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    args = ["node1"] + (["--rebuild"] if rebuild else [])
    _run_deploy(args, conn)

    if expected_target is None:
        conn.baremetal.set_node_provision_state.assert_not_called()
    else:
        conn.baremetal.set_node_provision_state.assert_called_once_with(
            node.id,
            expected_target,
            config_drive="config-drive",
            deploy_steps=None,
        )


def test_deploy_refreshes_instance_info_from_extra():
    node = FakeNode(
        instance_info={},
        extra={"instance_info": json.dumps({"image_source": "img"})},
    )
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.update_node.side_effect = lambda n, **kwargs: n

    _run_deploy(["node1"], conn)

    conn.baremetal.update_node.assert_called_once_with(
        node, instance_info={"image_source": "img"}
    )


def test_deploy_validation_failure_skips_node():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.validate_node.side_effect = openstack.exceptions.ValidationException(
        "invalid"
    )

    rc, _, _, _ = _run_deploy(["node1"], conn)

    assert rc == 1
    conn.baremetal.set_node_provision_state.assert_not_called()


def test_deploy_uses_netbox_local_context_data():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    device = MagicMock()
    device.local_context_data = {
        "base_var": "value",
        "frr_parameters": {"stale": True},
        "netplan_parameters": {"stale": True},
    }
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    _, captured, _, _ = _run_deploy(["node1"], conn, nb=nb)

    play = captured["playbook"][0]
    assert play["vars"]["base_var"] == "value"
    assert play["vars"]["hostname_name"] == "node1"
    assert "frr_parameters" not in play["vars"]
    assert "netplan_parameters" not in play["vars"]


def test_deploy_finds_device_via_inventory_hostname():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    device = MagicMock()
    device.local_context_data = {"base_var": "value"}
    nb = MagicMock()
    nb.dcim.devices.get.return_value = None
    nb.dcim.devices.filter.return_value = [device]

    _, captured, _, _ = _run_deploy(["node1"], conn, nb=nb)

    nb.dcim.devices.filter.assert_called_once_with(cf_inventory_hostname="node1")
    assert captured["playbook"][0]["vars"]["base_var"] == "value"


def test_deploy_continues_when_netbox_lookup_fails(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    nb = MagicMock()
    nb.dcim.devices.get.side_effect = RuntimeError("netbox down")

    _, captured, _, _ = _run_deploy(["node1"], conn, nb=nb)

    conn.baremetal.set_node_provision_state.assert_called_once()
    assert captured["playbook"][0]["vars"]["hostname_name"] == "node1"
    assert any(
        record["level"] == "WARNING"
        and "Failed to fetch NetBox data" in record["message"]
        for record in loguru_logs
    )


def test_deploy_netplan_parameters_extend_play():
    node = FakeNode(
        extra={"netplan_parameters": json.dumps({"network_ethernets": {"eth0": {}}})}
    )
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _, captured, _, _ = _run_deploy(["node1"], conn)

    play = captured["playbook"][0]
    assert play["vars"]["network_allow_service_restart"] is True
    assert play["vars"]["network_ethernets"] == {"eth0": {}}
    assert "osism.commons.network" in play["roles"]


def test_deploy_frr_parameters_extend_play():
    node = FakeNode(extra={"frr_parameters": json.dumps({"frr_local_as": 65000})})
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _, captured, deep_decrypt, vault = _run_deploy(["node1"], conn)

    play = captured["playbook"][0]
    assert play["vars"]["frr_dummy_interface"] == settings.FRR_DUMMY_INTERFACE
    assert play["vars"]["frr_local_as"] == 65000
    assert "osism.services.frr" in play["roles"]
    deep_decrypt.assert_called_once_with({"frr_local_as": 65000}, vault)


def test_deploy_supermicro_sets_cdrom_boot_device():
    node = FakeNode(properties={"vendor": "  Supermicro "})
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_deploy(["node1"], conn)

    conn.baremetal.set_node_boot_device.assert_called_once_with(
        node.id, "cdrom", persistent=False
    )


def test_deploy_boot_device_failure_does_not_block_deploy():
    node = FakeNode(properties={"vendor": "Supermicro"})
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_boot_device.side_effect = RuntimeError("ipmi error")

    _run_deploy(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once()


def test_deploy_with_target_raid_config_passes_deploy_steps():
    raid_config = {"logical_disks": [{"size_gb": 100}]}
    node = FakeNode(target_raid_config=raid_config)
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_deploy(["node1"], conn)

    kwargs = conn.baremetal.set_node_provision_state.call_args.kwargs
    assert kwargs["deploy_steps"] == [
        {
            "interface": "deploy",
            "step": "erase_devices_metadata",
            "args": {},
            "priority": 95,
        },
        {
            "interface": "raid",
            "step": "apply_configuration",
            "args": {"delete_existing": True, "raid_config": raid_config},
            "priority": 90,
        },
    ]


def test_deploy_config_drive_failure_skips_node(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    rc, _, _, _ = _run_deploy(
        ["node1"], conn, pack_side_effect=RuntimeError("pack failed")
    )

    assert rc == 1
    conn.baremetal.set_node_provision_state.assert_not_called()
    assert any(
        "Failed to build config drive" in record["message"] for record in loguru_logs
    )


def test_deploy_all_continues_after_provision_failure():
    nodes = [
        FakeNode(name="node1", id="uuid-1"),
        FakeNode(name="node2", id="uuid-2"),
    ]
    conn = MagicMock()
    conn.baremetal.nodes.return_value = nodes
    conn.baremetal.set_node_provision_state.side_effect = [
        RuntimeError("boom"),
        None,
    ]

    rc, _, _, _ = _run_deploy(["--all"], conn)

    # The failing node must not abort the loop, but the partially failed
    # run must still report a non-zero exit code.
    assert rc == 1
    conn.baremetal.nodes.assert_called_once_with(details=True)
    conn.baremetal.find_node.assert_not_called()
    assert conn.baremetal.set_node_provision_state.call_count == 2


# --- BaremetalDump (happy paths) ---


def _run_dump(args, conn=None, nb=None, metalbox_side_effect=None):
    cmd = baremetal.BaremetalDump(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn or MagicMock())
    vault = MagicMock()
    metalbox = MagicMock(return_value=None, side_effect=metalbox_side_effect)
    with _patch_cloud(setup, getconn, cleanup), patch(
        "osism.tasks.conductor.utils.get_vault", return_value=vault
    ), patch("osism.tasks.conductor.utils.deep_decrypt") as deep_decrypt, patch(
        "osism.commands.baremetal._get_metalbox_primary_ip4", metalbox
    ), patch.dict(
        "osism.utils.__dict__", {"nb": nb}
    ):
        rc = cmd.take_action(parsed_args)
    return rc, deep_decrypt, vault


def test_dump_ironic_prints_playbook(capsys):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    rc, _, _ = _run_dump(["node1", "--ironic"], conn=conn)

    assert rc is None
    play = yaml.safe_load(capsys.readouterr().out)[0]
    assert play["vars"]["hostname_name"] == "node1"
    assert play["roles"] == [
        "osism.commons.hostname",
        "osism.commons.hosts",
        "osism.commons.operator",
    ]
    assert play["tasks"][0]["ansible.builtin.systemd"] == {
        "name": "rsyslog",
        "state": "restarted",
    }


def test_dump_ironic_extra_parameters(capsys):
    node = FakeNode(
        extra={
            "netplan_parameters": json.dumps({"network_ethernets": {"eth0": {}}}),
            "frr_parameters": json.dumps({"frr_local_as": 65000}),
        }
    )
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _, deep_decrypt, vault = _run_dump(["node1", "--ironic"], conn=conn)

    play = yaml.safe_load(capsys.readouterr().out)[0]
    assert play["vars"]["network_allow_service_restart"] is True
    assert play["vars"]["network_ethernets"] == {"eth0": {}}
    assert play["vars"]["frr_local_as"] == 65000
    assert play["vars"]["frr_dummy_interface"] == settings.FRR_DUMMY_INTERFACE
    assert "osism.commons.network" in play["roles"]
    assert "osism.services.frr" in play["roles"]
    deep_decrypt.assert_called_once_with({"frr_local_as": 65000}, vault)


def test_dump_ironic_generation_error_returns_1(capsys, loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    device = MagicMock()
    device.name = "node1"
    device.local_context_data = None
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    rc, _, _ = _run_dump(
        ["node1", "--ironic"],
        conn=conn,
        nb=nb,
        metalbox_side_effect=RuntimeError("boom"),
    )

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert any(
        record["level"] == "ERROR"
        and "Failed to generate playbook" in record["message"]
        for record in loguru_logs
    )


def test_dump_netbox_device_by_name(capsys):
    device = MagicMock()
    device.name = "node1"
    device.local_context_data = {
        "base_var": "value",
        "frr_parameters": {"stale": True},
        "netplan_parameters": {"stale": True},
    }
    device.custom_fields = {
        "netplan_parameters": {"network_ethernets": {"eth0": {}}},
        "frr_parameters": {"frr_local_as": 65000},
    }
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    rc, deep_decrypt, vault = _run_dump(["node1"], nb=nb)

    assert rc is None
    play = yaml.safe_load(capsys.readouterr().out)[0]
    assert play["vars"]["hostname_name"] == "node1"
    assert play["vars"]["base_var"] == "value"
    assert "stale" not in play["vars"]
    assert play["vars"]["network_allow_service_restart"] is True
    assert play["vars"]["network_ethernets"] == {"eth0": {}}
    assert play["vars"]["frr_local_as"] == 65000
    assert play["vars"]["frr_dummy_interface"] == settings.FRR_DUMMY_INTERFACE
    assert "osism.commons.network" in play["roles"]
    assert "osism.services.frr" in play["roles"]
    deep_decrypt.assert_called_once_with({"frr_local_as": 65000}, vault)


def test_dump_netbox_device_via_inventory_hostname(capsys):
    device = MagicMock()
    device.name = "node1"
    device.local_context_data = None
    device.custom_fields = {}
    nb = MagicMock()
    nb.dcim.devices.get.return_value = None
    nb.dcim.devices.filter.return_value = [device]

    _run_dump(["node1"], nb=nb)

    nb.dcim.devices.filter.assert_called_once_with(cf_inventory_hostname="node1")
    play = yaml.safe_load(capsys.readouterr().out)[0]
    assert play["vars"]["hostname_name"] == "node1"


def test_dump_netbox_generation_error_returns_1(capsys, loguru_logs):
    device = MagicMock()
    device.name = "node1"
    device.local_context_data = None
    device.custom_fields = {}
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    rc, _, _ = _run_dump(["node1"], nb=nb, metalbox_side_effect=RuntimeError("boom"))

    assert rc == 1
    assert capsys.readouterr().out == ""
    assert any(
        record["level"] == "ERROR"
        and "Failed to generate playbook" in record["message"]
        for record in loguru_logs
    )


# --- BaremetalUndeploy ---


def _run_undeploy(args, conn, ssh_cleanup_result=True):
    cmd = baremetal.BaremetalUndeploy(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    ssh_cleanup = MagicMock(return_value=ssh_cleanup_result)
    with _patch_cloud(setup, getconn, cleanup), patch(
        "osism.commands.baremetal.cleanup_ssh_known_hosts_for_node", ssh_cleanup
    ):
        rc = cmd.take_action(parsed_args)
    return rc, ssh_cleanup


@pytest.mark.parametrize(
    "state", ["active", "wait call-back", "deploy failed", "error"]
)
def test_undeploy_supported_states(state):
    node = FakeNode(provision_state=state)
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.return_value = node

    _, ssh_cleanup = _run_undeploy(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(node.id, "undeploy")
    ssh_cleanup.assert_called_once_with("node1")


def test_undeploy_ssh_cleanup_success_logged(loguru_logs):
    node = FakeNode(provision_state="active")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.return_value = node

    _run_undeploy(["node1"], conn, ssh_cleanup_result=True)

    assert any(
        record["level"] == "INFO"
        and "SSH known_hosts cleanup completed successfully" in record["message"]
        for record in loguru_logs
    )


def test_undeploy_ssh_cleanup_warning_logged(loguru_logs):
    node = FakeNode(provision_state="active")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.return_value = node

    _run_undeploy(["node1"], conn, ssh_cleanup_result=False)

    assert any(
        record["level"] == "WARNING"
        and "SSH known_hosts cleanup completed with warnings" in record["message"]
        for record in loguru_logs
    )


def test_undeploy_unsupported_state_skipped(loguru_logs):
    node = FakeNode(provision_state="available")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _, ssh_cleanup = _run_undeploy(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_not_called()
    ssh_cleanup.assert_not_called()
    assert any(
        record["level"] == "WARNING"
        and "not in supported provision state" in record["message"]
        for record in loguru_logs
    )


def test_undeploy_provision_failure_returns_1():
    node = FakeNode(provision_state="active")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc, ssh_cleanup = _run_undeploy(["node1"], conn)

    assert rc == 1
    ssh_cleanup.assert_not_called()


def test_undeploy_all_iterates_nodes():
    nodes = [
        FakeNode(name="node1", id="uuid-1", provision_state="active"),
        FakeNode(name="node2", id="uuid-2", provision_state="active"),
    ]
    conn = MagicMock()
    conn.baremetal.nodes.return_value = nodes
    conn.baremetal.set_node_provision_state.side_effect = lambda node_id, state: next(
        n for n in nodes if n.id == node_id
    )

    _run_undeploy(["--all", "--yes-i-really-really-mean-it"], conn)

    conn.baremetal.nodes.assert_called_once_with()
    assert conn.baremetal.set_node_provision_state.call_count == 2


# --- BaremetalPing._ping_host ---


def _ping(run_result=None, side_effect=None):
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    results = {}
    run_mock = MagicMock(return_value=run_result, side_effect=side_effect)
    with patch("osism.commands.baremetal.subprocess.run", run_mock):
        cmd._ping_host("10.0.0.1", results, "node1")
    return results["node1"]


def _ping_output(returncode, stdout):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


def test_ping_host_success_with_round_trip_line():
    stdout = (
        "PING 10.0.0.1 (10.0.0.1): 56 data bytes\n"
        "3 packets transmitted, 3 packets received, 0% packet loss\n"
        "round-trip min/avg/max = 1.0/2.0/3.0 ms\n"
    )
    result = _ping(_ping_output(0, stdout))
    assert result == {
        "host": "10.0.0.1",
        "status": "SUCCESS",
        "time_info": "1.0/2.0/3.0 ms",
    }


def test_ping_host_partial_packet_loss():
    stdout = "3 packets transmitted, 2 packets received, 33% packet loss\n"
    result = _ping(_ping_output(0, stdout))
    assert result["status"] == "PARTIAL (33% packet loss)"
    assert result["time_info"] == "N/A"


def test_ping_host_success_without_stats_line():
    result = _ping(_ping_output(0, "PING 10.0.0.1 (10.0.0.1): 56 data bytes\n"))
    assert result["status"] == "SUCCESS"
    assert result["time_info"] == "N/A"


def test_ping_host_parses_linux_rtt_line():
    stdout = (
        "3 packets transmitted, 3 received, 0% packet loss, time 2003ms\n"
        "rtt min/avg/max/mdev = 1.1/2.2/3.3/0.4 ms\n"
    )
    result = _ping(_ping_output(0, stdout))
    assert result["status"] == "SUCCESS"
    assert result["time_info"] == "1.1/2.2/3.3/0.4 ms"


def test_ping_host_nonzero_returncode_fails():
    result = _ping(_ping_output(1, ""))
    assert result["status"] == "FAILED"
    assert result["time_info"] == "N/A"


def test_ping_host_timeout_reports_error():
    error = subprocess.TimeoutExpired(cmd="ping", timeout=20)
    result = _ping(side_effect=error)
    assert result["status"] == "ERROR"
    assert result["time_info"] == str(error)[:50]


# --- BaremetalPing.take_action (device discovery) ---


def _nb_device(
    name,
    ip="10.0.0.1/24",
    power_state="power on",
    provision_state="active",
    has_ip=True,
):
    device = MagicMock()
    device.name = name
    device.custom_fields = {
        "power_state": power_state,
        "provision_state": provision_state,
    }
    if has_ip:
        device.primary_ip4.address = ip
    else:
        device.primary_ip4 = None
    return device


def _run_ping_all(devices_per_query, queries=None, ping_impl=None):
    cmd = baremetal.BaremetalPing(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args([])

    if ping_impl is None:

        def ping_impl(self, host, results, host_name):
            results[host_name] = {
                "host": host,
                "status": "SUCCESS",
                "time_info": "1.0/2.0/3.0 ms",
            }

    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}), patch(
        "osism.tasks.conductor.netbox.get_nb_device_query_list_ironic",
        return_value=queries or [{"role": "server"}],
    ), patch(
        "osism.tasks.netbox.get_devices", side_effect=devices_per_query
    ) as get_devices, patch.object(
        baremetal.BaremetalPing, "_ping_host", ping_impl
    ):
        rc = cmd.take_action(parsed_args)
    return rc, get_devices


def test_ping_all_collects_devices_from_all_queries_and_filters(capsys):
    matching = _nb_device("node-a")
    wrong_power = _nb_device("node-b", power_state="power off")
    wrong_state = _nb_device("node-c", provision_state="available")

    rc, get_devices = _run_ping_all(
        devices_per_query=[[matching], [wrong_power, wrong_state]],
        queries=[{"role": "server"}, {"role": "storage"}],
    )

    assert rc is None
    assert get_devices.call_count == 2
    get_devices.assert_any_call(role="server")
    get_devices.assert_any_call(role="storage")
    out = capsys.readouterr().out
    assert "node-a" in out
    assert "node-b" not in out
    assert "node-c" not in out


def test_ping_all_no_matching_devices_returns_none(loguru_logs):
    rc, _ = _run_ping_all(
        devices_per_query=[[_nb_device("node-b", power_state="power off")]]
    )

    assert rc is None
    assert any(
        "No devices found matching criteria" in record["message"]
        for record in loguru_logs
    )


def test_ping_all_device_without_ip_excluded(capsys, loguru_logs):
    with_ip = _nb_device("node-a")
    without_ip = _nb_device("node-b", has_ip=False)

    _run_ping_all(devices_per_query=[[with_ip, without_ip]])

    out = capsys.readouterr().out
    assert "node-a" in out
    assert "node-b" not in out
    assert any(
        record["level"] == "WARNING" and "no primary IPv4 address" in record["message"]
        for record in loguru_logs
    )


def test_ping_all_only_ip_less_devices_returns_none(loguru_logs):
    rc, _ = _run_ping_all(devices_per_query=[[_nb_device("node-a", has_ip=False)]])

    assert rc is None
    assert any(
        "No devices found with primary IPv4 addresses" in record["message"]
        for record in loguru_logs
    )


def test_ping_all_strips_prefix_from_ip(capsys):
    _run_ping_all(devices_per_query=[[_nb_device("node-a", ip="10.0.0.5/24")]])

    out = capsys.readouterr().out
    assert "10.0.0.5" in out
    assert "10.0.0.5/24" not in out


def test_ping_all_summary_counts_partial_as_failed(capsys):
    def ping_impl(self, host, results, host_name):
        status = "SUCCESS" if host_name == "node-a" else "PARTIAL (33% packet loss)"
        results[host_name] = {"host": host, "status": status, "time_info": "N/A"}

    _run_ping_all(
        devices_per_query=[
            [
                _nb_device("node-a", ip="10.0.0.1/24"),
                _nb_device("node-b", ip="10.0.0.2/24"),
            ]
        ],
        ping_impl=ping_impl,
    )

    out = capsys.readouterr().out
    assert "Summary: 1 successful, 1 failed/partial out of 2 total" in out


# --- BaremetalBurnIn ---

DEFAULT_BURNIN_STEPS = [
    {"step": "burnin_cpu", "interface": "deploy"},
    {"step": "burnin_memory", "interface": "deploy"},
    {"step": "burnin_disk", "interface": "deploy"},
]


def _run_burnin(args, conn):
    cmd = baremetal.BaremetalBurnIn(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    with _patch_cloud(setup, getconn, cleanup):
        return cmd.take_action(parsed_args)


def test_burnin_manageable_uses_default_steps():
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_burnin(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(
        node.id, "clean", clean_steps=DEFAULT_BURNIN_STEPS
    )


def test_burnin_no_disk_removes_only_disk_step():
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_burnin(["node1", "--no-disk"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(
        node.id,
        "clean",
        clean_steps=[
            {"step": "burnin_cpu", "interface": "deploy"},
            {"step": "burnin_memory", "interface": "deploy"},
        ],
    )


def test_burnin_available_node_moved_to_manageable_first():
    available = FakeNode(provision_state="available")
    manageable = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = available
    conn.baremetal.set_node_provision_state.return_value = manageable
    conn.baremetal.wait_for_nodes_provision_state.return_value = [manageable]

    _run_burnin(["node1"], conn)

    assert conn.baremetal.set_node_provision_state.call_args_list == [
        call("uuid-1", "manage"),
        call("uuid-1", "clean", clean_steps=DEFAULT_BURNIN_STEPS),
    ]
    conn.baremetal.wait_for_nodes_provision_state.assert_called_once_with(
        ["uuid-1"], "manageable"
    )


def test_burnin_manage_failure_skips_node():
    available = FakeNode(provision_state="available")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = available
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc = _run_burnin(["node1"], conn)

    assert rc == 1
    assert conn.baremetal.set_node_provision_state.call_count == 1
    conn.baremetal.wait_for_nodes_provision_state.assert_not_called()


def test_burnin_manageable_refreshes_instance_info_and_boot_device():
    node = FakeNode(
        provision_state="manageable",
        instance_info={},
        extra={"instance_info": json.dumps({"image_source": "img"})},
        properties={"vendor": "Supermicro"},
    )
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.update_node.side_effect = lambda n, **kwargs: n

    _run_burnin(["node1"], conn)

    conn.baremetal.update_node.assert_called_once_with(
        node, instance_info={"image_source": "img"}
    )
    conn.baremetal.set_node_boot_device.assert_called_once_with(
        node.id, "cdrom", persistent=False
    )


def test_burnin_clean_failure_returns_1():
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc = _run_burnin(["node1"], conn)

    assert rc == 1


def test_burnin_active_without_confirmation_refused(loguru_logs):
    node = FakeNode(provision_state="active")
    node.set_provision_state = MagicMock()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_burnin(["node1"], conn)

    node.set_provision_state.assert_not_called()
    assert any(
        record["level"] == "ERROR"
        and "yes-i-really-really-mean-it" in record["message"]
        for record in loguru_logs
    )


def test_burnin_active_with_confirmation_uses_service_steps(loguru_logs):
    node = FakeNode(provision_state="active")
    node.set_provision_state = MagicMock()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_burnin(["node1", "--yes-i-really-really-mean-it"], conn)

    node.set_provision_state.assert_called_once_with(
        conn.baremetal,
        "service",
        service_steps=[
            {"step": "burnin_cpu", "interface": "deploy"},
            {"step": "burnin_memory", "interface": "deploy"},
        ],
    )
    assert any("Skipping disk burn-in" in record["message"] for record in loguru_logs)


def test_burnin_unsupported_state_warns(loguru_logs):
    node = FakeNode(provision_state="enroll")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    rc = _run_burnin(["node1"], conn)

    assert rc is None
    conn.baremetal.set_node_provision_state.assert_not_called()
    assert any(
        record["level"] == "WARNING" and "not in supported state" in record["message"]
        for record in loguru_logs
    )


# --- BaremetalClean ---

ERASE_DEVICES_STEP = {"interface": "deploy", "step": "erase_devices"}
RAID_DELETE_STEP = {"interface": "raid", "step": "delete_configuration"}


def _run_baremetal_clean(args, conn):
    cmd = baremetal.BaremetalClean(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    with _patch_cloud(setup, getconn, cleanup):
        return cmd.take_action(parsed_args)


def test_clean_manageable_without_raid_interface():
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_baremetal_clean(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(
        node.id, "clean", clean_steps=[ERASE_DEVICES_STEP]
    )


def test_clean_raid_interface_prepends_delete_configuration():
    node = FakeNode(provision_state="manageable", raid_interface="agent")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_baremetal_clean(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(
        node.id, "clean", clean_steps=[RAID_DELETE_STEP, ERASE_DEVICES_STEP]
    )


def test_clean_available_node_moved_to_manageable_first(loguru_logs):
    available = FakeNode(provision_state="available")
    manageable = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = available
    conn.baremetal.set_node_provision_state.return_value = manageable
    conn.baremetal.wait_for_nodes_provision_state.return_value = [manageable]

    _run_baremetal_clean(["node1"], conn)

    assert conn.baremetal.set_node_provision_state.call_args_list == [
        call("uuid-1", "manage"),
        call("uuid-1", "clean", clean_steps=[ERASE_DEVICES_STEP]),
    ]
    assert any(
        "Successfully initiated clean" in record["message"] for record in loguru_logs
    )


def test_clean_manage_failure_skips_node():
    available = FakeNode(provision_state="available")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = available
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc = _run_baremetal_clean(["node1"], conn)

    assert rc == 1
    assert conn.baremetal.set_node_provision_state.call_count == 1


def test_clean_failure_returns_1(loguru_logs):
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc = _run_baremetal_clean(["node1"], conn)

    assert rc == 1
    assert any(
        record["level"] == "WARNING" and "Clean of node" in record["message"]
        for record in loguru_logs
    )


def test_clean_unsupported_state_warns(loguru_logs):
    node = FakeNode(provision_state="active")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_baremetal_clean(["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_not_called()
    assert any(
        record["level"] == "WARNING" and "not in supported state" in record["message"]
        for record in loguru_logs
    )


# --- BaremetalProvide / Maintenance / Power (happy paths) ---


def _run_simple(cls, args, conn):
    cmd = cls(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    with _patch_cloud(setup, getconn, cleanup):
        return cmd.take_action(parsed_args)


def test_provide_manageable_node():
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalProvide, ["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_called_once_with(node.id, "provide")


def test_provide_maintenance_node_skipped(loguru_logs):
    node = FakeNode(provision_state="manageable", maintenance=True)
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalProvide, ["node1"], conn)

    conn.baremetal.set_node_provision_state.assert_not_called()
    assert any(
        record["level"] == "WARNING" and "not in supported state" in record["message"]
        for record in loguru_logs
    )


def test_provide_failure_warns(loguru_logs):
    node = FakeNode(provision_state="manageable")
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_provision_state.side_effect = RuntimeError("boom")

    rc = _run_simple(baremetal.BaremetalProvide, ["node1"], conn)

    assert rc == 1
    assert any(record["level"] == "WARNING" for record in loguru_logs)


def test_maintenance_set_with_reason():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalMaintenanceSet, ["node1", "--reason", "foo"], conn)

    conn.baremetal.set_node_maintenance.assert_called_once_with(node, reason="foo")


def test_maintenance_set_failure_logged(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_maintenance.side_effect = RuntimeError("boom")

    rc = _run_simple(baremetal.BaremetalMaintenanceSet, ["node1"], conn)

    assert rc == 1
    assert any(record["level"] == "ERROR" for record in loguru_logs)


def test_maintenance_unset():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalMaintenanceUnset, ["node1"], conn)

    conn.baremetal.unset_node_maintenance.assert_called_once_with(node)


def test_maintenance_unset_failure_logged(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.unset_node_maintenance.side_effect = RuntimeError("boom")

    rc = _run_simple(baremetal.BaremetalMaintenanceUnset, ["node1"], conn)

    assert rc == 1
    assert any(record["level"] == "ERROR" for record in loguru_logs)


def test_power_on():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalPowerOn, ["node1"], conn)

    conn.baremetal.set_node_power_state.assert_called_once_with(node.id, "power on")


@pytest.mark.parametrize(
    "args,target",
    [(["node1"], "power off"), (["node1", "--soft"], "soft power off")],
)
def test_power_off(args, target):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node

    _run_simple(baremetal.BaremetalPowerOff, args, conn)

    conn.baremetal.set_node_power_state.assert_called_once_with(node.id, target)


def test_power_failure_logged(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.set_node_power_state.side_effect = RuntimeError("boom")

    rc = _run_simple(baremetal.BaremetalPowerOn, ["node1"], conn)

    assert rc == 1
    assert any(record["level"] == "ERROR" for record in loguru_logs)


# --- BaremetalDelete ---


def _run_delete(args, conn, nb=None, secondary=None):
    cmd = baremetal.BaremetalDelete(MagicMock(), MagicMock())
    parsed_args = cmd.get_parser("test").parse_args(args)
    setup, getconn, cleanup = _cloud_helpers(conn)
    with _patch_cloud(setup, getconn, cleanup), patch.dict(
        "osism.utils.__dict__",
        {"nb": nb, "secondary_nb_list": secondary if secondary is not None else []},
    ):
        return cmd.take_action(parsed_args)


def test_delete_removes_ports_before_node():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = [MagicMock(id="port-1"), MagicMock(id="port-2")]

    _run_delete(["node1"], conn)

    conn.baremetal.ports.assert_called_once_with(node_uuid=node.id)
    assert conn.baremetal.delete_port.call_args_list == [
        call("port-1", ignore_missing=True),
        call("port-2", ignore_missing=True),
    ]
    conn.baremetal.delete_node.assert_called_once_with(node.id, ignore_missing=True)
    ordered = [
        name
        for name, _, _ in conn.baremetal.mock_calls
        if name in ("delete_port", "delete_node")
    ]
    assert ordered == ["delete_port", "delete_port", "delete_node"]


def test_delete_port_failure_does_not_block_deletion():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = [MagicMock(id="port-1"), MagicMock(id="port-2")]
    conn.baremetal.delete_port.side_effect = [RuntimeError("boom"), None]

    _run_delete(["node1"], conn)

    assert conn.baremetal.delete_port.call_count == 2
    conn.baremetal.delete_node.assert_called_once_with(node.id, ignore_missing=True)


def test_delete_clears_primary_netbox_states():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = []
    device = MagicMock()
    device.custom_fields = {"provision_state": "active", "power_state": "power on"}
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device

    _run_delete(["node1"], conn, nb=nb)

    assert device.custom_fields["provision_state"] is None
    assert device.custom_fields["power_state"] is None
    device.save.assert_called_once_with()


def test_delete_primary_device_not_found_warns(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = []
    nb = MagicMock()
    nb.dcim.devices.get.return_value = None

    rc = _run_delete(["node1"], conn, nb=nb)

    assert rc is None
    conn.baremetal.delete_node.assert_called_once()
    assert any(
        record["level"] == "WARNING"
        and "not found in primary NetBox" in record["message"]
        for record in loguru_logs
    )


def test_delete_primary_netbox_failure_continues_with_secondary(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = []
    nb = MagicMock()
    nb.dcim.devices.get.side_effect = RuntimeError("netbox down")
    secondary_device = MagicMock()
    secondary_device.custom_fields = {"provision_state": "active"}
    secondary = MagicMock()
    secondary.base_url = "https://secondary"
    secondary.dcim.devices.get.return_value = secondary_device

    rc = _run_delete(["node1"], conn, nb=nb, secondary=[secondary])

    assert rc is None
    secondary_device.save.assert_called_once_with()
    assert any(
        record["level"] == "WARNING"
        and "Failed to clear NetBox states" in record["message"]
        for record in loguru_logs
    )


def test_delete_secondary_netbox_failure_warns(loguru_logs):
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = []
    secondary = MagicMock()
    secondary.base_url = "https://secondary"
    secondary.dcim.devices.get.side_effect = RuntimeError("boom")

    rc = _run_delete(["node1"], conn, nb=None, secondary=[secondary])

    assert rc is None
    assert any(
        record["level"] == "WARNING" and "https://secondary" in record["message"]
        for record in loguru_logs
    )


def test_delete_without_netbox_still_deletes_node():
    node = FakeNode()
    conn = MagicMock()
    conn.baremetal.find_node.return_value = node
    conn.baremetal.ports.return_value = []

    rc = _run_delete(["node1"], conn, nb=None)

    assert rc is None
    conn.baremetal.delete_node.assert_called_once_with(node.id, ignore_missing=True)


def test_delete_all_continues_after_node_failure(loguru_logs):
    nodes = [
        FakeNode(name="node1", id="uuid-1"),
        FakeNode(name="node2", id="uuid-2"),
    ]
    conn = MagicMock()
    conn.baremetal.nodes.return_value = nodes
    conn.baremetal.ports.return_value = []
    conn.baremetal.delete_node.side_effect = [RuntimeError("boom"), None]

    rc = _run_delete(["--all", "--yes-i-really-really-mean-it"], conn, nb=None)

    # The failing node must not abort the loop, but the partially failed
    # run must still report a non-zero exit code.
    assert rc == 1
    assert conn.baremetal.delete_node.call_count == 2
    assert any(
        record["level"] == "ERROR" and "Failed to delete node" in record["message"]
        for record in loguru_logs
    )
