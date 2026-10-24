from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from .models import Listing
from .sources import FakeSource, FoundListing

router = APIRouter()


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    external_id: str
    title: str
    url: str
    price: Decimal
    shipping: Decimal | None
    total_price: Decimal
    postcode: str | None
    country: str | None
    first_seen: datetime
    last_seen: datetime
    matched_watch_ids: list[int]


class PollOut(BaseModel):
    seen: int
    new_listings: int
    new_matches: int
    price_drops: int


def _watcher(request: Request):
    return request.app.state.watcher


@router.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


@router.get("/listings", response_model=list[ListingOut], tags=["listings"])
async def list_listings(request: Request, matched: bool = False):
    """Listings seen so far, newest first. ``matched=true`` shows only those matching a watch."""
    async with _watcher(request).sessions() as session:
        listings = (await session.scalars(select(Listing).order_by(Listing.first_seen.desc()))).all()
    return [listing for listing in listings if listing.matches or not matched]


@router.post("/sources/{name}/poll", response_model=PollOut, tags=["sources"])
async def poll_source(request: Request, name: str):
    """Poll one source now instead of waiting for the schedule."""
    watcher = _watcher(request)
    if name not in watcher.sources:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No source named {name!r}")
    return await watcher.poll(name)


@router.post("/sources/fake/listings", status_code=status.HTTP_201_CREATED, tags=["sources"])
async def put_fake_listing(request: Request, listing: FoundListing):
    """Put a listing on the fake marketplace. Reusing an external_id changes that listing."""
    fake = _watcher(request).sources.get("fake")
    if not isinstance(fake, FakeSource):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The fake source is not enabled")
    fake.put(listing)
    return {"external_id": listing.external_id}
