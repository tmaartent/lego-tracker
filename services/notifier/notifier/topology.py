"""The notifier's queues.

    lego.events ──listing.*──► notifier.listings ──(reject)──► notifier.listings.dead
                                 ▲        │
                                 │        └─(temporary failure)─► notifier.listings.retry.<N>s
                                 │                                        │
                                 └──────────── after N seconds (TTL) ─────┘

Delayed retries use plain RabbitMQ, no plugin: a retry queue has a message TTL and
no consumers, and dead-letters expired messages back to the main queue through the
default exchange. Messages that keep failing, or can never be handled, end up in the
dead-letter queue, where they wait to be inspected and replayed.
"""
from faststream.rabbit import RabbitQueue

MAIN = "notifier.listings"
DEAD = "notifier.listings.dead"

# Headers on retried messages.
ATTEMPT_HEADER = "x-notifier-attempt"
ERROR_HEADER = "x-notifier-error"

main_queue = RabbitQueue(
    MAIN,
    durable=True,
    routing_key="listing.*",
    # A rejected message (unreadable, or not handled) goes to the dead-letter queue.
    arguments={"x-dead-letter-exchange": "", "x-dead-letter-routing-key": DEAD},
)

dead_queue = RabbitQueue(DEAD, durable=True)


def retry_queue_name(delay_seconds: int) -> str:
    return f"{MAIN}.retry.{delay_seconds}s"


def retry_queue(delay_seconds: int) -> RabbitQueue:
    return RabbitQueue(
        retry_queue_name(delay_seconds),
        durable=True,
        arguments={
            "x-message-ttl": delay_seconds * 1000,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": MAIN,
        },
    )
