# SPDX-License-Identifier: Apache-2.0

"""Integration tests for the OpenStack events WebSocket endpoint.

``GET /v1/events/openstack`` upgrades to a WebSocket served by the in-process
``websocket_manager`` (``osism/services/websocket_manager.py``). Driving it
through ``fastapi.testclient.TestClient`` exercises the connect / set-filters /
broadcast / disconnect path end-to-end. The manager broadcasts in-process via
an ``asyncio`` queue, so no service beyond the ``TestClient`` is needed; the
module is marked ``integration`` only to share the FastAPI / ``httpx`` setup
with the sibling facts test and stay in the same Tier 2 batch.
"""

import uuid

import pytest

from osism.services.websocket_manager import EventMessage, websocket_manager

# Most tests block on ``ws.receive_json()``, which bottoms out in Starlette's
# untimed ``queue.get()``. A regression that stops the server from emitting the
# ack or the matching event would otherwise hang forever and only die on the CI
# wall-clock timeout, disguising the failure. Cap every test so the hang turns
# into a quick failure at the exact ``receive_json()`` call. Everything runs
# in-process and completes in milliseconds; 10 seconds is generous headroom
# even on a slow CI runner.
pytestmark = [pytest.mark.integration, pytest.mark.timeout(10)]

# Endpoint under test; kept as a constant so a path change touches one line.
WS_ENDPOINT = "/v1/events/openstack"

# Representative event types shared across the tests: the tests subscribe to
# the compute event and use the baremetal event as the non-matching case.
MATCHING_EVENT_TYPE = "compute.instance.create.end"
NON_MATCHING_EVENT_TYPE = "baremetal.node.power_set.end"


def make_event(event_type):
    """Build an ``EventMessage`` with a unique payload.

    The unique payload lets tests assert full-message equality and tell events
    apart without depending on delivery order.
    """
    return EventMessage(event_type, "openstack", {"resource": str(uuid.uuid4())})


def set_filters(ws, **filters):
    """Send a ``set_filters`` message and return the acknowledgment.

    Keeps the message shape (``action`` key plus filter lists) in one place so
    a protocol change touches one line instead of every test.
    """
    ws.send_json({"action": "set_filters", **filters})
    return ws.receive_json()


@pytest.fixture(scope="module")
def client():
    """A module-scoped ``TestClient`` bound to the FastAPI app.

    ``osism.api`` is imported lazily because importing it wires the event
    bridge to Redis at module load -- safe only in the integration environment
    where Redis is up. The fixture is module-scoped on purpose: the global
    ``websocket_manager`` owns module-level ``asyncio`` primitives
    (``event_queue``, ``_lock``) that bind to the first event loop that touches
    them and raise "bound to a different event loop" on any other. Sharing one
    ``TestClient`` (one loop) across this module keeps them valid.
    """
    from fastapi.testclient import TestClient

    from osism import api

    with TestClient(api.app) as test_client:
        yield test_client


def test_websocket_connect_is_accepted(client):
    """The endpoint accepts the WebSocket upgrade."""
    with client.websocket_connect(WS_ENDPOINT):
        pass


def test_set_filters_is_acknowledged(client):
    """A ``set_filters`` message is processed and acknowledged verbatim."""
    with client.websocket_connect(WS_ENDPOINT) as ws:
        ack = set_filters(
            ws,
            event_filters=[MATCHING_EVENT_TYPE],
            node_filters=["server-01"],
            service_filters=["compute"],
        )

    assert ack["type"] == "filter_update"
    assert ack["status"] == "success"
    assert ack["event_filters"] == [MATCHING_EVENT_TYPE]
    assert ack["node_filters"] == ["server-01"]
    assert ack["service_filters"] == ["compute"]


def test_matching_event_is_delivered(client):
    """An event matching the connection's filters is delivered intact."""
    with client.websocket_connect(WS_ENDPOINT) as ws:
        set_filters(ws, event_filters=[MATCHING_EVENT_TYPE])

        event = make_event(MATCHING_EVENT_TYPE)
        # Push onto the in-process queue from the app's event loop: the queue is
        # loop-bound, so enqueuing from the test thread would be unsafe.
        client.portal.call(websocket_manager.add_event, event)

        received = ws.receive_json()

    assert received == event.to_dict()


def test_non_matching_event_is_filtered_out(client):
    """An event that does not match the filters is not delivered."""
    with client.websocket_connect(WS_ENDPOINT) as ws:
        set_filters(ws, event_filters=[MATCHING_EVENT_TYPE])

        non_matching = make_event(NON_MATCHING_EVENT_TYPE)
        sentinel = make_event(MATCHING_EVENT_TYPE)
        # Both are queued FIFO; the broadcaster skips the non-matching event, so
        # the first (and only) message received is the matching sentinel. This
        # proves the non-matching event was dropped without an absence/timeout.
        client.portal.call(websocket_manager.add_event, non_matching)
        client.portal.call(websocket_manager.add_event, sentinel)

        received = ws.receive_json()

    # Assert on the full payload (not just id/event_type): equality with the
    # sentinel guards against partial-delivery regressions, and the inequality
    # proves the dropped event's body is not what slipped through.
    assert received == sentinel.to_dict()
    assert received != non_matching.to_dict()


def test_disconnect_unregisters_connection(client):
    """Disconnecting runs the ``finally`` cleanup and unregisters the socket."""
    before = len(websocket_manager.connections)

    with client.websocket_connect(WS_ENDPOINT) as ws:
        set_filters(ws, event_filters=[MATCHING_EVENT_TYPE])

        event = make_event(MATCHING_EVENT_TYPE)
        client.portal.call(websocket_manager.add_event, event)
        # Receiving the broadcast proves the connection is registered with the
        # manager -- observable behavior instead of peeking at the registry.
        assert ws.receive_json() == event.to_dict()

    # A leaked registration has no client-visible symptom (the broadcaster
    # silently prunes dead sockets on the next send), so the registry size is
    # the only surface that can catch the leak; every other assertion in this
    # module sticks to observable behavior.
    assert len(websocket_manager.connections) == before
