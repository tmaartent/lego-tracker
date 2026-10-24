import logging

from faststream.exceptions import RejectMessage
from faststream.middlewares import AckPolicy
from faststream.rabbit import RabbitBroker
from faststream.rabbit.annotations import RabbitMessage
from lego_events import UnknownEventError, parse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .messaging import events_exchange, watches_queue
from .watches import handle_event

log = logging.getLogger(__name__)


def subscribe_to_watches(broker: RabbitBroker, sessions: async_sessionmaker[AsyncSession]) -> None:
    # NACK_ON_ERROR: a database hiccup puts the message back to be tried again.
    # A message that can never be handled is rejected instead, so it can't block the
    # queue. (Planned: a dead-letter queue to keep those for inspection.)
    @broker.subscriber(watches_queue, events_exchange, ack_policy=AckPolicy.NACK_ON_ERROR)
    async def on_watch_event(message: RabbitMessage) -> None:
        routing_key = message.raw_message.routing_key
        try:
            event = parse(routing_key, message.body)
        except (UnknownEventError, ValidationError) as exc:
            log.error("Rejecting unreadable %s message: %s", routing_key, exc)
            raise RejectMessage() from exc

        async with sessions() as session, session.begin():
            applied = await handle_event(session, event)
        log.info("%s %s for watch %s", "Applied" if applied else "Skipped", routing_key, _watch_id(event))


def _watch_id(event) -> int | None:
    return getattr(event, "watch_id", None) or getattr(getattr(event, "watch", None), "watch_id", None)
