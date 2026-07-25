"""
Configuration, loaded from environment variables (or a .env file).

Nothing secret is ever committed: copy .env.example to .env and fill it in.
"""

import os
from pathlib import Path

# --- optional .env loading (no hard dependency on python-dotenv) ------------
def _load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


REPO_ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(REPO_ROOT / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"Missing required setting: {name}\n"
            f"Copy .env.example to .env and fill it in (see README)."
        )
    return value


class Config:
    """Everything the coach needs to run. Reads env once, at import time."""

    # --- Garmin ---
    garmin_email = property(lambda self: _require("GARMIN_EMAIL"))
    garmin_password = property(lambda self: _require("GARMIN_PASSWORD"))

    # --- Telegram ---
    telegram_token = property(lambda self: _require("TELEGRAM_BOT_TOKEN"))

    @property
    def telegram_chat_ids(self) -> set[str]:
        """Allowlist. Only these chat IDs get replies."""
        raw = _require("TELEGRAM_CHAT_ID")
        return {c.strip() for c in raw.split(",") if c.strip()}

    # --- Anthropic ---
    @property
    def anthropic_api_key(self) -> str:
        return _require("ANTHROPIC_API_KEY")

    model = property(lambda self: os.environ.get("COACH_MODEL", "claude-sonnet-5"))
    effort = property(lambda self: os.environ.get("COACH_EFFORT", "medium"))
    language = property(lambda self: os.environ.get("COACH_LANGUAGE", "English"))

    # --- behaviour ---
    @property
    def data_dir(self) -> Path:
        d = Path(os.environ.get("COACH_DATA_DIR", str(Path.home() / ".garmin-ai-coach")))
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def snapshot_ttl(self) -> int:
        """Seconds to cache Garmin data in the chat daemon. Short on purpose:
        `get_activities` is a cheap read that does NOT re-login, so it isn't a
        rate-limit (429) risk — that comes from repeated logins. A long cache
        only makes the chat answer on stale data right after you upload a
        workout, which is exactly when you ask about it. Just coalesces bursts."""
        return int(os.environ.get("COACH_SNAPSHOT_TTL", "120"))

    @property
    def feedback_interval(self) -> int:
        """Seconds between activity checks when running the combined process."""
        return int(os.environ.get("COACH_FEEDBACK_INTERVAL", "900"))

    @property
    def history_turns(self) -> int:
        return int(os.environ.get("COACH_HISTORY_TURNS", "8"))

    # --- derived paths ---
    token_dir = property(lambda self: self.data_dir / "garmin_tokens")
    state_file = property(lambda self: self.data_dir / "state.json")
    offset_file = property(lambda self: self.data_dir / "chat_offset.json")
    profile_file = property(lambda self: self.data_dir / "coach_profile.md")
    plan_file = property(lambda self: self.data_dir / "coach_plan.md")
    images_dir = property(lambda self: self.data_dir / "images")

    def history_file(self, chat_id) -> Path:
        return self.data_dir / f"chat_history_{chat_id}.json"


config = Config()
