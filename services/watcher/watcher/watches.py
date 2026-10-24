"""Keeping the watcher's copy of core's watches up to date.

Two ways in: a snapshot from core's API at startup, and watch events from then on.
Both go through ``apply_state``, and a change only lands if its revision is newer
than what's stored, so the order they arrive in doesn't matter.
"""
from collections.abc import Sequence

import httpx
from lego_events import Event, WatchDeleted, WatchState, WatchUpserted
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ProcessedEvent, WatchCopy

_snapshot = TypeAdapter(list[WatchState])


async def apply_state(session: AsyncSession, state: WatchState) -> bool:
    """Store a watch's state unless a newer revision is already stored."""
    watch = await session.get(WatchCopy, state.watch_id)
    if watch is not None and watch.revision >= state.revision:
        return False
    if watch is None:
        watch = WatchCopy(watch_id=state.watch_id)
        session.add(watch)
    for field, value in state.model_dump().items():
        setattr(watch, field, value)
    watch.deleted = False
    return True


async def apply_deleted(session: AsyncSession, watch_id: int, revision: int) -> bool:
    watch = await session.get(WatchCopy, watch_id)
    if watch is not None and watch.revision >= revision:
        return False
    if watch is None:
        # Never seen it; keep a tombstone so an older upsert can't create it later.
        watch = WatchCopy(watch_id=watch_id, set_num="", set_name="", active=False)
        session.add(watch)
    watch.revision = revision
    watch.deleted = True
    return True


async def handle_event(session: AsyncSession, event: Event) -> bool:
    """Apply one event, once. Returns False for a duplicate or stale event."""
    if await session.get(ProcessedEvent, event.event_id) is not None:
        return False
    session.add(ProcessedEvent(event_id=event.event_id))
    match event:
        case WatchUpserted(watch=state):
            return await apply_state(session, state)
        case WatchDeleted(watch_id=watch_id, revision=revision):
            return await apply_deleted(session, watch_id, revision)
    return False


async def load_snapshot(session: AsyncSession, core: httpx.AsyncClient) -> int:
    """Apply core's current list of watches. Returns how many changed."""
    response = await core.get("/api/watches/")
    response.raise_for_status()
    changed = 0
    for state in _snapshot.validate_json(response.content):
        changed += await apply_state(session, state)
    return changed


async def live_watches(session: AsyncSession) -> Sequence[WatchCopy]:
    result = await session.scalars(
        select(WatchCopy).where(WatchCopy.active.is_(True), WatchCopy.deleted.is_(False))
    )
    return result.all()
