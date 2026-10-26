"""eBay, through the official Browse API.

One search per watched set, newest listings first, on the Belgian marketplace by
default. Only fixed-price listings: an auction's current bid isn't a price you can
buy at. The search asks for listings that ship to us, and tells eBay where home is,
so the shipping costs it returns are for delivery to our postcode.

Authentication is an application token (OAuth client credentials), which only
needs the keys of an eBay developer account; no eBay user has to log in. The
token is reused until shortly before it expires.

Docs: https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""
import logging
import time
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from lego_events import WatchState
from pydantic import ValidationError

from .base import FoundListing, Source

log = logging.getLogger(__name__)

PRODUCTION_URL = "https://api.ebay.com"
SANDBOX_URL = "https://api.sandbox.ebay.com"
PUBLIC_DATA_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_PATH = "/identity/v1/oauth2/token"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"

# Renew the token this long before eBay says it expires.
TOKEN_MARGIN_SECONDS = 60


class EbayError(Exception):
    """eBay refused a request. The message never contains the keys or the token."""


class EbaySource(Source):
    name = "ebay"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        home_postcode: str,
        home_country: str = "BE",
        marketplace: str = "EBAY_BE",
        seller_country: str | None = None,
        sandbox: bool = False,
        poll_interval_seconds: float = 900,
        page_size: int = 50,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._credentials = (client_id, client_secret)
        self._home = (home_country, home_postcode)
        self._marketplace = marketplace
        self._seller_country = seller_country
        self._page_size = page_size
        self.poll_interval_seconds = poll_interval_seconds
        self._http = httpx.AsyncClient(
            base_url=SANDBOX_URL if sandbox else PRODUCTION_URL, timeout=20, transport=transport
        )
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def fetch(self, watches: Sequence[WatchState]) -> list[FoundListing]:
        found: dict[str, FoundListing] = {}
        for set_num, max_price in searches(watches).items():
            for item in await self._search(set_num, max_price):
                listing = to_listing(item)
                if listing is not None:
                    found.setdefault(listing.external_id, listing)
        return list(found.values())

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _search(self, set_num: str, max_price: Decimal | None) -> list[dict[str, Any]]:
        params = {
            "q": f"lego {set_num.partition('-')[0]}",
            "filter": ",".join(self._filters(max_price)),
            "sort": "newlyListed",
            "limit": str(self._page_size),
        }
        response = await self._get(params)
        if response.status_code == 401:  # token revoked or expired early: get a new one, once
            self._token = None
            response = await self._get(params)
        if response.status_code != 200:
            raise EbayError(f"eBay search for {set_num} failed ({response.status_code}): {_error_text(response)}")
        return response.json().get("itemSummaries", [])

    async def _get(self, params: dict[str, str]) -> httpx.Response:
        country, postcode = self._home
        headers = {
            "Authorization": f"Bearer {await self._access_token()}",
            "X-EBAY-C-MARKETPLACE-ID": self._marketplace,
            # Where to quote shipping costs for. eBay wants the value URL-encoded.
            "X-EBAY-C-ENDUSERCTX": "contextualLocation=" + quote(f"country={country},zip={postcode}", safe=""),
        }
        return await self._http.get(SEARCH_PATH, params=params, headers=headers)

    def _filters(self, max_price: Decimal | None) -> list[str]:
        country, _ = self._home
        filters = ["buyingOptions:{FIXED_PRICE|BEST_OFFER}", f"deliveryCountry:{country}"]
        if max_price is not None:
            filters += [f"price:[..{max_price}]", "priceCurrency:EUR"]
        if self._seller_country:
            filters.append(f"itemLocationCountry:{self._seller_country}")
        return filters

    async def _access_token(self) -> str:
        if self._token is not None and self._clock() < self._token_expires_at:
            return self._token
        response = await self._http.post(
            TOKEN_PATH,
            auth=self._credentials,
            data={"grant_type": "client_credentials", "scope": PUBLIC_DATA_SCOPE},
        )
        if response.status_code != 200:
            raise EbayError(
                f"eBay refused the application token ({response.status_code}): {_error_text(response)}. "
                "Check WATCHER_EBAY_CLIENT_ID and WATCHER_EBAY_CLIENT_SECRET."
            )
        body = response.json()
        self._token = body["access_token"]
        self._token_expires_at = self._clock() + int(body["expires_in"]) - TOKEN_MARGIN_SECONDS
        return self._token


def searches(watches: Sequence[WatchState]) -> dict[str, Decimal | None]:
    """One search per set, with the highest price any live watch on it accepts.

    The price filter only covers the item price; shipping is checked by matching.
    No limit if any watch on the set has none.
    """
    limits: dict[str, Decimal | None] = {}
    for watch in watches:
        if not watch.active:
            continue
        if watch.set_num in limits:
            current = limits[watch.set_num]
            limits[watch.set_num] = (
                None if current is None or watch.max_total_price is None else max(current, watch.max_total_price)
            )
        else:
            limits[watch.set_num] = watch.max_total_price
    return limits


def to_listing(item: dict[str, Any]) -> FoundListing | None:
    """An item summary as a FoundListing, or None if it can't be used (e.g. not priced in euros)."""
    price = item.get("price") or {}
    if price.get("currency") != "EUR":
        log.debug("Skipping eBay item %s: priced in %s", item.get("itemId"), price.get("currency"))
        return None
    location = item.get("itemLocation") or {}
    try:
        return FoundListing(
            external_id=item["itemId"],
            title=item["title"],
            url=item["itemWebUrl"],
            price=Decimal(price["value"]),
            shipping=_cheapest_shipping(item.get("shippingOptions") or []),
            postcode=location.get("postalCode"),
            country=location.get("country"),
        )
    except (KeyError, ValidationError, ArithmeticError) as exc:
        log.warning("Skipping eBay item %s: %s", item.get("itemId"), exc)
        return None


def _cheapest_shipping(options: list[dict[str, Any]]) -> Decimal | None:
    costs = [
        Decimal(option["shippingCost"]["value"])
        for option in options
        if (option.get("shippingCost") or {}).get("currency") == "EUR"
    ]
    return min(costs, default=None)


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    errors = body.get("errors") or []
    if errors:
        return "; ".join(str(error.get("message", error)) for error in errors)
    return str(body.get("error_description") or body.get("error") or body)[:200]
