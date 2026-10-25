import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from lego_events import ListingMatched, ListingPriceDropped, ListingSnapshot
from sqlalchemy.pool import StaticPool

from notifier import models  # noqa: F401  (registers the tables)
from notifier.channels import TemporaryFailure
from notifier.db import Base, make_sessionmaker


@pytest.fixture
async def sessions():
    """A fresh database per test: in-memory SQLite, or NOTIFIER_TEST_DATABASE_URL (CI: PostgreSQL)."""
    url = os.environ.get("NOTIFIER_TEST_DATABASE_URL")
    maker = make_sessionmaker(url) if url else make_sessionmaker("sqlite+aiosqlite://", poolclass=StaticPool)
    engine = maker.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


class FakeChannel:
    """Records what it sends; can be told to fail the first N sends."""

    name = "fake"

    def __init__(self, fail_times: int = 0, failure: Exception | None = None):
        self.sent: list[str] = []
        self.calls = 0
        self.fail_times = fail_times
        self.failure = failure or TemporaryFailure("Telegram is down")

    async def send(self, text: str) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.failure
        self.sent.append(text)


def snapshot(**overrides) -> ListingSnapshot:
    fields = dict(
        source="2dehands",
        external_id="a1",
        title="LEGO 6086 kasteel compleet",
        url="https://example.test/a1",
        price=Decimal("110.00"),
        shipping=Decimal("10.00"),
        postcode="3500",
        country="BE",
        distance_km=13.7,
        first_seen=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
    )
    return ListingSnapshot(**fields | overrides)


def matched(**listing_overrides) -> ListingMatched:
    return ListingMatched(
        watch_id=1, set_num="6086-1", set_name="Black Knight's Castle", listing=snapshot(**listing_overrides)
    )


def price_dropped() -> ListingPriceDropped:
    return ListingPriceDropped(
        watch_id=1,
        set_num="6086-1",
        set_name="Black Knight's Castle",
        listing=snapshot(price=Decimal("90.00")),
        previous_total_price=Decimal("120.00"),
    )
