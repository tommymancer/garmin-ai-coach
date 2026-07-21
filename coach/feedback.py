#!/usr/bin/env python3
"""
Event-driven feedback: run this on a short interval (cron / launchd / systemd
timer). It is cheap and silent unless a NEW activity appeared on Garmin — only
then does it call Claude and message you.

    python -m coach.feedback
"""

import logging

from . import garmin, llm, telegram
from .config import config
from .load_model import compute_metrics, summarize_activity
from .prompts import feedback_prompt
from .store import load_state, save_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("coach.feedback")

SPORT_EMOJI = {"bike": "🚴", "run": "🏃", "swim": "🏊", "other": "🏋️"}


def fallback_message(activity: dict, metrics: dict) -> str:
    """Used when the API call fails, so you still get notified."""
    emoji = SPORT_EMOJI.get(activity["sport"], "🏋️")
    lines = [
        f"{emoji} {activity['sport'].capitalize()} {activity['duration_min']}min · "
        f"load {activity['training_load']:.0f}"
        + (f" ({activity['te_label']})" if activity.get("te_label") else "")
        + f" · {activity['calories']} kcal",
        f"📊 Week: acute load {metrics['acute_load_weekly']} · "
        f"ACWR {metrics['acwr']} {metrics['acwr_emoji']} ({metrics['acwr_status']}) · "
        + " / ".join(f"{k} {v}%" for k, v in metrics["sport_split_pct"].items()),
    ]
    weight = metrics.get("weight")
    if weight and weight.get("delta_kg") is not None:
        lines.append(
            f"⚖️ {weight['latest_kg']} kg ({weight['delta_kg']:+.1f} over "
            f"{weight['reference_days_ago']}d)"
            + (f" · body fat {weight['latest_body_fat_pct']}%"
               if weight.get("latest_body_fat_pct") else "")
        )
    if metrics["diet_alert"]:
        lines.append("💡 Training is on point but weight isn't moving — the lever is nutrition.")
    elif metrics["losing_too_fast"]:
        lines.append("💡 You're losing weight quickly — ease off to protect muscle.")
    elif metrics["acwr"] and metrics["acwr"] > 1.3:
        lines.append("💡 Load is high — keep the next sessions easy.")
    else:
        lines.append("💡 Keep the easy aerobic volume up; it's the engine of fat loss.")
    lines.append("🏋️ Next: " + _next_session(activity, metrics))
    return "\n".join(lines)


def _next_session(activity: dict, metrics: dict) -> str:
    ceiling = metrics.get("zone2_hr_ceiling")
    hr_note = f" HR<{ceiling}" if ceiling else ""
    rotation = {"bike": "swim", "swim": "run", "run": "bike"}
    other = rotation.get(activity["sport"], "run")
    acwr = metrics.get("acwr")
    if activity.get("is_hard") or (acwr and acwr > 1.3):
        return f"{other} 30-40min recovery, zone 1-2{hr_note}."
    if (acwr is not None and acwr < 0.8) or (
        metrics.get("easy_share") is not None
        and metrics["easy_share"] < metrics["easy_share_target"]
    ):
        return f"{other} 60min steady zone 2{hr_note} — aerobic volume burns fat sustainably."
    return f"{other} 45-60min zone 2{hr_note}; or one short quality session if you feel fresh."


def find_new_activities(activities, state):
    """Activities newer than the last processed one, oldest first."""
    last_start = state.get("last_start", "")
    seen = {str(i) for i in state.get("seen_ids", [])}
    fresh = [
        a for a in activities
        if str(a.get("activityId")) not in seen
        and not (last_start and (a.get("startTimeLocal") or "") <= last_start)
    ]
    fresh.sort(key=lambda a: a.get("startTimeLocal") or "")
    return fresh


def main() -> None:
    state = load_state()
    client = garmin.connect()
    activities = garmin.fetch_activities(client)
    if not activities:
        logger.info("no activities returned")
        return

    # First run: record a baseline so we don't blast messages for old workouts.
    if not state.get("initialized"):
        newest = max(activities, key=lambda a: a.get("startTimeLocal") or "")
        save_state({
            "initialized": True,
            "last_start": newest.get("startTimeLocal"),
            "seen_ids": [str(a.get("activityId")) for a in activities[:50]],
        })
        logger.info("baseline recorded — no notifications on first run")
        return

    fresh = find_new_activities(activities, state)
    if not fresh:
        logger.info("nothing new")
        return

    weighins = garmin.fetch_weighins(client)
    metrics = compute_metrics(activities, weighins)

    for activity in fresh:
        summary = summarize_activity(activity)
        message = llm.generate(feedback_prompt(summary, metrics)) \
            or fallback_message(summary, metrics)
        for chat_id in config.telegram_chat_ids:
            telegram.send_message(chat_id, message)
        logger.info("sent feedback for activity %s (%s)",
                    activity.get("activityId"), summary["sport"])

    newest = fresh[-1]
    seen = [str(a.get("activityId")) for a in fresh]
    seen += [str(i) for i in state.get("seen_ids", [])]
    save_state({
        "initialized": True,
        "last_start": newest.get("startTimeLocal"),
        "seen_ids": seen[:50],
    })


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("fatal error: %s", exc)
