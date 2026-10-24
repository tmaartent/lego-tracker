import pytest

from catalog.importer import import_colors, import_set
from catalog.models import Color, InventoryPart, LegoSet, Part
from catalog.rebrickable import RebrickableError

from .fakes import BLACK, BRICK_2X4, PLATE_1X2, RED, fake_client, parts_line

pytestmark = pytest.mark.django_db

CASTLE = "6086-1"


def castle_lines():
    return [
        parts_line(BRICK_2X4, RED, 4),
        parts_line(PLATE_1X2, BLACK, 10),
        parts_line(PLATE_1X2, BLACK, 1, is_spare=True),
    ]


def test_import_set_creates_set_parts_and_inventory():
    lego_set = import_set(fake_client({CASTLE: castle_lines()}), CASTLE)

    assert lego_set.name == "Black Knight's Castle"
    assert lego_set.inventory.count() == 3
    brick = InventoryPart.objects.get(lego_set=lego_set, part__part_num="3001")
    assert brick.quantity == 4
    assert brick.color.bricklink_id == 5
    assert brick.part.bricklink_id == "3001"


def test_import_set_twice_does_not_duplicate():
    client = fake_client({CASTLE: castle_lines()})
    import_set(client, CASTLE)
    import_set(client, CASTLE)

    assert LegoSet.objects.count() == 1
    assert Part.objects.count() == 2
    assert InventoryPart.objects.count() == 3


def test_reimport_applies_corrections_from_rebrickable():
    import_set(fake_client({CASTLE: castle_lines()}), CASTLE)
    corrected = [parts_line(BRICK_2X4, RED, 6)]  # quantity changed, plates removed

    lego_set = import_set(fake_client({CASTLE: corrected}), CASTLE)

    assert [(line.part.part_num, line.quantity) for line in lego_set.inventory.all()] == [("3001", 6)]


def test_import_follows_pagination():
    client = fake_client({CASTLE: castle_lines()}, page_size=1)

    lego_set = import_set(client, CASTLE)

    assert lego_set.inventory.count() == 3
    part_pages = [c for c in client.calls if c.url.path.endswith("/parts/")]
    assert len(part_pages) == 3


def test_unknown_set_raises_clear_error():
    with pytest.raises(RebrickableError, match="Not found"):
        import_set(fake_client({}), "99999-1")


def test_missing_external_ids_keep_known_bricklink_mapping():
    import_colors(fake_client({}, colors=[RED]))
    red_without_ids = {**RED, "external_ids": {}}

    import_set(fake_client({CASTLE: [parts_line(BRICK_2X4, red_without_ids, 1)]}), CASTLE)

    assert Color.objects.get(id=RED["id"]).bricklink_id == 5
