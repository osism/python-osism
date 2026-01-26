# SPDX-License-Identifier: Apache-2.0

import datetime
from logging.config import dictConfig
import logging
import json
import subprocess
from typing import Optional, Dict, Any, List, cast
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


class HostsResponse(BaseModel):
    hosts: List[str] = Field(
        ..., description="List of host names from Ansible inventory"
    )
    count: int = Field(..., description="Total number of hosts")


class HostvarEntry(BaseModel):
    name: str = Field(..., description="Variable name")
    value: Any = Field(..., description="Variable value")


class HostvarsResponse(BaseModel):
    host: str = Field(..., description="Host name")
    variables: List[HostvarEntry] = Field(..., description="List of host variables")
    count: int = Field(..., description="Total number of variables")


class HostvarSingleResponse(BaseModel):
    host: str = Field(..., description="Host name")
    name: str = Field(..., description="Variable name")
    value: Any = Field(..., description="Variable value")


class FactEntry(BaseModel):
    name: str = Field(..., description="Fact name")
    value: Any = Field(..., description="Fact value")


class FactsResponse(BaseModel):
    host: str = Field(..., description="Host name")
    facts: List[FactEntry] = Field(..., description="List of facts")
    count: int = Field(..., description="Total number of facts")
    from_cache: bool = Field(..., description="Whether facts were retrieved from cache")


class FactSingleResponse(BaseModel):
    host: str = Field(..., description="Host name")
    name: str = Field(..., description="Fact name")
    value: Any = Field(..., description="Fact value")
    from_cache: bool = Field(..., description="Whether fact was retrieved from cache")


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


# ============================================================================
# Inventory API Endpoints
# ============================================================================


@app.get("/v1/inventory/hosts", response_model=HostsResponse, tags=["inventory"])
async def get_inventory_hosts(limit: Optional[str] = None) -> HostsResponse:
    """Get list of all hosts from Ansible inventory.

    Args:
        limit: Optional pattern to limit hosts (e.g., 'compute*', 'control')
    """
    try:
        command = ["ansible-inventory", "-i", "/ansible/inventory/hosts.yml", "--list"]
        if limit:
            command.extend(["--limit", limit])

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"Error loading inventory: {result.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load Ansible inventory",
            )

        data = json.loads(result.stdout)
        hosts = list(data.get("_meta", {}).get("hostvars", {}).keys())
        hosts.sort()

        return HostsResponse(hosts=hosts, count=len(hosts))
    except subprocess.TimeoutExpired:
        logger.error("Timeout loading inventory")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout loading Ansible inventory",
        )
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing inventory JSON: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse Ansible inventory",
        )
    except Exception as e:
        logger.error(f"Error retrieving hosts: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve hosts: {str(e)}",
        )


@app.get(
    "/v1/inventory/hosts/{host}/hostvars",
    response_model=HostvarsResponse,
    tags=["inventory"],
)
async def get_host_hostvars(host: str) -> HostvarsResponse:
    """Get all host variables for a specific host from Ansible inventory."""
    try:
        result = subprocess.run(
            [
                "ansible-inventory",
                "-i",
                "/ansible/inventory/hosts.yml",
                "--host",
                host,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            if "Unable to parse" in result.stderr or "Could not match" in result.stderr:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Host '{host}' not found in inventory",
                )
            logger.error(f"Error getting hostvars for {host}: {result.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get host variables for {host}",
            )

        data = json.loads(result.stdout)
        variables = [
            HostvarEntry(name=name, value=value) for name, value in sorted(data.items())
        ]

        return HostvarsResponse(host=host, variables=variables, count=len(variables))
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting hostvars for {host}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Timeout getting host variables for {host}",
        )
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing hostvars JSON for {host}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse host variables for {host}",
        )
    except Exception as e:
        logger.error(f"Error retrieving hostvars for {host}: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve host variables: {str(e)}",
        )


@app.get(
    "/v1/inventory/hosts/{host}/hostvars/{variable}",
    response_model=HostvarSingleResponse,
    tags=["inventory"],
)
async def get_host_hostvar(host: str, variable: str) -> HostvarSingleResponse:
    """Get a specific host variable for a host from Ansible inventory."""
    try:
        result = subprocess.run(
            [
                "ansible-inventory",
                "-i",
                "/ansible/inventory/hosts.yml",
                "--host",
                host,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            if "Unable to parse" in result.stderr or "Could not match" in result.stderr:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Host '{host}' not found in inventory",
                )
            logger.error(f"Error getting hostvars for {host}: {result.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get host variables for {host}",
            )

        data = json.loads(result.stdout)

        if variable not in data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Variable '{variable}' not found for host '{host}'",
            )

        return HostvarSingleResponse(host=host, name=variable, value=data[variable])
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting hostvar {variable} for {host}")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Timeout getting host variable for {host}",
        )
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing hostvars JSON for {host}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse host variables for {host}",
        )
    except Exception as e:
        logger.error(f"Error retrieving hostvar {variable} for {host}: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve host variable: {str(e)}",
        )


@app.get(
    "/v1/inventory/hosts/{host}/facts",
    response_model=FactsResponse,
    tags=["inventory"],
)
async def get_host_facts(host: str) -> FactsResponse:
    """Get all cached Ansible facts for a specific host."""
    try:
        data = cast(bytes | None, utils.redis.get(f"ansible_facts{host}"))

        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No facts found in cache for host '{host}'",
            )

        facts_data = json.loads(data)
        facts = [
            FactEntry(name=name, value=value)
            for name, value in sorted(facts_data.items())
        ]

        return FactsResponse(host=host, facts=facts, count=len(facts), from_cache=True)
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing facts JSON for {host}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse facts for {host}",
        )
    except Exception as e:
        logger.error(f"Error retrieving facts for {host}: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve facts: {str(e)}",
        )


@app.get(
    "/v1/inventory/hosts/{host}/facts/{fact}",
    response_model=FactSingleResponse,
    tags=["inventory"],
)
async def get_host_fact(host: str, fact: str) -> FactSingleResponse:
    """Get a specific cached Ansible fact for a host."""
    try:
        data = cast(bytes | None, utils.redis.get(f"ansible_facts{host}"))

        if not data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No facts found in cache for host '{host}'",
            )

        facts_data = json.loads(data)

        if fact not in facts_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Fact '{fact}' not found for host '{host}'",
            )

        return FactSingleResponse(
            host=host, name=fact, value=facts_data[fact], from_cache=True
        )
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing facts JSON for {host}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse facts for {host}",
        )
    except Exception as e:
        logger.error(f"Error retrieving fact {fact} for {host}: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve fact: {str(e)}",
        )
