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

from coach.load_model import (acwr_status, compute_metrics, ewma_acwr,  # noqa: E402
                              is_hard, sport_bucket)

NOW = datetime(2026, 6, 15, 12, 0, 0)


def activity(days_ago, load, sport="road_biking", calories=500,
             avg_hr=130, aerobic_te=3.0, anaerobic_te=0.0, label="AEROBIC_BASE"):
    start = NOW - timedelta(days=days_ago)
    return {
        "activityId": f"a{days_ago}-{sport}",
        "activityName": "Test",
        "activityType": {"typeKey": sport},
        "startTimeLocal": start.strftime("%Y-%m-%d %H:%M:%S"),
        "duration": 3600.0,
        "distance": 20000.0,
        "calories": calories,
        "averageHR": avg_hr,
        "maxHR": avg_hr + 20,
        "activityTrainingLoad": load,
        "aerobicTrainingEffect": aerobic_te,
        "anaerobicTrainingEffect": anaerobic_te,
        "trainingEffectLabel": label,
    }


def test_sport_bucket_maps_garmin_type_keys():
    assert sport_bucket("road_biking") == "bike"
    assert sport_bucket("lap_swimming") == "swim"
    assert sport_bucket("trail_running") == "run"
    assert sport_bucket("rowing") == "other"


def test_is_hard_detects_intensity_three_ways():
    assert is_hard(activity(1, 100, label="VO2MAX"))
    assert is_hard(activity(1, 100, label="AEROBIC_BASE", anaerobic_te=2.0))
    assert is_hard(activity(1, 100, label="AEROBIC_BASE", aerobic_te=4.5))
    assert not is_hard(activity(1, 100, label="RECOVERY"))


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


def test_metrics_sport_split_and_easy_share():
    activities = [
        activity(1, 200, sport="road_biking", label="TEMPO", aerobic_te=4.2),  # hard
        activity(3, 50, sport="lap_swimming", label="RECOVERY", aerobic_te=2.0),
        activity(5, 50, sport="running", label="AEROBIC_BASE", aerobic_te=3.0),
    ]
    metrics = compute_metrics(activities, [], now=NOW)

    assert metrics["sport_split_pct"]["bike"] == 67
    assert metrics["easy_share"] == 0.33      # 100 easy of 300 total
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
