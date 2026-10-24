import json
from typing import Protocol

from django.db import transaction
from django.utils import timezone

from .models import OutboxEvent


class Publisher(Protocol):
    def publish(self, routing_key: str, body: bytes, message_id: str) -> None:
        """Return only once the broker has confirmed the message; raise otherwise."""


def relay_batch(publisher: Publisher, batch_size: int = 100) -> int:
    """Publish the oldest unpublished events in order. Returns how many were published.

    Rows are locked with SKIP LOCKED, so two relays never publish the same row at the
    same time. If the broker confirms but the commit fails, the event is published
    again on the next run: delivery is at-least-once and consumers deduplicate on
    the event id. A failed publish stops the batch, so events don't overtake each other.
    """
    published, error = [], None
    with transaction.atomic():
        pending = (
            OutboxEvent.objects.filter(published_at__isnull=True)
            .select_for_update(skip_locked=True)[:batch_size]
        )
        for row in pending:
            try:
                publisher.publish(
                    row.routing_key,
                    json.dumps(row.payload).encode(),
                    message_id=str(row.event_id),
                )
            except Exception as exc:
                error = exc
                break
            row.published_at = timezone.now()
            published.append(row)
        # Commit what was confirmed before a failure, so it isn't sent twice.
        OutboxEvent.objects.bulk_update(published, ["published_at"])
    if error:
        raise error
    return len(published)
