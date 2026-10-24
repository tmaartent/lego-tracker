from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EXCHANGE = "lego.events"

_registry: dict[str, type["Event"]] = {}


class UnknownEventError(ValueError):
    pass


class Event(BaseModel):
    """Base for all events.

    ``event_id`` is the idempotency key: delivery is at-least-once, so consumers
    remember which ids they have handled. Unknown fields are ignored, so a producer
    can add a field without breaking consumers that don't know it yet. Removing or
    changing a field means a new ``routing_key`` (e.g. ``watch.upserted.v2``).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    routing_key: ClassVar[str]

    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        super().__pydantic_init_subclass__(**kwargs)
        key = cls.__dict__.get("routing_key")
        if key is None:
            return
        if key in _registry:
            raise TypeError(f"routing key {key!r} is already used by {_registry[key].__name__}")
        _registry[key] = cls


def parse(routing_key: str, body: bytes | str) -> Event:
    """Turn a received message back into its event class."""
    try:
        cls = _registry[routing_key]
    except KeyError:
        raise UnknownEventError(routing_key) from None
    return cls.model_validate_json(body)
