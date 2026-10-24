"""Minimal client for the Rebrickable API v3 (https://rebrickable.com/api/v3/docs/)."""
from collections.abc import Iterator

import httpx

BASE_URL = "https://rebrickable.com/api/v3"


class RebrickableError(Exception):
    pass


class RebrickableClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        if not api_key:
            raise RebrickableError("REBRICKABLE_API_KEY is not set")
        self._http = http or httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"key {api_key}"},
            timeout=30,
        )

    def get_set(self, set_num: str) -> dict:
        return self._get(f"/lego/sets/{set_num}/")

    def iter_set_parts(self, set_num: str) -> Iterator[dict]:
        yield from self._paginate(f"/lego/sets/{set_num}/parts/", {"page_size": 1000})

    def iter_colors(self) -> Iterator[dict]:
        yield from self._paginate("/lego/colors/", {"page_size": 1000})

    def _get(self, url: str, params: dict | None = None) -> dict:
        response = self._http.get(url, params=params)
        if response.status_code == 404:
            raise RebrickableError(f"Not found on Rebrickable: {url}")
        response.raise_for_status()
        return response.json()

    def _paginate(self, url: str, params: dict) -> Iterator[dict]:
        page = self._get(url, params)
        while True:
            yield from page["results"]
            if not page.get("next"):
                return
            # "next" is an absolute URL that already carries the query string.
            page = self._get(page["next"])
