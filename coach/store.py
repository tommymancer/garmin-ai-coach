"""
Persistent state: what we've already seen, the athlete profile, the plan,
and per-chat conversation history.

All of it lives in COACH_DATA_DIR as plain files you can read and edit.
"""

import json
import os
import re
import time
from datetime import datetime

from .config import config


# --- processed-activity state ---------------------------------------------
def load_state() -> dict:
    try:
        return json.loads(config.state_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    config.state_file.write_text(json.dumps(state, indent=2, default=str))


# --- shared Garmin snapshot ------------------------------------------------
# The feedback poller and the chat daemon are separate processes. The poller
# fetches Garmin every run (to detect new activities) and writes the raw result
# here; the chat reads it. So right after a feedback fires, the chat reflects
# exactly the same data — no "ACWR 1.5 in the message, 1.19 in chat" desync —
# and the chat rarely has to hit Garmin itself.
def _snapshot_path():
    return config.data_dir / "snapshot.json"


def write_snapshot(activities: list, weighins: list) -> None:
    payload = {"fetched_at": time.time(), "activities": activities, "weighins": weighins}
    path = _snapshot_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, default=str))
    os.replace(tmp, path)          # atomic: readers never see a half-written file


def read_snapshot(max_age_seconds: float):
    """Return (activities, weighins) if a snapshot exists and is fresh enough,
    else None so the caller fetches its own."""
    try:
        data = json.loads(_snapshot_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if time.time() - data.get("fetched_at", 0) > max_age_seconds:
        return None
    return data.get("activities"), data.get("weighins")


# --- chat polling offset ---------------------------------------------------
def load_offset() -> int:
    try:
        return json.loads(config.offset_file.read_text()).get("offset", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def save_offset(offset: int) -> None:
    config.offset_file.write_text(json.dumps({"offset": offset}))


# --- conversation history (short-term memory) ------------------------------
def load_history(chat_id) -> list:
    try:
        return json.loads(config.history_file(chat_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(chat_id, history: list) -> None:
    trimmed = history[-config.history_turns * 2:]
    config.history_file(chat_id).write_text(
        json.dumps(trimmed, ensure_ascii=False, indent=2)
    )


# --- athlete profile (long-term memory) ------------------------------------
PROFILE_HEADER = (
    "# Coach profile\n\n"
    "Standing instructions, always in effect:\n\n"
)


def load_profile() -> str:
    try:
        return config.profile_file.read_text().strip()
    except FileNotFoundError:
        return ""


def append_note(note: str) -> None:
    """Add a permanent instruction, e.g. from a `remember: ...` message."""
    path = config.profile_file
    if not path.exists():
        path.write_text(PROFILE_HEADER)
    with path.open("a") as handle:
        handle.write(f"- {note}\n")


# --- training plan ---------------------------------------------------------
def load_plan() -> str:
    try:
        return config.plan_file.read_text().strip()
    except FileNotFoundError:
        return ""


def plan_with_week(now=None):
    """
    Return (plan_text, current_week_of_block).

    The plan is a repeating block; the current week is derived from a
    `block_start: YYYY-MM-DD` line and a `block_weeks: N` line in the file.
    """
    plan = load_plan()
    if not plan:
        return "", None

    start_match = re.search(r"block_start:\s*(\d{4}-\d{2}-\d{2})", plan)
    if not start_match:
        return plan, None
    weeks_match = re.search(r"block_weeks:\s*(\d+)", plan)
    block_weeks = int(weeks_match.group(1)) if weeks_match else 4

    start = datetime.strptime(start_match.group(1), "%Y-%m-%d").date()
    today = (now or datetime.now()).date()
    elapsed = (today - start).days // 7
    if elapsed < 0:
        return plan, 1
    return plan, (elapsed % block_weeks) + 1
