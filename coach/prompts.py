"""
Prompt construction.

Everything numeric is already decided by load_model.py — these prompts tell
Claude to phrase those numbers, never to invent or recompute them.
"""

import json

from .config import config
from .store import load_profile, plan_with_week

COACH_PERSONA = (
    "You are a personal endurance coach. Your athlete's primary goal is LOSING WEIGHT "
    "while varying between cycling, swimming and running. You track cross-sport training "
    "load (Garmin's EPOC-based activityTrainingLoad, ACWR, easy/hard balance).\n"
    "Be direct, concrete and encouraging but HONEST. Use ONLY the numbers provided — "
    "never invent data. If the training numbers look good but weight isn't dropping, "
    "say plainly that the bottleneck is nutrition (calorie deficit), not training. "
    "When you prescribe a workout be specific: sport, duration, and intensity "
    "(zone plus an indicative heart rate, using zone2_hr_ceiling as the easy ceiling)."
)


def _context_block() -> str:
    profile = load_profile()
    plan, week = plan_with_week()
    week_note = f" — today is WEEK {week} of the block" if week else ""
    return (
        f"STANDING INSTRUCTIONS FROM THE ATHLETE (always respect these):\n"
        f"{profile or '(none yet)'}\n\n"
        f"TRAINING PLAN IN PROGRESS{week_note}:\n"
        f"{plan or '(no plan set)'}\n"
    )


def feedback_prompt(activity: dict, metrics: dict) -> str:
    """One short Telegram message reacting to a just-uploaded activity."""
    briefing = {"activity_just_uploaded": activity, "week_overview": metrics}
    return f"""{COACH_PERSONA}

Reply in {config.language}.

{_context_block()}
The athlete just uploaded an activity to Garmin. Write ONE short Telegram
message (max 6 lines) in exactly this shape:

Line 1: sport emoji + short name + duration + training load + calories
Line 2: 📊 Week: acute load + ACWR (with its emoji and verdict) + sport split %
Line 3: ⚖️ current weight + change vs ~30 days + body fat % (SKIP this line entirely if no weight data)
Line 4: 💡 one sentence reading the situation (weight-loss progress + load)
Line 5: 🏋️ Next session: 1-2 CONCRETE options, each with SPORT + DURATION + INTENSITY.

Rules for the next-session suggestion:
- If ACWR is above 1.3, or the session just done was hard, suggest ONLY easy or
  recovery work. No intensity.
- If ACWR is below 0.8, or easy_share is under target, add easy aerobic volume.
- If ACWR is optimal and easy_share is healthy, ONE quality session is fine —
  keep the overall balance near 80/20.
- Rotate the sport away from the one just done and away from the dominant sport
  in the split.
- Compare what they did against the plan for today and the week's load target.
  If they skipped or shortened a session, say how to make it up without spiking ACWR.

Coaching rules:
- If "diet_alert" is true: say clearly that training is fine but weight isn't
  moving, so the bottleneck is nutrition. No empty praise.
- If "losing_too_fast" is true: warn that the rate risks muscle loss.
- If easy_share is below its target: push more easy zone-2 volume.
- If active_days_7d is below active_days_target: push consistency.

Respond with the message text ONLY — no preamble, no quotes, no explanation.

DATA:
{json.dumps(briefing, ensure_ascii=False, indent=2, default=str)}"""


def chat_prompt(user_message: str, context: dict, history: list,
                has_image: bool = False) -> str:
    """Conversational reply, optionally about an attached photo."""
    conversation = "\n".join(
        f"{'Athlete' if turn['role'] == 'user' else 'Coach'}: {turn['text']}"
        for turn in history
    )
    image_note = ""
    if has_image:
        image_note = (
            "The athlete attached a PHOTO (above). Interpret it as a coach:\n"
            "- If it is FOOD: estimate calories and macros (say clearly it is an "
            "estimate) and relate it to their calorie deficit and weight goal.\n"
            "- If it is a Garmin/app SCREENSHOT: read the numbers and comment on "
            "them against the plan and current load.\n"
            "- Otherwise: describe it briefly and comment as a coach.\n\n"
        )

    return f"""{COACH_PERSONA}

Reply in {config.language}. Keep it short enough for a chat message
(max ~8 lines) and avoid heavy markdown.

{_context_block()}
CURRENT GARMIN DATA (JSON):
{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

RECENT CONVERSATION:
{conversation or '(none)'}

{image_note}NEW MESSAGE FROM THE ATHLETE:
{user_message}

Respond with the coach's message text ONLY — no preamble."""
