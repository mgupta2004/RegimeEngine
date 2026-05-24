"""Layer 3 — Orderflow: CVD velocity, Buy/Sell imbalance, CVD consistency.

Uses KiteTicker to accumulate Cumulative Volume Delta (CVD) over a 15-minute
rolling window. Designed to run as a background monitor during market hours
(10:15–13:00 for primary window).

Call get_orderflow() to get a point-in-time read for the signal engine.
Call start_monitoring() / stop_monitoring() to manage the ticker lifecycle.
"""
from __future__ import annotations
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta

import pytz
from kiteconnect import KiteTicker
from data.kite_client import get_kite, get_instruments

IST = pytz.timezone("Asia/Kolkata")

API_KEY      = os.environ.get("KITE_API_KEY", "")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")


def _resolve_nifty_futures_token() -> int:
    """Return instrument token for the nearest Nifty futures contract."""
    from datetime import date
    futures = [
        i for i in get_instruments("NFO")
        if i["name"] == "NIFTY"
        and i["instrument_type"] == "FUT"
        and i["expiry"] >= date.today()
    ]
    if not futures:
        raise RuntimeError("No active Nifty futures found in NFO instruments")
    futures.sort(key=lambda x: x["expiry"])
    token = futures[0]["instrument_token"]
    print(f"[Orderflow] Nifty futures token: {token}  ({futures[0]['tradingsymbol']})")
    return token


# ── Tick State ────────────────────────────────────────────────────────────────

class OrderflowState:
    def __init__(self, window_minutes: int = 15):
        self.window         = timedelta(minutes=window_minutes)
        self._ticks: deque  = deque()
        self._lock          = threading.Lock()
        self.spot           = 0.0
        self.poc            = 0.0
        self._last_price    = 0.0
        self._last_direction = 1

    def on_tick(self, tick: dict):
        ts    = datetime.now(IST)
        price = tick.get("last_price", 0)
        qty   = tick.get("last_quantity", 0)

        if price > self._last_price:
            direction = 1
        elif price < self._last_price:
            direction = -1
        else:
            direction = self._last_direction

        self._last_price     = price
        self._last_direction = direction

        with self._lock:
            self._ticks.append((ts, qty * direction, direction))
            self.spot = price
            cutoff = ts - self.window
            while self._ticks and self._ticks[0][0] < cutoff:
                self._ticks.popleft()

    def snapshot(self) -> dict:
        with self._lock:
            ticks = list(self._ticks)

        if not ticks:
            return {
                "cvd_velocity": 0, "cvd_surge": False,
                "buy_volume": 0, "sell_volume": 0,
                "imbalance_ratio": 1.0, "imbalance_3to1": False,
                "cvd_consistency": 0.0, "cvd_sustained": False,
                "spot": self.spot, "spot_vs_poc": "UNKNOWN",
                "score": 0.0,
            }

        cvd_velocity = sum(d for _, d, _ in ticks)
        buy_volume   = sum(d for _, d, direction in ticks if direction > 0)
        sell_volume  = abs(sum(d for _, d, direction in ticks if direction < 0))

        imbalance_ratio = (buy_volume / sell_volume) if sell_volume > 0 else float("inf")
        imbalance_3to1  = imbalance_ratio >= 3.0 or (1 / imbalance_ratio if imbalance_ratio else 0) >= 3.0

        dominant        = 1 if cvd_velocity >= 0 else -1
        consistent_cnt  = sum(1 for _, _, d in ticks if d == dominant)
        cvd_consistency = consistent_cnt / len(ticks)
        cvd_sustained   = cvd_consistency > 0.60
        cvd_surge       = abs(cvd_velocity) >= 30_000

        spot_vs_poc = "UNKNOWN"
        if self.poc:
            spot_vs_poc = "ABOVE" if self.spot > self.poc else "BELOW"

        score = 0.0
        if cvd_surge or imbalance_3to1:
            score += 1.0
        if cvd_sustained:
            score += 0.5
        if spot_vs_poc == "ABOVE":
            score += 0.5
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


_state   = OrderflowState(window_minutes=15)
_ticker: KiteTicker | None = None
_nifty_token: int | None   = None


def _start_ticker():
    global _ticker, _nifty_token
    _nifty_token = _resolve_nifty_futures_token()
    _ticker = KiteTicker(API_KEY, ACCESS_TOKEN)

    def on_ticks(ws, ticks):
        for tick in ticks:
            if tick["instrument_token"] == _nifty_token:
                _state.on_tick(tick)

    def on_connect(ws, response):
        ws.subscribe([_nifty_token])
        ws.set_mode(ws.MODE_FULL, [_nifty_token])

    def on_error(ws, code, reason):
        print(f"[KiteTicker] Error {code}: {reason}")

    _ticker.on_ticks   = on_ticks
    _ticker.on_connect = on_connect
    _ticker.on_error   = on_error
    _ticker.connect(threaded=True)


def start_monitoring(poc_level: float = 0.0):
    """Start background tick collection. Call once at 09:10 from morning_monitor."""
    _state.poc = poc_level
    _start_ticker()
    print("[Orderflow] Ticker started. Collecting ticks...")


def stop_monitoring():
    if _ticker:
        _ticker.close()
    print("[Orderflow] Ticker stopped.")


def get_orderflow(poc_level: float = 0.0) -> dict:
    """Point-in-time orderflow snapshot for signal_engine.

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
