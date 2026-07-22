# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`osism.services.event_bridge`.

Covers Redis initialization, the publish path with reconnect and local-queue
fallback in ``add_event``, the subscriber and processor loops, single-event
processing and shutdown.

Every test constructs a fresh ``EventBridge`` with
``osism.services.event_bridge.redis.Redis`` patched (the ``bridge`` fixture)
instead of using the module-level ``event_bridge`` singleton, which attempts
a real Redis connection at import time.

The thread targets ``_redis_subscriber_loop`` and ``_process_events`` are
called synchronously; termination is driven through ``_shutdown_event`` from
``get_message`` / ``get`` side effects, so no real threads or sleeps are
involved. Note that a failing ``get_message`` only breaks the inner loop and
triggers a resubscribe; the retry counter and ``_shutdown_event.wait``
back-off only engage when ``subscribe()`` itself raises.

The module logs via the stdlib ``logging`` module (``osism.event_bridge``),
so the plain ``caplog`` fixture is used for log assertions.
"""

import json
import logging
import queue
from unittest.mock import AsyncMock, MagicMock

import pytest

from osism.services.event_bridge import EventBridge


@pytest.fixture
def redis_cls(mocker):
    return mocker.patch("osism.services.event_bridge.redis.Redis")


@pytest.fixture
def bridge(redis_cls):
    return EventBridge()


class TestInitRedis:
    def test_defaults(self, redis_cls, monkeypatch):
        for name in ("REDIS_HOST", "REDIS_PORT", "REDIS_DB"):
            monkeypatch.delenv(name, raising=False)
        EventBridge()
        redis_cls.assert_called_once_with(
            host="redis",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_timeout=None,
            health_check_interval=30,
        )

    def test_environment_variables_override_defaults(self, redis_cls, monkeypatch):
        monkeypatch.setenv("REDIS_HOST", "redis.example.com")
        monkeypatch.setenv("REDIS_PORT", "16379")
        monkeypatch.setenv("REDIS_DB", "2")
        EventBridge()
        assert redis_cls.call_args.kwargs["host"] == "redis.example.com"
        assert redis_cls.call_args.kwargs["port"] == 16379
        assert redis_cls.call_args.kwargs["db"] == 2

    def test_successful_ping_sets_client_and_subscriber(self, redis_cls):
        bridge = EventBridge()
        client = redis_cls.return_value
        client.ping.assert_called_once_with()
        assert bridge._redis_client is client
        client.pubsub.assert_called_once_with()
        assert bridge._redis_subscriber is client.pubsub.return_value

    def test_connection_failure_leaves_client_unset(self, redis_cls, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        redis_cls.return_value.ping.side_effect = ConnectionError("no redis")
        bridge = EventBridge()
        assert bridge._redis_client is None
        assert bridge._redis_subscriber is None
        assert "Failed to connect to Redis" in caplog.text

    def test_redis_not_available_uses_local_queue_only(self, redis_cls, mocker, caplog):
        caplog.set_level(logging.WARNING, logger="osism.event_bridge")
        mocker.patch("osism.services.event_bridge.REDIS_AVAILABLE", False)
        bridge = EventBridge()
        redis_cls.assert_not_called()
        assert bridge._redis_client is None
        assert "event bridge will use local queue only" in caplog.text


class TestSetWebsocketManager:
    def test_stores_manager_and_starts_threads(self, bridge, mocker):
        start_subscriber = mocker.patch.object(bridge, "_start_redis_subscriber")
        start_processor = mocker.patch.object(bridge, "_start_processor_thread")
        manager = MagicMock()
        bridge.set_websocket_manager(manager)
        assert bridge._websocket_manager is manager
        start_subscriber.assert_called_once_with()
        start_processor.assert_called_once_with()

    def test_subscriber_not_started_without_redis_client(self, bridge, mocker):
        bridge._redis_client = None
        start_subscriber = mocker.patch.object(bridge, "_start_redis_subscriber")
        mocker.patch.object(bridge, "_start_processor_thread")
        bridge.set_websocket_manager(MagicMock())
        start_subscriber.assert_not_called()

    def test_subscriber_not_started_twice(self, bridge, mocker):
        bridge._subscriber_thread = MagicMock()
        start_subscriber = mocker.patch.object(bridge, "_start_redis_subscriber")
        mocker.patch.object(bridge, "_start_processor_thread")
        bridge.set_websocket_manager(MagicMock())
        start_subscriber.assert_not_called()

    def test_processor_not_started_when_alive(self, bridge, mocker):
        thread = MagicMock()
        thread.is_alive.return_value = True
        bridge._processor_thread = thread
        mocker.patch.object(bridge, "_start_redis_subscriber")
        start_processor = mocker.patch.object(bridge, "_start_processor_thread")
        bridge.set_websocket_manager(MagicMock())
        start_processor.assert_not_called()

    def test_processor_restarted_when_dead(self, bridge, mocker):
        thread = MagicMock()
        thread.is_alive.return_value = False
        bridge._processor_thread = thread
        mocker.patch.object(bridge, "_start_redis_subscriber")
        start_processor = mocker.patch.object(bridge, "_start_processor_thread")
        bridge.set_websocket_manager(MagicMock())
        start_processor.assert_called_once_with()


class TestAddEvent:
    def test_publishes_event_to_redis(self, bridge, caplog):
        caplog.set_level(logging.INFO, logger="osism.event_bridge")
        client = bridge._redis_client
        client.publish.return_value = 3
        payload = {"a": 1}
        bridge.add_event("baremetal.node.power_set", payload)
        client.publish.assert_called_once_with(
            "osism:events",
            json.dumps({"event_type": "baremetal.node.power_set", "payload": payload}),
        )
        assert bridge._event_queue.qsize() == 0
        assert "Published event to Redis" in caplog.text
        assert "No Redis subscribers" not in caplog.text

    def test_warns_when_no_subscribers(self, bridge, caplog):
        caplog.set_level(logging.WARNING, logger="osism.event_bridge")
        bridge._redis_client.publish.return_value = 0
        bridge.add_event("a.b", {})
        assert "No Redis subscribers for event: a.b" in caplog.text

    def test_publish_retried_after_successful_reconnect(self, bridge, mocker, caplog):
        caplog.set_level(logging.INFO, logger="osism.event_bridge")
        client = bridge._redis_client
        client.publish.side_effect = [ConnectionError("gone"), 2]
        init_redis = mocker.patch.object(bridge, "_init_redis")
        bridge.add_event("a.b", {"x": 1})
        init_redis.assert_called_once_with()
        assert client.publish.call_count == 2
        assert bridge._event_queue.qsize() == 0
        assert "Published event to Redis after reconnect" in caplog.text

    def test_falls_back_to_local_queue_when_reconnect_fails(
        self, bridge, mocker, caplog
    ):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        client = bridge._redis_client
        client.publish.side_effect = ConnectionError("gone")

        def drop_client():
            bridge._redis_client = None

        mocker.patch.object(bridge, "_init_redis", side_effect=drop_client)
        bridge.add_event("a.b", {"x": 1})
        assert client.publish.call_count == 1
        assert bridge._event_queue.get_nowait() == {
            "event_type": "a.b",
            "payload": {"x": 1},
        }
        assert "Redis reconnection failed" in caplog.text

    def test_uses_local_queue_without_redis_client(self, bridge):
        bridge._redis_client = None
        bridge.add_event("a.b", {"x": 1})
        assert bridge._event_queue.get_nowait() == {
            "event_type": "a.b",
            "payload": {"x": 1},
        }

    def test_full_queue_drops_event_with_warning(self, bridge, mocker, caplog):
        """Defensive branch only: ``_event_queue`` is an unbounded
        ``queue.Queue``, so ``put_nowait`` never raises ``queue.Full`` in
        production. The handler is reachable solely by patching
        ``put_nowait``; this does not document real drop behavior.
        """
        caplog.set_level(logging.WARNING, logger="osism.event_bridge")
        bridge._redis_client = None
        mocker.patch.object(bridge._event_queue, "put_nowait", side_effect=queue.Full)
        bridge.add_event("a.b", {})
        assert "Event bridge queue is full, dropping event" in caplog.text

    def test_generic_error_is_swallowed(self, bridge, mocker, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        bridge._redis_client = None
        mocker.patch.object(
            bridge._event_queue, "put_nowait", side_effect=ValueError("boom")
        )
        bridge.add_event("a.b", {})
        assert "Error adding event to bridge: boom" in caplog.text


class TestRedisSubscriberLoop:
    @pytest.mark.timeout(10)
    def test_returns_immediately_without_subscriber(self, bridge, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        bridge._redis_subscriber = None
        bridge._redis_subscriber_loop()
        assert "Redis subscriber not available" in caplog.text

    @pytest.mark.timeout(10)
    def test_subscribes_and_stops_on_shutdown(self, bridge, caplog):
        caplog.set_level(logging.INFO, logger="osism.event_bridge")
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber

        def get_message(timeout=None):
            bridge._shutdown_event.set()
            return None

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        subscriber.subscribe.assert_called_once_with("osism:events")
        subscriber.get_message.assert_called_once_with(timeout=10.0)
        subscriber.close.assert_called_once_with()
        assert "Redis subscriber stopped" in caplog.text

    @pytest.mark.timeout(10)
    def test_valid_message_is_processed_with_manager(self, bridge, mocker):
        bridge._websocket_manager = MagicMock()
        process = mocker.patch.object(bridge, "_process_single_event")
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        event_data = {"event_type": "a.b", "payload": {"x": 1}}

        def get_message(timeout=None):
            bridge._shutdown_event.set()
            return {"type": "message", "data": json.dumps(event_data)}

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        process.assert_called_once_with(event_data)

    @pytest.mark.timeout(10)
    def test_valid_message_is_queued_without_manager(self, bridge):
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        event_data = {"event_type": "a.b", "payload": {"x": 1}}

        def get_message(timeout=None):
            bridge._shutdown_event.set()
            return {"type": "message", "data": json.dumps(event_data)}

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        assert bridge._event_queue.get_nowait() == event_data

    @pytest.mark.timeout(10)
    def test_invalid_json_logs_and_continues(self, bridge, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        calls = {"count": 0}

        def get_message(timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"type": "message", "data": "not-json"}
            bridge._shutdown_event.set()
            return None

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        assert subscriber.get_message.call_count == 2
        assert "Failed to decode Redis event message" in caplog.text

    @pytest.mark.timeout(10)
    def test_processing_error_logs_and_continues(self, bridge, mocker, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        bridge._websocket_manager = MagicMock()
        mocker.patch.object(
            bridge, "_process_single_event", side_effect=ValueError("boom")
        )
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        calls = {"count": 0}

        def get_message(timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return {"type": "message", "data": json.dumps({"event_type": "a.b"})}
            bridge._shutdown_event.set()
            return None

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        assert subscriber.get_message.call_count == 2
        assert "Error processing Redis event: boom" in caplog.text

    @pytest.mark.timeout(10)
    def test_get_message_error_triggers_resubscribe(self, bridge, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        calls = {"count": 0}

        def get_message(timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ConnectionError("lost")
            bridge._shutdown_event.set()
            return None

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        assert subscriber.subscribe.call_count == 2
        # The subscriber stays open across the resubscribe and is only
        # closed once when the loop exits.
        assert subscriber.close.call_count == 1
        assert "Error getting Redis message: lost" in caplog.text

    @pytest.mark.timeout(10)
    def test_subscribe_error_waits_and_reinitializes_redis(
        self, bridge, mocker, caplog
    ):
        """A failed subscriber is closed before ``_init_redis`` replaces it,
        and the retry subscribes on the newly created instance."""
        caplog.set_level(logging.INFO, logger="osism.event_bridge")
        failed = MagicMock()
        failed.subscribe.side_effect = ConnectionError("down")
        bridge._redis_subscriber = failed
        fresh = MagicMock()

        def get_message(timeout=None):
            bridge._shutdown_event.set()
            return None

        fresh.get_message.side_effect = get_message

        def install_fresh_subscriber():
            bridge._redis_subscriber = fresh

        init_redis = mocker.patch.object(
            bridge, "_init_redis", side_effect=install_fresh_subscriber
        )
        wait_mock = mocker.patch.object(
            bridge._shutdown_event, "wait", return_value=False
        )
        bridge._redis_subscriber_loop()
        wait_mock.assert_called_once_with(5)
        init_redis.assert_called_once_with()
        failed.subscribe.assert_called_once_with("osism:events")
        failed.close.assert_called_once_with()
        fresh.subscribe.assert_called_once_with("osism:events")
        fresh.close.assert_called_once_with()
        assert "Redis subscriber error (attempt 1/5)" in caplog.text
        assert "Retrying Redis subscription in 5 seconds" in caplog.text

    @pytest.mark.timeout(10)
    def test_gives_up_after_max_retries(self, bridge, mocker, caplog):
        """Every attempt subscribes on a distinct freshly created subscriber
        and closes it after its failure."""
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        subscribers = [MagicMock() for _ in range(5)]
        for subscriber in subscribers:
            subscriber.subscribe.side_effect = ConnectionError("down")
        replacements = iter(subscribers[1:])

        def install_fresh_subscriber():
            bridge._redis_subscriber = next(replacements)

        bridge._redis_subscriber = subscribers[0]
        init_redis = mocker.patch.object(
            bridge, "_init_redis", side_effect=install_fresh_subscriber
        )
        wait_mock = mocker.patch.object(
            bridge._shutdown_event, "wait", return_value=False
        )
        bridge._redis_subscriber_loop()
        for subscriber in subscribers:
            subscriber.subscribe.assert_called_once_with("osism:events")
            subscriber.close.assert_called_once_with()
        # No back-off after the fifth and final failure.
        assert wait_mock.call_count == 4
        assert init_redis.call_count == 4
        assert "Max Redis reconnection attempts reached, giving up" in caplog.text

    @pytest.mark.timeout(10)
    def test_close_error_in_cleanup_is_ignored(self, bridge):
        subscriber = MagicMock()
        subscriber.close.side_effect = ConnectionError("close boom")
        bridge._redis_subscriber = subscriber

        def get_message(timeout=None):
            bridge._shutdown_event.set()
            return None

        subscriber.get_message.side_effect = get_message
        bridge._redis_subscriber_loop()
        subscriber.close.assert_called_once_with()


class TestProcessSingleEvent:
    def test_without_manager_warns_and_returns(self, bridge, caplog):
        caplog.set_level(logging.WARNING, logger="osism.event_bridge")
        bridge._process_single_event({"event_type": "a.b", "payload": {}})
        assert "No WebSocket manager available, dropping event" in caplog.text

    def test_broadcasts_event_via_manager(self, bridge):
        manager = MagicMock()
        manager.broadcast_event_from_notification = AsyncMock()
        bridge._websocket_manager = manager
        bridge._process_single_event({"event_type": "a.b", "payload": {"x": 1}})
        manager.broadcast_event_from_notification.assert_awaited_once_with(
            "a.b", {"x": 1}
        )

    def test_coroutine_error_is_swallowed(self, bridge, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        manager = MagicMock()
        manager.broadcast_event_from_notification = AsyncMock(
            side_effect=ValueError("boom")
        )
        bridge._websocket_manager = manager
        bridge._process_single_event({"event_type": "a.b", "payload": {}})
        assert "Error processing event via bridge: boom" in caplog.text


class TestProcessEvents:
    @pytest.mark.timeout(10)
    def test_processes_queued_event_and_marks_task_done(self, bridge, mocker):
        event_data = {"event_type": "a.b", "payload": {}}
        bridge._event_queue.put(event_data)

        def process(data):
            bridge._shutdown_event.set()

        process_mock = mocker.patch.object(
            bridge, "_process_single_event", side_effect=process
        )
        bridge._process_events()
        process_mock.assert_called_once_with(event_data)
        assert bridge._event_queue.unfinished_tasks == 0

    @pytest.mark.timeout(10)
    def test_exits_immediately_when_shutdown_is_preset(self, bridge, mocker, caplog):
        caplog.set_level(logging.INFO, logger="osism.event_bridge")
        bridge._shutdown_event.set()
        get_mock = mocker.patch.object(bridge._event_queue, "get")
        bridge._process_events()
        get_mock.assert_not_called()
        assert "Event bridge processor stopped" in caplog.text

    @pytest.mark.timeout(10)
    def test_empty_queue_continues_until_shutdown(self, bridge, mocker):
        def get(timeout=None):
            bridge._shutdown_event.set()
            raise queue.Empty

        get_mock = mocker.patch.object(bridge._event_queue, "get", side_effect=get)
        process_mock = mocker.patch.object(bridge, "_process_single_event")
        bridge._process_events()
        get_mock.assert_called_once_with(timeout=1.0)
        process_mock.assert_not_called()

    @pytest.mark.timeout(10)
    def test_processing_error_logs_and_continues(self, bridge, mocker, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        first = {"event_type": "a.b", "payload": {}}
        second = {"event_type": "c.d", "payload": {}}
        bridge._event_queue.put(first)
        bridge._event_queue.put(second)
        processed = []

        def process(data):
            processed.append(data)
            if len(processed) == 1:
                raise ValueError("boom")
            bridge._shutdown_event.set()

        mocker.patch.object(bridge, "_process_single_event", side_effect=process)
        bridge._process_events()
        assert processed == [first, second]
        assert "Unexpected error in event bridge processor: boom" in caplog.text


class TestShutdown:
    def test_sets_shutdown_event_and_closes_subscriber(self, bridge):
        subscriber = MagicMock()
        bridge._redis_subscriber = subscriber
        bridge.shutdown()
        assert bridge._shutdown_event.is_set()
        subscriber.close.assert_called_once_with()

    def test_close_error_is_logged_and_shutdown_continues(self, bridge, caplog):
        caplog.set_level(logging.ERROR, logger="osism.event_bridge")
        subscriber = MagicMock()
        subscriber.close.side_effect = ConnectionError("boom")
        bridge._redis_subscriber = subscriber
        processor = MagicMock()
        processor.is_alive.return_value = True
        bridge._processor_thread = processor
        bridge.shutdown()
        assert "Error closing Redis subscriber: boom" in caplog.text
        processor.join.assert_called_once_with(timeout=5.0)

    def test_joins_alive_threads(self, bridge):
        processor = MagicMock()
        processor.is_alive.return_value = True
        subscriber_thread = MagicMock()
        subscriber_thread.is_alive.return_value = True
        bridge._processor_thread = processor
        bridge._subscriber_thread = subscriber_thread
        bridge.shutdown()
        processor.join.assert_called_once_with(timeout=5.0)
        subscriber_thread.join.assert_called_once_with(timeout=5.0)

    def test_skips_dead_or_missing_threads(self, bridge):
        processor = MagicMock()
        processor.is_alive.return_value = False
        bridge._processor_thread = processor
        bridge._subscriber_thread = None
        bridge.shutdown()
        processor.join.assert_not_called()
