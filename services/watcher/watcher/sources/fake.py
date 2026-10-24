from collections.abc import Sequence

from lego_events import WatchState

from .base import FoundListing, Source


class FakeSource(Source):
    """An in-memory marketplace, for tests and demos.

    Listings are added (or repriced, by reusing an external_id) with ``put``, either
    from code or through ``POST /sources/fake/listings``.
    """

    name = "fake"

    def __init__(self, listings: Sequence[FoundListing] = ()):
        self._listings = {listing.external_id: listing for listing in listings}

    def put(self, listing: FoundListing) -> None:
        self._listings[listing.external_id] = listing

    async def fetch(self, watches: Sequence[WatchState]) -> list[FoundListing]:
        return list(self._listings.values())
