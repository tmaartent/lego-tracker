import base64
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest

from watcher.app import AVAILABLE_SOURCES
from watcher.config import Settings
from watcher.sources import EbayError, EbaySource
from watcher.sources.ebay import searches, to_listing

from .conftest import watch_state


def item(**overrides) -> dict:
    fields = {
        "itemId": "v1|1234|0",
        "title": "LEGO 6086 Black Knight's Castle compleet",
        "itemWebUrl": "https://www.ebay.be/itm/1234",
        "price": {"value": "110.00", "currency": "EUR"},
        "shippingOptions": [
            {"shippingCostType": "FIXED", "shippingCost": {"value": "12.50", "currency": "EUR"}},
            {"shippingCostType": "FIXED", "shippingCost": {"value": "7.95", "currency": "EUR"}},
        ],
        "itemLocation": {"postalCode": "3500", "country": "BE"},
    }
    return fields | overrides


class FakeEbay:
    """Answers token and search requests like eBay does, and remembers what it was asked."""

    def __init__(self, items=(), token_status=200, search_status=200):
        self.items = list(items)
        self.token_status = token_status
        self.search_status = search_status
        self.tokens_issued = 0
        self.searches: list[httpx.Request] = []
        self.token_requests: list[httpx.Request] = []
        self.revoked: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/identity/v1/oauth2/token":
            self.token_requests.append(request)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client",
                                                               "error_description": "client authentication failed"})
            self.tokens_issued += 1
            return httpx.Response(200, json={"access_token": f"token-{self.tokens_issued}",
                                             "expires_in": 7200, "token_type": "Application Access Token"})
        self.searches.append(request)
        if request.headers["Authorization"].removeprefix("Bearer ") in self.revoked:
            return httpx.Response(401, json={"errors": [{"message": "Invalid access token"}]})
        if self.search_status != 200:
            return httpx.Response(self.search_status, json={"errors": [{"message": "Too many requests"}]})
        return httpx.Response(200, json={"total": len(self.items), "itemSummaries": self.items})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ebay():
    return FakeEbay([item()])


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
async def source(ebay, clock):
    source = EbaySource("my-app-id", "my-cert-id", home_postcode="3600",
                        transport=httpx.MockTransport(ebay.handler), clock=clock)
    yield source
    await source.aclose()


def search_params(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}


async def test_finds_listings_with_the_cheapest_shipping_and_location(source):
    [listing] = await source.fetch([watch_state()])

    assert listing.external_id == "v1|1234|0"
    assert listing.url == "https://www.ebay.be/itm/1234"
    assert listing.price == Decimal("110.00")
    assert listing.shipping == Decimal("7.95")
    assert (listing.postcode, listing.country) == ("3500", "BE")


async def test_searches_for_the_set_on_the_belgian_marketplace(source, ebay):
    await source.fetch([watch_state(set_num="6086-1", max_total_price=Decimal("150.00"))])

    [request] = ebay.searches
    params = search_params(request)
    assert request.url.path == "/buy/browse/v1/item_summary/search"
    assert params["q"] == "lego 6086"
    assert params["sort"] == "newlyListed"
    assert params["filter"].split(",") == [
        "buyingOptions:{FIXED_PRICE|BEST_OFFER}",
        "deliveryCountry:BE",
        "price:[..150.00]",
        "priceCurrency:EUR",
    ]
    assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_BE"
    assert request.headers["X-EBAY-C-ENDUSERCTX"] == "contextualLocation=country%3DBE%2Czip%3D3600"
    assert request.headers["Authorization"] == "Bearer token-1"


async def test_can_be_limited_to_sellers_in_one_country(ebay, clock):
    source = EbaySource("id", "secret", home_postcode="3600", seller_country="BE",
                        transport=httpx.MockTransport(ebay.handler), clock=clock)
    await source.fetch([watch_state()])
    await source.aclose()

    assert "itemLocationCountry:BE" in search_params(ebay.searches[0])["filter"].split(",")


async def test_asks_for_an_application_token_with_the_public_scope(source, ebay):
    await source.fetch([watch_state()])

    [request] = ebay.token_requests
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"my-app-id:my-cert-id").decode()
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["client_credentials"],
        "scope": ["https://api.ebay.com/oauth/api_scope"],
    }


async def test_reuses_the_token_until_shortly_before_it_expires(source, ebay, clock):
    await source.fetch([watch_state()])
    clock.now += 7200 - 61
    await source.fetch([watch_state()])
    assert ebay.tokens_issued == 1

    clock.now += 2
    await source.fetch([watch_state()])
    assert ebay.tokens_issued == 2


async def test_gets_a_new_token_when_eBay_rejects_the_old_one(source, ebay):
    await source.fetch([watch_state()])
    ebay.revoked.add("token-1")

    [listing] = await source.fetch([watch_state()])

    assert listing.external_id == "v1|1234|0"
    assert ebay.searches[-1].headers["Authorization"] == "Bearer token-2"


async def test_wrong_keys_give_a_clear_error_without_the_secret(ebay, clock):
    ebay.token_status = 401
    source = EbaySource("my-app-id", "my-cert-id", home_postcode="3600",
                        transport=httpx.MockTransport(ebay.handler), clock=clock)

    with pytest.raises(EbayError) as error:
        await source.fetch([watch_state()])
    await source.aclose()

    assert "client authentication failed" in str(error.value)
    assert "WATCHER_EBAY_CLIENT_ID" in str(error.value)
    assert "my-cert-id" not in str(error.value)


async def test_a_failed_search_raises(source, ebay):
    ebay.search_status = 429

    with pytest.raises(EbayError, match=r"6086-1 failed \(429\): Too many requests"):
        await source.fetch([watch_state()])


async def test_one_search_per_set_and_each_listing_once(source, ebay):
    watches = [
        watch_state(watch_id=1, set_num="6086-1"),
        watch_state(watch_id=2, set_num="6086-1"),
        watch_state(watch_id=3, set_num="10305-1"),
    ]

    found = await source.fetch(watches)

    assert [search_params(r)["q"] for r in ebay.searches] == ["lego 6086", "lego 10305"]
    assert len(found) == 1  # the fake returns the same item for both searches


async def test_no_searches_without_watches(source, ebay):
    assert await source.fetch([]) == []
    assert ebay.searches == [] and ebay.token_requests == []


def test_search_uses_the_highest_price_any_watch_accepts():
    watches = [
        watch_state(watch_id=1, set_num="6086-1", max_total_price=Decimal("100")),
        watch_state(watch_id=2, set_num="6086-1", max_total_price=Decimal("150")),
        watch_state(watch_id=3, set_num="10305-1", max_total_price=Decimal("300")),
        watch_state(watch_id=4, set_num="10305-1", max_total_price=None),
        watch_state(watch_id=5, set_num="6080-1", active=False),
    ]

    assert searches(watches) == {"6086-1": Decimal("150"), "10305-1": None}


def test_shipping_is_unknown_without_a_quote():
    assert to_listing(item(shippingOptions=[])).shipping is None
    calculated = [{"shippingCostType": "CALCULATED"}]
    assert to_listing(item(shippingOptions=calculated)).shipping is None
    del_options = item()
    del del_options["shippingOptions"]
    assert to_listing(del_options).shipping is None


def test_free_shipping_is_zero():
    free = [{"shippingCostType": "FIXED", "shippingCost": {"value": "0.00", "currency": "EUR"}}]
    assert to_listing(item(shippingOptions=free)).shipping == Decimal("0.00")


def test_items_not_priced_in_euros_are_skipped():
    assert to_listing(item(price={"value": "100.00", "currency": "GBP"})) is None


def test_unusable_items_are_skipped():
    assert to_listing({"itemId": "x", "price": {"value": "1", "currency": "EUR"}}) is None
    assert to_listing(item(price={"value": "-1", "currency": "EUR"})) is None


def test_location_is_optional():
    listing = to_listing(item(itemLocation={"country": "DE"}))
    assert (listing.postcode, listing.country) == (None, "DE")


def test_the_ebay_source_needs_keys():
    with pytest.raises(ValueError, match="WATCHER_EBAY_CLIENT_ID"):
        AVAILABLE_SOURCES["ebay"](Settings(ebay_client_id="id"))


async def test_the_ebay_source_is_built_from_settings():
    source = AVAILABLE_SOURCES["ebay"](Settings(ebay_client_id="id", ebay_client_secret="secret",
                                                ebay_poll_interval_seconds=600))
    assert source.name == "ebay"
    assert source.poll_interval_seconds == 600
    await source.aclose()
