# SPDX-License-Identifier: Apache-2.0

import datetime
from logging.config import dictConfig
import logging
import json
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import (
    FastAPI,
    Header,
    Request,
    Response,
    HTTPException,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from osism.tasks import reconciler, openstack
from osism import utils
from osism.services.listener import BaremetalEvents
from osism.services.websocket_manager import websocket_manager
from osism.services.event_bridge import event_bridge


class NotificationBaremetal(BaseModel):
    priority: str = Field(..., description="Notification priority level")
    event_type: str = Field(..., description="Type of the event")
    timestamp: str = Field(..., description="Event timestamp")
    publisher_id: str = Field(..., description="ID of the event publisher")
    message_id: UUID = Field(..., description="Unique message identifier")
    payload: Dict[str, Any] = Field(..., description="Event payload data")


class WebhookNetboxResponse(BaseModel):
    result: str = Field(..., description="Operation result status")


class WebhookNetboxData(BaseModel):
    username: str = Field(..., description="Username triggering the webhook")
    data: Dict[str, Any] = Field(..., description="Webhook data payload")
    snapshots: Dict[str, Any] = Field(..., description="Data snapshots")
    event: str = Field(..., description="Event type")
    timestamp: datetime.datetime = Field(..., description="Event timestamp")
    model: str = Field(..., description="Model type")
    request_id: UUID = Field(..., description="Unique request identifier")


class LogConfig(BaseModel):
    """Logging configuration for the OSISM API server."""

    LOGGER_NAME: str = "osism"
    LOG_FORMAT: str = "%(levelname)s | %(asctime)s | %(name)s | %(message)s"
    LOG_LEVEL: str = "INFO"

    # Logging config
    version: int = 1
    disable_existing_loggers: bool = False
    formatters: Dict[str, Any] = {
        "default": {
            "format": LOG_FORMAT,
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    handlers: Dict[str, Any] = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    }
    loggers: Dict[str, Any] = {
        "osism": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
        "api": {"handlers": ["default"], "level": LOG_LEVEL, "propagate": False},
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
    }


app = FastAPI(
    title="OSISM API",
    description="API for OpenStack Infrastructure & Service Manager",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS - in production, replace with specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Replace with actual allowed origins in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-Hook-Signature",
        "Sec-WebSocket-Protocol",
        "Sec-WebSocket-Key",
        "Sec-WebSocket-Version",
        "Sec-WebSocket-Extensions",
    ],
)

dictConfig(LogConfig().model_dump())
logger = logging.getLogger("osism.api")

baremetal_events = BaremetalEvents()

# Connect event bridge to WebSocket manager
event_bridge.set_websocket_manager(websocket_manager)


class DeviceSearchResult(BaseModel):
    result: str = Field(..., description="Operation result status")
    device: Optional[str] = Field(None, description="Device name if found")


class BaremetalNode(BaseModel):
    uuid: Optional[str] = Field(None, description="Unique identifier of the node")
    name: Optional[str] = Field(None, description="Name of the node")
    power_state: Optional[str] = Field(None, description="Current power state")
    provision_state: Optional[str] = Field(None, description="Current provision state")
    maintenance: Optional[bool] = Field(
        None, description="Whether node is in maintenance mode"
    )
    instance_uuid: Optional[str] = Field(
        None, description="UUID of associated instance"
    )
    driver: Optional[str] = Field(None, description="Driver used for the node")
    resource_class: Optional[str] = Field(
        None, description="Resource class of the node"
    )
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Node properties"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict, description="Extra node information"
    )
    last_error: Optional[str] = Field(None, description="Last error message")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class BaremetalNodesResponse(BaseModel):
    nodes: list[BaremetalNode] = Field(..., description="List of baremetal nodes")
    count: int = Field(..., description="Total number of nodes")


def find_device_by_identifier(identifier: str):
    """Find a device in NetBox by various identifiers."""
    if not utils.nb:
        return None

    device = None

    # Search by device name
    devices = utils.nb.dcim.devices.filter(name=identifier)
    if devices:
        device = list(devices)[0]

    # Search by inventory_hostname custom field
    if not device:
        devices = utils.nb.dcim.devices.filter(cf_inventory_hostname=identifier)
        if devices:
            device = list(devices)[0]

    # Search by serial number
    if not device:
        devices = utils.nb.dcim.devices.filter(serial=identifier)
        if devices:
            device = list(devices)[0]

    return device


@app.get("/", tags=["health"])
async def root() -> Dict[str, str]:
    """Health check endpoint."""
    return {"result": "ok"}


@app.get("/v1", tags=["health"])
async def v1() -> Dict[str, str]:
    """API version 1 health check endpoint."""
    return {"result": "ok"}


@app.get("/v1/events", tags=["events"])
async def events_info() -> Dict[str, str]:
    """Events endpoint info - WebSocket available at /v1/events/openstack."""
    return {
        "result": "ok",
        "websocket_endpoint": "/v1/events/openstack",
        "description": "Real-time OpenStack events via WebSocket",
    }


class SinkResponse(BaseModel):
    result: str = Field(..., description="Operation result status")


@app.post("/v1/meters/sink", response_model=SinkResponse, tags=["telemetry"])
async def write_sink_meters(request: Request) -> SinkResponse:
    """Write telemetry meters to sink."""
    try:
        data = await request.json()
        # TODO: Implement meter processing logic
        logger.info(
            f"Received meters data: {len(data) if isinstance(data, list) else 1} entries"
        )
        return SinkResponse(result="ok")
    except Exception as e:
        logger.error(f"Error processing meters: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process meters data",
        )


@app.post("/v1/events/sink", response_model=SinkResponse, tags=["telemetry"])
async def write_sink_events(request: Request) -> SinkResponse:
    """Write telemetry events to sink."""
    try:
        data = await request.json()
        # TODO: Implement event processing logic
        logger.info(
            f"Received events data: {len(data) if isinstance(data, list) else 1} entries"
        )
        return SinkResponse(result="ok")
    except Exception as e:
        logger.error(f"Error processing events: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process events data",
        )


@app.get(
    "/v1/baremetal/nodes", response_model=BaremetalNodesResponse, tags=["baremetal"]
)
async def get_baremetal_nodes_list() -> BaremetalNodesResponse:
    """Get list of all baremetal nodes managed by Ironic.

    Returns information similar to the 'baremetal list' command,
    including node details, power state, provision state, and more.
    """
    try:
        # Use the generalized function to get baremetal nodes
        nodes_data = openstack.get_baremetal_nodes()

        # Convert to response model
        nodes = [BaremetalNode(**node) for node in nodes_data]

        return BaremetalNodesResponse(nodes=nodes, count=len(nodes))
    except Exception as e:
        logger.error(f"Error retrieving baremetal nodes: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve baremetal nodes: {str(e)}",
        )


@app.post("/v1/notifications/baremetal", status_code=204, tags=["notifications"])
async def notifications_baremetal(notification: NotificationBaremetal) -> None:
    """Handle baremetal notifications."""
    try:
        handler = baremetal_events.get_handler(notification.event_type)
        handler(notification.payload)
        logger.info(
            f"Successfully processed baremetal notification: {notification.event_type}"
        )
    except Exception as e:
        logger.error(f"Error processing baremetal notification: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process baremetal notification",
        )


@app.post(
    "/v1/sonic/{identifier}/ztp/complete",
    response_model=DeviceSearchResult,
    tags=["sonic"],
)
async def sonic_ztp_complete(identifier: str) -> DeviceSearchResult:
    """Mark a switch as ZTP complete by setting provision_state to active."""
    if not utils.nb:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetBox is not enabled",
        )

    try:
        device = find_device_by_identifier(identifier)

        if device:
            logger.info(
                f"Found device {device.name} for ZTP complete with identifier {identifier}"
            )

            # Set provision_state custom field to active
            device.custom_fields["provision_state"] = "active"
            device.save()

            return DeviceSearchResult(result="ok", device=device.name)
        else:
            logger.warning(
                f"No device found for ZTP complete with identifier {identifier}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Device not found with identifier: {identifier}",
            )
    except Exception as e:
        logger.error(f"Error completing ZTP for device {identifier}: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to complete ZTP process",
        )


def process_netbox_webhook(webhook_input: WebhookNetboxData) -> None:
    """Process NetBox webhook data."""
    data = webhook_input.data
    url = data["url"]
    name = data["name"]

    if "devices" in url:
        tags = [x["name"] for x in data["tags"]]
        custom_fields = data["custom_fields"]
        device_type = custom_fields.get("device_type") or "node"

    elif "interfaces" in url:
        device_type = "interface"
        device_id = data["device"]["id"]
        device = utils.nb.dcim.devices.get(id=device_id)
        tags = [str(x) for x in device.tags]
        custom_fields = device.custom_fields
    else:
        logger.warning(f"Unknown webhook URL type: {url}")
        return

    if "Managed by OSISM" in tags:
        if device_type == "server":
            logger.info(
                f"Handling change for managed device {name} of type {device_type}"
            )
            reconciler.run.delay()
        elif device_type == "switch":
            logger.info(
                f"Handling change for managed device {name} of type {device_type}"
            )
            # TODO: Implement switch configuration generation
            # netbox.generate.delay(name, custom_fields['configuration_template'])
        elif device_type == "interface":
            logger.info(
                f"Handling change for interface {name} on managed device {device.name} of type {custom_fields['device_type']}"
            )
            # TODO: Implement interface configuration generation
            # netbox.generate.delay(device.name, custom_fields['configuration_template'])
    else:
        logger.info(f"Ignoring change for unmanaged device {name}")


@app.websocket("/v1/events/openstack")
async def websocket_openstack_events(websocket: WebSocket):
    """WebSocket endpoint for streaming all OpenStack events in real-time.

    Supports events from all OpenStack services: Ironic, Nova, Neutron, Cinder, Glance, Keystone

    Clients can send filter messages in JSON format:
    {
        "action": "set_filters",
        "event_filters": ["baremetal.node.power_set.end", "compute.instance.create.end", "network.port.create.end"],
        "node_filters": ["server-01", "server-02"],
        "service_filters": ["baremetal", "compute", "network"]
    }
    """
    await websocket_manager.connect(websocket)
    try:
        # Keep the connection alive and listen for client messages
        while True:
            try:
                # Receive messages from client for filtering configuration
                data = await websocket.receive_text()
                logger.debug(f"Received WebSocket message: {data}")

                try:
                    message = json.loads(data)
                    if message.get("action") == "set_filters":
                        event_filters = message.get("event_filters")
                        node_filters = message.get("node_filters")
                        service_filters = message.get("service_filters")

                        await websocket_manager.update_filters(
                            websocket,
                            event_filters=event_filters,
                            node_filters=node_filters,
                            service_filters=service_filters,
                        )

                        # Send acknowledgment
                        response = {
                            "type": "filter_update",
                            "status": "success",
                            "event_filters": event_filters,
                            "node_filters": node_filters,
                            "service_filters": service_filters,
                        }
                        await websocket.send_text(json.dumps(response))

                except json.JSONDecodeError:
                    logger.warning(
                        f"Invalid JSON received from WebSocket client: {data}"
                    )
                except Exception as e:
                    logger.error(f"Error processing WebSocket filter message: {e}")

            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected")
                break
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                break

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        await websocket_manager.disconnect(websocket)


@app.post(
    "/v1/webhook/netbox",
    response_model=WebhookNetboxResponse,
    status_code=200,
    tags=["webhooks"],
)
async def webhook(
    webhook_input: WebhookNetboxData,
    request: Request,
    response: Response,
    content_length: int = Header(...),
    x_hook_signature: Optional[str] = Header(None),
) -> WebhookNetboxResponse:
    """Handle NetBox webhook notifications."""
    if not utils.nb:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="NetBox webhook processing is not enabled",
        )

    try:
        # TODO: Validate webhook signature if x_hook_signature is provided
        process_netbox_webhook(webhook_input)
        return WebhookNetboxResponse(result="ok")
    except Exception as e:
        logger.error(f"Error processing NetBox webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process NetBox webhook",
        )
