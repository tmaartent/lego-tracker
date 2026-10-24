from xml.etree import ElementTree as ET

import pytest
from django.core.exceptions import ValidationError

from catalog.importer import import_set
from catalog.models import InventoryPart
from collection.models import MissingPart, OwnedSet
from collection.wanted_list import build_wanted_list, to_bricklink_xml

from .fakes import BLACK, BRICK_2X4, NO_MAPPING, PLATE_1X2, RED, fake_client, parts_line

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_sets():
    client = fake_client({
        "6086-1": [parts_line(BRICK_2X4, RED, 4), parts_line(PLATE_1X2, BLACK, 10)],
        "6080-1": [parts_line(BRICK_2X4, RED, 8), parts_line(PLATE_1X2, NO_MAPPING, 2)],
    })
    return import_set(client, "6086-1"), import_set(client, "6080-1")


def mark_missing(owned, part_num, quantity, color_id=None):
    line = InventoryPart.objects.get(
        lego_set=owned.lego_set, part__part_num=part_num,
        **({"color_id": color_id} if color_id is not None else {}),
    )
    return MissingPart.objects.create(owned_set=owned, inventory_part=line, quantity=quantity)


def test_missing_parts_from_several_sets_are_combined(two_sets):
    castle, king = (OwnedSet.objects.create(lego_set=s) for s in two_sets)
    mark_missing(castle, "3001", 2)
    mark_missing(castle, "3023", 3)
    mark_missing(king, "3001", 1)

    wanted = build_wanted_list([castle, king])

    quantities = {(i.bricklink_part_id, i.bricklink_color_id): i.quantity for i in wanted.items}
    assert quantities == {("3001", 5): 3, ("3023", 11): 3}
    assert wanted.unmapped == []


def test_parts_without_bricklink_mapping_are_reported_not_dropped_silently(two_sets):
    king = OwnedSet.objects.create(lego_set=two_sets[1])
    mark_missing(king, "3023", 1, color_id=NO_MAPPING["id"])

    wanted = build_wanted_list([king])

    assert wanted.items == []
    assert wanted.unmapped == ["3023 ([No Color/Any Color])"]


def test_xml_matches_bricklink_upload_format(two_sets):
    castle = OwnedSet.objects.create(lego_set=two_sets[0])
    mark_missing(castle, "3001", 2)

    root = ET.fromstring(to_bricklink_xml(build_wanted_list([castle]), condition="U"))

    item = root.find("ITEM")
    assert root.tag == "INVENTORY"
    assert {child.tag: child.text for child in item} == {
        "ITEMTYPE": "P", "ITEMID": "3001", "COLOR": "5", "MINQTY": "2", "CONDITION": "U",
    }


def test_cannot_miss_more_parts_than_the_set_contains(two_sets):
    castle = OwnedSet.objects.create(lego_set=two_sets[0])
    line = InventoryPart.objects.get(lego_set=castle.lego_set, part__part_num="3001")

    with pytest.raises(ValidationError, match="only contains 4"):
        MissingPart(owned_set=castle, inventory_part=line, quantity=5).clean()


def test_cannot_mark_a_part_from_another_set(two_sets):
    castle = OwnedSet.objects.create(lego_set=two_sets[0])
    other_line = InventoryPart.objects.get(lego_set=two_sets[1], part__part_num="3001")

    with pytest.raises(ValidationError, match="different set"):
        MissingPart(owned_set=castle, inventory_part=other_line, quantity=1).clean()
