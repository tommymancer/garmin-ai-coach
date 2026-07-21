"""
Cross-sport training load model + weight-loss lens.

Pure functions: raw Garmin activities in, computed metrics out. No I/O, no LLM.
This is the deterministic half of the coach — the LLM only phrases what this
module decides, so the numbers are always reproducible.

Key idea: Garmin's own `activityTrainingLoad` is an EPOC-based figure that is
already comparable ACROSS sports. That's what makes a unified bike/run/swim
load possible without inventing a scoring system.
"""

from datetime import datetime, timedelta

# --- Tunable thresholds ----------------------------------------------------
ACWR_LOW = 0.8            # below this: undertraining
ACWR_OK_HIGH = 1.3        # 0.8-1.3 is the sweet spot
ACWR_WARN_HIGH = 1.5      # 1.3-1.5 caution; above: overload risk
EASY_TARGET = 0.80        # share of load that should be easy (~80/20 rule)
ACTIVE_DAYS_TARGET = 4    # minimum active days per week for consistency
WEIGHT_RATE_FAST = -1.2   # %/week below which weight loss is too fast
WEIGHT_RATE_FLAT = -0.1   # %/week above which weight is "stalled"

ACUTE_DAYS = 7            # EWMA time constant for acute load
CHRONIC_DAYS = 28         # EWMA time constant for chronic load
MAX_HISTORY_DAYS = 56     # warm-up window for the EWMA

# --- Sport mapping ---------------------------------------------------------
BIKE = {"road_biking", "cycling", "gravel_cycling", "mountain_biking",
        "virtual_ride", "indoor_cycling", "cyclocross", "track_cycling",
        "bmx", "e_bike_fitness", "e_bike_mountain"}
RUN = {"running", "treadmill_running", "trail_running", "track_running",
       "virtual_run", "indoor_running", "obstacle_run"}
SWIM = {"lap_swimming", "open_water_swimming", "swimming"}

HARD_LABELS = {"TEMPO", "THRESHOLD", "LACTATE_THRESHOLD", "VO2MAX",
               "ANAEROBIC_CAPACITY", "ANAEROBIC", "OVERREACHING"}


def sport_bucket(type_key: str) -> str:
    if type_key in BIKE:
        return "bike"
    if type_key in RUN:
        return "run"
    if type_key in SWIM:
        return "swim"
    return "other"


def _num(value, default=0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def parse_start(activity: dict):
    raw = activity.get("startTimeLocal")
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def is_hard(activity: dict) -> bool:
    """Classify a session as hard (quality) vs easy (aerobic/recovery)."""
    label = (activity.get("trainingEffectLabel") or "").upper()
    return (
        label in HARD_LABELS
        or _num(activity.get("anaerobicTrainingEffect")) >= 1.5
        or _num(activity.get("aerobicTrainingEffect")) >= 4.0
    )


def summarize_activity(activity: dict) -> dict:
    """Readable summary of a single activity."""
    type_key = (activity.get("activityType") or {}).get("typeKey", "")
    return {
        "sport": sport_bucket(type_key),
        "type_key": type_key,
        "name": activity.get("activityName"),
        "date": (parse_start(activity) or datetime.min).strftime("%Y-%m-%d"),
        "duration_min": round(_num(activity.get("duration")) / 60),
        "distance_km": round(_num(activity.get("distance")) / 1000, 1),
        "calories": round(_num(activity.get("calories"))),
        "avg_hr": round(_num(activity.get("averageHR"))) or None,
        "max_hr": round(_num(activity.get("maxHR"))) or None,
        "training_load": round(_num(activity.get("activityTrainingLoad")), 1),
        "aerobic_te": round(_num(activity.get("aerobicTrainingEffect")), 1),
        "anaerobic_te": round(_num(activity.get("anaerobicTrainingEffect")), 1),
        "te_label": activity.get("trainingEffectLabel"),
        "is_hard": is_hard(activity),
    }


def ewma_acwr(activities, now, acute_days=ACUTE_DAYS,
              chronic_days=CHRONIC_DAYS, max_window=MAX_HISTORY_DAYS):
    """
    Acute:Chronic Workload Ratio using exponentially weighted moving averages
    (Williams et al. 2017), rather than a rolling sum.

    Why EWMA: a rolling sum stays flat until an activity falls out of the
    7-day window, then drops off a cliff. An EWMA decays a little every rest
    day, which matches how fatigue actually dissipates.

    Returns (acute_daily, chronic_daily, acwr).
    """
    dated = []
    for activity in activities:
        start = parse_start(activity)
        if start:
            dated.append((start.date(), _num(activity.get("activityTrainingLoad"))))
    if not dated:
        return None, None, None

    earliest = min(day for day, _ in dated)
    start_day = max(earliest, (now - timedelta(days=max_window)).date())

    daily = {}
    for day, load in dated:
        if day >= start_day:
            daily[day] = daily.get(day, 0.0) + load

    span = (now.date() - start_day).days + 1
    series = [daily.get(start_day + timedelta(days=i), 0.0) for i in range(span)]

    acute_lambda = 2.0 / (acute_days + 1)
    chronic_lambda = 2.0 / (chronic_days + 1)
    seed = sum(series) / len(series)          # warm start avoids a bogus early ACWR
    acute = chronic = seed
    for load in series:
        acute = load * acute_lambda + acute * (1 - acute_lambda)
        chronic = load * chronic_lambda + chronic * (1 - chronic_lambda)

    acwr = round(acute / chronic, 2) if chronic > 0 else None
    return acute, chronic, acwr


def acwr_status(acwr):
    if acwr is None:
        return "unknown", "⚪"
    if acwr < ACWR_LOW:
        return "undertraining", "⚪"
    if acwr <= ACWR_OK_HIGH:
        return "optimal", "🟢"
    if acwr <= ACWR_WARN_HIGH:
        return "caution", "🟡"
    return "overload", "🔴"


def _sport_split(activities):
    by_sport, total = {}, 0.0
    for activity in activities:
        load = _num(activity.get("activityTrainingLoad"))
        bucket = sport_bucket((activity.get("activityType") or {}).get("typeKey", ""))
        by_sport[bucket] = by_sport.get(bucket, 0.0) + load
        total += load
    if total <= 0:
        return {}
    return {k: round(v / total * 100) for k, v in by_sport.items()}


def _weight_trend(weighins, now):
    """weighins: Garmin dateWeightList entries (weight in grams)."""
    points = []
    for entry in weighins or []:
        date_raw, weight_g = entry.get("calendarDate"), entry.get("weight")
        if not date_raw or weight_g is None:
            continue
        try:
            day = datetime.strptime(date_raw[:10], "%Y-%m-%d")
        except ValueError:
            continue
        points.append((day, float(weight_g) / 1000.0, entry.get("bodyFat"), entry.get("bmi")))
    points.sort(key=lambda p: p[0])
    if not points:
        return None

    latest_day, latest_kg, latest_fat, latest_bmi = points[-1]
    target = now - timedelta(days=30)
    reference = None
    for point in points[:-1]:
        age = (now - point[0]).days
        if 18 <= age <= 45:
            if reference is None or abs((point[0] - target).days) < abs((reference[0] - target).days):
                reference = point

    trend = {
        "latest_kg": round(latest_kg, 1),
        "latest_body_fat_pct": round(latest_fat, 1) if latest_fat is not None else None,
        "latest_bmi": round(latest_bmi, 1) if latest_bmi is not None else None,
        "weighins_last_28d": sum(1 for p in points if (now - p[0]).days <= 28),
        "delta_kg": None,
        "rate_pct_per_week": None,
        "reference_days_ago": None,
    }
    if reference:
        span_days = max((latest_day - reference[0]).days, 1)
        delta = latest_kg - reference[1]
        trend["delta_kg"] = round(delta, 1)
        trend["reference_days_ago"] = span_days
        trend["rate_pct_per_week"] = round((delta / reference[1]) / span_days * 7 * 100, 2)
    return trend


def compute_metrics(activities, weighins, now=None) -> dict:
    """The full picture: cross-sport load, intensity balance, weight lens."""
    now = now or datetime.now()
    dated = [(parse_start(a), a) for a in activities]
    dated = [(dt, a) for dt, a in dated if dt is not None]

    def window(days):
        cutoff = now - timedelta(days=days)
        return [a for dt, a in dated if dt >= cutoff]

    last_7d, last_28d = window(7), window(28)

    # raw 7-day sum: used for composition (split, easy share), not for ACWR
    load_7d = sum(_num(a.get("activityTrainingLoad")) for a in last_7d)

    acute_daily, chronic_daily, acwr = ewma_acwr(activities, now)
    status_text, status_emoji = acwr_status(acwr)
    acute_weekly = round(acute_daily * 7) if acute_daily is not None else round(load_7d)
    chronic_weekly = round(chronic_daily * 7) if chronic_daily is not None else 0

    easy_load = sum(_num(a.get("activityTrainingLoad")) for a in last_7d if not is_hard(a))
    easy_share = round(easy_load / load_7d, 2) if load_7d > 0 else None

    # Estimate the top of zone 2 from the athlete's own easy sessions
    easy_hrs = sorted(
        _num(a.get("averageHR")) for a in last_28d
        if not is_hard(a) and _num(a.get("averageHR")) > 0
    )
    zone2_hr_ceiling = (
        round(easy_hrs[min(len(easy_hrs) - 1, int(0.75 * len(easy_hrs)))])
        if easy_hrs else None
    )

    active_days_7d = len({parse_start(a).date() for a in last_7d if parse_start(a)})
    calories_7d = round(sum(_num(a.get("calories")) for a in last_7d))
    calories_prev_7d = round(sum(
        _num(a.get("calories")) for dt, a in dated
        if now - timedelta(days=14) <= dt < now - timedelta(days=7)
    ))

    weight = _weight_trend(weighins, now)

    training_ok = (
        active_days_7d >= ACTIVE_DAYS_TARGET
        and (acwr is None or ACWR_LOW <= acwr <= ACWR_WARN_HIGH)
        and (easy_share is None or easy_share >= 0.5)
        and calories_7d > 0
    )
    diet_alert = False
    losing_too_fast = False
    if weight and weight["rate_pct_per_week"] is not None and weight["weighins_last_28d"] >= 2:
        rate = weight["rate_pct_per_week"]
        if training_ok and rate >= WEIGHT_RATE_FLAT:
            diet_alert = True
        if rate < WEIGHT_RATE_FAST:
            losing_too_fast = True

    return {
        "acute_load_weekly": acute_weekly,
        "chronic_load_weekly": chronic_weekly,
        "acwr": acwr,
        "acwr_status": status_text,
        "acwr_emoji": status_emoji,
        "sport_split_pct": _sport_split(last_7d),
        "easy_share": easy_share,
        "easy_share_target": EASY_TARGET,
        "zone2_hr_ceiling": zone2_hr_ceiling,
        "active_days_7d": active_days_7d,
        "active_days_target": ACTIVE_DAYS_TARGET,
        "calories_7d": calories_7d,
        "calories_prev_7d": calories_prev_7d,
        "sessions_7d": len(last_7d),
        "weight": weight,
        "training_ok": training_ok,
        "diet_alert": diet_alert,
        "losing_too_fast": losing_too_fast,
    }
