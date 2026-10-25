"""The notifier process: HTTP API and the RabbitMQ consumer in one."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from faststream.rabbit import RabbitBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import api
from .channels import Channel, ConsoleChannel, TelegramChannel
from .config import Settings
from .consumer import subscribe_to_listings
from .db import make_sessionmaker
from .topology import dead_queue, retry_queue

log = logging.getLogger(__name__)


def make_channel(settings: Settings) -> Channel:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return TelegramChannel(settings.telegram_bot_token.get_secret_value(), settings.telegram_chat_id)
    log.warning("Telegram isn't configured; notifications are only logged")
    return ConsoleChannel()


def create_app(
    settings: Settings | None = None,
    channel: Channel | None = None,
    sessions: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    sessions = sessions or make_sessionmaker(settings.database_url)
    channel = channel or make_channel(settings)

    broker = RabbitBroker(settings.rabbitmq_url)
    subscribe_to_listings(broker, sessions, channel, settings.retry_delays_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Declare the retry and dead-letter queues before consuming starts, so the
        # very first failure already has somewhere to go.
        await broker.connect()
        for delay in sorted(set(settings.retry_delays_seconds)):
            await broker.declare_queue(retry_queue(delay))
        await broker.declare_queue(dead_queue)
        await broker.start()
        try:
            yield
        finally:
            await broker.stop()
            if isinstance(channel, TelegramChannel):
                await channel.close()

    app = FastAPI(title="lego-tracker notifier", version="0.1.0", lifespan=lifespan)
    app.state.broker = broker
    app.state.sessions = sessions
    app.state.channel = channel
    app.include_router(api.router)
    return app
