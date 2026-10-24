"""A fake Rebrickable API, shaped like the real v3 responses."""
import httpx

from catalog.rebrickable import BASE_URL, RebrickableClient

RED = {"id": 4, "name": "Red", "rgb": "C91A09", "is_trans": False,
       "external_ids": {"BrickLink": {"ext_ids": [5], "ext_descrs": [["Red"]]}}}
BLACK = {"id": 0, "name": "Black", "rgb": "05131D", "is_trans": False,
         "external_ids": {"BrickLink": {"ext_ids": [11], "ext_descrs": [["Black"]]}}}
NO_MAPPING = {"id": 9999, "name": "[No Color/Any Color]", "rgb": "05131D", "is_trans": False,
              "external_ids": {}}

BRICK_2X4 = {"part_num": "3001", "name": "Brick 2 x 4", "part_img_url": "https://example.com/3001.jpg",
             "external_ids": {"BrickLink": ["3001"]}}
PLATE_1X2 = {"part_num": "3023", "name": "Plate 1 x 2", "part_img_url": None,
             "external_ids": {"BrickLink": ["3023"]}}


def set_payload(set_num, name="Black Knight's Castle"):
    return {"set_num": set_num, "name": name, "year": 1992, "num_parts": 588,
            "set_img_url": "https://example.com/set.jpg"}


def parts_line(part, color, quantity, is_spare=False):
    return {"part": part, "color": color, "quantity": quantity, "is_spare": is_spare}


def fake_client(sets: dict[str, list[dict]], colors=(RED, BLACK), page_size=None):
    """Build a client backed by in-memory data. page_size forces pagination."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path.removeprefix("/api/v3")
        page = int(request.url.params.get("page", 1))

        if path == "/lego/colors/":
            return paginated(list(colors), page, path)
        for set_num, lines in sets.items():
            if path == f"/lego/sets/{set_num}/":
                return httpx.Response(200, json=set_payload(set_num))
            if path == f"/lego/sets/{set_num}/parts/":
                return paginated(lines, page, path)
        return httpx.Response(404, json={"detail": "Not found."})

    def paginated(items, page, path):
        size = page_size or len(items) or 1
        chunk = items[(page - 1) * size: page * size]
        has_next = page * size < len(items)
        next_url = f"{BASE_URL}{path}?page={page + 1}" if has_next else None
        return httpx.Response(200, json={"count": len(items), "next": next_url, "results": chunk})

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    client = RebrickableClient("test-key", http=http)
    client.calls = calls
    return client
