"""Import sets and colors from Rebrickable into the local catalog.

Imports are idempotent: running one twice updates rows instead of duplicating them.
"""
from django.db import transaction

from .models import Color, InventoryPart, LegoSet, Part
from .rebrickable import RebrickableClient


def bricklink_color_id(color_data: dict) -> int | None:
    ids = (color_data.get("external_ids") or {}).get("BrickLink", {}).get("ext_ids") or []
    return ids[0] if ids else None


def bricklink_part_id(part_data: dict) -> str:
    ids = (part_data.get("external_ids") or {}).get("BrickLink") or []
    return ids[0] if ids else ""


def upsert_color(color_data: dict) -> Color:
    defaults = {
        "name": color_data["name"],
        "rgb": color_data.get("rgb") or "",
        "is_trans": color_data.get("is_trans", False),
    }
    # Set parts don't always include external ids; never overwrite a known mapping with nothing.
    bl_id = bricklink_color_id(color_data)
    if bl_id is not None:
        defaults["bricklink_id"] = bl_id
    color, _ = Color.objects.update_or_create(id=color_data["id"], defaults=defaults)
    return color


def upsert_part(part_data: dict) -> Part:
    defaults = {
        "name": part_data["name"],
        "image_url": part_data.get("part_img_url") or "",
    }
    bl_id = bricklink_part_id(part_data)
    if bl_id:
        defaults["bricklink_id"] = bl_id
    part, _ = Part.objects.update_or_create(part_num=part_data["part_num"], defaults=defaults)
    return part


def import_colors(client: RebrickableClient) -> int:
    count = 0
    with transaction.atomic():
        for color_data in client.iter_colors():
            upsert_color(color_data)
            count += 1
    return count


def import_set(client: RebrickableClient, set_num: str) -> LegoSet:
    set_data = client.get_set(set_num)
    lines = list(client.iter_set_parts(set_num))

    with transaction.atomic():
        lego_set, _ = LegoSet.objects.update_or_create(
            set_num=set_data["set_num"],
            defaults={
                "name": set_data["name"],
                "year": set_data.get("year"),
                "num_parts": set_data.get("num_parts") or 0,
                "image_url": set_data.get("set_img_url") or "",
            },
        )
        seen = set()
        for line in lines:
            part = upsert_part(line["part"])
            color = upsert_color(line["color"])
            item, _ = InventoryPart.objects.update_or_create(
                lego_set=lego_set,
                part=part,
                color=color,
                is_spare=line.get("is_spare", False),
                defaults={"quantity": line["quantity"]},
            )
            seen.add(item.pk)
        # Drop lines Rebrickable no longer lists, e.g. after an inventory correction.
        lego_set.inventory.exclude(pk__in=seen).delete()

    return lego_set
