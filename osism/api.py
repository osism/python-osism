import datetime
from uuid import UUID

from fastapi import FastAPI, Header, Request, Response
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware


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


app = FastAPI()

app.add_middleware(
    CORSMiddleware
)


@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/webhook/netbox", response_model=WebhookNetboxResponse, status_code=200)
async def webhook(
    webhook_input: WebhookNetboxData,
    request: Request,
    response: Response,
    content_length: int = Header(...),
    x_hook_signature: str = Header(None)
):
    print(webhook_input)
    return {"result": "ok"}
