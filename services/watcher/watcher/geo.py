"""Approximate distances between Belgian postcodes.

Each postcode is reduced to one point (the average of its places), so distances are
good to a few kilometres. Postcode data: GeoNames (https://www.geonames.org/),
CC BY 4.0.
"""
import csv
import math
from functools import cache
from importlib import resources

EARTH_RADIUS_KM = 6371.0


@cache
def _belgian_postcodes() -> dict[str, tuple[float, float]]:
    with resources.files("watcher.data").joinpath("postcodes_be.csv").open(encoding="utf-8") as f:
        return {row["postcode"]: (float(row["lat"]), float(row["lon"])) for row in csv.DictReader(f)}


def distance_km(home_postcode: str, postcode: str | None, country: str | None) -> float | None:
    """Distance from home to a Belgian postcode, or None if it can't be worked out."""
    if postcode is None or (country or "BE") != "BE":
        return None
    points = _belgian_postcodes()
    if home_postcode not in points or postcode.strip() not in points:
        return None
    return _haversine(points[home_postcode], points[postcode.strip()])


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))
