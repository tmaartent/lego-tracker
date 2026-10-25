import uuid
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, utcnow


class Notification(Base):
    """A notification that was sent. Keyed by event id, so an event is sent once."""

    __tablename__ = "notifications"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    watch_id: Mapped[int]
    channel: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=1)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
