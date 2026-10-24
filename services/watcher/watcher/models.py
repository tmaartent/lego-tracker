"""The watcher's own database. Nothing else reads or writes it."""
import uuid
from datetime import datetime
from decimal import Decimal

from lego_events import WatchState
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, Money, UTCDateTime, utcnow


class WatchCopy(Base):
    """The watcher's copy of a watch from core, kept up to date through events.

    A deleted watch stays as a tombstone, so its revision is remembered and a late
    event for it can't bring it back.
    """

    __tablename__ = "watches"

    watch_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    revision: Mapped[int]
    set_num: Mapped[str] = mapped_column(String(50))
    set_name: Mapped[str] = mapped_column(String(255))
    max_total_price: Mapped[Decimal | None] = mapped_column(Money)
    max_distance_km: Mapped[int | None]
    accept_incomplete: Mapped[bool] = mapped_column(default=True)
    active: Mapped[bool] = mapped_column(default=True)
    deleted: Mapped[bool] = mapped_column(default=False)

    @property
    def is_live(self) -> bool:
        return self.active and not self.deleted

    def to_state(self) -> WatchState:
        return WatchState.model_validate(self, from_attributes=True)


class Listing(Base):
    """A listing seen at a source. Identified by source and the source's own id."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))
    external_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    price: Mapped[Decimal] = mapped_column(Money)
    shipping: Mapped[Decimal | None] = mapped_column(Money)
    postcode: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(2))
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    matches: Mapped[list["Match"]] = relationship(back_populates="listing", lazy="selectin")

    @property
    def total_price(self) -> Decimal:
        return self.price + (self.shipping or 0)

    @property
    def matched_watch_ids(self) -> list[int]:
        return [match.watch_id for match in self.matches]


class Match(Base):
    """A listing that matches a watch. ``total_price`` is the lowest one announced."""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("listing_id", "watch_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.watch_id"))
    total_price: Mapped[Decimal] = mapped_column(Money)
    matched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    listing: Mapped[Listing] = relationship(back_populates="matches")


class ProcessedEvent(Base):
    """Ids of events already handled, so a redelivered message has no second effect."""

    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OutboxEvent(Base):
    """An event waiting to be published. The id gives the publishing order."""

    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    routing_key: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
