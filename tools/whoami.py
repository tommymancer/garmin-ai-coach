#!/usr/bin/env python3
"""
Find your Telegram chat ID.

1. Send any message to your bot.
2. Run:  python -m tools.whoami
3. Paste the printed ID into TELEGRAM_CHAT_ID in your .env

Only needs TELEGRAM_BOT_TOKEN to be set.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach.config import config  # noqa: E402


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or config.telegram_token
    with urllib.request.urlopen(
        f"https://api.telegram.org/bot{token}/getUpdates", timeout=20
    ) as response:
        payload = json.load(response)

    results = payload.get("result", [])
    if not results:
        print("No messages found.\n"
              "Open Telegram, send your bot any message, then run this again.")
        return

    seen = {}
    for update in results:
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id") and chat["id"] not in seen:
            seen[chat["id"]] = chat

    print("Found these chats:\n")
    for chat_id, chat in seen.items():
        name = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
        handle = f"@{chat['username']}" if chat.get("username") else ""
        print(f"  TELEGRAM_CHAT_ID={chat_id}    {name} {handle}".rstrip())


if __name__ == "__main__":
    main()
