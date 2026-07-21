"""Minimal Telegram Bot API client (standard library only)."""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import config

logger = logging.getLogger("coach.telegram")


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{config.telegram_token}/{method}"


def _post(method: str, payload: dict, timeout: int = 30) -> dict:
    request = urllib.request.Request(
        _api(method),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def send_message(chat_id, text: str) -> bool:
    try:
        result = _post("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        })
        return bool(result.get("ok"))
    except urllib.error.HTTPError as exc:
        logger.error("Telegram HTTP %s: %s", exc.code, exc.read().decode()[:300])
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
    return False


def send_typing(chat_id) -> None:
    try:
        _post("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=15)
    except Exception:
        pass  # cosmetic only


def get_updates(offset: int, timeout: int = 50):
    """Long-poll for incoming messages."""
    try:
        result = _post("getUpdates", {"offset": offset, "timeout": timeout},
                       timeout=timeout + 10)
        return result.get("result", [])
    except urllib.error.URLError:
        return []  # network hiccup or timeout: retry next loop
    except Exception as exc:
        logger.warning("getUpdates failed: %s", exc)
        time.sleep(3)
        return []


def download_photo(file_id: str) -> Path | None:
    """Download a photo the user sent, return its local path."""
    try:
        result = _post("getFile", {"file_id": file_id})
        remote_path = (result.get("result") or {}).get("file_path")
        if not remote_path:
            return None
        images_dir = config.images_dir
        images_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(remote_path).suffix or ".jpg"
        destination = images_dir / f"{int(time.time())}{suffix}"
        url = f"https://api.telegram.org/file/bot{config.telegram_token}/{remote_path}"
        urllib.request.urlretrieve(url, destination)
        return destination
    except Exception as exc:
        logger.error("photo download failed: %s", exc)
        return None
