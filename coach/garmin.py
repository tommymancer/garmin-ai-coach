"""
Garmin Connect access, with token caching.

Garmin rate-limits repeated logins (HTTP 429). Since the feedback poller runs
every ~15 minutes, we must NOT log in fresh each time: `login(tokenstore)`
resumes saved tokens and only falls back to a full login when they expire,
re-saving them automatically.
"""

import logging
from datetime import datetime, timedelta

from garminconnect import Garmin

from .config import config

logger = logging.getLogger("coach.garmin")


def connect() -> Garmin:
    """Return an authenticated Garmin client, reusing cached tokens."""
    token_dir = config.token_dir
    token_dir.mkdir(parents=True, exist_ok=True)
    had_tokens = any(token_dir.glob("*.json"))

    client = Garmin(config.garmin_email, config.garmin_password)
    client.login(str(token_dir))
    logger.info(
        "Garmin: %s",
        "resumed cached session" if had_tokens else f"fresh login, tokens saved to {token_dir}",
    )
    return client


def fetch_activities(client, limit=60):
    """Recent activities, newest first. 60 covers the EWMA warm-up window."""
    return client.get_activities(0, limit)


def fetch_weighins(client, days=45):
    """Body-composition entries; empty list if the user has no smart scale."""
    end = datetime.now().date()
    start = end - timedelta(days=days)
    try:
        data = client.get_body_composition(start.isoformat(), end.isoformat())
        return data.get("dateWeightList") or []
    except Exception as exc:  # scale data is optional — never fail the run
        logger.warning("weight data unavailable: %s", exc)
        return []
