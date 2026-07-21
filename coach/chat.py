#!/usr/bin/env python3
"""
Conversational coach: a long-running daemon that answers your Telegram
messages using live Garmin data.

    python -m coach.chat

Commands understood in chat:
    remember: <text>   store a permanent instruction
    profile            show what the coach remembers
    refresh            re-read Garmin now, ignoring the cache
"""

import logging
import time
from datetime import datetime

from . import garmin, llm, telegram
from .config import config
from .load_model import compute_metrics, summarize_activity
from .prompts import chat_prompt
from .store import (append_note, load_history, load_offset, load_profile,
                    save_history, save_offset)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("coach.chat")

MEMORY_TRIGGERS = ("remember:", "remember", "note:", "/remember", "/note")
PROFILE_TRIGGERS = ("profile", "/profile", "what do you remember")
REFRESH_STEMS = ("refresh", "sync", "update", "/refresh", "/sync")


def parse_memory_note(text: str):
    lowered = text.strip().lower()
    for trigger in MEMORY_TRIGGERS:
        if lowered.startswith(trigger):
            note = text.strip()[len(trigger):].lstrip(" :,-–").strip()
            return note or None
    return None


def is_refresh_command(text: str) -> bool:
    """Short messages starting with a sync verb, e.g. 'refresh', 'sync acwr'."""
    lowered = text.strip().lower().lstrip("/")
    return (
        any(lowered.startswith(stem.lstrip("/")) for stem in REFRESH_STEMS)
        and len(lowered.split()) <= 5
    )


class GarminSnapshot:
    """Keeps one Garmin session alive and caches data to avoid rate limits."""

    def __init__(self):
        self._client = None
        self._data = None
        self._fetched_at = 0.0

    def _build(self) -> dict:
        if self._client is None:
            self._client = garmin.connect()
        try:
            activities = garmin.fetch_activities(self._client)
        except Exception as exc:
            logger.info("Garmin: reconnecting (%s)", exc)
            self._client = garmin.connect()
            activities = garmin.fetch_activities(self._client)
        weighins = garmin.fetch_weighins(self._client)
        return {
            "overview": compute_metrics(activities, weighins),
            "recent_activities": [summarize_activity(a) for a in activities[:10]],
        }

    def get(self, force: bool = False) -> dict:
        now = time.time()
        if not force and self._data and now - self._fetched_at < config.snapshot_ttl:
            return self._data
        self._data = self._build()
        self._fetched_at = now
        return self._data


def handle_update(update: dict, snapshot: GarminSnapshot) -> None:
    message = update.get("message") or update.get("edited_message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    photos = message.get("photo") or []
    caption = (message.get("caption") or "").strip()

    if not chat_id or not (text or photos):
        return
    if str(chat_id) not in config.telegram_chat_ids:
        logger.info("ignored message from unauthorized chat %s", chat_id)
        return

    # --- photo (meal, screenshot, anything) ---
    if photos:
        logger.info("photo from %s (caption: %s)", chat_id, caption[:60] or "-")
        telegram.send_typing(chat_id)
        image_path = telegram.download_photo(photos[-1]["file_id"])
        if image_path is None:
            telegram.send_message(chat_id, "Couldn't download that photo, try again.")
            return
        context = _safe_snapshot(snapshot, chat_id)
        history = load_history(chat_id)
        user_message = caption or "(photo with no caption)"
        reply = llm.generate(
            chat_prompt(user_message, context, history, has_image=True),
            image_path=image_path,
        ) or "I couldn't process that image right now. Try again in a moment."
        telegram.send_message(chat_id, reply)
        history += [{"role": "user", "text": f"[photo] {user_message}"},
                    {"role": "coach", "text": reply}]
        save_history(chat_id, history)
        return

    logger.info("message from %s: %s", chat_id, text[:80])

    # --- store a permanent instruction ---
    note = parse_memory_note(text)
    if note is not None:
        append_note(note)
        telegram.send_message(chat_id, f"📝 Saved to your profile: {note}")
        return

    # --- show long-term memory ---
    if text.strip().lower() in PROFILE_TRIGGERS:
        profile = load_profile()
        telegram.send_message(chat_id, profile or
                              "Your profile is empty. Send 'remember: ...' to add something.")
        return

    # --- force a Garmin refresh ---
    if is_refresh_command(text):
        telegram.send_typing(chat_id)
        try:
            data = snapshot.get(force=True)
        except Exception as exc:
            logger.error("refresh failed: %s", exc)
            telegram.send_message(chat_id, "Couldn't reach Garmin right now, try again shortly.")
            return
        recent = data.get("recent_activities") or []
        overview = data.get("overview") or {}
        if recent:
            latest = recent[0]
            telegram.send_message(chat_id, (
                f"🔄 Garmin data refreshed.\n"
                f"Latest: {latest['sport']} {latest.get('name') or ''} · "
                f"load {latest['training_load']:.0f} · {latest['calories']} kcal\n"
                f"Week: acute load {overview.get('acute_load_weekly')} · "
                f"ACWR {overview.get('acwr')} {overview.get('acwr_emoji', '')}\n"
                f"Ask me anything."
            ))
        else:
            telegram.send_message(chat_id, "🔄 Garmin data refreshed.")
        return

    # --- normal conversation ---
    telegram.send_typing(chat_id)
    context = _safe_snapshot(snapshot, chat_id)
    history = load_history(chat_id)
    reply = llm.generate(chat_prompt(text, context, history)) \
        or "I can't reach the coaching model right now. Try again in a moment."
    telegram.send_message(chat_id, reply)
    history += [{"role": "user", "text": text}, {"role": "coach", "text": reply}]
    save_history(chat_id, history)


def _safe_snapshot(snapshot: GarminSnapshot, chat_id) -> dict:
    try:
        return snapshot.get()
    except Exception as exc:
        logger.error("Garmin snapshot failed: %s", exc)
        telegram.send_message(chat_id, "I can't read your Garmin data right now.")
        return {}


def main() -> None:
    logger.info("coach chat started at %s", datetime.now().isoformat(timespec="seconds"))
    snapshot = GarminSnapshot()
    offset = load_offset()
    while True:
        for update in telegram.get_updates(offset):
            offset = update["update_id"] + 1
            save_offset(offset)
            try:
                handle_update(update, snapshot)
            except Exception as exc:
                logger.exception("error handling update: %s", exc)


if __name__ == "__main__":
    main()
