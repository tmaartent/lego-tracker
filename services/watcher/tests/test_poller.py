import json
from decimal import Decimal

from lego_events import ListingMatched, ListingPriceDropped, WatchUpserted, parse
from sqlalchemy import select

from watcher.models import Listing, OutboxEvent
from watcher.poller import poll
from watcher.sources import FakeSource
from watcher.watches import handle_event

from .conftest import found, watch_state

GENK = "3600"


async def add_watch(sessions, **fields):
    async with sessions() as session, session.begin():
        await handle_event(session, WatchUpserted(watch=watch_state(**fields)))


async def outbox(sessions):
    async with sessions() as session:
        rows = (await session.scalars(select(OutboxEvent).order_by(OutboxEvent.id))).all()
    return [parse(row.routing_key, json.dumps(row.payload)) for row in rows]


async def test_new_matching_listing_is_announced(sessions):
    await add_watch(sessions)
    source = FakeSource([found()])

    result = await poll(sessions, source, GENK)

    assert (result.seen, result.new_listings, result.new_matches) == (1, 1, 1)
    [event] = await outbox(sessions)
    assert isinstance(event, ListingMatched)
    assert event.watch_id == 1
    assert event.listing.total_price == Decimal("120.00")
    assert 10 < event.listing.distance_km < 20


async def test_seeing_the_same_listing_again_announces_nothing(sessions):
    await add_watch(sessions)
    source = FakeSource([found()])
    await poll(sessions, source, GENK)

    result = await poll(sessions, source, GENK)

    assert (result.new_listings, result.new_matches, result.price_drops) == (0, 0, 0)
    assert len(await outbox(sessions)) == 1


async def test_price_drop_is_announced_once(sessions):
    await add_watch(sessions)
    source = FakeSource([found(price=Decimal("110"))])
    await poll(sessions, source, GENK)

    source.put(found(price=Decimal("90")))
    result = await poll(sessions, source, GENK)
    await poll(sessions, source, GENK)

    assert result.price_drops == 1
    events = await outbox(sessions)
    assert [type(e) for e in events] == [ListingMatched, ListingPriceDropped]
    assert events[1].previous_total_price == Decimal("120.00")
    assert events[1].listing.total_price == Decimal("100.00")


async def test_price_going_up_and_back_is_not_a_drop(sessions):
    await add_watch(sessions)
    source = FakeSource([found(price=Decimal("110"))])
    await poll(sessions, source, GENK)
    source.put(found(price=Decimal("130")))
    await poll(sessions, source, GENK)
    source.put(found(price=Decimal("110")))
    await poll(sessions, source, GENK)

    assert [type(e) for e in await outbox(sessions)] == [ListingMatched]


async def test_non_matching_listing_is_stored_but_not_announced(sessions):
    await add_watch(sessions)
    source = FakeSource([found(title="LEGO 6080 King's Castle")])

    result = await poll(sessions, source, GENK)

    assert (result.new_listings, result.new_matches) == (1, 0)
    assert await outbox(sessions) == []


async def test_listing_seen_before_the_watch_matches_once_the_watch_exists(sessions):
    source = FakeSource([found()])
    await poll(sessions, source, GENK)
    assert await outbox(sessions) == []

    await add_watch(sessions)
    result = await poll(sessions, source, GENK)

    assert result.new_matches == 1


async def test_one_listing_can_match_two_watches(sessions):
    await add_watch(sessions, watch_id=1, max_distance_km=50)
    await add_watch(sessions, watch_id=2, max_distance_km=None)

    await poll(sessions, FakeSource([found()]), GENK)

    assert sorted(e.watch_id for e in await outbox(sessions)) == [1, 2]
    async with sessions() as session:
        listing = await session.scalar(select(Listing))
    assert sorted(listing.matched_watch_ids) == [1, 2]
