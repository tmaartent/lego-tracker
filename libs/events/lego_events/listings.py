from decimal import Decimal
from typing import ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .base import Event


class ListingSnapshot(BaseModel):
    """A marketplace listing as the watcher saw it. Prices are in EUR."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(description='Where it was found, e.g. "ebay" or "2dehands".')
    external_id: str = Field(description="The listing's id at the source.")
    title: str
    url: str
    price: Decimal
    shipping: Decimal | None = Field(default=None, description="None means unknown.")
    postcode: str | None = None
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, e.g. BE.")
    distance_km: float | None = Field(default=None, description="Approximate, from home. None means unknown.")
    looks_incomplete: bool = Field(default=False, description="The title suggests parts are missing.")
    first_seen: AwareDatetime

    @property
    def total_price(self) -> Decimal:
        """Price plus shipping, or just the price when shipping is unknown."""
        return self.price + (self.shipping or 0)


class ListingMatched(Event):
    """A listing matches a watch for the first time."""

    routing_key: ClassVar[str] = "listing.matched"

    watch_id: int
    set_num: str
    listing: ListingSnapshot


class ListingPriceDropped(Event):
    """A listing that already matched a watch got cheaper."""

    routing_key: ClassVar[str] = "listing.price_dropped"

    watch_id: int
    set_num: str
    listing: ListingSnapshot
    previous_total_price: Decimal

