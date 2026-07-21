"""
Persistent state: what we've already seen, the athlete profile, the plan,
and per-chat conversation history.

All of it lives in COACH_DATA_DIR as plain files you can read and edit.
"""

import json
import re
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
