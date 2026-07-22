#!/usr/bin/env python3
"""
Combined runner: activity feedback (on a loop) + the chat daemon, in ONE
process. This is the container entrypoint, so `docker compose up` gives you
both halves with a single command.

    python -m coach.run

Locally you can still run the two halves separately (coach.feedback on a
schedule, coach.chat always-on) if you prefer — see the README.
"""

import logging
import threading
import time

from . import chat, feedback
from .config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("coach.run")


def feedback_loop() -> None:
    """Check Garmin for new activities forever, on the configured interval."""
    interval = config.feedback_interval
    logger.info("feedback loop started (every %ds)", interval)
    while True:
        try:
            feedback.main()
        except Exception:
            logger.exception("feedback run failed; will retry next cycle")
        time.sleep(interval)


def main() -> None:
    logger.info("starting combined coach (feedback loop + chat daemon)")
    # Feedback runs in the background; chat owns the main thread and blocks.
    threading.Thread(target=feedback_loop, name="feedback", daemon=True).start()
    chat.main()


if __name__ == "__main__":
    main()
