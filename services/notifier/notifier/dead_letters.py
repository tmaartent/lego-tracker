"""Looking at and replaying the dead-letter queue."""
import json

from faststream.rabbit import RabbitBroker
from pydantic import BaseModel

from .topology import ERROR_HEADER, MAIN, dead_queue


class DeadLetter(BaseModel):
    message_id: str | None
    event_type: str | None
    error: str | None
    title: str | None


async def count(broker: RabbitBroker) -> int:
    queue = await broker.declare_queue(dead_queue)
    return (await queue.declare()).message_count


async def peek(broker: RabbitBroker, limit: int = 20) -> list[DeadLetter]:
    """The first messages in the queue, left in place."""
    queue = await broker.declare_queue(dead_queue)
    held, letters = [], []
    try:
        while len(held) < limit and (message := await queue.get(no_ack=False, fail=False)):
            held.append(message)
            letters.append(
                DeadLetter(
                    message_id=message.message_id,
                    event_type=message.type,
                    error=_header(message, ERROR_HEADER),
                    title=_title(message.body),
                )
            )
    finally:
        for message in held:
            await message.nack(requeue=True)
    return letters


async def replay(broker: RabbitBroker, limit: int = 1000) -> int:
    """Move messages back to the main queue as fresh attempts. Returns how many."""
    queue = await broker.declare_queue(dead_queue)
    moved = 0
    while moved < limit and (message := await queue.get(no_ack=False, fail=False)):
        await broker.publish(
            message.body,
            queue=MAIN,
            message_type=message.type,
            message_id=message.message_id,
            content_type=message.content_type,
            persist=True,
        )
        # Ack only after the copy is safely published; a crash in between duplicates
        # the message, which the notifier's idempotency absorbs.
        await message.ack()
        moved += 1
    return moved


def _header(message, name: str) -> str | None:
    value = (message.headers or {}).get(name)
    return value.decode() if isinstance(value, bytes) else value


def _title(body: bytes) -> str | None:
    try:
        return json.loads(body)["listing"]["title"]
    except (ValueError, KeyError, TypeError):
        return None
