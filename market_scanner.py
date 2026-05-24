"""Nifty Market Scanner — entry point for the nifty-market-scanner skill.

All data utilities (fetch_ohlcv, compute_ema, classify_ib, vix_regime, etc.)
now live in data/kite_client.py. This file contains only the display logic
and the run_scanner() orchestrator.
"""
from datetime import datetime

import pytz
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from data.kite_client import (
    get_kite, get_active_future,
    fetch_ohlcv, compute_ema, price_vs_ema, ema_slope,
    vix_regime, classify_ib,
)

IST = pytz.timezone("Asia/Kolkata")

# Compatibility: some callers reference `kite` directly
kite = get_kite()


# ── Main Scanner ──────────────────────────────────────────────────────────────

def run_scanner() -> dict:
    crude_symbol  = get_active_future("MCX", "CRUDEOIL")
    usdinr_symbol = get_active_future("NSE", "USDINR")

    instruments = {
        "Nifty 50":  "NSE:NIFTY 50",
        "India VIX": "NSE:INDIA VIX",
        "Crude Oil": crude_symbol,
        "USD/INR":   usdinr_symbol,
    }

    results: dict = {}
    for name, symbol in instruments.items():
        results[name] = {}
        for tf, interval, n_candles in [("intraday", "15minute", 26), ("daily", "day", 30)]:
            df = fetch_ohlcv(symbol, interval, n_candles)
            if df.empty:
                results[name][tf] = None
                continue
            closes   = df["close"].tolist()
            ema_vals = compute_ema(closes, 21)
            last     = df.iloc[-1]
            results[name][tf] = {
                "timestamp": str(last["date"]),
                "open":      round(last["open"], 2),
                "high":      round(last["high"], 2),
                "low":       round(last["low"], 2),
                "close":     round(last["close"], 2),
                "volume":    int(last.get("volume", 0)),
                "ema21":     ema_vals[-1],
                "vs_ema":    price_vs_ema(last["close"], ema_vals[-1]),
                "ema_slope": ema_slope(ema_vals),
            }

    nifty_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
    ib_data     = classify_ib(nifty_15min)

    vix_intraday = results["India VIX"].get("intraday")
    vix_close    = vix_intraday["close"] if vix_intraday else None
    vix_mode     = vix_regime(vix_close) if vix_close else "UNKNOWN"

    _print_tables(results, ib_data, vix_close, vix_mode)

    return {
        "instruments": results,
        "ib":          ib_data,
        "vix_close":   vix_close,
        "vix_mode":    vix_mode,
    }


def _print_tables(results: dict, ib_data: dict, vix_close, vix_mode: str):
    print("\n" + "=" * 74)
    print("  NIFTY MARKET SCANNER")
    print("=" * 74)

    col_w   = [14, 9, 9, 9, 9, 9, 7, 9]
    headers = ["Instrument", "Open", "High", "Low", "Close", "21 EMA", "vs EMA", "Slope"]
    fmt     = "".join(f"{{:<{w}}}" for w in col_w)

    for label, tf_key in [("INTRADAY (15-min)", "intraday"), ("DAILY", "daily")]:
        print(f"\n── {label} ──")
        print(fmt.format(*headers))
        print("-" * sum(col_w))
        for name, data in results.items():
            d = data.get(tf_key)
            row = (
                [name, d["open"], d["high"], d["low"], d["close"],
                 d["ema21"], d["vs_ema"], d["ema_slope"]]
                if d else [name] + ["N/A"] * 7
            )
            print(fmt.format(*[str(x) for x in row]))

    print("\n── NIFTY IB STATUS ──")
    for k, v in ib_data.items():
        print(f"  {k:<18}: {v}")

    if vix_close:
        print(f"\n── VIX REGIME ──")
        print(f"  VIX  : {vix_close}")
        print(f"  Mode : {vix_mode}")

    print(f"\nData as of: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")


if __name__ == "__main__":
    run_scanner()
