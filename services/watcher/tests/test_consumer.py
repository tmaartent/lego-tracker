"""The RabbitMQ consumer, through FastStream's in-memory test broker."""
from faststream.rabbit import RabbitBroker, TestRabbitBroker
from lego_events import WatchDeleted, WatchUpserted

from watcher.consumer import subscribe_to_watches
from watcher.messaging import events_exchange
from watcher.models import WatchCopy

from .conftest import watch_state


def make_broker(sessions):
    broker = RabbitBroker()
    subscribe_to_watches(broker, sessions)
    return broker


async def publish(broker, event):
    await broker.publish(event.model_dump_json(), exchange=events_exchange, routing_key=event.routing_key)


async def test_watch_events_from_the_exchange_update_the_copy(sessions):
    broker = make_broker(sessions)
    async with TestRabbitBroker(broker):
        await publish(broker, WatchUpserted(watch=watch_state(revision=1)))
        await publish(broker, WatchDeleted(watch_id=1, revision=2))

    async with sessions() as session:
        watch = await session.get(WatchCopy, 1)
    assert watch.deleted
    assert watch.revision == 2


async def test_unreadable_message_is_rejected_without_crashing(sessions):
    broker = make_broker(sessions)
    async with TestRabbitBroker(broker):
        await broker.publish(b'{"watch": "nonsense"}', exchange=events_exchange, routing_key="watch.upserted")
        await broker.publish(b"{}", exchange=events_exchange, routing_key="watch.teleported")
        # The consumer keeps going after rejecting both.
        await publish(broker, WatchUpserted(watch=watch_state()))

    async with sessions() as session:
        assert await session.get(WatchCopy, 1) is not None
