import httpx
import pytest
from lego_events import WatchUpserted

from watcher.app import Watcher, create_app
from watcher.config import Settings
from watcher.sources import FakeSource
from watcher.watches import handle_event

from .conftest import watch_state


@pytest.fixture
async def client(sessions):
    app = create_app(Settings(), sources=[FakeSource()])
    # Swap in the test database. The lifespan (broker, background jobs) doesn't run here.
    app.state.watcher = Watcher(Settings(), sessions, [FakeSource()])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://watcher") as client:
        yield client


async def test_put_a_fake_listing_poll_and_see_the_match(client, sessions):
    async with sessions() as session, session.begin():
        await handle_event(session, WatchUpserted(watch=watch_state()))

    put = await client.post(
        "/sources/fake/listings",
        json={"external_id": "x1", "title": "LEGO 6086 kasteel", "url": "https://example.test/x1",
              "price": "100", "shipping": "8", "postcode": "3500"},
    )
    poll = await client.post("/sources/fake/poll")
    listings = await client.get("/listings", params={"matched": True})

    assert put.status_code == 201
    assert poll.json() == {"seen": 1, "new_listings": 1, "new_matches": 1, "price_drops": 0}
    [listing] = listings.json()
    assert listing["external_id"] == "x1"
    assert listing["total_price"] == "108.00"
    assert listing["matched_watch_ids"] == [1]


async def test_unknown_source(client):
    assert (await client.post("/sources/marktplaats/poll")).status_code == 404


async def test_invalid_listing_is_refused(client):
    response = await client.post("/sources/fake/listings", json={"external_id": "x", "price": "-5"})
    assert response.status_code == 422
