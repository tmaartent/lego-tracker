from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .base import Event


class WatchState(BaseModel):
    """Everything the watcher needs to know about a watch.

    Events carry the full state rather than a diff, so a consumer that missed a
    message is fixed by the next one. ``revision`` goes up on every change; a
    consumer ignores a message whose revision is not newer than what it has, which
    makes redelivered or reordered messages harmless.
    """

    model_config = ConfigDict(frozen=True)

    watch_id: int
    revision: int = Field(ge=1)
    set_num: str
    set_name: str
    max_total_price: Decimal | None = Field(
        default=None, description="EUR, including shipping. None means no limit."
    )
    max_distance_km: int | None = Field(default=None, description="None means no limit.")
    accept_incomplete: bool = True
    active: bool = True


class WatchUpserted(Event):
    routing_key: ClassVar[str] = "watch.upserted"

    watch: WatchState


class WatchDeleted(Event):
    routing_key: ClassVar[str] = "watch.deleted"

    watch_id: int
    revision: int
