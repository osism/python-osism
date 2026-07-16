# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the module-level helpers and Pydantic models in :mod:`osism.api`.

Covers ``_mask_inventory_secrets``, ``find_device_by_identifier``,
``process_netbox_webhook``, ``LogConfig`` and the request/response models.
The HTTP and WebSocket endpoints are exercised separately with the FastAPI
``TestClient`` and are out of scope here.

Importing :mod:`osism.api` has import-time side effects: it applies
``dictConfig(LogConfig().model_dump())`` and pulls in
``osism.services.event_bridge``, whose module-level ``EventBridge()``
instantiation attempts a Redis connection. That failure is caught and only
logged, so these tests need no Redis.

``osism.utils`` materializes its ``nb`` NetBox connection lazily via a module
``__getattr__``; tests therefore inject fakes with
``patch.dict("osism.utils.__dict__", {"nb": ...})`` instead of
``mocker.patch("osism.utils.nb")``, which would trigger a real connection
attempt when reading the original attribute.
"""

import copy
import datetime
from logging.config import dictConfig
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from osism import api

# ---------------------------------------------------------------------------
# _mask_inventory_secrets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "admin_password",
        "ADMIN_Password",
        "secret",
        "keystone_secret_key",
        "ironic_osism_user",
    ],
)
def test_mask_inventory_secrets_masks_secret_keys(key):
    assert api._mask_inventory_secrets({key: "value"}) == {key: "***"}


def test_mask_inventory_secrets_masks_vault_encrypted_values():
    data = {"var": "$ANSIBLE_VAULT;1.1;AES256\n61323964"}
    assert api._mask_inventory_secrets(data) == {"var": "***"}


def test_mask_inventory_secrets_masks_vault_values_with_leading_whitespace():
    data = {"var": "  $ANSIBLE_VAULT;1.1;AES256\n61323964"}
    assert api._mask_inventory_secrets(data) == {"var": "***"}


def test_mask_inventory_secrets_keeps_vault_marker_inside_value():
    data = {"var": "see $ANSIBLE_VAULT;1.1;AES256 for details"}
    assert api._mask_inventory_secrets(data) == dict(data)


def test_mask_inventory_secrets_recurses_into_nested_dicts():
    data = {"outer": {"inner": {"db_password": "hunter2", "port": 5432}}}
    assert api._mask_inventory_secrets(data) == {
        "outer": {"inner": {"db_password": "***", "port": 5432}}
    }


def test_mask_inventory_secrets_masks_dict_value_of_secret_key_as_whole():
    data = {"secrets": {"inner": "value"}}
    assert api._mask_inventory_secrets(data) == {"secrets": "***"}


@pytest.mark.parametrize("value", [42, [1, 2], None, True])
def test_mask_inventory_secrets_passes_through_non_dict_non_string_values(value):
    assert api._mask_inventory_secrets({"key": value}) == {"key": value}


def test_mask_inventory_secrets_recurses_into_lists():
    data = {"hosts": [{"db_password": "hunter2", "port": 5432}]}
    assert api._mask_inventory_secrets(data) == {
        "hosts": [{"db_password": "***", "port": 5432}]
    }


def test_mask_inventory_secrets_masks_vault_values_inside_lists():
    data = {"vars": ["plain", "$ANSIBLE_VAULT;1.1;AES256\n61323964"]}
    assert api._mask_inventory_secrets(data) == {"vars": ["plain", "***"]}


def test_mask_inventory_secrets_recurses_into_nested_lists():
    data = {"groups": [[{"api_secret": "token"}]]}
    assert api._mask_inventory_secrets(data) == {"groups": [[{"api_secret": "***"}]]}


def test_mask_inventory_secrets_empty_dict():
    assert api._mask_inventory_secrets({}) == {}


def test_mask_inventory_secrets_passes_through_non_string_keys():
    assert api._mask_inventory_secrets({42: "value"}) == {42: "value"}


def test_mask_inventory_secrets_does_not_mutate_input():
    data = {"db_password": "hunter2", "nested": {"api_secret": "token"}}
    original = copy.deepcopy(data)
    api._mask_inventory_secrets(data)
    assert data == original


# ---------------------------------------------------------------------------
# find_device_by_identifier
# ---------------------------------------------------------------------------


def make_nb(name_result=(), cf_result=(), serial_result=()):
    """Build a fake NetBox client whose device filter answers by kwarg."""
    nb = MagicMock()

    def filter_devices(**kwargs):
        if "name" in kwargs:
            return list(name_result)
        if "cf_inventory_hostname" in kwargs:
            return list(cf_result)
        if "serial" in kwargs:
            return list(serial_result)
        raise AssertionError(f"unexpected filter arguments: {kwargs}")

    nb.dcim.devices.filter.side_effect = filter_devices
    return nb


def test_find_device_returns_none_without_netbox_connection():
    with patch.dict("osism.utils.__dict__", {"nb": None}):
        assert api.find_device_by_identifier("node-1") is None


def test_find_device_by_name():
    device = MagicMock()
    nb = make_nb(name_result=[device])
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        assert api.find_device_by_identifier("node-1") is device
    assert nb.dcim.devices.filter.call_args_list == [call(name="node-1")]


def test_find_device_by_inventory_hostname():
    device = MagicMock()
    nb = make_nb(cf_result=[device])
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        assert api.find_device_by_identifier("node-1") is device
    assert nb.dcim.devices.filter.call_args_list == [
        call(name="node-1"),
        call(cf_inventory_hostname="node-1"),
    ]


def test_find_device_by_serial():
    device = MagicMock()
    nb = make_nb(serial_result=[device])
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        assert api.find_device_by_identifier("ABC123") is device
    assert nb.dcim.devices.filter.call_args_list == [
        call(name="ABC123"),
        call(cf_inventory_hostname="ABC123"),
        call(serial="ABC123"),
    ]


def test_find_device_returns_none_when_no_filter_matches():
    nb = make_nb()
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        assert api.find_device_by_identifier("node-1") is None
    assert nb.dcim.devices.filter.call_count == 3


def test_find_device_returns_first_of_multiple_matches():
    first = MagicMock()
    second = MagicMock()
    nb = make_nb(name_result=[first, second])
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        assert api.find_device_by_identifier("node-1") is first


# ---------------------------------------------------------------------------
# process_netbox_webhook
# ---------------------------------------------------------------------------


def make_webhook_input(data):
    return api.WebhookNetboxData(
        username="admin",
        data=data,
        snapshots={},
        event="updated",
        timestamp="2026-01-01T00:00:00Z",
        model="device",
        request_id="f8a6e0a4-3c1b-4f53-9c5f-2f4f3b2a1e00",
    )


def device_data(device_type="server", managed=True, **overrides):
    data = {
        "url": "/api/dcim/devices/1/",
        "name": "node-1",
        "tags": [{"name": "Managed by OSISM"}] if managed else [{"name": "other"}],
        "custom_fields": {"device_type": device_type},
    }
    data.update(overrides)
    return data


def test_webhook_managed_server_triggers_reconciler(mocker):
    run = mocker.patch("osism.api.reconciler.run")
    api.process_netbox_webhook(make_webhook_input(device_data()))
    run.delay.assert_called_once_with()


def test_webhook_managed_switch_does_not_trigger_reconciler(mocker):
    run = mocker.patch("osism.api.reconciler.run")
    api.process_netbox_webhook(make_webhook_input(device_data(device_type="switch")))
    run.delay.assert_not_called()


@pytest.mark.parametrize(
    "custom_fields", [{}, {"device_type": None}], ids=["missing", "none"]
)
def test_webhook_device_type_falls_back_to_node(mocker, custom_fields):
    run = mocker.patch("osism.api.reconciler.run")
    api.process_netbox_webhook(
        make_webhook_input(device_data(custom_fields=custom_fields))
    )
    run.delay.assert_not_called()


def test_webhook_interface_fetches_device_and_does_not_trigger_reconciler(mocker):
    run = mocker.patch("osism.api.reconciler.run")
    device = MagicMock()
    device.name = "node-1"
    device.tags = ["Managed by OSISM"]
    device.custom_fields = {"device_type": "server"}
    nb = MagicMock()
    nb.dcim.devices.get.return_value = device
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        api.process_netbox_webhook(
            make_webhook_input(
                {"url": "/api/dcim/interfaces/5/", "name": "eth0", "device": {"id": 1}}
            )
        )
    nb.dcim.devices.get.assert_called_once_with(id=1)
    run.delay.assert_not_called()


def test_webhook_unknown_url_returns_early(mocker):
    run = mocker.patch("osism.api.reconciler.run")
    nb = MagicMock()
    with patch.dict("osism.utils.__dict__", {"nb": nb}):
        api.process_netbox_webhook(
            make_webhook_input({"url": "/api/dcim/sites/1/", "name": "site-1"})
        )
    nb.dcim.devices.get.assert_not_called()
    run.delay.assert_not_called()


def test_webhook_unmanaged_device_is_ignored(mocker):
    run = mocker.patch("osism.api.reconciler.run")
    api.process_netbox_webhook(make_webhook_input(device_data(managed=False)))
    run.delay.assert_not_called()


def test_webhook_missing_data_keys_raises_key_error(mocker):
    mocker.patch("osism.api.reconciler.run")
    with pytest.raises(KeyError):
        api.process_netbox_webhook(make_webhook_input({}))


# ---------------------------------------------------------------------------
# LogConfig
# ---------------------------------------------------------------------------


def test_log_config_defaults():
    config = api.LogConfig()
    assert config.LOGGER_NAME == "osism"
    assert config.LOG_LEVEL == "INFO"
    assert config.version == 1
    assert config.disable_existing_loggers is False


def test_log_config_model_dump_structure():
    dump = api.LogConfig().model_dump()
    assert "default" in dump["formatters"]
    handler = dump["handlers"]["default"]
    assert handler["class"] == "logging.StreamHandler"
    assert handler["stream"] == "ext://sys.stderr"
    for name in ("osism", "api", "uvicorn", "uvicorn.error", "uvicorn.access"):
        assert name in dump["loggers"]


def test_log_config_is_usable_by_dict_config():
    dictConfig(api.LogConfig().model_dump())


# ---------------------------------------------------------------------------
# NotificationBaremetal
# ---------------------------------------------------------------------------


VALID_NOTIFICATION = {
    "priority": "INFO",
    "event_type": "baremetal.node.power_set.end",
    "timestamp": "2026-01-01 00:00:00.000000",
    "publisher_id": "ironic-conductor",
    "message_id": "f8a6e0a4-3c1b-4f53-9c5f-2f4f3b2a1e00",
    "payload": {"node": "node-1"},
}


def test_notification_baremetal_accepts_valid_payload():
    notification = api.NotificationBaremetal(**VALID_NOTIFICATION)
    assert notification.message_id == UUID(VALID_NOTIFICATION["message_id"])
    assert notification.payload == {"node": "node-1"}


def test_notification_baremetal_rejects_non_uuid_message_id():
    with pytest.raises(ValidationError):
        api.NotificationBaremetal(**{**VALID_NOTIFICATION, "message_id": "not-a-uuid"})


@pytest.mark.parametrize("field", sorted(VALID_NOTIFICATION))
def test_notification_baremetal_requires_field(field):
    payload = {k: v for k, v in VALID_NOTIFICATION.items() if k != field}
    with pytest.raises(ValidationError):
        api.NotificationBaremetal(**payload)


# ---------------------------------------------------------------------------
# WebhookNetboxData
# ---------------------------------------------------------------------------


VALID_WEBHOOK = {
    "username": "admin",
    "data": {"url": "/api/dcim/devices/1/", "name": "node-1"},
    "snapshots": {},
    "event": "updated",
    "timestamp": "2026-01-01T00:00:00Z",
    "model": "device",
    "request_id": "f8a6e0a4-3c1b-4f53-9c5f-2f4f3b2a1e00",
}


def test_webhook_netbox_data_coerces_timestamp_and_request_id():
    webhook = api.WebhookNetboxData(**VALID_WEBHOOK)
    assert isinstance(webhook.timestamp, datetime.datetime)
    assert webhook.request_id == UUID(VALID_WEBHOOK["request_id"])


@pytest.mark.parametrize(
    "field,value", [("timestamp", "not-a-date"), ("request_id", "not-a-uuid")]
)
def test_webhook_netbox_data_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        api.WebhookNetboxData(**{**VALID_WEBHOOK, field: value})


@pytest.mark.parametrize("field", sorted(VALID_WEBHOOK))
def test_webhook_netbox_data_requires_field(field):
    payload = {k: v for k, v in VALID_WEBHOOK.items() if k != field}
    with pytest.raises(ValidationError):
        api.WebhookNetboxData(**payload)


# ---------------------------------------------------------------------------
# Models with only optional fields
# ---------------------------------------------------------------------------


def test_baremetal_node_all_fields_optional():
    node = api.BaremetalNode()
    assert node.uuid is None
    assert node.name is None
    assert node.traits == []
    assert node.properties == {}
    assert node.extra == {}


def test_baremetal_node_default_factories_are_independent():
    first = api.BaremetalNode()
    second = api.BaremetalNode()
    first.traits.append("CUSTOM_TRAIT")
    first.properties["cpus"] = 4
    first.extra["note"] = "x"
    assert second.traits == []
    assert second.properties == {}
    assert second.extra == {}


@pytest.mark.parametrize(
    "model",
    [api.BaremetalNodeParameters, api.BaremetalNodeNetboxInfo, api.BaremetalPort],
    ids=lambda model: model.__name__,
)
def test_optional_models_instantiable_without_arguments(model):
    instance = model()
    assert all(value is None for value in instance.model_dump().values())


def test_device_search_result_device_defaults_to_none():
    result = api.DeviceSearchResult(result="ok")
    assert result.device is None


def test_device_search_result_requires_result():
    with pytest.raises(ValidationError):
        api.DeviceSearchResult()


# ---------------------------------------------------------------------------
# Models with required fields
# ---------------------------------------------------------------------------


REQUIRED_MODEL_CASES = [
    (api.WebhookNetboxResponse, {"result": "ok"}),
    (api.SinkResponse, {"result": "ok"}),
    (api.HostsResponse, {"hosts": ["node-1"], "count": 1}),
    (api.HostvarEntry, {"name": "ansible_host", "value": "10.0.0.1"}),
    (
        api.HostvarsResponse,
        {
            "host": "node-1",
            "variables": [{"name": "ansible_host", "value": "10.0.0.1"}],
            "count": 1,
        },
    ),
    (
        api.HostvarSingleResponse,
        {"host": "node-1", "name": "ansible_host", "value": "10.0.0.1"},
    ),
    (api.FactEntry, {"name": "ansible_hostname", "value": "node-1"}),
    (
        api.FactsResponse,
        {
            "host": "node-1",
            "facts": [{"name": "ansible_hostname", "value": "node-1"}],
            "count": 1,
            "from_cache": True,
        },
    ),
    (
        api.FactSingleResponse,
        {
            "host": "node-1",
            "name": "ansible_hostname",
            "value": "node-1",
            "from_cache": False,
        },
    ),
    (
        api.SearchResultEntry,
        {
            "host": "node-1",
            "name": "ansible_host",
            "value": "10.0.0.1",
            "source": "hostvars",
        },
    ),
    (
        api.SearchResponse,
        {
            "results": [
                {
                    "host": "node-1",
                    "name": "ansible_host",
                    "value": "10.0.0.1",
                    "source": "hostvars",
                }
            ],
            "count": 1,
            "hosts_searched": 1,
            "query": {"name": "ansible_host"},
        },
    ),
    (api.BaremetalNodesResponse, {"nodes": [{"name": "node-1"}], "count": 1}),
    (
        api.BaremetalPortsResponse,
        {"ports": [{"address": "aa:bb:cc:dd:ee:ff"}], "count": 1},
    ),
    (api.BaremetalNodesNetboxRequest, {"node_names": ["node-1"]}),
    (
        api.BaremetalNodesNetboxResponse,
        {"nodes": {"node-1": {"device_role": "server"}}},
    ),
]

REQUIRED_MODEL_IDS = [model.__name__ for model, _ in REQUIRED_MODEL_CASES]


@pytest.mark.parametrize("model,kwargs", REQUIRED_MODEL_CASES, ids=REQUIRED_MODEL_IDS)
def test_required_models_round_trip_through_model_dump(model, kwargs):
    instance = model(**kwargs)
    assert model(**instance.model_dump()) == instance


@pytest.mark.parametrize("model,kwargs", REQUIRED_MODEL_CASES, ids=REQUIRED_MODEL_IDS)
def test_required_models_reject_missing_required_field(model, kwargs):
    for field in kwargs:
        payload = {k: v for k, v in kwargs.items() if k != field}
        with pytest.raises(ValidationError):
            model(**payload)


@pytest.mark.parametrize("value", ["text", {"nested": 1}, [1, 2, 3], None])
@pytest.mark.parametrize(
    "model",
    [api.HostvarEntry, api.FactEntry, api.SearchResultEntry],
    ids=lambda model: model.__name__,
)
def test_any_value_fields_accept_arbitrary_types(model, value):
    kwargs = {"name": "var", "value": value}
    if model is api.SearchResultEntry:
        kwargs.update(host="node-1", source="facts")
    assert model(**kwargs).value == value


def test_baremetal_nodes_netbox_response_coerces_plain_dicts():
    response = api.BaremetalNodesNetboxResponse(
        nodes={"node-1": {"device_role": "server", "primary_ip4": "10.0.0.1"}}
    )
    info = response.nodes["node-1"]
    assert isinstance(info, api.BaremetalNodeNetboxInfo)
    assert info.device_role == "server"
    assert info.primary_ip4 == "10.0.0.1"
    assert info.primary_ip6 is None
