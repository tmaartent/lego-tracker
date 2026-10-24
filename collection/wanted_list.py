"""Combine missing parts from one or more owned sets into a BrickLink wanted list.

BrickLink accepts wanted lists as an XML upload (Wanted → Upload), so this needs
no BrickLink API access.
"""
from collections import defaultdict
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from .models import MissingPart, OwnedSet


@dataclass(frozen=True)
class WantedItem:
    bricklink_part_id: str
    bricklink_color_id: int
    quantity: int


@dataclass
class WantedList:
    items: list[WantedItem]
    # Parts that can't go on the list because Rebrickable had no BrickLink mapping.
    unmapped: list[str]


def build_wanted_list(owned_sets: list[OwnedSet]) -> WantedList:
    totals: dict[tuple[str, int], int] = defaultdict(int)
    unmapped = []

    missing = (
        MissingPart.objects.filter(owned_set__in=owned_sets)
        .select_related("inventory_part__part", "inventory_part__color")
    )
    for line in missing:
        part = line.inventory_part.part
        color = line.inventory_part.color
        if not part.bricklink_id or color.bricklink_id is None:
            unmapped.append(f"{part.part_num} ({color.name})")
            continue
        totals[(part.bricklink_id, color.bricklink_id)] += line.quantity

    items = [
        WantedItem(part_id, color_id, qty)
        for (part_id, color_id), qty in sorted(totals.items())
    ]
    return WantedList(items=items, unmapped=sorted(set(unmapped)))


def to_bricklink_xml(wanted: WantedList, condition: str = "X") -> str:
    """Render the BrickLink upload format. condition: N (new), U (used) or X (any)."""
    inventory = ET.Element("INVENTORY")
    for item in wanted.items:
        node = ET.SubElement(inventory, "ITEM")
        ET.SubElement(node, "ITEMTYPE").text = "P"
        ET.SubElement(node, "ITEMID").text = item.bricklink_part_id
        ET.SubElement(node, "COLOR").text = str(item.bricklink_color_id)
        ET.SubElement(node, "MINQTY").text = str(item.quantity)
        ET.SubElement(node, "CONDITION").text = condition
    ET.indent(inventory)
    return ET.tostring(inventory, encoding="unicode")
