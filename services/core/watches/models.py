"""Watches: which sets I'm looking for, and at what price and distance.

Every change is announced as an event through the outbox, in the same transaction.
Use save() and delete() on instances; QuerySet.update() and QuerySet.delete() skip
the events.
"""
from django.db import models, transaction
from lego_events import WatchDeleted, WatchState, WatchUpserted

from catalog.models import LegoSet
from outbox.models import enqueue


class Watch(models.Model):
    lego_set = models.ForeignKey(LegoSet, on_delete=models.PROTECT, related_name="watches")
    max_total_price = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="EUR, including shipping. Empty means no limit.",
    )
    max_distance_km = models.PositiveIntegerField(
        null=True, blank=True, help_text="From home. Empty means no limit."
    )
    accept_incomplete = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    # Goes up on every change, so consumers can ignore stale or redelivered events.
    revision = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["lego_set__set_num"]

    def __str__(self):
        return f"Watch for {self.lego_set}"

    def to_state(self) -> WatchState:
        return WatchState(
            watch_id=self.pk,
            revision=self.revision,
            set_num=self.lego_set.set_num,
            set_name=self.lego_set.name,
            max_total_price=self.max_total_price,
            max_distance_km=self.max_distance_km,
            accept_incomplete=self.accept_incomplete,
            active=self.active,
        )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                # Lock the row so two concurrent saves can't hand out the same revision.
                current = Watch.objects.select_for_update().values_list("revision", flat=True)
                self.revision = current.get(pk=self.pk)
            self.revision += 1
            super().save(*args, **kwargs)
            enqueue(WatchUpserted(watch=self.to_state()))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            watch_id = self.pk
            result = super().delete(*args, **kwargs)
            enqueue(WatchDeleted(watch_id=watch_id, revision=self.revision + 1))
            return result
