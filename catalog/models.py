"""Reference data about LEGO sets, mirrored from Rebrickable.

Rebrickable and BrickLink number parts and colors differently, so each part
and color also stores its BrickLink id for building wanted lists.
"""
from django.db import models


class Color(models.Model):
    # Rebrickable's color id is stable, so it's used as the primary key.
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    rgb = models.CharField(max_length=6, blank=True)
    is_trans = models.BooleanField(default=False)
    bricklink_id = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Part(models.Model):
    part_num = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    image_url = models.URLField(max_length=500, blank=True)
    bricklink_id = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["part_num"]

    def __str__(self):
        return f"{self.part_num} {self.name}"


class LegoSet(models.Model):
    set_num = models.CharField(max_length=50, unique=True)  # e.g. "6086-1"
    name = models.CharField(max_length=255)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    num_parts = models.PositiveIntegerField(default=0)
    image_url = models.URLField(max_length=500, blank=True)
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["set_num"]
        verbose_name = "LEGO set"

    def __str__(self):
        return f"{self.set_num} {self.name}"


class InventoryPart(models.Model):
    """One line of a set's parts list: a part in a color, with its quantity."""

    lego_set = models.ForeignKey(LegoSet, on_delete=models.CASCADE, related_name="inventory")
    part = models.ForeignKey(Part, on_delete=models.PROTECT)
    color = models.ForeignKey(Color, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    is_spare = models.BooleanField(default=False)

    class Meta:
        ordering = ["lego_set", "part__part_num", "color__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["lego_set", "part", "color", "is_spare"],
                name="unique_inventory_line",
            )
        ]

    def __str__(self):
        return f"{self.quantity}x {self.part.part_num} ({self.color}) in {self.lego_set.set_num}"
