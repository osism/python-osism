# SPDX-License-Identifier: Apache-2.0

"""Unit tests for :mod:`osism.services.websocket_manager`.

Covers the ``EventMessage`` value object, the per-connection filter logic in
``WebSocketConnection.matches_filters``, and the ``WebSocketManager``
connection registry, event queue and broadcaster loop.

Every test creates a fresh ``WebSocketManager`` instead of using the
module-level ``websocket_manager`` singleton so queues and locks bind to the
event loop of the running test and no state leaks between tests. Fake
websockets are plain ``MagicMock`` objects with ``AsyncMock`` methods; the
``WebSocket`` instance is only used as a dictionary key, so no spec is
required.

The modules under test log via the stdlib ``logging`` module
(``osism.websocket``), so the plain ``caplog`` fixture is used for log
assertions.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from osism.services.websocket_manager import (
    EventMessage,
    WebSocketConnection,
    WebSocketManager,
)


def make_websocket():
    """Return a fake websocket usable as a connection key."""
    websocket = MagicMock()
    websocket.accept = AsyncMock()
    websocket.send_text = AsyncMock()
    return websocket


async def wait_until(predicate, *, timeout=1.0):
    """Drive the event loop until ``predicate()`` is truthy or ``timeout`` elapses.

    Returns as soon as the condition holds, so the broadcaster tests assert on
    real state (a message was sent, a connection was dropped, the queue
    drained) instead of sleeping for a fixed, timing-sensitive duration.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0)


class TestEventMessage:
    def test_constructor_sets_attributes(self):
        event = EventMessage(
            event_type="baremetal.node.power_set",
            source="openstack",
            data={"key": "value"},
            node_name="node1",
        )
        assert event.event_type == "baremetal.node.power_set"
        assert event.source == "openstack"
        assert event.data == {"key": "value"}
        assert event.node_name == "node1"

    def test_node_name_defaults_to_none(self):
        event = EventMessage(event_type="a.b", source="test", data={})
        assert event.node_name is None

    def test_id_is_uuid4_and_unique(self):
        first = EventMessage(event_type="a.b", source="test", data={})
        second = EventMessage(event_type="a.b", source="test", data={})
        assert uuid.UUID(first.id).version == 4
        assert uuid.UUID(second.id).version == 4
        assert first.id != second.id

    def test_timestamp_is_iso8601_with_z_suffix(self):
        event = EventMessage(event_type="a.b", source="test", data={})
        assert event.timestamp.endswith("Z")
        # Must not raise; the exact value depends on datetime.utcnow().
        datetime.fromisoformat(event.timestamp[:-1])

    def test_to_dict_returns_exactly_the_expected_keys(self):
        event = EventMessage(
            event_type="a.b", source="test", data={"x": 1}, node_name="node1"
        )
        result = event.to_dict()
        assert set(result) == {
            "id",
            "timestamp",
            "event_type",
            "source",
            "node_name",
            "data",
        }
        assert result["id"] == event.id
        assert result["timestamp"] == event.timestamp
        assert result["event_type"] == "a.b"
        assert result["source"] == "test"
        assert result["node_name"] == "node1"
        assert result["data"] == {"x": 1}

    def test_to_json_round_trips_to_dict(self):
        event = EventMessage(
            event_type="a.b", source="test", data={"x": 1}, node_name="node1"
        )
        assert json.loads(event.to_json()) == event.to_dict()


class TestMatchesFilters:
    def make_event(self, event_type="a.b", node_name=None):
        return EventMessage(
            event_type=event_type, source="test", data={}, node_name=node_name
        )

    def test_no_filters_pass_all_events(self):
        connection = WebSocketConnection(MagicMock())
        assert connection.matches_filters(self.make_event()) is True

    def test_event_filter_matching_event_type(self):
        connection = WebSocketConnection(MagicMock())
        connection.event_filters = ["baremetal.node.power_set"]
        assert (
            connection.matches_filters(
                self.make_event(event_type="baremetal.node.power_set")
            )
            is True
        )

    def test_event_filter_non_matching_event_type(self):
        connection = WebSocketConnection(MagicMock())
        connection.event_filters = ["baremetal.node.power_set"]
        assert (
            connection.matches_filters(self.make_event(event_type="other.event"))
            is False
        )

    def test_node_filter_matching_node(self):
        connection = WebSocketConnection(MagicMock())
        connection.node_filters = ["node1"]
        assert connection.matches_filters(self.make_event(node_name="node1")) is True

    def test_node_filter_non_matching_node(self):
        connection = WebSocketConnection(MagicMock())
        connection.node_filters = ["node1"]
        assert connection.matches_filters(self.make_event(node_name="other")) is False

    def test_node_filter_rejects_event_without_node_name(self):
        connection = WebSocketConnection(MagicMock())
        connection.node_filters = ["node1"]
        assert connection.matches_filters(self.make_event(node_name=None)) is False

    def test_service_filter_matches_first_dot_segment(self):
        connection = WebSocketConnection(MagicMock())
        connection.service_filters = ["baremetal"]
        assert (
            connection.matches_filters(
                self.make_event(event_type="baremetal.node.power_set")
            )
            is True
        )

    def test_service_filter_non_matching_service(self):
        connection = WebSocketConnection(MagicMock())
        connection.service_filters = ["baremetal"]
        assert (
            connection.matches_filters(
                self.make_event(event_type="compute.instance.update")
            )
            is False
        )

    def test_empty_event_type_maps_to_unknown_service(self):
        connection = WebSocketConnection(MagicMock())
        connection.service_filters = ["unknown"]
        assert connection.matches_filters(self.make_event(event_type="")) is True

    def test_combined_filters_are_anded(self):
        connection = WebSocketConnection(MagicMock())
        connection.event_filters = ["a.b"]
        connection.node_filters = ["node1"]
        event = self.make_event(event_type="a.b", node_name="other")
        assert connection.matches_filters(event) is False


class TestConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_accepts_and_registers_connection(self):
        manager = WebSocketManager()
        manager._broadcast_events = MagicMock(return_value="broadcast-coro")
        websocket = make_websocket()
        with patch(
            "osism.services.websocket_manager.asyncio.create_task"
        ) as create_task:
            create_task.return_value = MagicMock(done=MagicMock(return_value=False))
            await manager.connect(websocket)
        websocket.accept.assert_awaited_once()
        assert isinstance(manager.connections[websocket], WebSocketConnection)

    @pytest.mark.asyncio
    async def test_connect_starts_broadcaster_only_once(self):
        manager = WebSocketManager()
        manager._broadcast_events = MagicMock(return_value="broadcast-coro")
        with patch(
            "osism.services.websocket_manager.asyncio.create_task"
        ) as create_task:
            task = MagicMock()
            task.done.return_value = False
            create_task.return_value = task
            await manager.connect(make_websocket())
            await manager.connect(make_websocket())
        create_task.assert_called_once_with("broadcast-coro")

    @pytest.mark.asyncio
    async def test_connect_restarts_broadcaster_when_task_is_done(self):
        manager = WebSocketManager()
        manager._broadcast_events = MagicMock(return_value="broadcast-coro")
        with patch(
            "osism.services.websocket_manager.asyncio.create_task"
        ) as create_task:
            task = MagicMock()
            task.done.return_value = True
            create_task.return_value = task
            await manager.connect(make_websocket())
            await manager.connect(make_websocket())
        assert create_task.call_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_removes_connection(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        manager.connections[websocket] = WebSocketConnection(websocket)
        await manager.disconnect(websocket)
        assert websocket not in manager.connections

    @pytest.mark.asyncio
    async def test_disconnect_unknown_websocket_is_a_noop(self):
        manager = WebSocketManager()
        await manager.disconnect(make_websocket())
        assert manager.connections == {}


class TestUpdateFilters:
    @pytest.mark.asyncio
    async def test_update_filters_sets_all_filter_lists(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        manager.connections[websocket] = WebSocketConnection(websocket)
        await manager.update_filters(
            websocket,
            event_filters=["a.b"],
            node_filters=["node1"],
            service_filters=["baremetal"],
        )
        connection = manager.connections[websocket]
        assert connection.event_filters == ["a.b"]
        assert connection.node_filters == ["node1"]
        assert connection.service_filters == ["baremetal"]

    @pytest.mark.asyncio
    async def test_update_filters_partial_update_keeps_other_lists(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        connection = WebSocketConnection(websocket)
        connection.event_filters = ["a.b"]
        connection.node_filters = ["node1"]
        connection.service_filters = ["baremetal"]
        manager.connections[websocket] = connection
        await manager.update_filters(websocket, node_filters=["node2"])
        assert connection.event_filters == ["a.b"]
        assert connection.node_filters == ["node2"]
        assert connection.service_filters == ["baremetal"]

    @pytest.mark.asyncio
    async def test_update_filters_empty_list_clears_a_filter(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        connection = WebSocketConnection(websocket)
        connection.event_filters = ["a.b"]
        manager.connections[websocket] = connection
        await manager.update_filters(websocket, event_filters=[])
        assert connection.event_filters == []

    @pytest.mark.asyncio
    async def test_update_filters_unknown_websocket_is_a_noop(self):
        manager = WebSocketManager()
        await manager.update_filters(make_websocket(), event_filters=["a.b"])
        assert manager.connections == {}


class TestAddEventAndHeartbeat:
    @pytest.mark.asyncio
    async def test_add_event_puts_event_on_queue(self):
        manager = WebSocketManager()
        event = EventMessage(event_type="a.b", source="test", data={})
        await manager.add_event(event)
        assert manager.event_queue.qsize() == 1
        assert manager.event_queue.get_nowait() is event

    @pytest.mark.asyncio
    async def test_send_heartbeat_without_connections_queues_nothing(self):
        manager = WebSocketManager()
        await manager.send_heartbeat()
        assert manager.event_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_send_heartbeat_queues_heartbeat_event(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        manager.connections[websocket] = WebSocketConnection(websocket)
        await manager.send_heartbeat()
        event = manager.event_queue.get_nowait()
        assert event.event_type == "heartbeat"
        assert event.source == "osism"
        assert event.data == {"message": "ping"}


class TestBroadcastEventFromNotification:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type,payload,expected_node_name,expected_resource_id",
        [
            pytest.param(
                "baremetal.node.power_set.end",
                {"ironic_object.data": {"name": "node1", "uuid": "abc-123"}},
                "node1",
                "abc-123",
                id="baremetal",
            ),
            pytest.param(
                "compute.instance.update",
                {
                    "nova_object.data": {
                        "host": "compute-1",
                        "name": "instance-a",
                        "uuid": "u-1",
                    }
                },
                "compute-1",
                "u-1",
                id="compute-prefers-host",
            ),
            pytest.param(
                "nova.instance.update",
                {"nova_object.data": {"name": "instance-a", "uuid": "u-1"}},
                "instance-a",
                "u-1",
                id="nova-falls-back-to-name",
            ),
            pytest.param(
                "network.floatingip.update.end",
                {"neutron_object.data": {"id": "net-1", "name": "public"}},
                "public",
                "net-1",
                id="network",
            ),
            pytest.param(
                "neutron.port.create.end",
                {"neutron_object.data": {"uuid": "net-2", "device_id": "dev-1"}},
                "dev-1",
                "net-2",
                id="neutron-fallbacks",
            ),
            pytest.param(
                "volume.volume.create.end",
                {"cinder_object.data": {"id": "vol-1", "name": "volume-a"}},
                "volume-a",
                "vol-1",
                id="volume",
            ),
            pytest.param(
                "volume.volume.update.end",
                {"cinder_object.data": {"uuid": "vol-2", "display_name": "disp-a"}},
                "disp-a",
                "vol-2",
                id="volume-fallbacks",
            ),
            pytest.param(
                "image.image.upload.end",
                {"glance_object.data": {"id": "img-1", "name": "cirros"}},
                "cirros",
                "img-1",
                id="image",
            ),
            pytest.param(
                "image.image.update.end",
                {"glance_object.data": {"uuid": "img-2"}},
                None,
                "img-2",
                id="image-uuid-fallback",
            ),
            pytest.param(
                "identity.project.created",
                {"keystone_object.data": {"id": "proj-1", "name": "admin"}},
                "admin",
                "proj-1",
                id="identity",
            ),
            pytest.param(
                "identity.user.updated",
                {"keystone_object.data": {"uuid": "user-2"}},
                None,
                "user-2",
                id="identity-uuid-fallback",
            ),
        ],
    )
    async def test_extracts_identifiers_per_service_type(
        self, event_type, payload, expected_node_name, expected_resource_id
    ):
        manager = WebSocketManager()
        await manager.broadcast_event_from_notification(event_type, payload)
        event = manager.event_queue.get_nowait()
        assert event.event_type == event_type
        assert event.source == "openstack"
        assert event.node_name == expected_node_name
        assert event.data["resource_id"] == expected_resource_id
        assert event.data["service_type"] == event_type.split(".")[0]

    @pytest.mark.asyncio
    async def test_known_service_without_expected_payload_key(self):
        manager = WebSocketManager()
        await manager.broadcast_event_from_notification(
            "baremetal.node.power_set.end", {"foo": "bar"}
        )
        event = manager.event_queue.get_nowait()
        assert event.node_name is None
        assert event.data["resource_id"] is None
        assert event.data["service_type"] == "baremetal"

    @pytest.mark.asyncio
    async def test_unknown_service_type_queues_event_without_extraction(self):
        manager = WebSocketManager()
        await manager.broadcast_event_from_notification("foo.bar", {"x": 1})
        event = manager.event_queue.get_nowait()
        assert event.node_name is None
        assert event.data["service_type"] == "foo"
        assert event.data["resource_id"] is None
        assert event.data["x"] == 1

    @pytest.mark.asyncio
    async def test_empty_event_type_maps_to_unknown_service(self):
        manager = WebSocketManager()
        await manager.broadcast_event_from_notification("", {})
        event = manager.event_queue.get_nowait()
        assert event.data["service_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_payload_is_copied_and_not_mutated(self):
        manager = WebSocketManager()
        payload = {"ironic_object.data": {"name": "node1", "uuid": "abc-123"}}
        await manager.broadcast_event_from_notification(
            "baremetal.node.power_set.end", payload
        )
        assert payload == {"ironic_object.data": {"name": "node1", "uuid": "abc-123"}}
        event = manager.event_queue.get_nowait()
        assert event.data["ironic_object.data"] == payload["ironic_object.data"]
        assert event.data["service_type"] == "baremetal"
        assert event.data["resource_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_error_is_caught_and_nothing_is_queued(self, caplog):
        caplog.set_level(logging.ERROR, logger="osism.websocket")
        manager = WebSocketManager()
        # A list payload survives the "key in payload" checks and .copy(),
        # but fails on the string-keyed item assignment afterwards.
        await manager.broadcast_event_from_notification("baremetal.node.power_set", [])
        assert manager.event_queue.qsize() == 0
        assert "Error creating event from notification" in caplog.text


class TestBroadcastEvents:
    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_matching_event_is_sent_to_connection(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        manager.connections[websocket] = WebSocketConnection(websocket)
        event = EventMessage(event_type="a.b", source="test", data={"x": 1})
        manager.event_queue.put_nowait(event)

        task = asyncio.create_task(manager._broadcast_events())
        try:
            await wait_until(lambda: websocket.send_text.await_count == 1)
            websocket.send_text.assert_awaited_once_with(event.to_json())
        finally:
            task.cancel()
            await task

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_non_matching_connection_is_skipped(self):
        manager = WebSocketManager()
        filtered_websocket = make_websocket()
        filtered_connection = WebSocketConnection(filtered_websocket)
        filtered_connection.event_filters = ["other.event"]
        manager.connections[filtered_websocket] = filtered_connection
        open_websocket = make_websocket()
        manager.connections[open_websocket] = WebSocketConnection(open_websocket)
        event = EventMessage(event_type="a.b", source="test", data={})
        manager.event_queue.put_nowait(event)

        task = asyncio.create_task(manager._broadcast_events())
        try:
            # The filtered connection is registered first, so it is always
            # evaluated before the open one sends and satisfies this wait.
            await wait_until(lambda: open_websocket.send_text.await_count == 1)
            filtered_websocket.send_text.assert_not_awaited()
            open_websocket.send_text.assert_awaited_once_with(event.to_json())
        finally:
            task.cancel()
            await task

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_websocket_disconnect_removes_connection(self):
        manager = WebSocketManager()
        websocket = make_websocket()
        websocket.send_text.side_effect = WebSocketDisconnect()
        manager.connections[websocket] = WebSocketConnection(websocket)
        manager.event_queue.put_nowait(
            EventMessage(event_type="a.b", source="test", data={})
        )

        task = asyncio.create_task(manager._broadcast_events())
        try:
            await wait_until(lambda: websocket not in manager.connections)
        finally:
            task.cancel()
            await task

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_generic_send_error_logs_and_removes_connection(self, caplog):
        caplog.set_level(logging.ERROR, logger="osism.websocket")
        manager = WebSocketManager()
        websocket = make_websocket()
        websocket.send_text.side_effect = RuntimeError("boom")
        manager.connections[websocket] = WebSocketConnection(websocket)
        manager.event_queue.put_nowait(
            EventMessage(event_type="a.b", source="test", data={})
        )

        task = asyncio.create_task(manager._broadcast_events())
        try:
            await wait_until(lambda: websocket not in manager.connections)
            assert "Error sending message to WebSocket" in caplog.text
        finally:
            task.cancel()
            await task

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_event_without_connections_is_consumed(self):
        manager = WebSocketManager()
        manager.event_queue.put_nowait(
            EventMessage(event_type="a.b", source="test", data={})
        )

        task = asyncio.create_task(manager._broadcast_events())
        try:
            await wait_until(lambda: manager.event_queue.qsize() == 0)
            assert not task.done()
        finally:
            task.cancel()
            await task

    @pytest.mark.asyncio
    @pytest.mark.timeout(10)
    async def test_cancellation_stops_the_loop_cleanly(self, caplog):
        caplog.set_level(logging.INFO, logger="osism.websocket")
        manager = WebSocketManager()

        task = asyncio.create_task(manager._broadcast_events())
        # Let the broadcaster start and park on the queue.get() await before
        # cancelling. Cancelling a task that has not run yet delivers the
        # CancelledError at the coroutine's entry, bypassing the loop's
        # try/except; only once it is suspended inside the loop does the
        # except catch it and exit via break, so awaiting the task must not
        # raise.
        await wait_until(lambda: "Starting WebSocket event broadcaster" in caplog.text)
        task.cancel()
        await task
        assert task.done()
        assert "WebSocket broadcaster task cancelled" in caplog.text
