from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from lego_events import WatchState
from pydantic import BaseModel, Field


class FoundListing(BaseModel):
    """A listing as a source reports it, before the watcher has seen it."""

    external_id: str
    title: str
    url: str
    price: Decimal = Field(ge=0, description="EUR.")
    shipping: Decimal | None = Field(default=None, ge=0, description="EUR. None means unknown.")
    postcode: str | None = None
    country: str | None = Field(default="BE", min_length=2, max_length=2)


class Source(Protocol):
    """A place listings come from.

    A source gets the live watches and decides itself what to fetch: a search API
    runs one query per watch, an email inbox just returns whatever arrived.

    Our own sources subclass it explicitly, so the type checker verifies them where
    they're defined. Being a Protocol, it also accepts any object of the right shape.
    """

    name: str
    # How often to poll it; None means the watcher's default. APIs with a daily
    # call limit set their own.
    poll_interval_seconds: float | None = None

    async def fetch(self, watches: Sequence[WatchState]) -> list[FoundListing]: ...

    async def aclose(self) -> None:
        """Release connections when the watcher stops."""
