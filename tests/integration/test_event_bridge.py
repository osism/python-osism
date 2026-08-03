# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the cross-container event path of ``EventBridge``.

``EventBridge.add_event`` publishes an event as JSON to a Redis pub/sub
channel; a second ``EventBridge`` subscribes in a background thread and hands
every decoded event to its websocket manager. Both sides run here against the
live Redis, so an actual ``PUBLISH`` has to reach an actual subscriber
connection -- the wire the unit suite
(``tests/unit/services/test_event_bridge.py``) can only simulate with mocks.

Each test builds its bridges on its own ``itest-events-<uuid4>`` channel,
passed to the ``EventBridge`` constructor. That isolation is needed because
importing ``osism.api`` subscribes the module-level ``event_bridge`` singleton
to the default channel for the rest of the session, which the sibling API test
modules do; on a shared channel the singleton would consume test events and no
channel would ever have zero subscribers.

The module logs through the stdlib ``logging`` module (``osism.event_bridge``),
so log assertions use the plain ``caplog`` fixture.
"""

import json
import logging
import threading
import time
import uuid

import pytest
import redis

from osism import settings
from osism.services.event_bridge import EventBridge

# Background threads carry the receiving half of every round trip, so a
# regression must fail at the wait that never finished instead of hanging until
# the CI wall clock kills the job. The shutdown test needs ~12 s even when it
# passes: closing the pubsub does not interrupt the subscriber's in-flight 10 s
# ``get_message``, so its threads outlive ``shutdown`` by that much. The bound
# covers that plus the two startup waits.
pytestmark = [pytest.mark.integration, pytest.mark.timeout(60)]

POLL_INTERVAL = 0.05

# Names ``EventBridge`` gives its two background threads. Watching the running
# threads by name keeps the shutdown test off the bridge's private attributes
# and turns it into the check that matters: no thread outlives its bridge.
BRIDGE_THREAD_NAMES = {"RedisEventSubscriber", "EventBridgeProcessor"}


class RecordingManager:
    """Minimal stand-in for the websocket manager, recording what it receives.

    ``_process_single_event`` reads ``loop`` to decide how to drive the
    coroutine. ``None`` selects its private-loop path, which needs no running
    event loop and keeps FastAPI out of this module.
    """

    loop = None

    def __init__(self):
        self.events = []

    async def broadcast_event_from_notification(self, event_type, payload):
        self.events.append((event_type, payload))


def _wait_until(condition, message, timeout=10.0):
    """Poll ``condition`` until it holds, or fail the test at ``timeout``."""
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"{message} (waited {timeout}s)")
        time.sleep(POLL_INTERVAL)


def _subscriber_count(client, channel):
    """Return the number of subscribers Redis reports for ``channel``."""
    return client.pubsub_numsub(channel)[0][1]


def _bridge_threads():
    """Return the live background threads any bridge is currently running."""
    return {
        thread for thread in threading.enumerate() if thread.name in BRIDGE_THREAD_NAMES
    }


def _next_message(subscriber, timeout=10.0):
    """Return the next published frame, skipping subscribe confirmations."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        frame = subscriber.get_message(timeout=1.0)
        if frame is not None and frame["type"] == "message":
            return frame
    pytest.fail(f"no message arrived within {timeout}s")


def _subscribed_bridge(bridge_factory, redis_client, channel):
    """Return a bridge whose subscriber thread is live, plus its manager.

    ``set_websocket_manager`` starts the subscriber thread, but the
    subscription itself happens inside that thread. Waiting for Redis to report
    it is what keeps a publish from racing ahead of the subscriber.
    """
    bridge = bridge_factory()
    manager = RecordingManager()
    bridge.set_websocket_manager(manager)
    _wait_until(
        lambda: _subscriber_count(redis_client, channel) >= 1,
        f"the bridge never subscribed to {channel}",
    )
    return bridge, manager


@pytest.fixture(scope="module")
def redis_client():
    """A raw Redis client for publishing and inspecting subscriptions."""
    client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def events_channel():
    """A pub/sub channel only this test uses."""
    return f"itest-events-{uuid.uuid4()}"


@pytest.fixture
def bridge_factory(events_channel):
    """Build bridges on this test's channel and shut every one of them down."""
    bridges = []

    def _build():
        bridge = EventBridge(channel=events_channel)
        bridges.append(bridge)
        return bridge

    yield _build

    for bridge in bridges:
        bridge.shutdown()


def test_add_event_publishes_wire_format(bridge_factory, redis_client, events_channel):
    """A published event carries exactly ``event_type`` and ``payload``."""
    payload = {
        "node": "node-01",
        "power_state": "power on",
        "marker": str(uuid.uuid4()),
        "nested": {"instance_uuid": None, "ports": [1, 2]},
    }

    subscriber = redis_client.pubsub()
    try:
        subscriber.subscribe(events_channel)
        _wait_until(
            lambda: _subscriber_count(redis_client, events_channel) >= 1,
            f"the raw subscriber never appeared on {events_channel}",
        )

        bridge_factory().add_event("baremetal.node.power_set", payload)

        message = _next_message(subscriber)
    finally:
        subscriber.close()

    assert json.loads(message["data"]) == {
        "event_type": "baremetal.node.power_set",
        "payload": payload,
    }


def test_bridge_to_bridge_round_trip(bridge_factory, redis_client, events_channel):
    """An event published by one bridge reaches a second bridge unchanged."""
    _, manager = _subscribed_bridge(bridge_factory, redis_client, events_channel)
    event_type = "baremetal.node.provision_set"
    payload = {
        "marker": str(uuid.uuid4()),
        "node": "node-02",
        "retries": 3,
        "targets": ["compute", "storage"],
        "meta": {"reason": None, "maintenance": True},
    }

    bridge_factory().add_event(event_type, payload)

    _wait_until(
        lambda: manager.events, "the published event never reached the second bridge"
    )
    assert manager.events == [(event_type, payload)]


def test_round_trip_empty_payload(bridge_factory, redis_client, events_channel):
    """An empty payload round-trips as an empty dict, not as an error."""
    _, manager = _subscribed_bridge(bridge_factory, redis_client, events_channel)

    bridge_factory().add_event("itest.empty", {})

    _wait_until(
        lambda: manager.events,
        "the empty-payload event never reached the second bridge",
    )
    assert manager.events == [("itest.empty", {})]


def test_publish_without_subscribers_logs_warning(
    bridge_factory, redis_client, events_channel, caplog
):
    """Publishing to a channel nobody listens on warns instead of failing."""
    caplog.set_level(logging.WARNING, logger="osism.event_bridge")
    assert _subscriber_count(redis_client, events_channel) == 0

    assert (
        bridge_factory().add_event("itest.nosub", {"marker": str(uuid.uuid4())}) is None
    )

    assert "No Redis subscribers for event: itest.nosub" in caplog.text


def test_invalid_messages_are_skipped_and_loop_continues(
    bridge_factory, redis_client, events_channel, caplog
):
    """A frame the subscriber cannot use is logged; the next one still arrives."""
    caplog.set_level(logging.ERROR, logger="osism.event_bridge")
    _, manager = _subscribed_bridge(bridge_factory, redis_client, events_channel)

    # ``publish`` returns only after the server accepted the command, so both
    # bad frames are queued on the subscriber connection before the sentinel is
    # sent, and the subscriber thread processes frames in order.
    redis_client.publish(events_channel, "not-json")
    redis_client.publish(events_channel, json.dumps({"event_type": "itest.nopayload"}))

    sentinel_payload = {"marker": str(uuid.uuid4())}
    bridge_factory().add_event("itest.sentinel", sentinel_payload)

    _wait_until(
        lambda: manager.events, "the sentinel event never reached the second bridge"
    )

    assert manager.events == [("itest.sentinel", sentinel_payload)]
    assert "Failed to decode Redis event message" in caplog.text
    assert "Error processing event via bridge" in caplog.text


def test_shutdown_stops_background_threads(
    bridge_factory, redis_client, events_channel
):
    """Shutting a bridge down ends both threads and drops the subscription."""
    # Anything already running belongs to another bridge; only the threads this
    # test adds have to be gone at the end.
    before = _bridge_threads()

    bridge, _ = _subscribed_bridge(bridge_factory, redis_client, events_channel)
    _wait_until(
        lambda: len(_bridge_threads() - before) == 2,
        "the bridge did not start both of its background threads",
    )

    bridge.shutdown()

    # ``shutdown`` joins for 5 s per thread, and the subscriber loop may still
    # sit in one last ``get_message(timeout=10.0)`` when that join gives up.
    _wait_until(
        lambda: not _bridge_threads() - before,
        "the bridge's background threads outlived shutdown",
        timeout=15.0,
    )
    _wait_until(
        lambda: _subscriber_count(redis_client, events_channel) == 0,
        f"Redis still reports a subscriber on {events_channel}",
        timeout=15.0,
    )
