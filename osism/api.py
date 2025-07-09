# SPDX-License-Identifier: Apache-2.0

import datetime
from logging.config import dictConfig
import logging
from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import FastAPI, Header, Request, Response, HTTPException, status
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from osism.tasks import reconciler
from osism import utils
from osism.services.listener import BaremetalEvents


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
    ],
)

dictConfig(LogConfig().model_dump())
logger = logging.getLogger("osism.api")

baremetal_events = BaremetalEvents()


class DeviceSearchResult(BaseModel):
    result: str = Field(..., description="Operation result status")
    device: Optional[str] = Field(None, description="Device name if found")


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
