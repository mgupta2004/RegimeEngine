"""Layer 1 — Swing Bias from NSE EOD bhavcopy.

Run this in the evening (after 18:00 IST) to compute the next-day directional lean.
Downloads NSE bhavcopy CSV, extracts Nifty 50 OHLC, applies swing signal logic.
If VIX >= 22, swing signal is bypassed in favour of OI-driven PCR/Max Pain logic
(resolved by kite_oi_live.py at runtime).
"""
import os
import io
import requests
import zipfile
from datetime import date, timedelta

import pandas as pd
from market_scanner import fetch_ohlcv, compute_ema, vix_regime


BHAVCOPY_URL = (
    "https://archives.nseindia.com/content/historical/EQUITIES/"
    "{year}/{month}/cm{dd}{MON}{year}bhav.csv.zip"
)

MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


def _last_trading_day() -> date:
    """Return most recent weekday (simple heuristic; does not account for holidays)."""
    d = date.today()
    # If run after market close on a trading day, use today; otherwise step back
    while d.weekday() >= 5:  # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def fetch_nifty_eod_kite(lookback_days: int = 32) -> pd.DataFrame:
    """Fetch Nifty 50 daily OHLCV from Kite (more reliable than bhavcopy scraping)."""
    df = fetch_ohlcv("NSE:NIFTY 50", "day", lookback_days)
    return df


def compute_swing_bias(df_daily: pd.DataFrame) -> dict:
    """
    Swing signal logic:
      - Close > 21 EMA AND close > prior-day high  → LONG (+1.0)
      - Close < 21 EMA AND close < prior-day low   → SHORT (+1.0)
      - Otherwise                                  → SKIP (0.0)
    """
    if len(df_daily) < 3:
        return {"bias": "SKIP", "score": 0.0, "reason": "insufficient data"}

    closes = df_daily["close"].tolist()
    ema_vals = compute_ema(closes, 21)

    last_close = closes[-1]
    last_ema   = ema_vals[-1]
    prev_high  = df_daily["high"].iloc[-2]
    prev_low   = df_daily["low"].iloc[-2]

    if last_close > last_ema and last_close > prev_high:
        return {
            "bias": "LONG",
            "score": 1.0,
            "reason": f"close {last_close} > EMA {last_ema:.2f} and prev high {prev_high}",
        }
    if last_close < last_ema and last_close < prev_low:
        return {
            "bias": "SHORT",
            "score": 1.0,
            "reason": f"close {last_close} < EMA {last_ema:.2f} and prev low {prev_low}",
        }
    return {
        "bias": "SKIP",
        "score": 0.0,
        "reason": f"close {last_close}, EMA {last_ema:.2f}, prev H/L {prev_high}/{prev_low}",
    }


def get_swing_bias() -> dict:
    """
    Entry point called by signal_engine.py.

    Returns:
        bias: LONG | SHORT | SKIP
        score: 0.0 | 1.0
        vix_mode: NORMAL | HIGH VOL
        vix_override: True if HIGH VIX bypassed swing signal
    """
    df_daily = fetch_nifty_eod_kite(32)
    if df_daily.empty:
        return {"bias": "SKIP", "score": 0.0, "vix_mode": "UNKNOWN", "vix_override": False}

    # Determine VIX mode
    df_vix = fetch_ohlcv("NSE:INDIA VIX", "day", 5)
    vix_close = df_vix["close"].iloc[-1] if not df_vix.empty else 0.0
    mode = vix_regime(vix_close)
    high_vix = mode == "HIGH VOL"

    if high_vix:
        # Swing signal bypassed; OI layer (kite_oi_live) drives directional lean
        return {
            "bias": "SKIP",
            "score": 0.0,
            "vix_mode": mode,
            "vix_close": round(vix_close, 2),
            "vix_override": True,
            "note": "HIGH VIX: bias determined by PCR/Max Pain in Layer 2",
        }

    swing = compute_swing_bias(df_daily)
    return {
        "bias": swing["bias"],
        "score": swing["score"],
        "vix_mode": mode,
        "vix_close": round(vix_close, 2),
        "vix_override": False,
        "reason": swing["reason"],
    }


if __name__ == "__main__":
    result = get_swing_bias()
    print(f"Bias      : {result['bias']}")
    print(f"Score     : {result['score']}")
    print(f"VIX Mode  : {result['vix_mode']} ({result.get('vix_close', 'N/A')})")
    if result.get("vix_override"):
        print(f"Note      : {result['note']}")
    else:
        print(f"Reason    : {result.get('reason', '')}")
