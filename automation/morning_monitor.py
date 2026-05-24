"""Morning Observation Phase — 09:10–10:15 IST.

Observation-only window (Rule 5: no trades before 10:15).
Tasks:
  09:10 — Start KiteTicker for orderflow warm-up
  09:15 — Print IB high/low as it forms; log CVD direction every 5 mins
  10:00 — Save OI snapshot as baseline for fresh_build comparison
  10:15 — Print frozen IB + day_type; exit (trade_window.py takes over)

Run by Windows Task Scheduler at 09:10 on weekdays.
"""
import os
import sys
import time
from datetime import date, datetime, time as dtime

import pytz
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST = pytz.timezone("Asia/Kolkata")

_IB_FROZEN    = dtime(10, 15)
_OI_SNAPSHOT  = dtime(10, 0)
_POLL_SECS    = 300   # 5 minutes


def _is_trading_day() -> bool:
    return date.today().weekday() < 5


def run():
    # if not _is_trading_day():
    #     print("[MorningMonitor] Not a trading day — exiting.")
    #     return

    from data.kite_client import fetch_ohlcv, classify_ib
    from layers.orderflow import start_monitoring, _state as orderflow_state
    from layers.oi_scanner import get_oi_levels
    from data.oi_store import save_snapshot

    print(f"[MorningMonitor] Started at {datetime.now(IST).strftime('%H:%M IST')}")

    # Start KiteTicker early for CVD warm-up
    start_monitoring(poc_level=0.0)

    oi_saved = False

    while True:
        now_ist  = datetime.now(IST)
        now_time = now_ist.time()

        # Fetch latest IB status
        df_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
        ib = classify_ib(df_15min)

        # CVD snapshot
        cvd_snap = orderflow_state.snapshot()

        print(f"  [{now_ist.strftime('%H:%M')}] "
              f"IB={ib.get('status')}  day_type={ib.get('day_type', '?')}  "
              f"ib_H={ib.get('ib_high', '?')}  ib_L={ib.get('ib_low', '?')}  "
              f"CVD={cvd_snap['cvd_velocity']:+,}  spot={cvd_snap['spot']}")

        # Save OI snapshot at 10:00 as fresh_build baseline
        if now_time >= _OI_SNAPSHOT and not oi_saved:
            try:
                l2 = get_oi_levels()
                save_snapshot(
                    call_wall_oi=l2.get("call_wall_oi_raw", 0),
                    put_wall_oi=l2.get("put_wall_oi_raw", 0),
                )
                print(f"  [OI Baseline] call_wall={l2.get('call_wall')}  "
                      f"put_wall={l2.get('put_wall')}  snapshot saved")
                oi_saved = True
            except Exception as exc:
                print(f"  [OI Baseline] Error: {exc}")

        # Hand off at 10:15 (IB frozen)
        if now_time >= _IB_FROZEN:
            print(f"\n[MorningMonitor] IB frozen — day_type={ib.get('day_type')}  "
                  f"range={ib.get('ib_range')}  extension={ib.get('ib_extension')}")
            print("[MorningMonitor] Handing off to trade_window.py")
            break

        time.sleep(_POLL_SECS)


if __name__ == "__main__":
    run()
