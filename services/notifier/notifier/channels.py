"""Where notifications go.

A channel raises ``TemporaryFailure`` when trying again later may work (network
trouble, rate limits, Telegram having a bad moment) and ``PermanentFailure`` when it
won't without someone fixing something (a wrong token or chat id). The first is
retried with a delay; the second goes straight to the dead-letter queue.
"""
import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)


class DeliveryFailure(Exception):
    pass


class TemporaryFailure(DeliveryFailure):
    pass


class PermanentFailure(DeliveryFailure):
    pass


class Channel(Protocol):
    name: str

    async def send(self, text: str) -> None: ...


class ConsoleChannel(Channel):
    """Logs notifications. Used when Telegram isn't configured."""

    name = "console"

    async def send(self, text: str) -> None:
        log.info("Notification:\n%s", text)


class TelegramChannel(Channel):
    """Sends through the Telegram Bot API (sendMessage)."""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, http: httpx.AsyncClient | None = None):
        self._chat_id = chat_id
        self._http = http or httpx.AsyncClient(timeout=10)
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def send(self, text: str) -> None:
        try:
            response = await self._http.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "HTML"},
            )
        except httpx.TransportError as exc:
            raise TemporaryFailure(f"could not reach Telegram: {exc!r}") from exc

        if response.is_success:
            return
        # Never include the URL in errors: it contains the bot token.
        description = _description(response)
        if response.status_code == 429 or response.is_server_error:
            raise TemporaryFailure(f"Telegram answered {response.status_code}: {description}")
        raise PermanentFailure(f"Telegram refused the message ({response.status_code}): {description}")

    async def close(self) -> None:
        await self._http.aclose()


def _description(response: httpx.Response) -> str:
    try:
        return str(response.json().get("description", ""))
    except ValueError:
        return response.text[:200]
