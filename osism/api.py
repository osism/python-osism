import datetime
from logging.config import dictConfig
import logging
from uuid import UUID

from fastapi import FastAPI, Header, Request, Response
from pydantic import BaseModel
import pynetbox
from starlette.middleware.cors import CORSMiddleware

from osism.tasks import reconciler
from osism import settings


class WebhookNetboxResponse(BaseModel):
    result: str


class WebhookNetboxData(BaseModel):
    username: str
    data: dict
    snapshots: dict
    event: str
    timestamp: datetime.datetime
    model: str
    request_id: UUID


# https://stackoverflow.com/questions/63510041/adding-python-logging-to-fastapi-endpoints-hosted-on-docker-doesnt-display-api
class LogConfig(BaseModel):
    """Logging configuration to be set for the server"""

    LOGGER_NAME: str = "mycoolapp"
    LOG_FORMAT: str = "%(levelprefix)s | %(asctime)s | %(message)s"
    LOG_LEVEL: str = "DEBUG"

    # Logging config
    version = 1
    disable_existing_loggers = False
    formatters = {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": LOG_FORMAT,
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    }
    handlers = {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    }
    loggers = {
        "api": {"handlers": ["default"], "level": LOG_LEVEL},
    }


app = FastAPI()

app.add_middleware(CORSMiddleware)

dictConfig(LogConfig().dict())
logger = logging.getLogger("api")

nb = None


@app.on_event("startup")
async def startup_event():
    global nb

    if settings.NETBOX_URL and settings.NETBOX_TOKEN:
        nb = pynetbox.api(settings.NETBOX_URL, token=settings.NETBOX_TOKEN)

        if settings.IGNORE_SSL_ERRORS:
            import requests

            requests.packages.urllib3.disable_warnings()
            session = requests.Session()
            session.verify = False
            nb.http_session = session


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/webhook/netbox", response_model=WebhookNetboxResponse, status_code=200)
async def webhook(
    webhook_input: WebhookNetboxData,
    request: Request,
    response: Response,
    content_length: int = Header(...),
    x_hook_signature: str = Header(None),
):
    global nb

    if nb:
        data = webhook_input.data
        url = data["url"]
        name = data["name"]

        if "devices" in url:
            tags = [x["name"] for x in data["tags"]]

            custom_fields = data["custom_fields"]
            device_type = custom_fields["device_type"]

            # NOTE: device without a defined device_type are nodes
            if not device_type:
                device_type = "node"

        elif "interfaces" in url:
            device_type = "interface"

            device_id = data["device"]["id"]
            device = nb.dcim.devices.get(id=device_id)
            tags = [str(x) for x in device.tags]
            custom_fields = device.custom_fields

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
                # netbox.generate.delay(name, custom_fields['configuration_template'])
            elif device_type == "interface":
                logger.info(
                    f"Handling change for interface {name} on managed device {device.name} of type {custom_fields['device_type']}"
                )
                # netbox.generate.delay(device.name, custom_fields['configuration_template'])

        else:
            logger.info(f"Ignoring change for unmanaged device {name}")

        return {"result": "ok"}

    else:
        return {"result": "webhook netbox not enabled"}
