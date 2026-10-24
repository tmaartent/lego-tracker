"""Transactional outbox, the same pattern as in core (see docs/architecture.md, 7.1).

Events are added to the session that makes the change, so they commit or roll back
together; ``relay_batch`` publishes them afterwards.
"""
import json
from typing import Protocol

from faststream.rabbit import RabbitBroker
from lego_events import Event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import utcnow
from .messaging import events_exchange
from .models import OutboxEvent


def enqueue(session: AsyncSession, event: Event) -> None:
    session.add(
        OutboxEvent(
            event_id=event.event_id,
            routing_key=event.routing_key,
            payload=event.model_dump(mode="json"),
        )
    )


class Publisher(Protocol):
    async def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        """Return only once the broker has confirmed the message; raise otherwise."""


class BrokerPublisher:
    def __init__(self, broker: RabbitBroker):
        self._broker = broker

    async def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        # The broker's channel has publisher confirms on, so this waits for the ack.
        # Not mandatory: an event nobody listens to yet is fine, not an error.
        await self._broker.publish(
            body,
            exchange=events_exchange,
            routing_key=routing_key,
            message_id=message_id,
            message_type=routing_key,
            content_type="application/json",
            persist=True,
            mandatory=False,
        )


async def relay_batch(sessions: async_sessionmaker[AsyncSession], publisher: Publisher, batch_size: int = 100) -> int:
    """Publish the oldest unpublished events in order. Returns how many were published.

    A failed publish stops the batch; what was confirmed before it is still marked,
    so it isn't sent twice.
    """
    published, error = 0, None
    async with sessions() as session, session.begin():
        rows = await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        for row in rows:
            try:
                await publisher.publish(row.routing_key, json.dumps(row.payload).encode(), str(row.event_id))
            except Exception as exc:
                error = exc
                break
            row.published_at = utcnow()
            published += 1
    if error:
        raise error
    return published
