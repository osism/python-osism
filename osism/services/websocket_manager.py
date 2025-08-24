# SPDX-License-Identifier: Apache-2.0

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("osism.websocket")


class EventMessage:
    """Represents an event message for WebSocket streaming."""

    def __init__(
        self,
        event_type: str,
        source: str,
        data: Dict[str, Any],
        node_name: Optional[str] = None,
    ):
        self.id = str(uuid4())
        self.timestamp = datetime.utcnow().isoformat() + "Z"
        self.event_type = event_type
        self.source = source
        self.node_name = node_name
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        """Convert event message to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source": self.source,
            "node_name": self.node_name,
            "data": self.data,
        }

    def to_json(self) -> str:
        """Convert event message to JSON string."""
        return json.dumps(self.to_dict())


class WebSocketConnection:
    """Represents a WebSocket connection with filtering options."""

    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.event_filters: List[str] = []  # List of event types to filter
        self.node_filters: List[str] = []  # List of node names to filter
        self.service_filters: List[str] = []  # List of service types to filter

    def matches_filters(self, event: "EventMessage") -> bool:
        """Check if event matches this connection's filters."""
        # If no filters are set, pass all events
        if (
            not self.event_filters
            and not self.node_filters
            and not self.service_filters
        ):
            return True

        # Check event type filters
        event_match = not self.event_filters or event.event_type in self.event_filters

        # Check node filters
        node_match = not self.node_filters or (
            event.node_name is not None and event.node_name in self.node_filters
        )

        # Check service filters
        service_type = event.event_type.split(".")[0] if event.event_type else "unknown"
        service_match = not self.service_filters or service_type in self.service_filters

        return event_match and node_match and service_match


class WebSocketManager:
    """Manages WebSocket connections and event broadcasting."""

    def __init__(self):
        # Store active WebSocket connections with filtering support
        self.connections: Dict[WebSocket, WebSocketConnection] = {}
        # Event queue for broadcasting
        self.event_queue: asyncio.Queue = asyncio.Queue()
        # Background task for event broadcasting
        self._broadcaster_task: Optional[asyncio.Task] = None
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.connections[websocket] = WebSocketConnection(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.connections)}")

        # Start broadcaster if this is the first connection
        if not self._broadcaster_task or self._broadcaster_task.done():
            self._broadcaster_task = asyncio.create_task(self._broadcast_events())

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self.connections.pop(websocket, None)
        logger.info(
            f"WebSocket disconnected. Total connections: {len(self.connections)}"
        )

    async def update_filters(
        self,
        websocket: WebSocket,
        event_filters: Optional[List[str]] = None,
        node_filters: Optional[List[str]] = None,
        service_filters: Optional[List[str]] = None,
    ) -> None:
        """Update filters for a specific WebSocket connection."""
        async with self._lock:
            if websocket in self.connections:
                connection = self.connections[websocket]
                if event_filters is not None:
                    connection.event_filters = event_filters
                if node_filters is not None:
                    connection.node_filters = node_filters
                if service_filters is not None:
                    connection.service_filters = service_filters
                logger.debug(
                    f"Updated filters for WebSocket: events={connection.event_filters}, "
                    f"nodes={connection.node_filters}, services={connection.service_filters}"
                )

    async def add_event(self, event: EventMessage) -> None:
        """Add an event to the broadcast queue."""
        await self.event_queue.put(event)

    async def broadcast_event_from_notification(
        self, event_type: str, payload: Dict[str, Any]
    ) -> None:
        """Create and broadcast an event from RabbitMQ notification."""
        try:
            logger.info(f"Processing event for WebSocket broadcast: {event_type}")
            logger.debug(f"Active WebSocket connections: {len(self.connections)}")

            # Extract relevant identifiers from different service types
            node_name = None
            resource_id = None
            service_type = event_type.split(".")[0] if event_type else "unknown"

            # Extract identifiers based on service type
            if service_type == "baremetal" and "ironic_object.data" in payload:
                ironic_data = payload["ironic_object.data"]
                node_name = ironic_data.get("name")
                resource_id = ironic_data.get("uuid")
            elif service_type in ["compute", "nova"] and "nova_object.data" in payload:
                nova_data = payload["nova_object.data"]
                node_name = nova_data.get("host") or nova_data.get("name")
                resource_id = nova_data.get("uuid")
            elif service_type in ["network", "neutron"]:
                # Neutron events may have different payload structures
                if "neutron_object.data" in payload:
                    neutron_data = payload["neutron_object.data"]
                    resource_id = neutron_data.get("id") or neutron_data.get("uuid")
                    node_name = neutron_data.get("name") or neutron_data.get(
                        "device_id"
                    )
            elif service_type == "volume" and "cinder_object.data" in payload:
                cinder_data = payload["cinder_object.data"]
                resource_id = cinder_data.get("id") or cinder_data.get("uuid")
                node_name = cinder_data.get("name") or cinder_data.get("display_name")
            elif service_type == "image" and "glance_object.data" in payload:
                glance_data = payload["glance_object.data"]
                resource_id = glance_data.get("id") or glance_data.get("uuid")
                node_name = glance_data.get("name")
            elif service_type == "identity" and "keystone_object.data" in payload:
                keystone_data = payload["keystone_object.data"]
                resource_id = keystone_data.get("id") or keystone_data.get("uuid")
                node_name = keystone_data.get("name")

            # Create event message with enhanced metadata
            event_data = payload.copy()
            event_data["service_type"] = service_type
            event_data["resource_id"] = resource_id

            event = EventMessage(
                event_type=event_type,
                source="openstack",
                data=event_data,
                node_name=node_name,
            )

            await self.add_event(event)
            logger.info(
                f"Added {service_type} event to WebSocket queue: {event_type} for resource {node_name or resource_id}"
            )
            logger.debug(f"Event queue size: {self.event_queue.qsize()}")

        except Exception as e:
            logger.error(f"Error creating event from notification: {e}")

    async def _broadcast_events(self) -> None:
        """Background task to broadcast events to all connected clients."""
        logger.info("Starting WebSocket event broadcaster")

        while True:
            try:
                # Wait for an event
                event = await self.event_queue.get()

                if not self.connections:
                    # No connections, skip broadcasting
                    continue

                # Broadcast to filtered connections
                message = event.to_json()
                disconnected_connections = set()
                sent_count = 0

                async with self._lock:
                    connections_copy = dict(self.connections)

                for websocket, connection in connections_copy.items():
                    try:
                        # Check if event matches connection filters
                        if connection.matches_filters(event):
                            await websocket.send_text(message)
                            sent_count += 1
                    except WebSocketDisconnect:
                        disconnected_connections.add(websocket)
                    except Exception as e:
                        logger.error(f"Error sending message to WebSocket: {e}")
                        disconnected_connections.add(websocket)

                # Remove disconnected connections
                if disconnected_connections:
                    async with self._lock:
                        for websocket in disconnected_connections:
                            self.connections.pop(websocket, None)
                    logger.info(
                        f"Removed {len(disconnected_connections)} disconnected WebSocket(s). "
                        f"Active connections: {len(self.connections)}"
                    )

                logger.info(
                    f"Broadcasted event {event.event_type} to {sent_count}/{len(self.connections)} connection(s)"
                )

            except asyncio.CancelledError:
                logger.info("WebSocket broadcaster task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in WebSocket broadcaster: {e}")
                # Continue broadcasting even if there's an error

    async def send_heartbeat(self) -> None:
        """Send heartbeat to all connected clients."""
        if not self.connections:
            return

        heartbeat_event = EventMessage(
            event_type="heartbeat", source="osism", data={"message": "ping"}
        )

        await self.add_event(heartbeat_event)


# Global WebSocket manager instance
websocket_manager = WebSocketManager()
