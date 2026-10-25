"""What to do with one delivered event. No RabbitMQ in here, so it's easy to test.

The consumer turns the decision into broker actions: ack, publish to a retry queue,
or publish to the dead-letter queue.
"""
from dataclasses import dataclass
from enum import Enum

from lego_events import Event, ListingMatched, ListingPriceDropped
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .channels import Channel, PermanentFailure, TemporaryFailure
from .messages import render
from .models import Notification


class Outcome(Enum):
    SENT = "sent"
    DUPLICATE = "duplicate"  # already sent; a redelivery
    IGNORED = "ignored"  # an event type the notifier doesn't act on
    RETRY = "retry"
    DEAD = "dead"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    retry_in_seconds: int | None = None
    reason: str = ""


async def handle(
    event: Event,
    attempt: int,
    sessions: async_sessionmaker[AsyncSession],
    channel: Channel,
    retry_delays: list[int],
) -> Decision:
    """Send the notification for an event, unless it was sent before.

    ``attempt`` counts earlier failed tries of this message (0 the first time).
    The record that it was sent is written after Telegram accepted it. If the
    process dies in between, the message is redelivered and sent again: a rare
    double notification is the price of never silently losing one.
    """
    if not isinstance(event, ListingMatched | ListingPriceDropped):
        return Decision(Outcome.IGNORED)

    async with sessions() as session:
        if await session.get(Notification, event.event_id) is not None:
            return Decision(Outcome.DUPLICATE)

    text = render(event)
    try:
        await channel.send(text)
    except PermanentFailure as exc:
        return Decision(Outcome.DEAD, reason=str(exc))
    except TemporaryFailure as exc:
        if attempt < len(retry_delays):
            return Decision(Outcome.RETRY, retry_in_seconds=retry_delays[attempt], reason=str(exc))
        return Decision(Outcome.DEAD, reason=f"gave up after {attempt + 1} attempts: {exc}")

    async with sessions() as session, session.begin():
        session.add(
            Notification(
                event_id=event.event_id,
                event_type=event.routing_key,
                watch_id=event.watch_id,
                channel=channel.name,
                text=text,
                attempts=attempt + 1,
            )
        )
    return Decision(Outcome.SENT)
