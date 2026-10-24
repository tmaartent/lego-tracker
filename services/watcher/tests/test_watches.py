import json

import httpx
from lego_events import WatchDeleted, WatchUpserted

from watcher.models import WatchCopy
from watcher.watches import handle_event, live_watches, load_snapshot

from .conftest import watch_state


async def apply(sessions, event):
    async with sessions() as session, session.begin():
        return await handle_event(session, event)


async def stored(sessions, watch_id=1):
    async with sessions() as session:
        return await session.get(WatchCopy, watch_id)


async def test_upsert_creates_and_updates(sessions):
    await apply(sessions, WatchUpserted(watch=watch_state(revision=1)))
    await apply(sessions, WatchUpserted(watch=watch_state(revision=2, max_distance_km=80)))

    watch = await stored(sessions)
    assert watch.revision == 2
    assert watch.max_distance_km == 80


async def test_older_revision_arriving_late_is_ignored(sessions):
    await apply(sessions, WatchUpserted(watch=watch_state(revision=3, max_distance_km=80)))

    applied = await apply(sessions, WatchUpserted(watch=watch_state(revision=2, max_distance_km=10)))

    assert not applied
    assert (await stored(sessions)).max_distance_km == 80


async def test_redelivered_event_has_no_second_effect(sessions):
    event = WatchUpserted(watch=watch_state())

    assert await apply(sessions, event)
    assert not await apply(sessions, event)


async def test_delete_leaves_a_tombstone_that_blocks_older_upserts(sessions):
    await apply(sessions, WatchUpserted(watch=watch_state(revision=1)))
    await apply(sessions, WatchDeleted(watch_id=1, revision=2))

    # The upsert for revision 1 is redelivered after the delete, as a new message.
    await apply(sessions, WatchUpserted(watch=watch_state(revision=1)))

    watch = await stored(sessions)
    assert watch.deleted
    async with sessions() as session:
        assert await live_watches(session) == []


async def test_delete_for_a_watch_never_seen(sessions):
    await apply(sessions, WatchDeleted(watch_id=7, revision=4))
    await apply(sessions, WatchUpserted(watch=watch_state(watch_id=7, revision=3)))

    assert (await stored(sessions, 7)).deleted


async def test_snapshot_from_core(sessions):
    body = [watch_state(watch_id=1).model_dump(mode="json"), watch_state(watch_id=2, set_num="6080-1").model_dump(mode="json")]
    requests = []

    def core(request: httpx.Request):
        requests.append(request.url.path)
        return httpx.Response(200, content=json.dumps(body))

    async with httpx.AsyncClient(transport=httpx.MockTransport(core), base_url="http://core") as client:
        async with sessions() as session, session.begin():
            changed = await load_snapshot(session, client)

    assert requests == ["/api/watches/"]
    assert changed == 2
    assert (await stored(sessions, 2)).set_num == "6080-1"


async def test_snapshot_does_not_undo_newer_events(sessions):
    await apply(sessions, WatchUpserted(watch=watch_state(revision=5, max_distance_km=80)))
    stale = [watch_state(revision=4, max_distance_km=10).model_dump(mode="json")]

    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(stale)))
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        async with sessions() as session, session.begin():
            await load_snapshot(session, client)

    assert (await stored(sessions)).max_distance_km == 80
