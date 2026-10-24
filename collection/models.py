"""Sets I own (usually bought second-hand) and the parts they're missing."""
from django.core.exceptions import ValidationError
from django.db import models

from catalog.models import InventoryPart, LegoSet


class OwnedSet(models.Model):
    class Condition(models.TextChoices):
        COMPLETE = "complete", "Complete"
        INCOMPLETE = "incomplete", "Incomplete"
        UNCHECKED = "unchecked", "Not checked yet"

    lego_set = models.ForeignKey(LegoSet, on_delete=models.PROTECT, related_name="copies")
    acquired_on = models.DateField(null=True, blank=True)
    price_paid = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    source = models.CharField(max_length=100, blank=True, help_text="Where it was bought, e.g. 2dehands or a flea market")
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.UNCHECKED)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-acquired_on", "lego_set__set_num"]

    def __str__(self):
        return f"{self.lego_set} (#{self.pk})"


class MissingPart(models.Model):
    owned_set = models.ForeignKey(OwnedSet, on_delete=models.CASCADE, related_name="missing_parts")
    inventory_part = models.ForeignKey(InventoryPart, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["owned_set", "inventory_part"], name="unique_missing_line"),
        ]

    def clean(self):
        if self.inventory_part.lego_set_id != self.owned_set.lego_set_id:
            raise ValidationError("This part belongs to a different set's inventory.")
        if self.quantity > self.inventory_part.quantity:
            raise ValidationError(
                f"The set only contains {self.inventory_part.quantity} of this part."
            )

    def __str__(self):
        return f"{self.quantity}x {self.inventory_part.part.part_num} missing from {self.owned_set}"
