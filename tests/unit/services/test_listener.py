# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the RabbitMQ notification listener (``osism/services/listener.py``).

Covers the ``EXCHANGES_CONFIG`` module constants, the ``BaremetalEvents``
dispatcher (handler resolution and the NetBox task calls of every handler),
the ``NotificationsDump`` consumer (initialization, passive exchange
discovery, consumer setup and message handling including event-bridge
forwarding and OSISM API delivery retries) and the ``main()`` retry loop.

The NetBox Celery tasks are only ever invoked via ``.delay`` here, so the
three ``osism.services.listener.netbox.*.delay`` attributes are patched and
no broker is needed. Threads and timeouts are never real: the discovery loop
is driven synchronously with a scripted ``_stop_discovery`` mock,
``threading.Thread`` and ``time.sleep`` are patched, and ``main()``'s
``while True`` loop is escaped with a sentinel exception.
"""

import json
import sys
from unittest.mock import MagicMock, call

import pytest
import requests

from osism.services import listener

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SERVICES = ["ironic", "nova", "neutron", "cinder", "keystone", "glance"]

# Full ``BaremetalEvents._handler`` tree: event type -> handler method name.
HANDLER_EVENT_TYPES = [
    ("baremetal.node.power_set.end", "node_power_set_end"),
    (
        "baremetal.node.power_state_corrected.success",
        "node_power_state_corrected_success",
    ),
    ("baremetal.node.maintenance_set.end", "node_maintenance_set_end"),
    ("baremetal.node.provision_set.start", "node_provision_set_start"),
    ("baremetal.node.provision_set.end", "node_provision_set_end"),
    ("baremetal.node.provision_set.success", "node_provision_set_success"),
    ("baremetal.node.delete.end", "node_delete_end"),
    ("baremetal.node.create.end", "node_create_end"),
]

API_URL = "http://api:8000/notifications/baremetal"


class LoopExit(Exception):
    """Sentinel used to escape ``while True`` loops in ``main()`` tests."""


def _has_log(records, level, substring):
    return any(r["level"] == level and substring in r["message"] for r in records)


def _make_data(event_type="baremetal.node.power_set.end", payload=None):
    if payload is None:
        payload = {"ironic_object.data": {"name": "node-1", "power_state": "power on"}}
    return {
        "event_type": event_type,
        "payload": payload,
        "priority": "INFO",
        "timestamp": "2026-01-01 00:00:00.000000",
        "publisher_id": "baremetal.host.example.com",
        "message_id": "00000000-0000-0000-0000-000000000000",
    }


def _make_body(data):
    return {"oslo.message": json.dumps(data)}


@pytest.fixture
def netbox_delays(mocker):
    """Patch the ``.delay`` attribute of the three NetBox tasks used by handlers."""
    from types import SimpleNamespace

    return SimpleNamespace(
        set_power_state=mocker.patch(
            "osism.services.listener.netbox.set_power_state.delay"
        ),
        set_provision_state=mocker.patch(
            "osism.services.listener.netbox.set_provision_state.delay"
        ),
        set_maintenance=mocker.patch(
            "osism.services.listener.netbox.set_maintenance.delay"
        ),
    )


@pytest.fixture
def baremetal_events():
    return listener.BaremetalEvents()


@pytest.fixture
def consumer(mocker):
    """``NotificationsDump`` with the OSISM API disabled and a mock connection."""
    mocker.patch("osism.services.listener.settings.OSISM_API_URL", None)
    return listener.NotificationsDump(MagicMock())


@pytest.fixture
def api_consumer(consumer):
    """Consumer wired for OSISM API delivery with stubbed session and events."""
    consumer.event_bridge = None
    consumer.baremetal_events = MagicMock()
    consumer.osism_api_session = MagicMock()
    consumer.osism_baremetal_api_url = API_URL
    return consumer


@pytest.fixture
def sleep_mock(mocker):
    """Patch ``time.sleep`` with a bounded guard so regressions cannot hang."""
    sleep = mocker.patch("osism.services.listener.time.sleep")
    sleep.side_effect = [None] * 5 + [RuntimeError("time.sleep called too often")]
    return sleep


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


def test_exchanges_config_contains_exactly_the_six_services():
    assert sorted(listener.EXCHANGES_CONFIG) == sorted(SERVICES)


@pytest.mark.parametrize("service", SERVICES)
def test_exchanges_config_entry(service):
    assert listener.EXCHANGES_CONFIG[service] == {
        "exchange": service,
        "routing_key": f"{service}_versioned_notifications.info",
        "queue": f"osism-listener-{service}",
    }


def test_legacy_constants_match_ironic_entry():
    ironic = listener.EXCHANGES_CONFIG["ironic"]
    assert listener.EXCHANGE_NAME == ironic["exchange"]
    assert listener.ROUTING_KEY == ironic["routing_key"]
    assert listener.QUEUE_NAME == ironic["queue"]


# ---------------------------------------------------------------------------
# BaremetalEvents.get_handler() / get_object_data()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_type,method_name", HANDLER_EVENT_TYPES)
def test_get_handler_resolves_registered_event_types(
    baremetal_events, event_type, method_name
):
    handler = baremetal_events.get_handler(event_type)
    assert handler == getattr(baremetal_events, method_name)


@pytest.mark.parametrize(
    "event_type",
    [
        pytest.param("baremetal.node.power_set.start", id="unknown-leaf"),
        pytest.param("baremetal.port.create.end", id="unknown-branch"),
    ],
)
def test_get_handler_unknown_event_returns_default_handler(
    baremetal_events, netbox_delays, loguru_logs, event_type
):
    handler = baremetal_events.get_handler(event_type)
    assert handler.__name__ == "default_handler"

    handler({"ironic_object.data": {"name": "node-1"}})

    assert _has_log(loguru_logs, "INFO", f"{event_type} ## node-1")
    netbox_delays.set_power_state.assert_not_called()
    netbox_delays.set_provision_state.assert_not_called()
    netbox_delays.set_maintenance.assert_not_called()


def test_get_handler_ignores_extra_segments(baremetal_events):
    handler = baremetal_events.get_handler("baremetal.node.provision_set.end.extra")
    assert handler == baremetal_events.node_provision_set_end


def test_get_handler_too_few_segments_raises_index_error(baremetal_events):
    # Only KeyError is caught; short event types leak an IndexError. This
    # path is currently dormant (ironic event types always carry four
    # segments) and the leak is not the intended end-state.
    with pytest.raises(IndexError):
        baremetal_events.get_handler("baremetal.node.power_set")


def test_get_object_data_missing_key_raises_key_error(baremetal_events):
    with pytest.raises(KeyError):
        baremetal_events.get_object_data({"payload": {}})


# ---------------------------------------------------------------------------
# BaremetalEvents handler methods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name,power_state",
    [
        ("node_power_set_end", "power on"),
        ("node_power_state_corrected_success", "power off"),
    ],
)
def test_power_handlers_set_power_state(
    baremetal_events, netbox_delays, method_name, power_state
):
    payload = {"ironic_object.data": {"name": "node-1", "power_state": power_state}}
    getattr(baremetal_events, method_name)(payload)
    netbox_delays.set_power_state.assert_called_once_with("node-1", power_state)
    netbox_delays.set_provision_state.assert_not_called()
    netbox_delays.set_maintenance.assert_not_called()


def test_node_maintenance_set_end_sets_maintenance_keyword(
    baremetal_events, netbox_delays
):
    payload = {"ironic_object.data": {"name": "node-1", "maintenance": True}}
    baremetal_events.node_maintenance_set_end(payload)
    netbox_delays.set_maintenance.assert_called_once_with("node-1", state=True)


@pytest.mark.parametrize(
    "method_name,provision_state",
    [
        ("node_provision_set_start", "deploying"),
        ("node_provision_set_end", "active"),
        ("node_provision_set_success", "available"),
    ],
)
def test_provision_handlers_set_provision_state(
    baremetal_events, netbox_delays, method_name, provision_state
):
    payload = {
        "ironic_object.data": {"name": "node-1", "provision_state": provision_state}
    }
    getattr(baremetal_events, method_name)(payload)
    netbox_delays.set_provision_state.assert_called_once_with("node-1", provision_state)
    netbox_delays.set_power_state.assert_not_called()


def test_node_delete_end_resets_provision_and_power_state(
    baremetal_events, netbox_delays
):
    payload = {"ironic_object.data": {"name": "node-1"}}
    baremetal_events.node_delete_end(payload)
    netbox_delays.set_provision_state.assert_called_once_with("node-1", None)
    netbox_delays.set_power_state.assert_called_once_with("node-1", None)


def test_node_create_end_sets_provision_and_power_state(
    baremetal_events, netbox_delays
):
    payload = {
        "ironic_object.data": {
            "name": "node-1",
            "provision_state": "enroll",
            "power_state": "power off",
        }
    }
    baremetal_events.node_create_end(payload)
    netbox_delays.set_provision_state.assert_called_once_with("node-1", "enroll")
    netbox_delays.set_power_state.assert_called_once_with("node-1", "power off")


# ---------------------------------------------------------------------------
# NotificationsDump.__init__()
# ---------------------------------------------------------------------------


def test_init_without_api_url(mocker):
    mocker.patch("osism.services.listener.settings.OSISM_API_URL", None)
    session_cls = mocker.patch("osism.services.listener.requests.Session")

    dump = listener.NotificationsDump(MagicMock())

    assert dump.osism_api_session is None
    assert dump.osism_baremetal_api_url is None
    session_cls.assert_not_called()


def test_init_with_api_url_strips_trailing_slash(mocker):
    mocker.patch("osism.services.listener.settings.OSISM_API_URL", "http://api:8000/")
    session_cls = mocker.patch("osism.services.listener.requests.Session")

    dump = listener.NotificationsDump(MagicMock())

    assert dump.osism_api_session is session_cls.return_value
    assert dump.osism_baremetal_api_url == "http://api:8000/notifications/baremetal"


def test_init_connects_event_bridge_singleton(consumer):
    from osism.services.event_bridge import event_bridge

    assert consumer.event_bridge is event_bridge


def test_init_event_bridge_import_error(mocker, loguru_logs):
    mocker.patch("osism.services.listener.settings.OSISM_API_URL", None)
    # Mapping the module to None makes ``from ... import`` raise ImportError.
    mocker.patch.dict(sys.modules, {"osism.services.event_bridge": None})

    dump = listener.NotificationsDump(MagicMock())

    assert dump.event_bridge is None
    assert _has_log(loguru_logs, "WARNING", "Event bridge not available")


def test_init_initial_discovery_state(consumer):
    assert consumer._available_exchanges == {}
    assert consumer._discovery_thread is None
    assert not consumer._stop_discovery.is_set()
    assert not consumer._new_exchanges_found.is_set()


# ---------------------------------------------------------------------------
# _get_exchange_properties()
# ---------------------------------------------------------------------------


def test_get_exchange_properties_existing_exchange(consumer):
    channel = MagicMock()

    props = consumer._get_exchange_properties(channel, "ironic")

    assert props == {"type": "topic", "durable": True}
    channel.exchange_declare.assert_called_once_with(
        exchange="ironic", type="topic", passive=True
    )


def test_get_exchange_properties_missing_exchange(consumer, loguru_logs):
    channel = MagicMock()
    channel.exchange_declare.side_effect = Exception("NOT_FOUND")

    props = consumer._get_exchange_properties(channel, "ironic")

    assert props is None
    assert _has_log(loguru_logs, "DEBUG", "Exchange 'ironic' does not exist")


# ---------------------------------------------------------------------------
# _check_for_new_exchanges()
# ---------------------------------------------------------------------------


def test_check_for_new_exchanges_none_available(consumer, mocker):
    mocker.patch.object(consumer, "_get_exchange_properties", return_value=None)

    assert consumer._check_for_new_exchanges() is False
    assert consumer._available_exchanges == {}


def test_check_for_new_exchanges_adds_available_exchange(consumer, mocker):
    props = {"type": "topic", "durable": True}
    mocker.patch.object(
        consumer,
        "_get_exchange_properties",
        side_effect=lambda channel, name: props if name == "ironic" else None,
    )

    assert consumer._check_for_new_exchanges() is True
    assert consumer._available_exchanges == {
        "ironic": {**listener.EXCHANGES_CONFIG["ironic"], "exchange_props": props}
    }


def test_check_for_new_exchanges_skips_known_services(consumer, mocker):
    known = {"exchange": "ironic", "exchange_props": {"type": "topic"}}
    consumer._available_exchanges["ironic"] = known
    check = mocker.patch.object(consumer, "_get_exchange_properties", return_value=None)

    assert consumer._check_for_new_exchanges() is False

    checked = [c.args[1] for c in check.call_args_list]
    assert "ironic" not in checked
    assert sorted(checked) == sorted(s for s in SERVICES if s != "ironic")
    assert consumer._available_exchanges["ironic"] is known


def test_check_for_new_exchanges_channel_error(consumer, loguru_logs):
    consumer.connection.channel.side_effect = Exception("channel gone")

    assert consumer._check_for_new_exchanges() is False
    assert _has_log(loguru_logs, "WARNING", "Error checking for new exchanges")


# ---------------------------------------------------------------------------
# _exchange_discovery_loop()
# ---------------------------------------------------------------------------


def test_discovery_loop_stops_when_stop_requested(consumer, mocker):
    stop = MagicMock()
    stop.is_set.return_value = False
    stop.wait.return_value = True
    consumer._stop_discovery = stop
    check = mocker.patch.object(consumer, "_check_for_new_exchanges")

    consumer._exchange_discovery_loop()

    check.assert_not_called()


def test_discovery_loop_stops_when_all_exchanges_available(
    consumer, mocker, loguru_logs
):
    stop = MagicMock()
    stop.is_set.return_value = False
    stop.wait.return_value = False
    consumer._stop_discovery = stop
    consumer._available_exchanges = {
        service: dict(config) for service, config in listener.EXCHANGES_CONFIG.items()
    }
    check = mocker.patch.object(consumer, "_check_for_new_exchanges")

    consumer._exchange_discovery_loop()

    check.assert_not_called()
    assert _has_log(loguru_logs, "INFO", "Stopping exchange discovery")


def test_discovery_loop_signals_restart_on_new_exchanges(consumer, mocker):
    stop = MagicMock()
    stop.is_set.side_effect = [False, True]
    stop.wait.return_value = False
    consumer._stop_discovery = stop
    mocker.patch.object(consumer, "_check_for_new_exchanges", return_value=True)

    consumer._exchange_discovery_loop()

    assert consumer._new_exchanges_found.is_set()
    assert consumer.should_stop is True


def test_discovery_loop_continues_without_new_exchanges(consumer, mocker):
    stop = MagicMock()
    stop.is_set.return_value = False
    stop.wait.side_effect = [False, True]
    consumer._stop_discovery = stop
    check = mocker.patch.object(
        consumer, "_check_for_new_exchanges", return_value=False
    )

    consumer._exchange_discovery_loop()

    check.assert_called_once_with()
    assert not consumer._new_exchanges_found.is_set()
    assert consumer.should_stop is False


# ---------------------------------------------------------------------------
# _start_exchange_discovery() / _stop_exchange_discovery()
# ---------------------------------------------------------------------------


def test_start_exchange_discovery_skipped_when_all_available(consumer, mocker):
    thread_cls = mocker.patch("osism.services.listener.threading.Thread")
    consumer._available_exchanges = {
        service: dict(config) for service, config in listener.EXCHANGES_CONFIG.items()
    }

    consumer._start_exchange_discovery()

    thread_cls.assert_not_called()


def test_start_exchange_discovery_starts_daemon_thread(consumer, mocker):
    thread_cls = mocker.patch("osism.services.listener.threading.Thread")
    stop = MagicMock()
    consumer._stop_discovery = stop

    consumer._start_exchange_discovery()

    stop.clear.assert_called_once_with()
    thread_cls.assert_called_once_with(
        target=consumer._exchange_discovery_loop,
        name="exchange-discovery",
        daemon=True,
    )
    thread_cls.return_value.start.assert_called_once_with()
    assert consumer._discovery_thread is thread_cls.return_value


def test_stop_exchange_discovery_joins_alive_thread(consumer):
    stop = MagicMock()
    consumer._stop_discovery = stop
    thread = MagicMock()
    thread.is_alive.return_value = True
    consumer._discovery_thread = thread

    consumer._stop_exchange_discovery()

    stop.set.assert_called_once_with()
    thread.join.assert_called_once_with(timeout=5)


def test_stop_exchange_discovery_without_thread(consumer):
    consumer._discovery_thread = None

    consumer._stop_exchange_discovery()

    assert consumer._stop_discovery.is_set()


def test_stop_exchange_discovery_dead_thread_not_joined(consumer):
    thread = MagicMock()
    thread.is_alive.return_value = False
    consumer._discovery_thread = thread

    consumer._stop_exchange_discovery()

    thread.join.assert_not_called()


# ---------------------------------------------------------------------------
# _wait_for_exchanges()
# ---------------------------------------------------------------------------


def test_wait_for_exchanges_returns_immediately_when_available(
    consumer, mocker, sleep_mock
):
    consumer._available_exchanges["ironic"] = {"exchange": "ironic"}
    check = mocker.patch.object(consumer, "_check_for_new_exchanges")

    consumer._wait_for_exchanges()

    check.assert_not_called()
    sleep_mock.assert_not_called()


def test_wait_for_exchanges_retries_until_exchange_appears(
    consumer, mocker, sleep_mock
):
    calls = {"count": 0}

    def fake_check():
        calls["count"] += 1
        if calls["count"] == 2:
            consumer._available_exchanges["ironic"] = {"exchange": "ironic"}

    mocker.patch.object(consumer, "_check_for_new_exchanges", side_effect=fake_check)

    consumer._wait_for_exchanges()

    assert calls["count"] == 2
    sleep_mock.assert_called_once_with(listener.EXCHANGE_RETRY_INTERVAL)


# ---------------------------------------------------------------------------
# get_consumers()
# ---------------------------------------------------------------------------


def _prepare_get_consumers(consumer, mocker, available):
    mocker.patch.object(consumer, "_wait_for_exchanges")
    mocker.patch.object(consumer, "_start_exchange_discovery")
    consumer._available_exchanges = available
    exchange_cls = mocker.patch("osism.services.listener.Exchange")
    queue_cls = mocker.patch("osism.services.listener.Queue")
    return exchange_cls, queue_cls, MagicMock()


def test_get_consumers_creates_consumer_per_available_exchange(consumer, mocker):
    available = {
        "ironic": {
            **listener.EXCHANGES_CONFIG["ironic"],
            "exchange_props": {"type": "topic", "durable": True},
        },
        "nova": {
            **listener.EXCHANGES_CONFIG["nova"],
            "exchange_props": {"type": "fanout", "durable": False},
        },
    }
    exchange_cls, queue_cls, factory = _prepare_get_consumers(
        consumer, mocker, available
    )

    consumers = consumer.get_consumers(factory, None)

    assert consumers == [factory.return_value, factory.return_value]
    assert exchange_cls.call_args_list == [
        call("ironic", type="topic", durable=True, passive=True),
        call("nova", type="fanout", durable=False, passive=True),
    ]
    assert queue_cls.call_args_list == [
        call(
            "osism-listener-ironic",
            exchange_cls.return_value,
            routing_key="ironic_versioned_notifications.info",
            auto_delete=False,
            no_ack=True,
        ),
        call(
            "osism-listener-nova",
            exchange_cls.return_value,
            routing_key="nova_versioned_notifications.info",
            auto_delete=False,
            no_ack=True,
        ),
    ]
    assert factory.call_args_list == [
        call(queue_cls.return_value, callbacks=[consumer.on_message]),
        call(queue_cls.return_value, callbacks=[consumer.on_message]),
    ]


def test_get_consumers_defaults_for_missing_exchange_props(consumer, mocker):
    available = {
        "ironic": {**listener.EXCHANGES_CONFIG["ironic"], "exchange_props": {}}
    }
    exchange_cls, _, factory = _prepare_get_consumers(consumer, mocker, available)

    consumers = consumer.get_consumers(factory, None)

    assert len(consumers) == 1
    exchange_cls.assert_called_once_with(
        "ironic", type="topic", durable=True, passive=True
    )


def test_get_consumers_continues_after_exchange_error(consumer, mocker, loguru_logs):
    available = {
        "ironic": {
            **listener.EXCHANGES_CONFIG["ironic"],
            "exchange_props": {"type": "topic", "durable": True},
        },
        "nova": {
            **listener.EXCHANGES_CONFIG["nova"],
            "exchange_props": {"type": "topic", "durable": True},
        },
    }
    exchange_cls, _, factory = _prepare_get_consumers(consumer, mocker, available)
    exchange_cls.side_effect = [Exception("boom"), MagicMock()]

    consumers = consumer.get_consumers(factory, None)

    assert consumers == [factory.return_value]
    assert _has_log(loguru_logs, "ERROR", "Failed to configure consumer for ironic")


def test_get_consumers_no_exchanges_returns_empty_list(consumer, mocker, loguru_logs):
    _, _, factory = _prepare_get_consumers(consumer, mocker, {})

    consumers = consumer.get_consumers(factory, None)

    assert consumers == []
    factory.assert_not_called()
    assert _has_log(loguru_logs, "ERROR", "No consumers could be configured")


# ---------------------------------------------------------------------------
# on_message() - payload info extraction / logging
# ---------------------------------------------------------------------------


def test_on_message_baremetal_payload_info(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    payload = {
        "ironic_object.data": {
            "name": "node-1",
            "provision_state": "active",
            "power_state": "power on",
            "uuid": "should-not-be-logged",
        }
    }
    data = _make_data("baremetal.node.provision_set.end", payload)

    consumer.on_message(_make_body(data), MagicMock())

    debug = next(
        r
        for r in loguru_logs
        if r["level"] == "DEBUG"
        and r["message"].startswith("baremetal.node.provision_set.end:")
    )
    assert "'name': 'node-1'" in debug["message"]
    assert "'provision_state': 'active'" in debug["message"]
    assert "'power_state': 'power on'" in debug["message"]
    assert "uuid" not in debug["message"]
    assert _has_log(
        loguru_logs,
        "INFO",
        "Received baremetal event: baremetal.node.provision_set.end",
    )


def test_on_message_nova_payload_info(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    payload = {
        "nova_object.data": {
            "uuid": "instance-1",
            "host": "compute-1",
            "state": "active",
            "task_state": None,
            "flavor": "should-not-be-logged",
        }
    }
    data = _make_data("compute.instance.update", payload)

    consumer.on_message(_make_body(data), MagicMock())

    debug = next(
        r
        for r in loguru_logs
        if r["level"] == "DEBUG" and r["message"].startswith("compute.instance.update:")
    )
    assert "'uuid': 'instance-1'" in debug["message"]
    assert "'host': 'compute-1'" in debug["message"]
    assert "'state': 'active'" in debug["message"]
    assert "'task_state': None" in debug["message"]
    assert "flavor" not in debug["message"]


def test_on_message_neutron_payload_info(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data("network.port.create.end", {"port": {"id": "port-1"}})

    consumer.on_message(_make_body(data), MagicMock())

    assert _has_log(
        loguru_logs, "DEBUG", "network.port.create.end: {'service': 'neutron'}"
    )


def test_on_message_other_service_payload_info(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data("identity.user.created", {"user": {"id": "user-1"}})

    consumer.on_message(_make_body(data), MagicMock())

    assert _has_log(
        loguru_logs, "DEBUG", "identity.user.created: {'service': 'identity'}"
    )
    assert _has_log(loguru_logs, "INFO", "Received identity event")


def test_on_message_missing_event_type(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    data = _make_data()
    del data["event_type"]

    # The service type falls back to "unknown", but the handler dispatch then
    # accesses data["event_type"] directly. This path is currently dormant
    # (oslo.messaging notifications always carry an event_type) and the
    # KeyError is not the intended end-state.
    with pytest.raises(KeyError):
        consumer.on_message(_make_body(data), MagicMock())

    assert _has_log(loguru_logs, "INFO", "Received unknown event")


# ---------------------------------------------------------------------------
# on_message() - event bridge forwarding
# ---------------------------------------------------------------------------


def test_on_message_forwards_to_event_bridge(consumer):
    bridge = MagicMock()
    consumer.event_bridge = bridge
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data()

    consumer.on_message(_make_body(data), MagicMock())

    bridge.add_event.assert_called_once_with(data["event_type"], data["payload"])


def test_on_message_event_bridge_error_is_logged_and_processing_continues(
    consumer, loguru_logs
):
    bridge = MagicMock()
    bridge.add_event.side_effect = RuntimeError("bridge down")
    consumer.event_bridge = bridge
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data("baremetal.node.power_set.end")

    consumer.on_message(_make_body(data), MagicMock())

    assert _has_log(
        loguru_logs, "ERROR", "Error forwarding event to bridge: bridge down"
    )
    assert _has_log(
        loguru_logs, "ERROR", "Event data was: baremetal.node.power_set.end - node-1"
    )
    consumer.baremetal_events.get_handler.assert_called_once_with(data["event_type"])


def test_on_message_event_bridge_error_non_ironic_payload(consumer, loguru_logs):
    bridge = MagicMock()
    bridge.add_event.side_effect = RuntimeError("bridge down")
    consumer.event_bridge = bridge
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data("compute.instance.update", {"nova_object.data": {"uuid": "u1"}})

    consumer.on_message(_make_body(data), MagicMock())

    assert _has_log(
        loguru_logs, "ERROR", "Event data was: compute.instance.update - unknown"
    )


def test_on_message_without_event_bridge(consumer, loguru_logs):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data()

    consumer.on_message(_make_body(data), MagicMock())

    assert not any("Forwarding event to WebSocket" in r["message"] for r in loguru_logs)


# ---------------------------------------------------------------------------
# on_message() - OSISM API delivery
# ---------------------------------------------------------------------------


def test_on_message_api_delivery_success(api_consumer, loguru_logs):
    api_consumer.osism_api_session.post.return_value = MagicMock(status_code=204)
    data = _make_data()

    api_consumer.on_message(_make_body(data), MagicMock())

    api_consumer.osism_api_session.post.assert_called_once_with(
        API_URL,
        timeout=5,
        json={
            "priority": data["priority"],
            "event_type": data["event_type"],
            "timestamp": data["timestamp"],
            "publisher_id": data["publisher_id"],
            "message_id": data["message_id"],
            "payload": data["payload"],
        },
    )
    assert _has_log(loguru_logs, "INFO", "Successfully delivered notification")
    api_consumer.baremetal_events.get_handler.assert_not_called()


def test_on_message_api_delivery_non_baremetal_event(api_consumer):
    # API delivery does not filter by event type: with a session configured,
    # any event is posted to the baremetal endpoint and the handler dispatch
    # in the else branch is skipped. This path is currently dormant (only
    # ironic emits versioned notifications by default, and OSISM_API_URL is
    # unset in a default deployment) and not the intended end-state.
    api_consumer.osism_api_session.post.return_value = MagicMock(status_code=204)
    data = _make_data("compute.instance.update", {"nova_object.data": {"uuid": "u1"}})

    api_consumer.on_message(_make_body(data), MagicMock())

    api_consumer.osism_api_session.post.assert_called_once()
    posted = api_consumer.osism_api_session.post.call_args.kwargs["json"]
    assert posted["event_type"] == "compute.instance.update"
    api_consumer.baremetal_events.get_handler.assert_not_called()


def test_on_message_api_delivery_succeeds_after_transient_error(
    api_consumer, sleep_mock, loguru_logs
):
    api_consumer.osism_api_session.post.side_effect = [
        requests.ConnectionError,
        MagicMock(status_code=204),
    ]

    api_consumer.on_message(_make_body(_make_data()), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 2
    sleep_mock.assert_called_once_with(3)
    assert _has_log(loguru_logs, "INFO", "Successfully delivered notification")


@pytest.mark.parametrize(
    "exception",
    [requests.ConnectionError, requests.Timeout],
    ids=["connection", "timeout"],
)
def test_on_message_api_delivery_retries_and_gives_up(
    api_consumer, sleep_mock, loguru_logs, exception
):
    api_consumer.osism_api_session.post.side_effect = exception
    data = _make_data()

    api_consumer.on_message(_make_body(data), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 3
    assert sleep_mock.call_args_list == [call(3), call(9)]
    give_up = next(
        r
        for r in loguru_logs
        if r["level"] == "ERROR" and "Giving up delivering notification" in r["message"]
    )
    assert json.dumps(data) in give_up["message"]


def test_on_message_api_delivery_gives_up_early_on_http_error(
    api_consumer, sleep_mock, loguru_logs
):
    # A 4xx client error is not retried.
    response = MagicMock(status_code=404)
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    api_consumer.osism_api_session.post.return_value = response

    api_consumer.on_message(_make_body(_make_data()), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 1
    sleep_mock.assert_not_called()
    assert _has_log(loguru_logs, "ERROR", "client side error, giving up early")


@pytest.mark.xfail(
    strict=True,
    reason="listener guards with status_code <= 500; a server 500 is retryable "
    "and the boundary should be < 500",
)
def test_on_message_api_delivery_retries_on_500(api_consumer, sleep_mock):
    # A 500 is a server error and should be retried like the 503 case.
    response = MagicMock(status_code=500)
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    api_consumer.osism_api_session.post.return_value = response

    api_consumer.on_message(_make_body(_make_data()), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 3


def test_on_message_api_delivery_retries_on_server_error(api_consumer, sleep_mock):
    response = MagicMock(status_code=503)
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    api_consumer.osism_api_session.post.return_value = response

    api_consumer.on_message(_make_body(_make_data()), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 3
    assert sleep_mock.call_args_list == [call(3), call(9)]


def test_on_message_api_delivery_status_200_retries(
    api_consumer, sleep_mock, loguru_logs
):
    # Only 204 counts as success; a 200 passes raise_for_status() and falls
    # through to the retry branch. This path is currently dormant (API
    # delivery only runs when OSISM_API_URL is set) and not the intended
    # end-state.
    response = MagicMock(status_code=200)
    response.raise_for_status.return_value = None
    api_consumer.osism_api_session.post.return_value = response

    api_consumer.on_message(_make_body(_make_data()), MagicMock())

    assert api_consumer.osism_api_session.post.call_count == 3
    assert _has_log(loguru_logs, "ERROR", "Giving up delivering notification")


# ---------------------------------------------------------------------------
# on_message() - handler dispatch without API session
# ---------------------------------------------------------------------------


def test_on_message_dispatches_to_handler(consumer):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    consumer.baremetal_events = MagicMock()
    data = _make_data()

    consumer.on_message(_make_body(data), MagicMock())

    consumer.baremetal_events.get_handler.assert_called_once_with(data["event_type"])
    consumer.baremetal_events.get_handler.return_value.assert_called_once_with(
        data["payload"]
    )


def test_on_message_dispatch_triggers_netbox_task(consumer, netbox_delays):
    consumer.event_bridge = None
    consumer.osism_api_session = None
    data = _make_data(
        "baremetal.node.power_set.end",
        {"ironic_object.data": {"name": "node-1", "power_state": "power on"}},
    )

    consumer.on_message(_make_body(data), MagicMock())

    netbox_delays.set_power_state.assert_called_once_with("node-1", "power on")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_retries_on_connection_refused(mocker, loguru_logs):
    mocker.patch("osism.services.listener.BROKER_URI", "amqp://broker")
    sleep = mocker.patch("osism.services.listener.time.sleep")
    connection_cls = mocker.patch(
        "osism.services.listener.Connection",
        side_effect=[ConnectionRefusedError, LoopExit],
    )
    mocker.patch("osism.services.listener.NotificationsDump")

    with pytest.raises(LoopExit):
        listener.main()

    assert connection_cls.call_args_list == (
        [call("amqp://broker", connect_timeout=30.0)] * 2
    )
    sleep.assert_called_once_with(60)
    assert _has_log(loguru_logs, "ERROR", "Connection with broker refused")


def test_main_restarts_consumer_when_new_exchanges_found(mocker, loguru_logs):
    mocker.patch("osism.services.listener.BROKER_URI", "amqp://broker")
    mocker.patch("osism.services.listener.time.sleep")
    connection_cls = mocker.patch("osism.services.listener.Connection")
    dump_cls = mocker.patch("osism.services.listener.NotificationsDump")

    discovered = {"ironic": {"exchange": "ironic", "exchange_props": {}}}
    first = MagicMock()
    first.run.side_effect = lambda: first._available_exchanges.update(discovered)
    first._new_exchanges_found.is_set.return_value = True
    second = MagicMock()
    second.run.side_effect = LoopExit
    dump_cls.side_effect = [first, second]

    with pytest.raises(LoopExit):
        listener.main()

    connection = connection_cls.return_value.__enter__.return_value
    assert dump_cls.call_args_list == [call(connection)] * 2
    first._stop_exchange_discovery.assert_called_once_with()
    first._new_exchanges_found.clear.assert_called_once_with()
    # The exchanges discovered in the first iteration are carried over into
    # the restarted consumer.
    assert second._available_exchanges == discovered
    assert _has_log(loguru_logs, "INFO", "Restarting consumer to add new exchange")
