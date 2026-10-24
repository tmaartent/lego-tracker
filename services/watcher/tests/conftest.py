import os
from decimal import Decimal

import pytest
from lego_events import WatchState
from sqlalchemy.pool import StaticPool

from watcher import models  # noqa: F401  (registers the tables)
from watcher.db import Base, make_sessionmaker
from watcher.sources import FoundListing


@pytest.fixture
async def sessions():
    """A fresh database per test: in-memory SQLite, or WATCHER_TEST_DATABASE_URL (CI: PostgreSQL)."""
    url = os.environ.get("WATCHER_TEST_DATABASE_URL")
    if url:
        maker = make_sessionmaker(url)
    else:
        maker = make_sessionmaker("sqlite+aiosqlite://", poolclass=StaticPool)
    engine = maker.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield maker
    await engine.dispose()


def watch_state(**overrides) -> WatchState:
    fields = dict(
        watch_id=1,
        revision=1,
        set_num="6086-1",
        set_name="Black Knight's Castle",
        max_total_price=Decimal("150.00"),
        max_distance_km=50,
        accept_incomplete=True,
        active=True,
    )
    return WatchState(**fields | overrides)


def found(**overrides) -> FoundListing:
    fields = dict(
        external_id="a1",
        title="LEGO 6086 Black Knight's Castle compleet",
        url="https://example.test/a1",
        price=Decimal("110.00"),
        shipping=Decimal("10.00"),
        postcode="3500",  # Hasselt, ~13 km from Genk
        country="BE",
    )
    return FoundListing(**fields | overrides)
