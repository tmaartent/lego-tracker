import logging

from faststream.exceptions import RejectMessage
from faststream.middlewares import AckPolicy
from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange
from faststream.rabbit.annotations import RabbitMessage
from lego_events import EXCHANGE, UnknownEventError, parse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .channels import Channel
from .handling import Outcome, handle
from .topology import ATTEMPT_HEADER, DEAD, ERROR_HEADER, main_queue, retry_queue_name

log = logging.getLogger(__name__)

events_exchange = RabbitExchange(EXCHANGE, type=ExchangeType.TOPIC, durable=True)


def subscribe_to_listings(
    broker: RabbitBroker,
    sessions: async_sessionmaker[AsyncSession],
    channel: Channel,
    retry_delays: list[int],
) -> None:
    @broker.subscriber(main_queue, events_exchange, ack_policy=AckPolicy.NACK_ON_ERROR)
    async def on_listing_event(message: RabbitMessage) -> None:
        raw = message.raw_message
        # Retried and replayed messages come back through the default exchange, so
        # their routing key is the queue name. The message type always holds the event type.
        event_type = raw.type or raw.routing_key
        try:
            event = parse(event_type, message.body)
        except (UnknownEventError, ValidationError) as exc:
            log.error("Rejecting unreadable %s message: %s", event_type, exc)
            raise RejectMessage() from exc  # the queue dead-letters it

        attempt = int((message.headers or {}).get(ATTEMPT_HEADER, 0))
        decision = await handle(event, attempt, sessions, channel, retry_delays)

        if decision.outcome is Outcome.RETRY:
            queue = retry_queue_name(decision.retry_in_seconds)
            log.warning("Sending %s failed (%s); retrying in %ss", event.event_id, decision.reason, decision.retry_in_seconds)
            await _forward(broker, message, event_type, queue, attempt + 1, decision.reason)
        elif decision.outcome is Outcome.DEAD:
            log.error("Dead-lettering %s: %s", event.event_id, decision.reason)
            await _forward(broker, message, event_type, DEAD, attempt + 1, decision.reason)
        else:
            log.info("%s %s for watch %s", decision.outcome.value.capitalize(), event_type, event.watch_id)
        # Returning normally acks the original. If forwarding failed, the exception
        # nacks it instead, so it's tried again rather than lost.


async def _forward(broker: RabbitBroker, message, event_type: str, queue: str, attempt: int, error: str) -> None:
    await broker.publish(
        message.body,
        queue=queue,
        headers={ATTEMPT_HEADER: attempt, ERROR_HEADER: error[:500]},
        message_type=event_type,
        message_id=message.raw_message.message_id,
        content_type="application/json",
        persist=True,
    )
