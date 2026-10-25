"""Print the chat ids your bot has seen, to fill in NOTIFIER_TELEGRAM_CHAT_ID.

Send your bot any message in Telegram first, then run:

    NOTIFIER_TELEGRAM_BOT_TOKEN=... python -m notifier.find_chat_id
"""
import sys

import httpx

from .config import Settings


def main() -> int:
    token = Settings().telegram_bot_token
    if token is None:
        print("Set NOTIFIER_TELEGRAM_BOT_TOKEN first.", file=sys.stderr)
        return 1
    response = httpx.get(f"https://api.telegram.org/bot{token.get_secret_value()}/getUpdates", timeout=10)
    if not response.is_success:
        print(f"Telegram answered {response.status_code}: {response.json().get('description')}", file=sys.stderr)
        return 1

    chats = {}
    for update in response.json().get("result", []):
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not chats:
        print("No messages yet. Send your bot a message in Telegram and run this again.")
        return 1
    for chat_id, name in chats.items():
        print(f"{chat_id}\t{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
