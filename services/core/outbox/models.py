"""Transactional outbox.

An event is stored in the same database transaction as the change it describes,
and a separate relay publishes it to RabbitMQ afterwards. Publishing directly from
the request would either lose the event (database commits, broker is down) or
announce a change that never happened (broker accepts, database rolls back).
"""
from django.db import models, transaction
from lego_events import Event


class OutboxEvent(models.Model):
    # The event's own id, so a message on the broker can be traced back to its row.
    id = models.UUIDField(primary_key=True)
    routing_key = models.CharField(max_length=100)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.routing_key} {self.id}"


def enqueue(event: Event) -> OutboxEvent:
    """Store an event for publishing. Must run inside the transaction that made the change."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("enqueue() must be called inside transaction.atomic()")
    return OutboxEvent.objects.create(
        id=event.event_id,
        routing_key=event.routing_key,
        payload=event.model_dump(mode="json"),
    )
