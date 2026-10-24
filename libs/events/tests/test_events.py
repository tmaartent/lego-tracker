import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lego_events import (
    Event,
    ListingMatched,
    ListingSnapshot,
    UnknownEventError,
    WatchDeleted,
    WatchState,
    WatchUpserted,
    parse,
)


def castle_watch(**overrides):
    fields = dict(
        watch_id=1,
        revision=1,
        set_num="6086-1",
        set_name="Black Knight's Castle",
        max_total_price=Decimal("150.00"),
        max_distance_km=50,
    )
    return WatchState(**fields | overrides)


def test_round_trip_through_json():
    sent = WatchUpserted(watch=castle_watch())

    received = parse(sent.routing_key, sent.model_dump_json())

    assert received == sent
    assert isinstance(received, WatchUpserted)


def test_unknown_fields_are_ignored_so_producers_can_add_fields():
    body = json.loads(WatchDeleted(watch_id=1, revision=3).model_dump_json())
    body["added_in_a_later_version"] = "x"

    received = parse("watch.deleted", json.dumps(body))

    assert received.watch_id == 1


def test_unknown_routing_key():
    with pytest.raises(UnknownEventError):
        parse("listing.teleported", "{}")


def test_invalid_message_is_rejected():
    with pytest.raises(ValidationError):
        parse("watch.upserted", '{"watch": {"watch_id": "not a number"}}')


def test_routing_keys_must_be_unique():
    with pytest.raises(TypeError, match="already used"):

        class Duplicate(Event):
            routing_key = "watch.deleted"


def test_listing_event_round_trip_and_total_price():
    listing = ListingSnapshot(
        source="fake", external_id="a1", title="LEGO 6086", url="https://example.test",
        price=Decimal("110.00"), shipping=Decimal("10.00"), first_seen=datetime.now(UTC),
    )
    sent = ListingMatched(watch_id=1, set_num="6086-1", listing=listing)

    received = parse("listing.matched", sent.model_dump_json())

    assert received == sent
    assert received.listing.total_price == Decimal("120.00")
    assert listing.model_copy(update={"shipping": None}).total_price == Decimal("110.00")
