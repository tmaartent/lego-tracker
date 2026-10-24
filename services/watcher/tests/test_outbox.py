import json

import pytest
from lego_events import WatchDeleted
from sqlalchemy import select

from watcher.models import OutboxEvent
from watcher.outbox import enqueue, relay_batch


class FakePublisher:
    def __init__(self, fail_on_call=None):
        self.sent = []
        self.fail_on_call = fail_on_call

    async def publish(self, routing_key, body, message_id):
        if len(self.sent) + 1 == self.fail_on_call:
            raise ConnectionError("broker went away")
        self.sent.append((routing_key, json.loads(body), message_id))


async def store(sessions, *events):
    async with sessions() as session, session.begin():
        for event in events:
            enqueue(session, event)


def event(n):
    return WatchDeleted(watch_id=n, revision=1)


async def test_publishes_in_order_with_the_event_id_as_message_id(sessions):
    events = [event(1), event(2), event(3)]
    await store(sessions, *events)
    publisher = FakePublisher()

    assert await relay_batch(sessions, publisher) == 3

    assert [payload["watch_id"] for _, payload, _ in publisher.sent] == [1, 2, 3]
    assert [message_id for _, _, message_id in publisher.sent] == [str(e.event_id) for e in events]
    assert await relay_batch(sessions, FakePublisher()) == 0


async def test_failure_keeps_confirmed_events_and_stops_the_rest(sessions):
    await store(sessions, event(1), event(2), event(3))

    with pytest.raises(ConnectionError):
        await relay_batch(sessions, FakePublisher(fail_on_call=2))

    async with sessions() as session:
        pending = (await session.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None)))).all()
    assert [row.payload["watch_id"] for row in pending] == [2, 3]

    retry = FakePublisher()
    await relay_batch(sessions, retry)
    assert [payload["watch_id"] for _, payload, _ in retry.sent] == [2, 3]


async def test_rolled_back_change_leaves_no_event(sessions):
    with pytest.raises(RuntimeError):
        async with sessions() as session, session.begin():
            enqueue(session, event(1))
            raise RuntimeError("the change failed")

    assert await relay_batch(sessions, FakePublisher()) == 0
