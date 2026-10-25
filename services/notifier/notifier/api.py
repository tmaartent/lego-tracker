from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from . import dead_letters
from .models import Notification

router = APIRouter()


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_type: str
    watch_id: int
    channel: str
    attempts: int
    sent_at: datetime
    text: str


class DeadLettersOut(BaseModel):
    count: int
    first: list[dead_letters.DeadLetter]


@router.get("/health", tags=["ops"])
async def health(request: Request):
    return {"status": "ok", "channel": request.app.state.channel.name}


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
async def recent_notifications(request: Request, limit: int = 50):
    async with request.app.state.sessions() as session:
        rows = await session.scalars(select(Notification).order_by(Notification.sent_at.desc()).limit(limit))
        return rows.all()


@router.get("/dead-letters", response_model=DeadLettersOut, tags=["dead letters"])
async def list_dead_letters(request: Request, limit: int = 20):
    """How many messages gave up, and the first few, left in the queue."""
    broker = request.app.state.broker
    return DeadLettersOut(count=await dead_letters.count(broker), first=await dead_letters.peek(broker, limit))


@router.post("/dead-letters/replay", tags=["dead letters"])
async def replay_dead_letters(request: Request):
    """Put every dead letter back on the main queue, e.g. after fixing the Telegram settings."""
    return {"replayed": await dead_letters.replay(request.app.state.broker)}
