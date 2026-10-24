"""The watcher process: HTTP API, RabbitMQ consumer, poller and outbox relay in one.

Startup order matters: the broker starts first, which declares and binds the
watcher's queue, so watch changes start collecting there. Only then is core's
snapshot loaded. Anything that changes in between is in the queue, and revisions
sort out the overlap.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import api
from .config import Settings
from .consumer import subscribe_to_watches
from .db import make_sessionmaker
from .outbox import BrokerPublisher, relay_batch
from .poller import poll
from .sources import FakeSource, Source
from .watches import load_snapshot

log = logging.getLogger(__name__)

AVAILABLE_SOURCES: dict[str, Callable[[], Source]] = {
    "fake": FakeSource,
}


class Watcher:
    """Everything the watcher runs, wired together. Created once per process."""

    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession], sources: Sequence[Source]):
        self.settings = settings
        self.sessions = sessions
        self.sources = {source.name: source for source in sources}
        self._poll_locks = {name: asyncio.Lock() for name in self.sources}

    async def poll(self, name: str):
        # One poll per source at a time, so a manual poll can't race the scheduled one.
        async with self._poll_locks[name]:
            result = await poll(self.sessions, self.sources[name], self.settings.home_postcode)
        log.info("Polled %s: %s", name, result)
        return result

    async def poll_all(self) -> None:
        for name in self.sources:
            try:
                await self.poll(name)
            except Exception:
                log.exception("Polling %s failed; trying again next round", name)

    async def load_snapshot(self) -> None:
        async with httpx.AsyncClient(base_url=self.settings.core_url, timeout=10) as core:
            async with self.sessions() as session, session.begin():
                changed = await load_snapshot(session, core)
        log.info("Loaded watches from core: %d changed", changed)


def create_app(settings: Settings | None = None, sources: Sequence[Source] | None = None) -> FastAPI:
    settings = settings or Settings()
    if sources is None:
        sources = [AVAILABLE_SOURCES[name]() for name in settings.sources]
    watcher = Watcher(settings, make_sessionmaker(settings.database_url), sources)

    broker = RabbitBroker(settings.rabbitmq_url)
    subscribe_to_watches(broker, watcher.sessions)
    publisher = BrokerPublisher(broker)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await broker.start()
        tasks = [
            asyncio.create_task(_retry_until_done(watcher.load_snapshot, "loading watches from core")),
            asyncio.create_task(_every(settings.poll_interval_seconds, watcher.poll_all)),
            asyncio.create_task(_every(settings.relay_interval_seconds, lambda: _relay(watcher, publisher))),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await broker.stop()

    app = FastAPI(title="lego-tracker watcher", version="0.1.0", lifespan=lifespan)
    app.state.watcher = watcher
    app.include_router(api.router)
    return app


async def _relay(watcher: Watcher, publisher: BrokerPublisher) -> None:
    while published := await relay_batch(watcher.sessions, publisher):
        log.info("Published %d event(s)", published)


async def _every(seconds: float, job: Callable[[], Awaitable[None]]) -> None:
    while True:
        try:
            await job()
        except Exception:
            log.exception("Background job failed; trying again in %ss", seconds)
        await asyncio.sleep(seconds)


async def _retry_until_done(job: Callable[[], Awaitable[None]], what: str, delay: float = 5) -> None:
    while True:
        try:
            return await job()
        except Exception as exc:
            log.warning("%s failed (%r); retrying in %ss", what, exc, delay)
            await asyncio.sleep(delay)
