"""Tests for the shared snapshot the poller and chat use to stay in sync."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fresh_store(tmp_path, monkeypatch):
    """Point the store at a throwaway data dir and reload it."""
    monkeypatch.setenv("COACH_DATA_DIR", str(tmp_path))
    import importlib

    import coach.config as config_mod
    importlib.reload(config_mod)
    import coach.store as store_mod
    importlib.reload(store_mod)
    return store_mod


def test_snapshot_round_trips(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    activities = [{"activityId": "1", "activityTrainingLoad": 100}]
    weighins = [{"calendarDate": "2026-07-20", "weight": 96000}]
    store.write_snapshot(activities, weighins)
    got = store.read_snapshot(max_age_seconds=60)
    assert got == (activities, weighins)


def test_snapshot_expires(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.write_snapshot([{"activityId": "1"}], [])
    # asking for something fresher than it is returns nothing
    assert store.read_snapshot(max_age_seconds=-1) is None


def test_snapshot_missing_is_none(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    assert store.read_snapshot(max_age_seconds=60) is None


def test_poller_write_is_visible_to_a_second_reader(tmp_path, monkeypatch):
    # Simulates the real fix: the poller writes, the chat (a separate reader)
    # sees the same data immediately — no desync.
    store = _fresh_store(tmp_path, monkeypatch)
    poller_activities = [{"activityId": "42", "activityTrainingLoad": 207}]
    store.write_snapshot(poller_activities, [])
    seen_by_chat = store.read_snapshot(max_age_seconds=120)
    assert seen_by_chat is not None
    assert seen_by_chat[0] == poller_activities


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["python", "-m", "pytest", __file__, "-q"]))
