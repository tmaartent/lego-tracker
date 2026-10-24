"""Event contracts shared by the lego-tracker services.

Every event is published to one topic exchange, with its ``routing_key`` as the
routing key. Consumers bind queues to the keys (or patterns like ``watch.*``) they
care about.
"""
from .base import EXCHANGE, Event, UnknownEventError, parse
from .listings import ListingMatched, ListingPriceDropped, ListingSnapshot
from .watches import WatchDeleted, WatchState, WatchUpserted

__all__ = [
    "EXCHANGE",
    "Event",
    "ListingMatched",
    "ListingPriceDropped",
    "ListingSnapshot",
    "UnknownEventError",
    "WatchDeleted",
    "WatchState",
    "WatchUpserted",
    "parse",
]
