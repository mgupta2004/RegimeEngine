"""Layer 3 — Orderflow: CVD velocity, Buy/Sell imbalance, CVD consistency.

Uses KiteTicker to accumulate Cumulative Volume Delta (CVD) over a 15-minute
rolling window. Designed to run as a background monitor during market hours
(10:15–13:00 for primary window).

Call snapshot() to get a point-in-time read for the signal engine.
Call monitor(duration_seconds) to stream ticks for a fixed period.
"""
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta

import pytz
from kiteconnect import KiteConnect, KiteTicker
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY      = os.environ.get("KITE_API_KEY", "")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

IST = pytz.timezone("Asia/Kolkata")
NIFTY_TOKEN = 256265  # static, never changes

# ── Tick State ────────────────────────────────────────────────────────────────
class OrderflowState:
    def __init__(self, window_minutes: int = 15):
        self.window = timedelta(minutes=window_minutes)
        # Each entry: (timestamp, delta_volume, direction)
        # direction: +1 = buy tick, -1 = sell tick
        self._ticks: deque = deque()
        self._lock = threading.Lock()
        self.spot = 0.0
        self.poc  = 0.0   # Point of Control (price level with most volume today)

    def on_tick(self, tick: dict):
        ts = datetime.now(IST)
        price = tick.get("last_price", 0)
        qty   = tick.get("last_quantity", 0)
        # Kite tick: buy_quantity > sell_quantity → aggressive buy
        buy_qty  = tick.get("buy_quantity", 0)
        sell_qty = tick.get("sell_quantity", 0)
        direction = 1 if buy_qty >= sell_qty else -1

        with self._lock:
            self._ticks.append((ts, qty * direction, direction))
            self.spot = price
            # Prune ticks outside the rolling window
            cutoff = ts - self.window
            while self._ticks and self._ticks[0][0] < cutoff:
                self._ticks.popleft()

    def snapshot(self) -> dict:
        with self._lock:
            ticks = list(self._ticks)

        if not ticks:
            return {
                "cvd_velocity": 0,
                "cvd_surge": False,
                "buy_volume": 0,
                "sell_volume": 0,
                "imbalance_ratio": 1.0,
                "imbalance_3to1": False,
                "cvd_consistency": 0.0,
                "cvd_sustained": False,
                "spot": self.spot,
                "spot_vs_poc": "UNKNOWN",
                "score": 0.0,
            }

        cvd_velocity = sum(d for _, d, _ in ticks)
        buy_volume   = sum(d for _, d, direction in ticks if direction > 0)
        sell_volume  = abs(sum(d for _, d, direction in ticks if direction < 0))

        imbalance_ratio = (buy_volume / sell_volume) if sell_volume > 0 else float("inf")
        imbalance_3to1  = imbalance_ratio >= 3.0 or (1 / imbalance_ratio) >= 3.0

        dominant = 1 if cvd_velocity >= 0 else -1
        consistent_count = sum(1 for _, _, direction in ticks if direction == dominant)
        cvd_consistency = consistent_count / len(ticks) if ticks else 0.0
        cvd_sustained = cvd_consistency > 0.60

        cvd_surge = abs(cvd_velocity) >= 30_000

        spot_vs_poc = "UNKNOWN"
        if self.poc:
            spot_vs_poc = "ABOVE" if self.spot > self.poc else "BELOW"

        # Score
        score = 0.0
        if cvd_surge:
            score += 1.0
        elif imbalance_3to1:
            score += 1.0
        if cvd_sustained:
            score += 0.5
        if spot_vs_poc == "ABOVE":
            score += 0.5
        # Cap score per spec max of 1.0 for Layer 3 trigger
        score = min(score, 1.0)

        return {
            "cvd_velocity":    round(cvd_velocity),
            "cvd_surge":       cvd_surge,
            "buy_volume":      round(buy_volume),
            "sell_volume":     round(sell_volume),
            "imbalance_ratio": round(imbalance_ratio, 2),
            "imbalance_3to1":  imbalance_3to1,
            "cvd_consistency": round(cvd_consistency, 3),
            "cvd_sustained":   cvd_sustained,
            "spot":            round(self.spot, 2),
            "spot_vs_poc":     spot_vs_poc,
            "score":           round(score, 2),
        }


# Singleton state shared between ticker callbacks and signal engine
_state = OrderflowState(window_minutes=15)
_ticker: KiteTicker | None = None


def _start_ticker():
    global _ticker
    _ticker = KiteTicker(API_KEY, ACCESS_TOKEN)

    def on_ticks(ws, ticks):
        for tick in ticks:
            if tick["instrument_token"] == NIFTY_TOKEN:
                _state.on_tick(tick)

    def on_connect(ws, response):
        ws.subscribe([NIFTY_TOKEN])
        ws.set_mode(ws.MODE_FULL, [NIFTY_TOKEN])

    def on_error(ws, code, reason):
        print(f"[KiteTicker] Error {code}: {reason}")

    _ticker.on_ticks   = on_ticks
    _ticker.on_connect = on_connect
    _ticker.on_error   = on_error
    _ticker.connect(threaded=True)


def start_monitoring(poc_level: float = 0.0):
    """Start background tick collection. Call once before market opens."""
    _state.poc = poc_level
    _start_ticker()
    print("[Orderflow] Ticker started. Collecting ticks...")


def stop_monitoring():
    if _ticker:
        _ticker.close()
    print("[Orderflow] Ticker stopped.")


def get_orderflow(poc_level: float = 0.0) -> dict:
    """
    Point-in-time orderflow snapshot for signal_engine.py.
    If ticker is not running, starts a 60-second warm-up collection.
    """
    global _ticker
    _state.poc = poc_level

    if _ticker is None:
        print("[Orderflow] Starting 60s tick warm-up...")
        _start_ticker()
        time.sleep(60)

    return _state.snapshot()


if __name__ == "__main__":
    import sys
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(f"Collecting orderflow for {duration}s...")
    start_monitoring()
    time.sleep(duration)
    snap = _state.snapshot()
    for k, v in snap.items():
        print(f"  {k:<22}: {v}")
    stop_monitoring()
