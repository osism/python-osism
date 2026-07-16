# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the baremetal/NetBox getters and the thin Celery task wrappers
of ``osism/tasks/openstack.py``.

Covers ``get_baremetal_nodes``, the NetBox info getters, ``get_baremetal_node_ports``,
``get_baremetal_node_parameters`` (including its secret-masking helper
``_mask_node_secret_parameters``) and the thin task wrappers around the OpenStack
SDK.

Every external effect is mocked: the SDK connection comes from a patched
``osism.utils.get_openstack_connection`` (the no-argument helper, via ``mock_conn``)
and the NetBox client replaces the lazy ``osism.utils.nb`` attribute (``mock_nb``).
The bound tasks (``bind=True``) are exercised through ``task.__wrapped__(...)``
(already bound to the task instance, so ``self.request.id`` is ``None``).

The masking behavior lives behind ``_mask_node_secret_parameters``, which
encapsulates the dependency on ``osism.tasks.conductor.utils``. Tests of
``get_baremetal_node_parameters`` stub that helper (``stub_mask``), so only the
helper's own tests reach into the conductor internals (``get_vault``,
``deep_decrypt``, ``mask_secrets``, patched at source).
"""

import json
from operator import attrgetter
from types import SimpleNamespace
from unittest.mock import call

import pytest

from osism.tasks import openstack as openstack_tasks


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _node(extra, name="node-1"):
    return SimpleNamespace(extra=extra, name=name)


DEFAULT_NETBOX_INFO = {
    "device_role": None,
    "primary_ip4": None,
    "primary_ip6": None,
    "netbox_url": None,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_conn(mocker):
    """Replace the no-arg ``osism.utils.get_openstack_connection`` helper."""
    conn = mocker.MagicMock()
    mocker.patch(
        "osism.tasks.openstack.utils.get_openstack_connection", return_value=conn
    )
    return conn


@pytest.fixture
def mock_nb(mocker):
    """Replace ``osism.utils.nb`` (lazy attribute) with a fresh MagicMock."""
    nb = mocker.MagicMock()
    mocker.patch("osism.tasks.openstack.utils.nb", new=nb, create=True)
    return nb


@pytest.fixture
def no_netbox(mocker):
    """Force ``osism.utils.nb`` to ``None`` (no NetBox integration)."""
    mocker.patch("osism.tasks.openstack.utils.nb", new=None, create=True)


@pytest.fixture
def stub_mask(mocker):
    """Stub ``_mask_node_secret_parameters`` so ``get_baremetal_node_parameters``
    tests stay decoupled from ``conductor.utils``; by default it returns the
    parameters unchanged."""
    return mocker.patch(
        "osism.tasks.openstack._mask_node_secret_parameters",
        side_effect=lambda node_name, kernel, netplan, frr: (kernel, netplan, frr),
    )


@pytest.fixture
def node_params_env(mocker, mock_nb):
    """Wire up the NetBox device and the vault helpers for the masking path.

    ``get_vault``/``deep_decrypt`` are imported inside the function under
    test, so they are patched at source in ``osism.tasks.conductor.utils``;
    ``mask_secrets`` stays real unless a test patches it explicitly.
    """
    device = SimpleNamespace(custom_fields={"secrets": {}})
    mock_nb.dcim.devices.get.return_value = device
    get_vault = mocker.patch(
        "osism.tasks.conductor.utils.get_vault", return_value=mocker.MagicMock()
    )
    deep_decrypt = mocker.patch("osism.tasks.conductor.utils.deep_decrypt")
    return SimpleNamespace(
        nb=mock_nb,
        device=device,
        get_vault=get_vault,
        deep_decrypt=deep_decrypt,
    )


# ---------------------------------------------------------------------------
# get_baremetal_nodes
# ---------------------------------------------------------------------------


def test_get_baremetal_nodes_maps_all_fields(mock_conn):
    node = SimpleNamespace(
        uuid="u1",
        name="n1",
        power_state="power on",
        provision_state="active",
        maintenance=False,
        maintenance_reason="mr",
        fault="f",
        instance_uuid="i1",
        driver="redfish",
        resource_class="bm",
        conductor="cond",
        owner="own",
        lessee="les",
        description="desc",
        allocation_uuid="alloc",
        traits=["CUSTOM_X"],
        properties={"cpus": 4},
        extra={"k": "v"},
        driver_info={"redfish_address": "https://bmc.example"},
        last_error="err",
        provision_updated_at="p-ts",
        created_at="c-ts",
        updated_at="u-ts",
    )
    mock_conn.baremetal.nodes.return_value = iter([node])

    result = openstack_tasks.get_baremetal_nodes()

    mock_conn.baremetal.nodes.assert_called_once_with(details=True)
    assert result == [
        {
            "uuid": "u1",
            "name": "n1",
            "device_role": None,
            "primary_ip4": None,
            "primary_ip6": None,
            "power_state": "power on",
            "provision_state": "active",
            "maintenance": False,
            "maintenance_reason": "mr",
            "fault": "f",
            "instance_uuid": "i1",
            "driver": "redfish",
            "resource_class": "bm",
            "conductor": "cond",
            "owner": "own",
            "lessee": "les",
            "description": "desc",
            "allocation_uuid": "alloc",
            "traits": ["CUSTOM_X"],
            "properties": {"cpus": 4},
            "extra": {"k": "v"},
            "redfish_address": "https://bmc.example",
            "last_error": "err",
            "provision_updated_at": "p-ts",
            "created_at": "c-ts",
            "updated_at": "u-ts",
        }
    ]


def test_get_baremetal_nodes_fallbacks(mock_conn):
    """Missing ``uuid`` falls back to ``id``; ``traits``/``driver_info`` of
    ``None`` are normalized. ``SimpleNamespace`` models missing attributes."""
    node = SimpleNamespace(id="fallback-id", traits=None, driver_info=None)
    mock_conn.baremetal.nodes.return_value = iter([node])

    (info,) = openstack_tasks.get_baremetal_nodes()

    assert info["uuid"] == "fallback-id"
    assert info["name"] is None
    assert info["traits"] == []
    assert info["redfish_address"] is None
    assert info["properties"] == {}
    assert info["extra"] == {}


def test_get_baremetal_nodes_empty(mock_conn):
    mock_conn.baremetal.nodes.return_value = iter([])

    assert openstack_tasks.get_baremetal_nodes() == []


# ---------------------------------------------------------------------------
# get_baremetal_node_netbox_info / get_baremetal_nodes_netbox_info
# ---------------------------------------------------------------------------


def test_netbox_info_without_netbox_client(no_netbox):
    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    assert result == DEFAULT_NETBOX_INFO


def test_netbox_info_without_node_name(mock_nb):
    result = openstack_tasks.get_baremetal_node_netbox_info("")

    assert result == DEFAULT_NETBOX_INFO
    mock_nb.dcim.devices.get.assert_not_called()


def test_netbox_info_device_found(mocker, mock_nb):
    """Role name, split primary IPs and the device URL are extracted."""
    mocker.patch(
        "osism.tasks.openstack.settings.NETBOX_URL", "https://netbox.example.com/"
    )
    device = SimpleNamespace(
        id=42,
        role=SimpleNamespace(name="server"),
        primary_ip4="10.0.0.1/24",
        primary_ip6="fd00::1/64",
    )
    mock_nb.dcim.devices.get.return_value = device

    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    mock_nb.dcim.devices.get.assert_called_once_with(name="node-1")
    assert result == {
        "device_role": "server",
        "primary_ip4": "10.0.0.1",
        "primary_ip6": "fd00::1",
        "netbox_url": "https://netbox.example.com/dcim/devices/42/",
    }


def test_netbox_info_inventory_hostname_fallback(mocker, mock_nb):
    """No direct name match: the first ``cf_inventory_hostname`` filter hit is
    used. With ``NETBOX_URL`` unset, ``netbox_url`` stays ``None``."""
    mocker.patch("osism.tasks.openstack.settings.NETBOX_URL", None)
    device = SimpleNamespace(
        id=7,
        role=SimpleNamespace(name="switch"),
        primary_ip4=None,
        primary_ip6=None,
    )
    mock_nb.dcim.devices.get.return_value = None
    mock_nb.dcim.devices.filter.return_value = [device]

    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    mock_nb.dcim.devices.filter.assert_called_once_with(cf_inventory_hostname="node-1")
    assert result["device_role"] == "switch"
    assert result["netbox_url"] is None


def test_netbox_info_no_device_found(mock_nb):
    mock_nb.dcim.devices.get.return_value = None
    mock_nb.dcim.devices.filter.return_value = []

    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    assert result == DEFAULT_NETBOX_INFO


@pytest.mark.parametrize("role", [None, object()], ids=["none", "no-name"])
def test_netbox_info_role_without_name(mocker, mock_nb, role):
    """A missing role or one without a ``name`` leaves ``device_role`` unset."""
    mocker.patch("osism.tasks.openstack.settings.NETBOX_URL", None)
    device = SimpleNamespace(id=1, role=role, primary_ip4=None, primary_ip6=None)
    mock_nb.dcim.devices.get.return_value = device

    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    assert result["device_role"] is None


def test_netbox_info_lookup_error_returns_defaults(mock_nb, loguru_logs):
    mock_nb.dcim.devices.get.side_effect = Exception("netbox down")

    result = openstack_tasks.get_baremetal_node_netbox_info("node-1")

    assert result == DEFAULT_NETBOX_INFO
    assert _has_log(loguru_logs, "DEBUG", "Could not get NetBox info for node-1")


def test_nodes_netbox_info_without_netbox_client(no_netbox):
    assert openstack_tasks.get_baremetal_nodes_netbox_info(["a"]) == {}


def test_nodes_netbox_info_empty_names(mocker, mock_nb):
    single = mocker.patch("osism.tasks.openstack.get_baremetal_node_netbox_info")

    assert openstack_tasks.get_baremetal_nodes_netbox_info([]) == {}

    single.assert_not_called()


def test_nodes_netbox_info_queries_each_name(mocker, mock_nb):
    single = mocker.patch(
        "osism.tasks.openstack.get_baremetal_node_netbox_info",
        side_effect=lambda name: {"device_role": f"role-{name}"},
    )

    result = openstack_tasks.get_baremetal_nodes_netbox_info(["a", "b"])

    assert result == {
        "a": {"device_role": "role-a"},
        "b": {"device_role": "role-b"},
    }
    assert single.call_args_list == [call("a"), call("b")]


# ---------------------------------------------------------------------------
# get_baremetal_node_ports
# ---------------------------------------------------------------------------


def test_get_baremetal_node_ports(mock_conn):
    port1 = SimpleNamespace(
        uuid="p1",
        address="aa:bb:cc:dd:ee:ff",
        node_uuid="n1",
        pxe_enabled=True,
        created_at="c-ts",
        updated_at="u-ts",
    )
    port2 = SimpleNamespace(id="p2")
    mock_conn.baremetal.ports.return_value = iter([port1, port2])

    result = openstack_tasks.get_baremetal_node_ports("n1")

    mock_conn.baremetal.ports.assert_called_once_with(details=True, node_uuid="n1")
    assert result[0] == {
        "uuid": "p1",
        "address": "aa:bb:cc:dd:ee:ff",
        "node_uuid": "n1",
        "pxe_enabled": True,
        "created_at": "c-ts",
        "updated_at": "u-ts",
    }
    assert result[1]["uuid"] == "p2"
    assert result[1]["address"] is None


def test_get_baremetal_node_ports_empty(mock_conn):
    mock_conn.baremetal.ports.return_value = iter([])

    assert openstack_tasks.get_baremetal_node_ports("n1") == []


# ---------------------------------------------------------------------------
# get_baremetal_node_parameters (orchestration)
# ---------------------------------------------------------------------------
#
# These tests stub ``_mask_node_secret_parameters`` so they exercise only the
# extraction/parsing of the Ironic node's ``extra`` field and the shaping of
# the result dict; the masking helper is tested separately below.


@pytest.mark.parametrize("extra", [None, {}], ids=["none", "empty"])
def test_node_parameters_empty_extra(mock_conn, stub_mask, extra):
    mock_conn.baremetal.get_node.return_value = _node(extra)

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    mock_conn.baremetal.get_node.assert_called_once_with("u1")
    assert result == {
        "kernel_append_params": None,
        "netplan_parameters": None,
        "frr_parameters": None,
    }


def test_node_parameters_extracts_kernel_append_params(mock_conn, stub_mask):
    extra = {"instance_info": json.dumps({"kernel_append_params": "console=tty0"})}
    mock_conn.baremetal.get_node.return_value = _node(extra)

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    assert result["kernel_append_params"] == "console=tty0"


@pytest.mark.parametrize("instance_info", ["{invalid", 12345], ids=["json", "type"])
def test_node_parameters_invalid_instance_info(mock_conn, stub_mask, instance_info):
    """Unparsable ``instance_info`` (bad JSON or non-string) is ignored."""
    mock_conn.baremetal.get_node.return_value = _node({"instance_info": instance_info})

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    assert result["kernel_append_params"] is None


def test_node_parameters_parses_netplan_and_frr(mock_conn, stub_mask):
    extra = {
        "netplan_parameters": json.dumps({"eth0": "dhcp"}),
        "frr_parameters": json.dumps({"asn": "65000"}),
    }
    mock_conn.baremetal.get_node.return_value = _node(extra)

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    assert result["netplan_parameters"] == {"eth0": "dhcp"}
    assert result["frr_parameters"] == {"asn": "65000"}


def test_node_parameters_invalid_netplan_and_frr(mock_conn, stub_mask):
    extra = {"netplan_parameters": "{invalid", "frr_parameters": "{invalid"}
    mock_conn.baremetal.get_node.return_value = _node(extra)

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    assert result["netplan_parameters"] is None
    assert result["frr_parameters"] is None


def test_node_parameters_forwards_parsed_values_to_masking(mock_conn, stub_mask):
    """The node name and parsed parameters are handed to the masking helper."""
    extra = {
        "instance_info": json.dumps({"kernel_append_params": "pw=hunter2"}),
        "netplan_parameters": json.dumps({"eth0": "dhcp"}),
        "frr_parameters": json.dumps({"asn": "65000"}),
    }
    mock_conn.baremetal.get_node.return_value = _node(extra, name="node-7")

    openstack_tasks.get_baremetal_node_parameters("u1")

    stub_mask.assert_called_once_with(
        "node-7", "pw=hunter2", {"eth0": "dhcp"}, {"asn": "65000"}
    )


def test_node_parameters_returns_masked_values(mock_conn, mocker):
    """The masking helper's output is what the task returns."""
    mocker.patch(
        "osism.tasks.openstack._mask_node_secret_parameters",
        return_value=("masked-kernel", {"net": "masked"}, {"frr": "masked"}),
    )
    extra = {"instance_info": json.dumps({"kernel_append_params": "raw"})}
    mock_conn.baremetal.get_node.return_value = _node(extra)

    result = openstack_tasks.get_baremetal_node_parameters("u1")

    assert result == {
        "kernel_append_params": "masked-kernel",
        "netplan_parameters": {"net": "masked"},
        "frr_parameters": {"frr": "masked"},
    }


# ---------------------------------------------------------------------------
# _mask_node_secret_parameters (masking helper)
# ---------------------------------------------------------------------------
#
# This is the single seam onto ``osism.tasks.conductor.utils``; the conductor
# internals (``get_vault``, ``deep_decrypt``, ``mask_secrets``) are patched at
# source only here.


def test_mask_without_netbox(no_netbox):
    """Without a NetBox client no masking happens and inputs pass through."""
    result = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2", {}, {}
    )

    assert result == ("pw=hunter2", {}, {})


def test_mask_without_node_name(mock_nb):
    """A missing node name skips the NetBox lookup and returns raw values."""
    result = openstack_tasks._mask_node_secret_parameters(None, "pw=hunter2", {}, {})

    assert result == ("pw=hunter2", {}, {})
    mock_nb.dcim.devices.get.assert_not_called()


def test_mask_secrets_none_treated_as_empty(node_params_env):
    """A ``secrets`` custom field of ``None`` behaves like an empty dict."""
    node_params_env.device.custom_fields["secrets"] = None

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2", {}, {}
    )

    assert kernel == "pw=hunter2"
    node_params_env.deep_decrypt.assert_called_once_with(
        {}, node_params_env.get_vault.return_value
    )


def test_mask_masks_secret_values(node_params_env):
    """Stripped values of password/secret keys are replaced by ``***``; other
    values stay visible."""
    node_params_env.device.custom_fields["secrets"] = {
        "os_password": " hunter2 ",
        "api_secret": "tok123",
        "plain": "visible",
    }

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2 tok=tok123 keep=visible", {}, {}
    )

    assert kernel == "pw=*** tok=*** keep=visible"


def test_mask_ironic_osism_param_by_name(node_params_env):
    """The ``ironic_osism_aa`` param name is collected before decryption, so
    the ``osism-aa=...`` argument is masked by the name-based regex even when
    vault decryption drops the key and its value cannot be collected."""
    node_params_env.device.custom_fields["secrets"] = {"ironic_osism_aa": "topsecret"}
    node_params_env.deep_decrypt.side_effect = lambda secrets, vault: secrets.pop(
        "ironic_osism_aa", None
    )

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "osism-aa=topsecret other=x", {}, {}
    )

    assert kernel == "osism-aa=*** other=x"


def test_mask_ignores_non_string_secret_values(node_params_env):
    node_params_env.device.custom_fields["secrets"] = {"db_password": 42}

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=42", {}, {}
    )

    assert kernel == "pw=42"


def test_mask_forwards_secret_values_to_mask_secrets(mocker, node_params_env):
    """The collected secret values reach ``mask_secrets`` for both parameter
    dicts (frr first, then netplan) with the ``***`` mask."""
    node_params_env.device.custom_fields["secrets"] = {"os_password": "hunter2"}
    mask = mocker.patch(
        "osism.tasks.conductor.utils.mask_secrets", return_value={"masked": True}
    )

    _, netplan, frr = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2", {"eth0": "dhcp"}, {"asn": "65000"}
    )

    assert mask.call_args_list == [
        call({"asn": "65000"}, mask="***", secret_values={"hunter2"}),
        call({"eth0": "dhcp"}, mask="***", secret_values={"hunter2"}),
    ]
    assert frr == {"masked": True}
    assert netplan == {"masked": True}


def test_mask_device_lookup_fallback(node_params_env):
    """No direct name match: the ``cf_inventory_hostname`` filter hit is used."""
    node_params_env.nb.dcim.devices.get.return_value = None
    device = SimpleNamespace(custom_fields={"secrets": {"os_password": "hunter2"}})
    node_params_env.nb.dcim.devices.filter.return_value = [device]

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2", {}, {}
    )

    node_params_env.nb.dcim.devices.filter.assert_called_once_with(
        cf_inventory_hostname="node-1"
    )
    assert kernel == "pw=***"


def test_mask_error_returns_unmasked(node_params_env, loguru_logs):
    """A failing NetBox/vault path only logs a debug message; the parameters
    are returned unmasked."""
    node_params_env.nb.dcim.devices.get.side_effect = Exception("netbox down")

    kernel, _, _ = openstack_tasks._mask_node_secret_parameters(
        "node-1", "pw=hunter2", {}, {}
    )

    assert kernel == "pw=hunter2"
    assert _has_log(loguru_logs, "DEBUG", "Could not mask secrets")


# ---------------------------------------------------------------------------
# Thin Celery task wrappers (parametrized)
# ---------------------------------------------------------------------------

# Each wrapper fetches a connection and delegates to exactly one SDK method,
# propagating its return value: (task name, call args, call kwargs, SDK method
# path on the connection, expected args, expected kwargs).
THIN_WRAPPER_VARIANTS = [
    pytest.param(
        "image_get",
        ("cirros",),
        {},
        "image.find_image",
        ("cirros",),
        {},
        id="image_get",
    ),
    pytest.param(
        "network_get",
        ("net1",),
        {},
        "network.find_network",
        ("net1",),
        {},
        id="network_get",
    ),
    pytest.param(
        "baremetal_node_create",
        ("node1",),
        {},
        "baremetal.create_node",
        (),
        {"name": "node1"},
        id="node_create_default",
    ),
    pytest.param(
        "baremetal_node_create",
        ("node1", {"driver": "redfish"}),
        {},
        "baremetal.create_node",
        (),
        {"driver": "redfish", "name": "node1"},
        id="node_create_attributes",
    ),
    pytest.param(
        "baremetal_node_delete",
        ("n1",),
        {},
        "baremetal.delete_node",
        ("n1",),
        {},
        id="node_delete",
    ),
    pytest.param(
        "baremetal_node_update",
        ("n1",),
        {},
        "baremetal.update_node",
        ("n1",),
        {},
        id="node_update_default",
    ),
    pytest.param(
        "baremetal_node_update",
        ("n1", {"maintenance": True}),
        {},
        "baremetal.update_node",
        ("n1",),
        {"maintenance": True},
        id="node_update_attributes",
    ),
    pytest.param(
        "baremetal_node_show",
        ("n1",),
        {},
        "baremetal.find_node",
        ("n1", False),
        {},
        id="node_show_default",
    ),
    pytest.param(
        "baremetal_node_show",
        ("n1",),
        {"ignore_missing": True},
        "baremetal.find_node",
        ("n1", True),
        {},
        id="node_show_ignore_missing",
    ),
    pytest.param(
        "baremetal_node_validate",
        ("n1",),
        {},
        "baremetal.validate_node",
        ("n1",),
        {"required": ()},
        id="node_validate",
    ),
    pytest.param(
        "baremetal_node_set_provision_state",
        ("n1", "active"),
        {},
        "baremetal.set_node_provision_state",
        ("n1", "active"),
        {},
        id="node_set_provision_state",
    ),
    pytest.param(
        "baremetal_port_create",
        ({"address": "aa:bb"},),
        {},
        "baremetal.create_port",
        (),
        {"address": "aa:bb"},
        id="port_create",
    ),
    pytest.param(
        "baremetal_port_delete",
        ("p1",),
        {},
        "baremetal.delete_port",
        ("p1",),
        {},
        id="port_delete",
    ),
]


@pytest.mark.parametrize(
    "task_name, args, kwargs, method_path, expected_args, expected_kwargs",
    THIN_WRAPPER_VARIANTS,
)
def test_thin_wrapper_delegates(
    mock_conn, task_name, args, kwargs, method_path, expected_args, expected_kwargs
):
    task = getattr(openstack_tasks, task_name)
    method = attrgetter(method_path)(mock_conn)

    result = task.__wrapped__(*args, **kwargs)

    method.assert_called_once_with(*expected_args, **expected_kwargs)
    assert result is method.return_value


def test_baremetal_node_list_materializes_generator(mock_conn):
    nodes = [SimpleNamespace(name="a"), SimpleNamespace(name="b")]
    mock_conn.baremetal.nodes.return_value = iter(nodes)

    result = openstack_tasks.baremetal_node_list.__wrapped__()

    mock_conn.baremetal.nodes.assert_called_once_with()
    assert result == nodes


def test_baremetal_port_list_materializes_generator_with_defaults(mock_conn):
    ports = [SimpleNamespace(id="p1")]
    mock_conn.baremetal.ports.return_value = iter(ports)

    result = openstack_tasks.baremetal_port_list.__wrapped__()

    mock_conn.baremetal.ports.assert_called_once_with(details=False)
    assert result == ports


def test_baremetal_port_list_forwards_attributes(mock_conn):
    mock_conn.baremetal.ports.return_value = iter([])

    openstack_tasks.baremetal_port_list.__wrapped__(
        details=True, attributes={"node_uuid": "n1"}
    )

    mock_conn.baremetal.ports.assert_called_once_with(details=True, node_uuid="n1")


def test_wait_for_nodes_provision_state_returns_first_result(mock_conn):
    mock_conn.baremetal.wait_for_nodes_provision_state.return_value = [
        "first",
        "second",
    ]

    result = openstack_tasks.baremetal_node_wait_for_nodes_provision_state.__wrapped__(
        "n1", "active"
    )

    mock_conn.baremetal.wait_for_nodes_provision_state.assert_called_once_with(
        ["n1"], "active"
    )
    assert result == "first"


def test_wait_for_nodes_provision_state_empty_result(mock_conn):
    mock_conn.baremetal.wait_for_nodes_provision_state.return_value = []

    result = openstack_tasks.baremetal_node_wait_for_nodes_provision_state.__wrapped__(
        "n1", "active"
    )

    assert result is None


def test_set_boot_device_defaults_to_non_persistent(mock_conn):
    result = openstack_tasks.baremetal_node_set_boot_device.__wrapped__("n1", "pxe")

    mock_conn.baremetal.set_node_boot_device.assert_called_once_with(
        "n1", "pxe", persistent=False
    )
    assert result is None


def test_set_boot_device_forwards_persistent(mock_conn):
    openstack_tasks.baremetal_node_set_boot_device.__wrapped__(
        "n1", "disk", persistent=True
    )

    mock_conn.baremetal.set_node_boot_device.assert_called_once_with(
        "n1", "disk", persistent=True
    )


def test_set_power_state_without_wait_returns_node(mock_conn):
    result = openstack_tasks.baremetal_node_set_power_state.__wrapped__(
        "n1", "power on"
    )

    mock_conn.baremetal.set_node_power_state.assert_called_once_with("n1", "power on")
    mock_conn.baremetal.get_node.assert_called_once_with("n1")
    mock_conn.baremetal.wait_for_node_power_state.assert_not_called()
    assert result is mock_conn.baremetal.get_node.return_value


def test_set_power_state_with_wait(mock_conn):
    result = openstack_tasks.baremetal_node_set_power_state.__wrapped__(
        "n1", "power on", wait=True, timeout=30
    )

    mock_conn.baremetal.wait_for_node_power_state.assert_called_once_with(
        "n1", "power on", timeout=30
    )
    mock_conn.baremetal.get_node.assert_not_called()
    assert result is mock_conn.baremetal.wait_for_node_power_state.return_value


def test_set_target_raid_config(mock_conn):
    """The node's RAID state endpoint is PUT with the pinned microversion."""
    mock_conn.baremetal.get_node.return_value = {"uuid": "u1"}
    mock_conn.baremetal.put.return_value = SimpleNamespace(ok=True, content=b"payload")

    result = openstack_tasks.baremetal_node_set_target_raid_config.__wrapped__(
        "n1", {"logical_disks": []}
    )

    mock_conn.baremetal.get_node.assert_called_once_with("n1")
    mock_conn.baremetal.put.assert_called_once_with(
        "/nodes/u1/states/raid", microversion="1.12", json={"logical_disks": []}
    )
    assert result == (True, b"payload")


def test_setup_periodic_tasks_is_noop(mocker):
    sender = mocker.MagicMock()

    openstack_tasks.setup_periodic_tasks(sender)

    assert sender.mock_calls == []
