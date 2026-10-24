from datetime import UTC, datetime

from sqlalchemy import DateTime, Numeric
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetimes, stored in UTC.

    SQLite has no timezone support and hands back naive values; those are UTC
    because that's what was stored, so the timezone is put back on load.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"naive datetime {value!r}; use an aware one")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


Money = Numeric(10, 2, asdecimal=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


def make_sessionmaker(url: str, **engine_options) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(url, **engine_options)
    return async_sessionmaker(engine, expire_on_commit=False)

