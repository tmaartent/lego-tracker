"""The consumer, through FastStream's in-memory test broker."""
from faststream.rabbit import RabbitBroker, TestRabbitBroker
from faststream.rabbit.annotations import RabbitMessage

from notifier.consumer import events_exchange, subscribe_to_listings
from notifier.topology import ATTEMPT_HEADER, DEAD, ERROR_HEADER, retry_queue_name

from .conftest import FakeChannel, matched

DELAYS = [10, 60]


def make_broker(sessions, channel):
    broker = RabbitBroker()
    subscribe_to_listings(broker, sessions, channel, DELAYS)
    forwarded = []

    # Stand-ins for the retry and dead-letter queues, to see what lands there.
    def capture_into(queue):
        async def capture(message: RabbitMessage):
            forwarded.append((queue, message.headers, message.raw_message.type))

        return capture

    for queue in (retry_queue_name(10), DEAD):
        broker.subscriber(queue)(capture_into(queue))

    return broker, forwarded


async def publish(broker, event):
    await broker.publish(
        event.model_dump_json(),
        exchange=events_exchange,
        routing_key=event.routing_key,
        message_type=event.routing_key,
    )


async def test_matching_listing_is_sent(sessions):
    channel = FakeChannel()
    broker, forwarded = make_broker(sessions, channel)

    async with TestRabbitBroker(broker):
        await publish(broker, matched())

    assert len(channel.sent) == 1
    assert forwarded == []


async def test_temporary_failure_goes_to_the_first_retry_queue(sessions):
    broker, forwarded = make_broker(sessions, FakeChannel(fail_times=1))

    async with TestRabbitBroker(broker):
        await publish(broker, matched())

    [(queue, headers, message_type)] = forwarded
    assert queue == retry_queue_name(10)
    assert headers[ATTEMPT_HEADER] == 1
    assert headers[ERROR_HEADER] == "Telegram is down"
    assert message_type == "listing.matched"  # so the event type survives the detour


async def test_retried_message_is_recognised_by_its_type(sessions):
    """Back from a retry queue, the routing key is the queue name; the type still says what it is."""
    channel = FakeChannel()
    broker, _ = make_broker(sessions, channel)

    async with TestRabbitBroker(broker):
        event = matched()
        await broker.publish(
            event.model_dump_json(),
            exchange=events_exchange,
            routing_key="listing.matched",
            message_type="listing.matched",
            headers={ATTEMPT_HEADER: 1},
        )

    assert len(channel.sent) == 1


async def test_last_failure_goes_to_the_dead_letter_queue(sessions):
    broker, forwarded = make_broker(sessions, FakeChannel(fail_times=99))

    async with TestRabbitBroker(broker):
        await broker.publish(
            matched().model_dump_json(),
            exchange=events_exchange,
            routing_key="listing.matched",
            message_type="listing.matched",
            headers={ATTEMPT_HEADER: len(DELAYS)},
        )

    [(queue, headers, _)] = forwarded
    assert queue == DEAD
    assert "gave up after 3 attempts" in headers[ERROR_HEADER]
