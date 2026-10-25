"""The retry and dead-letter route on a real RabbitMQ: TTLs and dead-lettering can't be faked.

Runs when NOTIFIER_TEST_RABBITMQ_URL is set (CI does). It uses the real queue names,
so don't run it while a notifier is consuming from the same broker.
"""
import asyncio
import os

import pytest
from faststream.rabbit import RabbitBroker

from notifier import dead_letters
from notifier.consumer import events_exchange, subscribe_to_listings
from notifier.models import Notification
from notifier.topology import dead_queue, main_queue, retry_queue

from .conftest import FakeChannel, matched

pytestmark = [
    pytest.mark.rabbitmq,
    pytest.mark.skipif("NOTIFIER_TEST_RABBITMQ_URL" not in os.environ, reason="NOTIFIER_TEST_RABBITMQ_URL not set"),
]

DELAYS = [1]


async def running_notifier(sessions, channel, *, purge: bool = True) -> RabbitBroker:
    broker = RabbitBroker(os.environ["NOTIFIER_TEST_RABBITMQ_URL"], logger=None)
    subscribe_to_listings(broker, sessions, channel, DELAYS)
    await broker.connect()
    for queue in (retry_queue(1), dead_queue, main_queue):
        declared = await broker.declare_queue(queue)
        if purge:
            await declared.purge()
    await broker.start()
    return broker


async def publish(broker, event):
    await broker.publish(
        event.model_dump_json(), exchange=events_exchange, routing_key=event.routing_key,
        message_type=event.routing_key, persist=True,
    )


async def eventually(check, timeout=10.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.2)
    return False


async def test_temporary_failure_is_retried_after_the_delay(sessions):
    channel = FakeChannel(fail_times=1)
    broker = await running_notifier(sessions, channel)
    event = matched()
    try:
        await publish(broker, event)

        async def sent():
            async with sessions() as session:
                return await session.get(Notification, event.event_id)

        assert await eventually(sent)
        assert (await sent()).attempts == 2
        assert len(channel.sent) == 1
    finally:
        await broker.stop()


async def test_message_that_keeps_failing_ends_up_dead_and_can_be_replayed(sessions):
    failing = FakeChannel(fail_times=99)
    broker = await running_notifier(sessions, failing)
    event = matched()
    try:
        await publish(broker, event)

        async def dead():
            return await dead_letters.count(broker) == 1

        assert await eventually(dead)
        [letter] = await dead_letters.peek(broker)
        assert letter.event_type == "listing.matched"
        assert "gave up after 2 attempts" in letter.error
        assert await dead_letters.count(broker) == 1  # peeking leaves it there
    finally:
        await broker.stop()

    # "Telegram is fixed": a working notifier replays the dead letter and sends it.
    working = FakeChannel()
    broker = await running_notifier(sessions, working, purge=False)
    try:
        assert await dead_letters.replay(broker) == 1

        async def sent():
            return len(working.sent) == 1

        assert await eventually(sent)
        assert await dead_letters.count(broker) == 0
    finally:
        await broker.stop()

