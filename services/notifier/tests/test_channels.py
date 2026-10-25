import json

import httpx
import pytest

from notifier.channels import PermanentFailure, TelegramChannel, TemporaryFailure

TOKEN = "123:secret-token"


def channel(handler) -> TelegramChannel:
    return TelegramChannel(TOKEN, "42", http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_sends_html_message_to_the_chat():
    requests = []

    def telegram(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    await channel(telegram).send("<b>hi</b>")

    [request] = requests
    assert request.url.path == f"/bot{TOKEN}/sendMessage"
    assert json.loads(request.content) == {"chat_id": "42", "text": "<b>hi</b>", "parse_mode": "HTML"}


@pytest.mark.parametrize("status", [429, 500, 502])
async def test_rate_limits_and_server_errors_are_temporary(status):
    reply = httpx.Response(status, json={"ok": False, "description": "Too Many Requests: retry after 5"})

    with pytest.raises(TemporaryFailure):
        await channel(lambda request: reply).send("hi")


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_bad_token_or_chat_is_permanent(status):
    reply = httpx.Response(status, json={"ok": False, "description": "Unauthorized"})

    with pytest.raises(PermanentFailure, match="Unauthorized") as error:
        await channel(lambda request: reply).send("hi")
    assert TOKEN not in str(error.value)


async def test_network_trouble_is_temporary_and_does_not_leak_the_token():
    def unreachable(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(TemporaryFailure) as error:
        await channel(unreachable).send("hi")
    assert TOKEN not in str(error.value)
