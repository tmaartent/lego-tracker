"""Does a listing match a watch?

Sellers write titles like "lego kasteel 6086 compleet?" or "LEGO 6086-1 Black Knight's
Castle", so matching looks for the set number in the title, and for words that
suggest parts are missing. It is deliberately simple and errs on the side of
reporting a listing: a false alarm costs a glance, a missed deal costs the deal.
"""
import re
from dataclasses import dataclass
from decimal import Decimal

from .geo import distance_km
from .models import Listing, WatchCopy

# A 3-7 digit number, optionally with a "-1" style variant, that isn't part of a
# longer number or a decimal, and doesn't look like a price ("€6086", "6086 euro").
_SET_NUMBER = re.compile(r"(?<![\d.,€])(\d{3,7})(?:-(\d{1,2}))?(?![\d,.]|\s*(?:€|eur))", re.IGNORECASE)

_INCOMPLETE = re.compile(
    r"\b(?:"
    r"in\s?compleet|niet\s+(?:volledig|compleet)|onvolledig\w*|ontbre\w*|mist\b|missend\w*"  # nl
    r"|incomplete?|not\s+complete|missing"  # en
    r"|incomplet\w*|manqu\w*"  # fr
    r"|unvollst(?:ä|ae)ndig\w*|fehl\w*"  # de
    r")",
    re.IGNORECASE,
)


def mentions_set(title: str, set_num: str) -> bool:
    """True if the title names the set. "6086" matches set 6086-1; "6086-2" does not."""
    base, _, variant = set_num.partition("-")
    for found_base, found_variant in _SET_NUMBER.findall(title):
        if found_base == base and found_variant in ("", variant):
            return True
    return False


def looks_incomplete(title: str) -> bool:
    return bool(_INCOMPLETE.search(title))


@dataclass(frozen=True)
class Verdict:
    matches: bool
    reason: str
    distance_km: float | None = None
    looks_incomplete: bool = False


def evaluate(listing: Listing, watch: WatchCopy, home_postcode: str) -> Verdict:
    """Check one listing against one watch.

    Unknown shipping or distance doesn't rule a listing out; the notification shows
    it as unknown instead.
    """
    if not watch.is_live:
        return Verdict(False, "watch is not active")
    if not mentions_set(listing.title, watch.set_num):
        return Verdict(False, "set number not in title")

    incomplete = looks_incomplete(listing.title)
    if incomplete and not watch.accept_incomplete:
        return Verdict(False, "looks incomplete", looks_incomplete=True)

    if watch.max_total_price is not None and listing.total_price > Decimal(watch.max_total_price):
        return Verdict(False, "too expensive", looks_incomplete=incomplete)

    distance = distance_km(home_postcode, listing.postcode, listing.country)
    if watch.max_distance_km is not None and distance is not None and distance > watch.max_distance_km:
        return Verdict(False, "too far", distance_km=distance, looks_incomplete=incomplete)

    return Verdict(True, "match", distance_km=distance, looks_incomplete=incomplete)
