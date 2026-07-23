# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the HTTP and WebSocket endpoints in :mod:`osism.api`.

All endpoints are exercised through ``fastapi.testclient.TestClient`` against
the module-level ``app``. The module-level helpers and Pydantic models are
covered separately in ``test_api_helpers.py``; response-level effects such as
secret masking in hostvars responses belong here.

Importing :mod:`osism.api` has import-time side effects: it applies
``dictConfig(LogConfig().model_dump())`` and pulls in
``osism.services.event_bridge``, whose module-level ``EventBridge()``
instantiation attempts a Redis connection. That failure is caught and only
logged, so these tests need no Redis.

``osism.utils`` materializes its ``nb`` NetBox connection and ``redis`` client
lazily via a module ``__getattr__``; tests therefore inject fakes with
``patch.dict("osism.utils.__dict__", {...})`` instead of
``mocker.patch("osism.utils.nb")``, which would trigger a real connection
attempt when reading the original attribute.

The endpoints call the Celery task functions in ``osism.tasks.openstack``
synchronously; patching ``osism.api.openstack.<task>`` replaces the attribute
on the shared module object, so no Celery broker is involved.
"""

import json
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, call, mock_open, patch
from uuid import UUID

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient

from osism import api

INVENTORY_PATH = "/inventory/hosts.yml"
FULL_INVENTORY = "/inventory/hosts.yml"
MINIFIED_INVENTORY = "/inventory/hosts-minified.yml"


@pytest.fixture(scope="module")
def client():
    return TestClient(api.app)


def completed(stdout="", returncode=0, stderr=""):
    """Build a CompletedProcess as returned by subprocess.run(text=True)."""
    return subprocess.CompletedProcess(
        args=["ansible-inventory"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["/", "/v1"])
def test_health_endpoints_return_ok(client, endpoint):
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.json() == {"result": "ok"}


def test_events_info_points_to_websocket_endpoint(client):
    response = client.get("/v1/events")
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "ok"
    assert body["websocket_endpoint"] == "/v1/events/openstack"


# ---------------------------------------------------------------------------
# Telemetry sinks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["/v1/meters/sink", "/v1/events/sink"])
@pytest.mark.parametrize(
    "body",
    [[{"counter_name": "cpu"}, {"counter_name": "memory"}], {"counter_name": "cpu"}],
    ids=["list", "object"],
)
def test_sink_accepts_json(client, endpoint, body):
    response = client.post(endpoint, json=body)
    assert response.status_code == 200
    assert response.json() == {"result": "ok"}


@pytest.mark.parametrize(
    "endpoint,detail",
    [
        ("/v1/meters/sink", "Failed to process meters data"),
        ("/v1/events/sink", "Failed to process events data"),
    ],
)
def test_sink_rejects_malformed_json(client, endpoint, detail):
    response = client.post(endpoint, content=b"{not json")
    assert response.status_code == 500
    assert response.json()["detail"] == detail


# ---------------------------------------------------------------------------
# get_baremetal_nodes_list
# ---------------------------------------------------------------------------


def test_baremetal_nodes_returns_mapped_nodes(client, mocker):
    nodes_data = [
        {
            "uuid": "uuid-1",
            "name": "node-1",
            "power_state": "power on",
            "provision_state": "active",
            "maintenance": False,
            "traits": ["CUSTOM_TRAIT"],
            "properties": {"cpus": 8},
        },
        {
            "uuid": "uuid-2",
            "name": "node-2",
            "power_state": "power off",
            "provision_state": "available",
            "maintenance": True,
            "maintenance_reason": "repair",
        },
    ]
    mocker.patch("osism.api.openstack.get_baremetal_nodes", return_value=nodes_data)

    response = client.get("/v1/baremetal/nodes")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    first, second = body["nodes"]
    assert first["uuid"] == "uuid-1"
    assert first["name"] == "node-1"
    assert first["power_state"] == "power on"
    assert first["provision_state"] == "active"
    assert first["maintenance"] is False
    assert first["traits"] == ["CUSTOM_TRAIT"]
    assert first["properties"] == {"cpus": 8}
    assert first["driver"] is None
    assert second["maintenance"] is True
    assert second["maintenance_reason"] == "repair"


def test_baremetal_nodes_empty_list(client, mocker):
    mocker.patch("osism.api.openstack.get_baremetal_nodes", return_value=[])
    response = client.get("/v1/baremetal/nodes")
    assert response.status_code == 200
    assert response.json() == {"nodes": [], "count": 0}


def test_baremetal_nodes_error(client, mocker):
    mocker.patch(
        "osism.api.openstack.get_baremetal_nodes",
        side_effect=RuntimeError("ironic down"),
    )
    response = client.get("/v1/baremetal/nodes")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail.startswith("Failed to retrieve baremetal nodes:")
    assert "ironic down" in detail


# ---------------------------------------------------------------------------
# NetBox info endpoints
# ---------------------------------------------------------------------------


def test_baremetal_node_netbox_info(client, mocker):
    info = mocker.patch(
        "osism.api.openstack.get_baremetal_node_netbox_info",
        return_value={
            "device_role": "compute",
            "primary_ip4": "10.0.0.1/24",
            "primary_ip6": "fd00::1/64",
            "netbox_url": "https://netbox/dcim/devices/1/",
        },
    )

    response = client.get("/v1/baremetal/nodes/node-1/netbox")

    assert response.status_code == 200
    assert response.json() == {
        "device_role": "compute",
        "primary_ip4": "10.0.0.1/24",
        "primary_ip6": "fd00::1/64",
        "netbox_url": "https://netbox/dcim/devices/1/",
    }
    info.assert_called_once_with("node-1")


def test_baremetal_node_netbox_info_error_includes_node_name(client, mocker):
    mocker.patch(
        "osism.api.openstack.get_baremetal_node_netbox_info",
        side_effect=RuntimeError("netbox down"),
    )
    response = client.get("/v1/baremetal/nodes/node-1/netbox")
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "node-1" in detail
    assert "netbox down" in detail


def test_baremetal_nodes_netbox_info_bulk(client, mocker):
    info = mocker.patch(
        "osism.api.openstack.get_baremetal_nodes_netbox_info",
        return_value={
            "n1": {"device_role": "compute", "primary_ip4": "10.0.0.1/24"},
            "n2": {"device_role": "storage"},
        },
    )

    response = client.post(
        "/v1/baremetal/nodes/netbox", json={"node_names": ["n1", "n2"]}
    )

    assert response.status_code == 200
    nodes = response.json()["nodes"]
    assert set(nodes) == {"n1", "n2"}
    assert nodes["n1"]["device_role"] == "compute"
    assert nodes["n1"]["primary_ip4"] == "10.0.0.1/24"
    assert nodes["n2"]["device_role"] == "storage"
    assert nodes["n2"]["primary_ip4"] is None
    info.assert_called_once_with(["n1", "n2"])


def test_baremetal_nodes_netbox_info_requires_node_names(client, mocker):
    info = mocker.patch("osism.api.openstack.get_baremetal_nodes_netbox_info")
    response = client.post("/v1/baremetal/nodes/netbox", json={})
    assert response.status_code == 422
    info.assert_not_called()


def test_baremetal_nodes_netbox_info_bulk_error(client, mocker):
    mocker.patch(
        "osism.api.openstack.get_baremetal_nodes_netbox_info",
        side_effect=RuntimeError("netbox down"),
    )
    response = client.post("/v1/baremetal/nodes/netbox", json={"node_names": ["n1"]})
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to retrieve NetBox info: netbox down"


# ---------------------------------------------------------------------------
# get_baremetal_node_ports / get_baremetal_node_parameters
# ---------------------------------------------------------------------------


def test_baremetal_node_ports(client, mocker):
    ports = mocker.patch(
        "osism.api.openstack.get_baremetal_node_ports",
        return_value=[
            {
                "uuid": "port-1",
                "address": "aa:bb:cc:dd:ee:ff",
                "node_uuid": "uuid-1",
                "pxe_enabled": True,
            },
            {"uuid": "port-2", "address": "11:22:33:44:55:66"},
        ],
    )

    response = client.get("/v1/baremetal/nodes/uuid-1/ports")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    first = body["ports"][0]
    assert first["uuid"] == "port-1"
    assert first["address"] == "aa:bb:cc:dd:ee:ff"
    assert first["node_uuid"] == "uuid-1"
    assert first["pxe_enabled"] is True
    ports.assert_called_once_with("uuid-1")


def test_baremetal_node_ports_error_includes_node_uuid(client, mocker):
    mocker.patch(
        "osism.api.openstack.get_baremetal_node_ports",
        side_effect=RuntimeError("ironic down"),
    )
    response = client.get("/v1/baremetal/nodes/uuid-1/ports")
    assert response.status_code == 500
    assert "uuid-1" in response.json()["detail"]


def test_baremetal_node_parameters(client, mocker):
    params = mocker.patch(
        "osism.api.openstack.get_baremetal_node_parameters",
        return_value={
            "kernel_append_params": "console=ttyS0",
            "netplan_parameters": {"ethernets": {"eth0": {"dhcp4": True}}},
            "frr_parameters": {"asn": 65000},
        },
    )

    response = client.get("/v1/baremetal/nodes/uuid-1/parameters")

    assert response.status_code == 200
    assert response.json() == {
        "kernel_append_params": "console=ttyS0",
        "netplan_parameters": {"ethernets": {"eth0": {"dhcp4": True}}},
        "frr_parameters": {"asn": 65000},
    }
    params.assert_called_once_with("uuid-1")


def test_baremetal_node_parameters_error_includes_node_uuid(client, mocker):
    mocker.patch(
        "osism.api.openstack.get_baremetal_node_parameters",
        side_effect=RuntimeError("ironic down"),
    )
    response = client.get("/v1/baremetal/nodes/uuid-1/parameters")
    assert response.status_code == 500
    assert "uuid-1" in response.json()["detail"]


# ---------------------------------------------------------------------------
# notifications_baremetal
# ---------------------------------------------------------------------------


VALID_NOTIFICATION = {
    "priority": "INFO",
    "event_type": "baremetal.node.power_set.end",
    "timestamp": "2026-01-01 00:00:00.000000",
    "publisher_id": "ironic-conductor",
    "message_id": "f8a6e0a4-3c1b-4f53-9c5f-2f4f3b2a1e00",
    "payload": {"node": "node-1"},
}


def test_notifications_baremetal_dispatches_to_handler(client, mocker):
    get_handler = mocker.patch.object(api.baremetal_events, "get_handler")

    response = client.post("/v1/notifications/baremetal", json=VALID_NOTIFICATION)

    assert response.status_code == 204
    assert response.content == b""
    get_handler.assert_called_once_with("baremetal.node.power_set.end")
    get_handler.return_value.assert_called_once_with({"node": "node-1"})


def test_notifications_baremetal_handler_error(client, mocker):
    get_handler = mocker.patch.object(api.baremetal_events, "get_handler")
    get_handler.return_value.side_effect = RuntimeError("handler broken")

    response = client.post("/v1/notifications/baremetal", json=VALID_NOTIFICATION)

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to process baremetal notification"


def test_notifications_baremetal_rejects_non_uuid_message_id(client):
    notification = {**VALID_NOTIFICATION, "message_id": "not-a-uuid"}
    response = client.post("/v1/notifications/baremetal", json=notification)
    assert response.status_code == 422


def test_notifications_baremetal_unknown_event_type_uses_default_handler(client):
    notification = {
        **VALID_NOTIFICATION,
        "event_type": "foo.bar.baz.qux",
        "payload": {"ironic_object.data": {"name": "n1"}},
    }
    response = client.post("/v1/notifications/baremetal", json=notification)
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# sonic_ztp_complete
# ---------------------------------------------------------------------------


def test_sonic_ztp_complete_without_netbox(client):
    with patch.dict("osism.utils.__dict__", {"nb": None}):
        response = client.post("/v1/sonic/sw1/ztp/complete")
    assert response.status_code == 503
    assert response.json()["detail"] == "NetBox is not enabled"


def test_sonic_ztp_complete_marks_device_active(client, mocker):
    device = MagicMock()
    device.name = "sw1"
    device.custom_fields = {}
    find = mocker.patch("osism.api.find_device_by_identifier", return_value=device)

    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/sonic/serial-1/ztp/complete")

    assert response.status_code == 200
    assert response.json() == {"result": "ok", "device": "sw1"}
    find.assert_called_once_with("serial-1")
    assert device.custom_fields["provision_state"] == "active"
    device.save.assert_called_once_with()


def test_sonic_ztp_complete_device_not_found(client, mocker):
    mocker.patch("osism.api.find_device_by_identifier", return_value=None)
    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/sonic/unknown-device/ztp/complete")
    assert response.status_code == 404
    assert "unknown-device" in response.json()["detail"]


def test_sonic_ztp_complete_save_error(client, mocker):
    device = MagicMock()
    device.name = "sw1"
    device.custom_fields = {}
    device.save.side_effect = RuntimeError("netbox down")
    mocker.patch("osism.api.find_device_by_identifier", return_value=device)

    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/sonic/sw1/ztp/complete")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to complete ZTP process"


# ---------------------------------------------------------------------------
# webhook
# ---------------------------------------------------------------------------


VALID_WEBHOOK = {
    "username": "admin",
    "data": {
        "url": "/api/dcim/devices/1/",
        "name": "sw1",
        "tags": [{"name": "Managed by OSISM"}],
        "custom_fields": {"device_type": "server"},
    },
    "snapshots": {},
    "event": "updated",
    "timestamp": "2026-01-01T00:00:00Z",
    "model": "device",
    "request_id": "f8a6e0a4-3c1b-4f53-9c5f-2f4f3b2a1e00",
}


def test_webhook_without_netbox(client):
    with patch.dict("osism.utils.__dict__", {"nb": None}):
        response = client.post("/v1/webhook/netbox", json=VALID_WEBHOOK)
    assert response.status_code == 503
    assert response.json()["detail"] == "NetBox webhook processing is not enabled"


def test_webhook_processes_parsed_data(client, mocker):
    process = mocker.patch("osism.api.process_netbox_webhook")

    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/webhook/netbox", json=VALID_WEBHOOK)

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    process.assert_called_once()
    webhook_input = process.call_args.args[0]
    assert isinstance(webhook_input, api.WebhookNetboxData)
    assert webhook_input.username == "admin"
    assert webhook_input.data == VALID_WEBHOOK["data"]
    assert webhook_input.request_id == UUID(VALID_WEBHOOK["request_id"])


def test_webhook_processing_error(client, mocker):
    mocker.patch("osism.api.process_netbox_webhook", side_effect=RuntimeError("broken"))
    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/webhook/netbox", json=VALID_WEBHOOK)
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to process NetBox webhook"


def test_webhook_rejects_missing_required_field(client, mocker):
    process = mocker.patch("osism.api.process_netbox_webhook")
    body = {k: v for k, v in VALID_WEBHOOK.items() if k != "request_id"}
    with patch.dict("osism.utils.__dict__", {"nb": MagicMock()}):
        response = client.post("/v1/webhook/netbox", json=body)
    assert response.status_code == 422
    process.assert_not_called()


# ---------------------------------------------------------------------------
# websocket_openstack_events
# ---------------------------------------------------------------------------


FILTERS = {
    "event_filters": ["baremetal.node.power_set.end"],
    "node_filters": ["server-01"],
    "service_filters": ["baremetal"],
}


@pytest.fixture
def ws_manager(mocker):
    """Stub the module-level WebSocket manager.

    The real ``connect`` accepts the socket and starts the broadcaster
    background task; the stub only accepts, so no task is started.
    """
    manager = MagicMock()

    async def fake_connect(websocket):
        await websocket.accept()

    manager.connect = AsyncMock(side_effect=fake_connect)
    manager.update_filters = AsyncMock()
    manager.disconnect = AsyncMock()
    mocker.patch("osism.api.websocket_manager", manager)
    return manager


def test_websocket_connect_and_disconnect(client, ws_manager):
    with client.websocket_connect("/v1/events/openstack"):
        pass
    ws_manager.connect.assert_awaited_once()
    websocket = ws_manager.connect.await_args.args[0]
    assert isinstance(websocket, WebSocket)
    ws_manager.disconnect.assert_awaited_once_with(websocket)


def test_websocket_set_filters_acknowledged(client, ws_manager):
    with client.websocket_connect("/v1/events/openstack") as websocket:
        websocket.send_text(json.dumps({"action": "set_filters", **FILTERS}))
        ack = websocket.receive_json()

    assert ack == {"type": "filter_update", "status": "success", **FILTERS}
    connected = ws_manager.connect.await_args.args[0]
    ws_manager.update_filters.assert_awaited_once_with(
        connected,
        event_filters=FILTERS["event_filters"],
        node_filters=FILTERS["node_filters"],
        service_filters=FILTERS["service_filters"],
    )


def test_websocket_set_filters_missing_keys_default_to_none(client, ws_manager):
    with client.websocket_connect("/v1/events/openstack") as websocket:
        websocket.send_text(
            json.dumps({"action": "set_filters", "event_filters": ["x"]})
        )
        ack = websocket.receive_json()

    assert ack == {
        "type": "filter_update",
        "status": "success",
        "event_filters": ["x"],
        "node_filters": None,
        "service_filters": None,
    }
    assert ws_manager.update_filters.await_args.kwargs == {
        "event_filters": ["x"],
        "node_filters": None,
        "service_filters": None,
    }


def test_websocket_invalid_json_is_ignored(client, ws_manager):
    with client.websocket_connect("/v1/events/openstack") as websocket:
        websocket.send_text("{not json")
        websocket.send_text(json.dumps({"action": "set_filters", **FILTERS}))
        ack = websocket.receive_json()

    assert ack["type"] == "filter_update"
    assert ack["event_filters"] == FILTERS["event_filters"]
    ws_manager.update_filters.assert_awaited_once()


def test_websocket_other_action_is_ignored(client, ws_manager):
    with client.websocket_connect("/v1/events/openstack") as websocket:
        websocket.send_text(json.dumps({"action": "subscribe"}))
        websocket.send_text(json.dumps({"action": "set_filters", **FILTERS}))
        ack = websocket.receive_json()

    assert ack["status"] == "success"
    ws_manager.update_filters.assert_awaited_once()


def test_websocket_update_filters_error_keeps_connection_open(client, ws_manager):
    ws_manager.update_filters.side_effect = [RuntimeError("boom"), None]

    with client.websocket_connect("/v1/events/openstack") as websocket:
        websocket.send_text(json.dumps({"action": "set_filters", **FILTERS}))
        websocket.send_text(json.dumps({"action": "set_filters", **FILTERS}))
        ack = websocket.receive_json()

    assert ack["status"] == "success"
    assert ws_manager.update_filters.await_count == 2


# ---------------------------------------------------------------------------
# get_inventory_hosts
# ---------------------------------------------------------------------------


def test_get_inventory_hosts_missing_inventory(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=False)
    response = client.get("/v1/inventory/hosts")
    assert response.status_code == 503
    assert INVENTORY_PATH in response.json()["detail"]


def test_get_inventory_hosts_load_error(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(returncode=1, stderr="broken inventory"),
    )
    response = client.get("/v1/inventory/hosts")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to load Ansible inventory"


def test_get_inventory_hosts_returns_hosts(client, mocker):
    inventory = {"_meta": {"hostvars": {}}, "all": {"hosts": ["node-1", "node-2"]}}
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    run = mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps(inventory)),
    )
    get_hosts = mocker.patch(
        "osism.api.get_hosts_from_inventory", return_value=["node-1", "node-2"]
    )

    response = client.get("/v1/inventory/hosts")

    assert response.status_code == 200
    assert response.json() == {"hosts": ["node-1", "node-2"], "count": 2}
    assert run.call_args.args[0] == [
        "ansible-inventory",
        "-i",
        INVENTORY_PATH,
        "--list",
    ]
    get_hosts.assert_called_once_with(inventory)


def test_get_inventory_hosts_limit_extends_command(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    run = mocker.patch("osism.api.subprocess.run", return_value=completed(stdout="{}"))
    mocker.patch("osism.api.get_hosts_from_inventory", return_value=[])

    response = client.get("/v1/inventory/hosts", params={"limit": "compute*"})

    assert response.status_code == 200
    assert run.call_args.args[0] == [
        "ansible-inventory",
        "-i",
        INVENTORY_PATH,
        "--list",
        "--limit",
        "compute*",
    ]


def test_get_inventory_hosts_timeout(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    mocker.patch(
        "osism.api.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ansible-inventory", timeout=30),
    )
    response = client.get("/v1/inventory/hosts")
    assert response.status_code == 504


def test_get_inventory_hosts_invalid_json(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    mocker.patch("osism.api.subprocess.run", return_value=completed(stdout="{not json"))
    response = client.get("/v1/inventory/hosts")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to parse Ansible inventory"


def test_get_inventory_hosts_generic_error(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.os.path.exists", return_value=True)
    mocker.patch("osism.api.subprocess.run", return_value=completed(stdout="{}"))
    mocker.patch("osism.api.get_hosts_from_inventory", side_effect=RuntimeError("boom"))
    response = client.get("/v1/inventory/hosts")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to retrieve hosts: boom"


# ---------------------------------------------------------------------------
# get_host_hostvars / get_host_hostvar
# ---------------------------------------------------------------------------


HOSTVARS_URLS = [
    "/v1/inventory/hosts/node-1/hostvars",
    "/v1/inventory/hosts/node-1/hostvars/ansible_host",
]
HOSTVARS_URL_IDS = ["all", "single"]


def test_get_host_hostvars_returns_sorted_variables(client, mocker):
    inventory_path = mocker.patch(
        "osism.api.get_inventory_path", return_value=INVENTORY_PATH
    )
    run = mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps({"b_var": 2, "a_var": 1})),
    )

    response = client.get("/v1/inventory/hosts/node-1/hostvars")

    assert response.status_code == 200
    assert response.json() == {
        "host": "node-1",
        "variables": [
            {"name": "a_var", "value": 1},
            {"name": "b_var", "value": 2},
        ],
        "count": 2,
    }
    inventory_path.assert_called_once_with(INVENTORY_PATH, prefer_minified=False)
    assert run.call_args.args[0] == [
        "ansible-inventory",
        "-i",
        INVENTORY_PATH,
        "--host",
        "node-1",
    ]


def test_get_host_hostvars_masks_secrets(client, mocker):
    hostvars = {
        "ansible_password": "x",
        "vaulted": "$ANSIBLE_VAULT;1.1;AES256\n61323964",
    }
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps(hostvars)),
    )

    response = client.get("/v1/inventory/hosts/node-1/hostvars")

    assert response.status_code == 200
    assert response.json()["variables"] == [
        {"name": "ansible_password", "value": "***"},
        {"name": "vaulted", "value": "***"},
    ]


@pytest.mark.parametrize("url", HOSTVARS_URLS, ids=HOSTVARS_URL_IDS)
@pytest.mark.parametrize(
    "stderr,expected_status",
    [
        ("Could not match supplied host pattern: node-1", 404),
        ("Unable to parse /inventory/hosts.yml", 500),
        ("some other error", 500),
    ],
    ids=["no-match", "unparsable", "other"],
)
def test_hostvars_endpoints_map_ansible_errors(
    client, mocker, url, stderr, expected_status
):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(returncode=1, stderr=stderr),
    )
    response = client.get(url)
    assert response.status_code == expected_status
    if expected_status == 404:
        assert response.json()["detail"] == "Host 'node-1' not found in inventory"


@pytest.mark.parametrize("url", HOSTVARS_URLS, ids=HOSTVARS_URL_IDS)
def test_hostvars_endpoints_timeout(client, mocker, url):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ansible-inventory", timeout=30),
    )
    response = client.get(url)
    assert response.status_code == 504


@pytest.mark.parametrize("url", HOSTVARS_URLS, ids=HOSTVARS_URL_IDS)
def test_hostvars_endpoints_invalid_json(client, mocker, url):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch("osism.api.subprocess.run", return_value=completed(stdout="{not json"))
    response = client.get(url)
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to parse host variables for node-1"


def test_get_host_hostvar_returns_value(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps({"ansible_host": "10.0.0.1"})),
    )
    response = client.get("/v1/inventory/hosts/node-1/hostvars/ansible_host")
    assert response.status_code == 200
    assert response.json() == {
        "host": "node-1",
        "name": "ansible_host",
        "value": "10.0.0.1",
    }


def test_get_host_hostvar_masks_secret_value(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps({"database_password": "hunter2"})),
    )
    response = client.get("/v1/inventory/hosts/node-1/hostvars/database_password")
    assert response.status_code == 200
    assert response.json()["value"] == "***"


def test_get_host_hostvar_not_found(client, mocker):
    mocker.patch("osism.api.get_inventory_path", return_value=INVENTORY_PATH)
    mocker.patch(
        "osism.api.subprocess.run",
        return_value=completed(stdout=json.dumps({"other": 1})),
    )
    response = client.get("/v1/inventory/hosts/node-1/hostvars/ansible_host")
    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "Variable 'ansible_host' not found for host 'node-1'"
    )


# ---------------------------------------------------------------------------
# get_host_facts / get_host_fact
# ---------------------------------------------------------------------------


def get_with_redis(client, fake_redis, url):
    with patch.dict("osism.utils.__dict__", {"redis": fake_redis}):
        return client.get(url)


def test_get_host_facts_cache_miss(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = None

    response = get_with_redis(client, fake_redis, "/v1/inventory/hosts/node-1/facts")

    assert response.status_code == 404
    assert response.json()["detail"] == "No facts found in cache for host 'node-1'"
    fake_redis.get.assert_called_once_with("ansible_factsnode-1")


def test_get_host_facts_returns_sorted_facts(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"b_fact": 2, "a_fact": 1}).encode()

    response = get_with_redis(client, fake_redis, "/v1/inventory/hosts/node-1/facts")

    assert response.status_code == 200
    assert response.json() == {
        "host": "node-1",
        "facts": [
            {"name": "a_fact", "value": 1},
            {"name": "b_fact", "value": 2},
        ],
        "count": 2,
        "from_cache": True,
    }


def test_get_host_facts_invalid_json(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = b"{not json"

    response = get_with_redis(client, fake_redis, "/v1/inventory/hosts/node-1/facts")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to parse facts for node-1"


def test_get_host_facts_redis_error(client):
    fake_redis = MagicMock()
    fake_redis.get.side_effect = RuntimeError("redis down")

    response = get_with_redis(client, fake_redis, "/v1/inventory/hosts/node-1/facts")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to retrieve facts: redis down"


def test_get_host_fact_returns_value(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"ansible_hostname": "node-1"}).encode()

    response = get_with_redis(
        client, fake_redis, "/v1/inventory/hosts/node-1/facts/ansible_hostname"
    )

    assert response.status_code == 200
    assert response.json() == {
        "host": "node-1",
        "name": "ansible_hostname",
        "value": "node-1",
        "from_cache": True,
    }


def test_get_host_fact_not_found(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = json.dumps({"other": 1}).encode()

    response = get_with_redis(
        client, fake_redis, "/v1/inventory/hosts/node-1/facts/ansible_hostname"
    )

    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "Fact 'ansible_hostname' not found for host 'node-1'"
    )


def test_get_host_fact_cache_miss(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = None

    response = get_with_redis(
        client, fake_redis, "/v1/inventory/hosts/node-1/facts/ansible_hostname"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "No facts found in cache for host 'node-1'"


def test_get_host_fact_invalid_json(client):
    fake_redis = MagicMock()
    fake_redis.get.return_value = b"{not json"

    response = get_with_redis(
        client, fake_redis, "/v1/inventory/hosts/node-1/facts/ansible_hostname"
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to parse facts for node-1"


# ---------------------------------------------------------------------------
# search_inventory
# ---------------------------------------------------------------------------


def setup_search(
    mocker, *, hosts, hostvars=None, facts=None, inventory_exists=True, list_result=None
):
    """Patch the collaborators of the search endpoint.

    ``hostvars`` maps host name to a dict (JSON-encoded as ansible-inventory
    stdout), a raw stdout string, or an exception to raise from
    ``subprocess.run``. ``facts`` maps host name to a dict or raw string
    (facts file content) or an exception to raise from ``open``; only hosts
    listed in ``facts`` have an existing facts file.
    """
    hostvars = hostvars or {}
    facts = facts or {}

    def fake_inventory_path(base_path, prefer_minified=True):
        return FULL_INVENTORY if prefer_minified is False else MINIFIED_INVENTORY

    inventory_path = mocker.patch(
        "osism.api.get_inventory_path", side_effect=fake_inventory_path
    )

    def fake_exists(path):
        if path == MINIFIED_INVENTORY:
            return inventory_exists
        return path in {f"/cache/facts/{host}" for host in facts}

    mocker.patch("osism.api.os.path.exists", side_effect=fake_exists)

    def fake_run(command, **kwargs):
        if "--list" in command:
            return list_result or completed(stdout="{}")
        host = command[command.index("--host") + 1]
        spec = hostvars[host]
        if isinstance(spec, Exception):
            raise spec
        if isinstance(spec, str):
            return completed(stdout=spec)
        return completed(stdout=json.dumps(spec))

    run = mocker.patch("osism.api.subprocess.run", side_effect=fake_run)
    mocker.patch("osism.api.get_hosts_from_inventory", return_value=hosts)

    def fake_open(path, *args, **kwargs):
        spec = facts[os.path.basename(path)]
        if isinstance(spec, Exception):
            raise spec
        data = spec if isinstance(spec, str) else json.dumps(spec)
        return mock_open(read_data=data)(path)

    mocker.patch("builtins.open", side_effect=fake_open)

    return inventory_path, run


def search(client, **params):
    return client.get("/v1/inventory/search", params=params)


def test_search_requires_name_pattern(client):
    response = client.get("/v1/inventory/search")
    assert response.status_code == 422


def test_search_invalid_name_pattern(client):
    response = search(client, name_pattern="[")
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Invalid name_pattern regex:")


def test_search_invalid_host_pattern(client):
    response = search(client, name_pattern="ansible", host_pattern="[")
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Invalid host_pattern regex:")


def test_search_invalid_source(client):
    response = search(client, name_pattern="ansible", source="bogus")
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "source must be 'hostvars', 'facts', or omitted for both"
    )


def test_search_missing_inventory(client, mocker):
    setup_search(mocker, hosts=[], inventory_exists=False)
    response = search(client, name_pattern="ansible")
    assert response.status_code == 503
    assert MINIFIED_INVENTORY in response.json()["detail"]


def test_search_inventory_load_failure(client, mocker):
    setup_search(
        mocker,
        hosts=[],
        list_result=completed(returncode=1, stderr="broken inventory"),
    )
    response = search(client, name_pattern="ansible")
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to load Ansible inventory"


def test_search_hostvars_matches_and_masks(client, mocker):
    inventory_path, run = setup_search(
        mocker,
        hosts=["node-1", "node-2"],
        hostvars={
            "node-1": {"ansible_host": "10.0.0.1", "ansible_password": "x", "other": 1},
            "node-2": {"ansible_hostname": "node-2"},
        },
    )

    response = search(client, name_pattern="ANSIBLE", source="hostvars")

    assert response.status_code == 200
    body = response.json()
    assert body["hosts_searched"] == 2
    assert body["count"] == 3
    assert all(result["source"] == "hostvars" for result in body["results"])
    values = {
        (result["host"], result["name"]): result["value"] for result in body["results"]
    }
    assert values == {
        ("node-1", "ansible_host"): "10.0.0.1",
        ("node-1", "ansible_password"): "***",
        ("node-2", "ansible_hostname"): "node-2",
    }
    assert body["query"] == {
        "name_pattern": "ANSIBLE",
        "host_pattern": None,
        "source": "hostvars",
        "limit": 100,
    }
    assert inventory_path.call_args_list == [
        call(INVENTORY_PATH, prefer_minified=False),
        call(INVENTORY_PATH),
    ]
    commands = [command.args[0] for command in run.call_args_list]
    assert commands == [
        ["ansible-inventory", "-i", MINIFIED_INVENTORY, "--list"],
        ["ansible-inventory", "-i", FULL_INVENTORY, "--host", "node-1"],
        ["ansible-inventory", "-i", FULL_INVENTORY, "--host", "node-2"],
    ]


def test_search_host_pattern_filters_hosts(client, mocker):
    _, run = setup_search(
        mocker,
        hosts=["compute-1", "control-1"],
        hostvars={
            "compute-1": {"ansible_host": "10.0.0.1"},
            "control-1": {"ansible_host": "10.0.0.2"},
        },
    )

    response = search(
        client, name_pattern="ansible", host_pattern="compute.*", source="hostvars"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["hosts_searched"] == 1
    assert [result["host"] for result in body["results"]] == ["compute-1"]
    assert run.call_count == 2  # the --list call plus one --host call


def test_search_facts_source_skips_hostvars(client, mocker):
    _, run = setup_search(
        mocker,
        hosts=["node-1", "node-2"],
        facts={"node-1": {"ansible_hostname": "node-1", "misc": 1}},
    )

    response = search(client, name_pattern="ansible", source="facts")

    assert response.status_code == 200
    body = response.json()
    assert body["hosts_searched"] == 2
    assert body["results"] == [
        {
            "host": "node-1",
            "name": "ansible_hostname",
            "value": "node-1",
            "source": "facts",
        }
    ]
    assert run.call_count == 1  # only the --list call, no per-host lookups


def test_search_limit_stops_early(client, mocker):
    _, run = setup_search(
        mocker,
        hosts=["node-1", "node-2"],
        hostvars={
            "node-1": {"ansible_a": 1, "ansible_b": 2, "ansible_c": 3},
            "node-2": {"ansible_d": 4},
        },
    )

    response = search(client, name_pattern="ansible", source="hostvars", limit=2)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert len(body["results"]) == 2
    assert body["query"]["limit"] == 2
    assert run.call_count == 2  # node-2 is never queried once the limit is hit


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired(cmd="ansible-inventory", timeout=10), "{not json"],
    ids=["timeout", "invalid-json"],
)
def test_search_skips_hosts_with_hostvar_failures(client, mocker, failure):
    setup_search(
        mocker,
        hosts=["node-1", "node-2"],
        hostvars={"node-1": failure, "node-2": {"ansible_host": "10.0.0.2"}},
    )

    response = search(client, name_pattern="ansible", source="hostvars")

    assert response.status_code == 200
    body = response.json()
    assert body["hosts_searched"] == 2
    assert [result["host"] for result in body["results"]] == ["node-2"]


@pytest.mark.parametrize(
    "failure",
    ["{not json", IOError("unreadable")],
    ids=["invalid-json", "io-error"],
)
def test_search_skips_unreadable_facts(client, mocker, failure):
    setup_search(
        mocker,
        hosts=["node-1", "node-2"],
        facts={"node-1": failure, "node-2": {"ansible_hostname": "node-2"}},
    )

    response = search(client, name_pattern="ansible", source="facts")

    assert response.status_code == 200
    body = response.json()
    assert [result["host"] for result in body["results"]] == ["node-2"]
