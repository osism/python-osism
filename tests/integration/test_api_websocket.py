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
# into a 30-second failure at the exact ``receive_json()`` call instead.
pytestmark = [pytest.mark.integration, pytest.mark.timeout(30)]


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
    with client.websocket_connect("/v1/events/openstack"):
        pass


def test_set_filters_is_acknowledged(client):
    """A ``set_filters`` message is processed and acknowledged verbatim."""
    with client.websocket_connect("/v1/events/openstack") as ws:
        ws.send_json(
            {
                "action": "set_filters",
                "event_filters": ["compute.instance.create.end"],
                "node_filters": ["server-01"],
                "service_filters": ["compute"],
            }
        )

        ack = ws.receive_json()

    assert ack["type"] == "filter_update"
    assert ack["status"] == "success"
    assert ack["event_filters"] == ["compute.instance.create.end"]
    assert ack["node_filters"] == ["server-01"]
    assert ack["service_filters"] == ["compute"]


def test_matching_event_is_delivered(client):
    """An event matching the connection's filters is delivered intact."""
    with client.websocket_connect("/v1/events/openstack") as ws:
        ws.send_json(
            {"action": "set_filters", "event_filters": ["compute.instance.create.end"]}
        )
        ws.receive_json()  # filter acknowledgment

        event = EventMessage(
            "compute.instance.create.end", "openstack", {"server": str(uuid.uuid4())}
        )
        # Push onto the in-process queue from the app's event loop: the queue is
        # loop-bound, so enqueuing from the test thread would be unsafe.
        client.portal.call(websocket_manager.add_event, event)

        received = ws.receive_json()

    assert received == event.to_dict()


def test_non_matching_event_is_filtered_out(client):
    """An event that does not match the filters is not delivered."""
    with client.websocket_connect("/v1/events/openstack") as ws:
        ws.send_json(
            {"action": "set_filters", "event_filters": ["compute.instance.create.end"]}
        )
        ws.receive_json()  # filter acknowledgment

        non_matching = EventMessage(
            "baremetal.node.power_set.end", "openstack", {"node": str(uuid.uuid4())}
        )
        sentinel = EventMessage(
            "compute.instance.create.end", "openstack", {"server": str(uuid.uuid4())}
        )
        # Both are queued FIFO; the broadcaster skips the non-matching event, so
        # the first (and only) message received is the matching sentinel. This
        # proves the non-matching event was dropped without an absence/timeout.
        client.portal.call(websocket_manager.add_event, non_matching)
        client.portal.call(websocket_manager.add_event, sentinel)

        received = ws.receive_json()

    assert received["id"] == sentinel.id
    assert received["event_type"] == "compute.instance.create.end"


def test_disconnect_drops_connection_count(client):
    """Disconnecting runs the ``finally`` cleanup and drops the count."""
    before = len(websocket_manager.connections)

    with client.websocket_connect("/v1/events/openstack") as ws:
        # Set filters and consume the ack to force the handler past
        # ``connect()``'s registration before asserting the count.
        ws.send_json({"action": "set_filters", "event_filters": ["compute.x"]})
        ws.receive_json()

        assert len(websocket_manager.connections) == before + 1

    assert len(websocket_manager.connections) == before
