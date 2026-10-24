import pika
from lego_events import EXCHANGE


class RabbitPublisher:
    """Publishes persistent messages to the events exchange, with publisher confirms."""

    def __init__(self, url: str):
        self._connection = pika.BlockingConnection(pika.URLParameters(url))
        self._channel = self._connection.channel()
        self._channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
        self._channel.confirm_delivery()

    def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        # With confirms enabled this blocks until the broker has the message and
        # raises if it refuses it.
        self._channel.basic_publish(
            exchange=EXCHANGE,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=message_id,
                type=routing_key,
            ),
        )

    def close(self) -> None:
        if self._connection.is_open:
            self._connection.close()
