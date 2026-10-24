import json
import os
import uuid

import pytest
from django.db import transaction
from lego_events import EXCHANGE, WatchDeleted

from outbox.models import OutboxEvent, enqueue
from outbox.relay import relay_batch

pytestmark = pytest.mark.django_db


class FakePublisher:
    def __init__(self, fail_on_call: int | None = None):
        self.sent = []
        self.fail_on_call = fail_on_call

    def publish(self, routing_key, body, message_id):
        if len(self.sent) + 1 == self.fail_on_call:
            raise ConnectionError("broker went away")
        self.sent.append((routing_key, json.loads(body), message_id))


def store(*events):
    with transaction.atomic():
        for event in events:
            enqueue(event)


def deleted(watch_id):
    return WatchDeleted(watch_id=watch_id, revision=1)


def test_publishes_pending_events_in_order_and_marks_them():
    store(deleted(1), deleted(2), deleted(3))
    publisher = FakePublisher()

    assert relay_batch(publisher) == 3

    assert [payload["watch_id"] for _, payload, _ in publisher.sent] == [1, 2, 3]
    assert not OutboxEvent.objects.filter(published_at__isnull=True).exists()


def test_message_id_is_the_event_id():
    event = deleted(1)
    store(event)
    publisher = FakePublisher()

    relay_batch(publisher)

    assert publisher.sent == [("watch.deleted", json.loads(event.model_dump_json()), str(event.event_id))]


def test_published_events_are_not_sent_again():
    store(deleted(1))
    relay_batch(FakePublisher())

    assert relay_batch(FakePublisher()) == 0


def test_failure_keeps_confirmed_events_and_stops_the_rest():
    store(deleted(1), deleted(2), deleted(3))

    with pytest.raises(ConnectionError):
        relay_batch(FakePublisher(fail_on_call=2))

    pending = OutboxEvent.objects.filter(published_at__isnull=True)
    assert [row.payload["watch_id"] for row in pending] == [2, 3]

    retry = FakePublisher()
    relay_batch(retry)
    assert [payload["watch_id"] for _, payload, _ in retry.sent] == [2, 3]


@pytest.mark.rabbitmq
@pytest.mark.skipif("RABBITMQ_URL" not in os.environ, reason="RABBITMQ_URL not set")
def test_round_trip_through_a_real_broker():
    import pika

    from outbox.rabbitmq import RabbitPublisher

    url = os.environ["RABBITMQ_URL"]
    publisher = RabbitPublisher(url)
    connection = pika.BlockingConnection(pika.URLParameters(url))
    channel = connection.channel()
    queue = channel.queue_declare(f"test-{uuid.uuid4()}", exclusive=True).method.queue
    channel.queue_bind(queue, EXCHANGE, routing_key="watch.*")
    try:
        event = deleted(42)
        store(event)
        relay_batch(publisher)

        method, properties, body = channel.basic_get(queue, auto_ack=True)
        assert method.routing_key == "watch.deleted"
        assert properties.message_id == str(event.event_id)
        assert json.loads(body)["watch_id"] == 42
    finally:
        publisher.close()
        connection.close()
