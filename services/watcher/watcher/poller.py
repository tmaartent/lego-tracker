from dataclasses import dataclass

from lego_events import ListingMatched, ListingPriceDropped, ListingSnapshot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db import utcnow
from .matching import Verdict, evaluate
from .models import Listing, Match, WatchCopy
from .outbox import enqueue
from .sources import FoundListing, Source
from .watches import live_watches


@dataclass(frozen=True)
class PollResult:
    seen: int
    new_listings: int
    new_matches: int
    price_drops: int


async def poll(sessions: async_sessionmaker[AsyncSession], source: Source, home_postcode: str) -> PollResult:
    """Fetch from one source, store what's new, and announce new matches and price drops.

    The source is called outside any database transaction, so a slow marketplace
    doesn't hold locks. Everything found is then stored, matched and announced in one
    transaction.
    """
    async with sessions() as session:
        watches = await live_watches(session)
    found = await source.fetch([watch.to_state() for watch in watches])

    new_listings = new_matches = price_drops = 0
    async with sessions() as session, session.begin():
        watches = await live_watches(session)
        for item in found:
            listing, is_new = await _upsert(session, source.name, item)
            new_listings += is_new
            for watch in watches:
                verdict = evaluate(listing, watch, home_postcode)
                if not verdict.matches:
                    continue
                outcome = await _record_match(session, listing, watch, verdict)
                new_matches += outcome == "matched"
                price_drops += outcome == "price_dropped"
    return PollResult(len(found), new_listings, new_matches, price_drops)


async def _upsert(session: AsyncSession, source: str, item: FoundListing) -> tuple[Listing, bool]:
    listing = await session.scalar(
        select(Listing).where(Listing.source == source, Listing.external_id == item.external_id)
    )
    is_new = listing is None
    if is_new:
        listing = Listing(source=source, external_id=item.external_id, matches=[])
        session.add(listing)
    for field in ("title", "url", "price", "shipping", "postcode", "country"):
        setattr(listing, field, getattr(item, field))
    listing.last_seen = utcnow()
    await session.flush()
    return listing, is_new


async def _record_match(session: AsyncSession, listing: Listing, watch: WatchCopy, verdict: Verdict) -> str | None:
    snapshot = _snapshot(listing, verdict)
    about = dict(watch_id=watch.watch_id, set_num=watch.set_num, set_name=watch.set_name)
    match = next((m for m in listing.matches if m.watch_id == watch.watch_id), None)

    if match is None:
        listing.matches.append(Match(watch_id=watch.watch_id, total_price=snapshot.total_price))
        enqueue(session, ListingMatched(**about, listing=snapshot))
        return "matched"

    if snapshot.total_price < match.total_price:
        enqueue(
            session,
            ListingPriceDropped(**about, listing=snapshot, previous_total_price=match.total_price),
        )
        match.total_price = snapshot.total_price
        return "price_dropped"
    return None


def _snapshot(listing: Listing, verdict: Verdict) -> ListingSnapshot:
    return ListingSnapshot(
        source=listing.source,
        external_id=listing.external_id,
        title=listing.title,
        url=listing.url,
        price=listing.price,
        shipping=listing.shipping,
        postcode=listing.postcode,
        country=listing.country,
        distance_km=None if verdict.distance_km is None else round(verdict.distance_km, 1),
        looks_incomplete=verdict.looks_incomplete,
        first_seen=listing.first_seen,
    )
