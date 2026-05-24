"""Evening Phase — post-18:00 IST.

Prepares for the next trading day:
  1. Warns user to refresh Kite token via kite_login.py
  2. Computes swing bias from EOD data (layers/swing_bias.py)
  3. Writes a preliminary open_trade.json (bias + vix_mode; no entry signal yet)
  4. Resets state/daily_pnl.json for the next day
  5. Saves a baseline OI snapshot for overnight fresh_build reference

Run by Windows Task Scheduler at 18:00 on weekdays.
"""
import json
import os
import sys
from datetime import date, datetime

import pytz
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST         = pytz.timezone("Asia/Kolkata")
CAPITAL     = float(os.environ.get("TRADING_CAPITAL", "1000000"))
_TRADE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "open_trade.json")
_PNL_FILE   = os.path.join(os.path.dirname(__file__), "..", "state", "daily_pnl.json")


def _is_trading_day() -> bool:
    return date.today().weekday() < 5


def run():
    # if not _is_trading_day():
    #     print("[EveningRunner] Not a trading day — exiting.")
    #     return

    print(f"[EveningRunner] Started at {datetime.now(IST).strftime('%H:%M IST')}")
    print("[EveningRunner] ⚠  Ensure kite_login.py was run today to refresh the access token.")

    # Step 1: Compute swing bias
    from layers.swing_bias import get_swing_bias
    bias = get_swing_bias()
    print(f"[EveningRunner] Swing bias: {bias['bias']}  VIX mode: {bias['vix_mode']}  "
          f"VIX close: {bias.get('vix_close', 'N/A')}")

    # Step 2: Write preliminary open_trade.json
    today = str(date.today())
    os.makedirs(os.path.dirname(_TRADE_FILE), exist_ok=True)
    prelim = {
        "date":        today,
        "generated":   datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "bias":        bias["bias"],
        "vix_mode":    bias["vix_mode"],
        "vix_close":   bias.get("vix_close"),
        "signal":      "PENDING",
        "spread_type": "UNKNOWN",
        "note":        "Pre-market; signal_engine will update this after IB freezes at 10:15",
    }
    with open(_TRADE_FILE, "w") as f:
        json.dump(prelim, f, indent=2)
    print(f"[EveningRunner] Preliminary open_trade.json written.")

    # Step 3: Reset daily_pnl.json for the next day
    import datetime as dt
    next_day = (dt.date.today() + dt.timedelta(days=1))
    # Find next weekday
    while next_day.weekday() >= 5:
        next_day += dt.timedelta(days=1)
    fresh_pnl = {
        "date":         str(next_day),
        "capital":      CAPITAL,
        "realized_pnl": 0.0,
        "trades":       [],
    }
    os.makedirs(os.path.dirname(_PNL_FILE), exist_ok=True)
    with open(_PNL_FILE, "w") as f:
        json.dump(fresh_pnl, f, indent=2)
    print(f"[EveningRunner] daily_pnl.json reset for {next_day}.")

    # Step 4: Save overnight OI baseline
    try:
        from layers.oi_scanner import get_oi_levels
        from data.oi_store import save_snapshot
        l2 = get_oi_levels()
        save_snapshot(
            call_wall_oi=l2.get("call_wall_oi_raw", 0),
            put_wall_oi=l2.get("put_wall_oi_raw", 0),
        )
        print(f"[EveningRunner] OI baseline saved — call_wall={l2.get('call_wall')}  "
              f"put_wall={l2.get('put_wall')}")
    except Exception as exc:
        print(f"[EveningRunner] OI snapshot failed (non-critical): {exc}")

    print("[EveningRunner] Done. Good night.")


if __name__ == "__main__":
    run()
