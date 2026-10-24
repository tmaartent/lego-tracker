from decimal import Decimal

import pytest

from watcher.geo import distance_km
from watcher.matching import evaluate, looks_incomplete, mentions_set
from watcher.models import Listing, WatchCopy

GENK = "3600"


@pytest.mark.parametrize(
    "title",
    [
        "LEGO 6086 Black Knight's Castle",
        "lego kasteel 6086 compleet?",
        "LEGO 6086-1 met doos",
        "Lego6086 ridders",
        "Kasteel (6086), 1992",
    ],
)
def test_finds_the_set_number(title):
    assert mentions_set(title, "6086-1")


@pytest.mark.parametrize(
    "title",
    [
        "LEGO 60861 politiebureau",  # a different, longer number
        "LEGO 6086-2",  # a different variant
        "LEGO kasteel €6086",  # a price
        "LEGO kasteel 6086 euro",
        "LEGO 16086",
        "LEGO 6080 King's Castle",
    ],
)
def test_ignores_other_numbers(title):
    assert not mentions_set(title, "6086-1")


@pytest.mark.parametrize(
    "title",
    [
        "LEGO 6086 incompleet",
        "LEGO 6086 niet volledig",
        "LEGO 6086, enkele stukken ontbreken",
        "LEGO 6086 incomplete, missing 2 minifigs",
        "LEGO 6086 incomplet",
        "LEGO 6086 unvollständig",
    ],
)
def test_spots_incomplete_sets(title):
    assert looks_incomplete(title)


def test_complete_set_is_not_flagged():
    assert not looks_incomplete("LEGO 6086 100% compleet met doos en boekje")


def test_distance_between_postcodes():
    assert 10 < distance_km(GENK, "3500", "BE") < 20  # Hasselt
    assert 50 < distance_km(GENK, "3000", "BE") < 65  # Leuven


def test_distance_unknown_outside_belgium_or_for_unknown_postcodes():
    assert distance_km(GENK, "52062", "DE") is None
    assert distance_km(GENK, "0000", "BE") is None
    assert distance_km(GENK, None, "BE") is None


def watch(**fields):
    defaults = dict(
        watch_id=1, revision=1, set_num="6086-1", set_name="Castle",
        max_total_price=Decimal("150"), max_distance_km=50,
        accept_incomplete=True, active=True, deleted=False,
    )
    return WatchCopy(**defaults | fields)


def listing(**fields):
    defaults = dict(
        source="fake", external_id="a1", title="LEGO 6086", url="https://example.test",
        price=Decimal("100"), shipping=Decimal("10"), postcode="3500", country="BE",
    )
    return Listing(**defaults | fields)


def test_match_within_limits():
    verdict = evaluate(listing(), watch(), GENK)

    assert verdict.matches
    assert 10 < verdict.distance_km < 20


@pytest.mark.parametrize(
    ("listing_fields", "watch_fields", "reason"),
    [
        ({}, {"active": False}, "watch is not active"),
        ({}, {"deleted": True}, "watch is not active"),
        ({"title": "LEGO 6080"}, {}, "set number not in title"),
        ({"price": Decimal("145")}, {}, "too expensive"),  # 145 + 10 shipping > 150
        ({"postcode": "8000"}, {}, "too far"),  # Brugge
        ({"title": "LEGO 6086 incompleet"}, {"accept_incomplete": False}, "looks incomplete"),
    ],
)
def test_no_match(listing_fields, watch_fields, reason):
    verdict = evaluate(listing(**listing_fields), watch(**watch_fields), GENK)

    assert not verdict.matches
    assert verdict.reason == reason


def test_unknown_shipping_and_distance_do_not_rule_a_listing_out():
    verdict = evaluate(listing(shipping=None, postcode="52062", country="DE"), watch(), GENK)

    assert verdict.matches
    assert verdict.distance_km is None


def test_no_limits_means_anything_goes():
    verdict = evaluate(
        listing(price=Decimal("900"), postcode="8000"),
        watch(max_total_price=None, max_distance_km=None),
        GENK,
    )
    assert verdict.matches
