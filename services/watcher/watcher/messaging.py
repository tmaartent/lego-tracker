from faststream.rabbit import ExchangeType, RabbitExchange, RabbitQueue
from lego_events import EXCHANGE

events_exchange = RabbitExchange(EXCHANGE, type=ExchangeType.TOPIC, durable=True)

# The watcher's own queue: survives restarts, so watch changes made while the
# watcher is down are waiting for it when it comes back.
watches_queue = RabbitQueue("watcher.watches", durable=True, routing_key="watch.*")
