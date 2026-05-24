"""OI snapshot history — fixes the fresh_build always-False bug.

save_snapshot() is called by signal_engine after each L2 fetch.
get_prior_snapshot() is called by signal_engine before the L2 fetch
to supply the previous OI figures for delta comparison.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta

import pytz

IST = pytz.timezone("Asia/Kolkata")
_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "oi_history.json")
_PRUNE_HOURS  = 24
_WINDOW_MIN   = 30   # snapshot must be at least this many minutes old
_WINDOW_MAX   = 90   # … and no older than this


def _load() -> list:
    if not os.path.exists(_HISTORY_FILE):
        return []
    try:
        with open(_HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _dump(records: list) -> None:
    os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
    with open(_HISTORY_FILE, "w") as f:
        json.dump(records, f, indent=2)


def save_snapshot(call_wall_oi: float, put_wall_oi: float) -> None:
    """Append a timestamped OI snapshot and prune records older than 24 hours."""
    records = _load()
    records.append({
        "timestamp":    datetime.now(IST).isoformat(),
        "call_wall_oi": call_wall_oi,
        "put_wall_oi":  put_wall_oi,
    })
    cutoff = (datetime.now(IST) - timedelta(hours=_PRUNE_HOURS)).isoformat()
    records = [r for r in records if r["timestamp"] >= cutoff]
    _dump(records)


def get_prior_snapshot(minutes_ago: int = 45) -> dict | None:
    """Return the snapshot closest to `minutes_ago` minutes in the past.

    Returns None if no snapshot falls within the [WINDOW_MIN, WINDOW_MAX] range.
    """
    records = _load()
    if not records:
        return None

    now = datetime.now(IST)
    target = now - timedelta(minutes=minutes_ago)
    lo = now - timedelta(minutes=_WINDOW_MAX)
    hi = now - timedelta(minutes=_WINDOW_MIN)

    candidates = [
        r for r in records
        if lo.isoformat() <= r["timestamp"] <= hi.isoformat()
    ]
    if not candidates:
        return None

    # Pick the candidate closest to target
    return min(
        candidates,
        key=lambda r: abs(
            (datetime.fromisoformat(r["timestamp"]) - target).total_seconds()
        ),
    )


if __name__ == "__main__":
    import time
    print("Saving snapshot 1...")
    save_snapshot(call_wall_oi=12_000_000, put_wall_oi=9_500_000)
    print("Waiting 65 seconds for window test...")
    time.sleep(65)
    save_snapshot(call_wall_oi=12_100_000, put_wall_oi=9_400_000)
    result = get_prior_snapshot(minutes_ago=1)
    print(f"Prior snapshot (1 min ago): {result}")
