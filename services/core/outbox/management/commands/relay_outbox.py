import time

import pika.exceptions
from django.conf import settings
from django.core.management.base import BaseCommand

from outbox.rabbitmq import RabbitPublisher
from outbox.relay import relay_batch


class Command(BaseCommand):
    help = "Publish stored outbox events to RabbitMQ."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Publish what's pending, then exit.")
        parser.add_argument("--interval", type=float, default=1.0, help="Seconds between polls.")

    def handle(self, *args, once, interval, **options):
        publisher = None
        while True:
            try:
                publisher = publisher or RabbitPublisher(settings.RABBITMQ_URL)
                while published := relay_batch(publisher):
                    self.stdout.write(f"Published {published} event(s)")
            except pika.exceptions.AMQPError as exc:
                # The events stay in the outbox; reconnect and try again.
                self.stderr.write(f"RabbitMQ unavailable ({exc!r}), retrying")
                if publisher:
                    publisher.close()
                publisher = None
                if once:
                    raise
            if once:
                break
            time.sleep(interval)
        if publisher:
            publisher.close()
