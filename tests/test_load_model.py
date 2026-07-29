"""
Tests for the deterministic half of the coach.

Run with:  python -m pytest tests/ -q      (or plain `python tests/test_load_model.py`)

These matter: the LLM only phrases what load_model decides, so if the numbers
here are wrong, the coaching is wrong.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach.load_model import (_weight_trend, acwr_status, compute_metrics,  # noqa: E402
                              ewma_acwr, is_hard, sport_bucket)

NOW = datetime(2026, 6, 15, 12, 0, 0)


def activity(days_ago, load, sport="road_biking", calories=500,
             avg_hr=130, aerobic_te=3.0, anaerobic_te=0.0, label="AEROBIC_BASE",
             zones=None):
    """`zones` = seconds in HR zones (Z1..Z5). Defaults to a mostly-easy hour."""
    start = NOW - timedelta(days=days_ago)
    if zones is None:
        zones = (600, 2400, 600, 0, 0)     # 1h, 83% in zones 1-2
    a = {
        "activityId": f"a{days_ago}-{sport}",
        "activityName": "Test",
        "activityType": {"typeKey": sport},
        "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
        "duration": float(sum(zones)) or 3600.0,
        "distance": 20000.0,
        "calories": calories,
        "averageHR": avg_hr,
        "maxHR": avg_hr + 20,
        "activityTrainingLoad": load,
        "aerobicTrainingEffect": aerobic_te,
        "anaerobicTrainingEffect": anaerobic_te,
        "trainingEffectLabel": label,
    }
    for i, sec in enumerate(zones, start=1):
        a[f"hrTimeInZone_{i}"] = sec
    return a


def test_sport_bucket_maps_garmin_type_keys():
    assert sport_bucket("road_biking") == "bike"
    assert sport_bucket("lap_swimming") == "swim"
    assert sport_bucket("trail_running") == "run"
    assert sport_bucket("rowing") == "other"


def test_is_hard_uses_time_in_zone_not_labels():
    # real vigorous work (time in zones 4-5) -> hard
    assert is_hard(activity(1, 100, zones=(120, 300, 600, 900, 400)))
    # the real ride: labelled TEMPO but 72% in zones 1-2, 1% in zone 4 -> NOT hard
    assert not is_hard(activity(1, 122, label="TEMPO",
                                zones=(582, 3633, 1559, 64, 0)))
    # mostly recovery -> not hard
    assert not is_hard(activity(1, 40, zones=(1800, 600, 0, 0, 0)))
    # no HR-zone data -> fall back to the label
    assert is_hard(activity(1, 100, label="VO2MAX", zones=()))


def test_easy_share_is_time_in_zone_not_session_labels():
    # The exact bike from real use: TEMPO label, but 72% of time in zones 1-2.
    real_bike = activity(1, 122, sport="road_biking", label="TEMPO",
                         aerobic_te=4.5, zones=(582, 3633, 1559, 64, 0))
    m = compute_metrics([real_bike], [], now=NOW)
    assert m["easy_share"] == 0.72, m["easy_share"]  # (582+3633)/5838


def test_easy_share_sums_time_across_the_week():
    activities = [
        activity(1, 200, zones=(0, 600, 1800, 1200, 0)),      # hard-ish ride
        activity(3, 80, zones=(1200, 1800, 0, 0, 0)),         # easy
    ]
    m = compute_metrics(activities, [], now=NOW)
    # easy time (Z1+Z2) = 600 + 3000 = 3600; total = 3600 + 3000 = 6600
    assert m["easy_share"] == round(3600 / 6600, 2)


def test_acwr_status_bands():
    assert acwr_status(0.5)[0] == "undertraining"
    assert acwr_status(1.0)[0] == "optimal"
    assert acwr_status(1.4)[0] == "caution"
    assert acwr_status(2.0)[0] == "overload"
    assert acwr_status(None)[0] == "unknown"


def test_ewma_decays_on_rest_days():
    """The whole reason for EWMA over a rolling sum: rest lowers acute load."""
    activities = [activity(d, 100) for d in (10, 12, 14, 16, 18, 20)]
    activities.append(activity(5, 300))  # a big spike 5 days ago

    _, _, acwr_day_after = ewma_acwr(activities, NOW - timedelta(days=4))
    _, _, acwr_three_days_later = ewma_acwr(activities, NOW - timedelta(days=1))

    assert acwr_day_after > acwr_three_days_later, (
        "ACWR must fall during rest days, not stay flat"
    )


def test_steady_training_lands_in_the_optimal_band():
    activities = [activity(d, 100) for d in range(1, 40, 2)]
    _, _, acwr = ewma_acwr(activities, NOW)
    assert 0.8 <= acwr <= 1.3, f"steady load should be optimal, got {acwr}"


def test_metrics_sport_split_and_time():
    activities = [
        activity(1, 200, sport="road_biking", zones=(0, 900, 1800, 900, 0)),
        activity(3, 50, sport="lap_swimming", zones=(600, 1200, 0, 0, 0)),
        activity(5, 50, sport="running", zones=(600, 1200, 0, 0, 0)),
    ]
    metrics = compute_metrics(activities, [], now=NOW)

    assert metrics["sport_split_pct"]["bike"] == 67   # by load, unchanged
    # easy time = 900 + 1800 + 1800 = 4500; total = 3600 + 1800 + 1800 = 7200
    assert metrics["easy_share"] == round(4500 / 7200, 2)
    assert metrics["active_days_7d"] == 3
    assert metrics["calories_7d"] == 1500


def test_diet_alert_only_fires_when_training_is_good_and_weight_stalls():
    # steady easy load across the month -> training_ok
    activities = [activity(d, 60, label="AEROBIC_BASE") for d in range(1, 30)]
    # Needs >= 2 weigh-ins inside 28 days: a single reading is too noisy
    # (hydration, time of day) to accuse anyone's diet on.
    weighins = [
        {"calendarDate": (NOW - timedelta(days=30)).strftime("%Y-%m-%d"),
         "weight": 90000, "bodyFat": 20.0, "bmi": 26.0},
        {"calendarDate": (NOW - timedelta(days=10)).strftime("%Y-%m-%d"),
         "weight": 90300, "bodyFat": 20.0, "bmi": 26.1},
        {"calendarDate": (NOW - timedelta(days=1)).strftime("%Y-%m-%d"),
         "weight": 90500, "bodyFat": 20.1, "bmi": 26.1},  # went UP
    ]
    metrics = compute_metrics(activities, weighins, now=NOW)

    assert metrics["training_ok"] is True
    assert metrics["diet_alert"] is True, "weight up + training fine => nutrition is the lever"
    assert metrics["losing_too_fast"] is False


# Real weigh-in pattern that produced the bug: essentially flat around
# 96-97 kg, with one 98.0 kg outlier ~30 days back. (days-ago, kg)
_REAL_WEIGHINS = [
    (33, 96.4), (30, 98.0), (24, 96.7), (23, 96.6), (12, 97.2), (10, 97.0),
    (7, 96.9), (6, 97.0), (5, 97.1), (4, 96.2), (3, 96.3), (1, 95.7),
]


def _real_weighins():
    return [{"calendarDate": (NOW - timedelta(days=d)).strftime("%Y-%m-%d"),
             "weight": kg * 1000} for d, kg in _REAL_WEIGHINS]


def test_weight_trend_is_robust_to_a_single_outlier():
    # Weight is basically flat here; the 98.0 outlier must not make the trend
    # read as a big loss (the bug reported -1.7 kg on one day).
    t = _weight_trend(_real_weighins(), NOW)
    assert abs(t["delta_kg"]) < 1.5, (
        f"a single outlier weigh-in must not dominate the 30-day trend; "
        f"got delta {t['delta_kg']} kg"
    )


def test_weight_trend_has_no_day_to_day_whiplash():
    # A real trend may drift slowly (even cross zero); what it must NOT do is
    # jump around — the bug swung -1.7 -> +0.7 (a ~2.4 kg lurch) between days.
    weighins = _real_weighins()
    deltas = [_weight_trend(weighins, NOW - timedelta(days=b))["delta_kg"]
              for b in range(0, 6)]
    jumps = [abs(deltas[i] - deltas[i + 1]) for i in range(len(deltas) - 1)]
    assert max(jumps) < 1.0, (
        f"day-to-day trend change should be small; got deltas {deltas}"
    )


def test_losing_too_fast_flags_rapid_drop():
    activities = [activity(d, 60) for d in range(1, 30)]
    weighins = [
        {"calendarDate": (NOW - timedelta(days=28)).strftime("%Y-%m-%d"), "weight": 90000},
        {"calendarDate": (NOW - timedelta(days=1)).strftime("%Y-%m-%d"), "weight": 84000},
    ]
    metrics = compute_metrics(activities, weighins, now=NOW)
    assert metrics["losing_too_fast"] is True


def test_no_data_is_handled_gracefully():
    metrics = compute_metrics([], [], now=NOW)
    assert metrics["acwr"] is None
    assert metrics["weight"] is None
    assert metrics["sport_split_pct"] == {}


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL  {name}: {exc}")
    print(f"\n{'all tests passed' if not failures else f'{failures} failing'}")
    sys.exit(1 if failures else 0)
