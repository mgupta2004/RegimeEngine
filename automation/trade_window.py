"""Primary Trade Window — 10:15–13:00 IST.

Drives the signal → risk → execute loop at 5-minute intervals.
Run by Windows Task Scheduler at 10:15 on weekdays.

Exit conditions (in priority order):
  1. Past hard exit time (15:15 HIGH VOL, 15:20 NORMAL)
  2. Daily loss limit hit (1.5%)
  3. Position stop-loss triggered
  4. Position near max pain (partial profit)
"""
import os
import sys
import time
from datetime import date, datetime

import pytz
from dotenv import load_dotenv

# Ensure repo root is importable when run as a script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST = pytz.timezone("Asia/Kolkata")
CAPITAL = float(os.environ.get("TRADING_CAPITAL", "1000000"))
POLL_SECONDS = 300   # 5-minute evaluation cycle


def _is_trading_day() -> bool:
    return date.today().weekday() < 5   # Mon–Fri


def _estimate_net_premium(legs: list[dict]) -> float:
    """Rough net premium estimate from current LTPs (buy cost − sell credit)."""
    from execution.order_manager import get_ltp
    net = 0.0
    for leg in legs:
        ltp = get_ltp(leg["tradingsymbol"])
        net += ltp if leg["transaction_type"] == "BUY" else -ltp
    return round(net, 2)


def run():
    if not _is_trading_day():
        print("[TradeWindow] Not a trading day — exiting.")
        return

    from engine.signal_engine import run as get_signal
    from engine.risk_manager import RiskManager
    from engine.strike_selector import select_strikes
    from execution.order_manager import place_spread
    from execution.position_manager import PositionManager

    risk = RiskManager(capital=CAPITAL)
    pm   = PositionManager()

    print(f"[TradeWindow] Started at {datetime.now(IST).strftime('%H:%M IST')}")

    while True:
        try:
            signal   = get_signal()
            vix_mode = signal["vix_mode"]

            # ── Hard exit checks ──────────────────────────────────────────────
            if risk.force_exit_required(vix_mode) or risk.is_loss_limit_hit():
                if pm.has_open_position():
                    pos   = pm.get_position()
                    lots  = pos["legs"][0]["lots"]
                    realized = pm.close_all(reason="hard_exit", lots=lots)
                    risk.record_pnl(realized, spread_type=pos["spread_type"])
                print(f"[TradeWindow] Session ended at {datetime.now(IST).strftime('%H:%M IST')}")
                break

            # ── Monitor open position ─────────────────────────────────────────
            if pm.has_open_position():
                pos      = pm.get_position()
                spot     = signal["key_levels"].get("spot", 0)
                lots     = pos["legs"][0]["lots"]

                if pm.check_stop_loss(current_spot=spot):
                    realized = pm.close_all(reason="stop_loss", lots=lots)
                    risk.record_pnl(realized, spread_type=pos["spread_type"])

                elif pm.is_near_max_pain(signal["key_levels"]["max_pain"], spot):
                    realized = pm.close_all(reason="target_max_pain", lots=lots)
                    risk.record_pnl(realized, spread_type=pos["spread_type"])

            # ── New entry ─────────────────────────────────────────────────────
            elif signal["signal"] == "ENTER" and signal["spread_type"] != "NO_TRADE":
                allowed, reason = risk.check_entry_allowed(vix_mode)
                if not allowed:
                    print(f"[TradeWindow] Entry blocked: {reason}")
                else:
                    expiry = signal.get("expiry", "")
                    if not expiry:
                        print("[TradeWindow] No expiry in signal — skipping entry")
                    else:
                        legs = select_strikes(
                            spread_type=signal["spread_type"],
                            spot=signal["key_levels"]["spot"],
                            call_wall=signal["key_levels"].get("call_wall"),
                            put_wall=signal["key_levels"].get("put_wall"),
                            max_pain=signal["key_levels"]["max_pain"],
                            expiry=expiry,
                        )
                        net_premium = _estimate_net_premium(legs)
                        lots        = risk.compute_position_lots(spread_ltp=abs(net_premium))
                        result      = place_spread(legs, lots)
                        sl, target  = pm.stop_loss_for_spread(
                            signal["spread_type"], signal["key_levels"]
                        )
                        pm.open_position(
                            legs=legs,
                            spread_type=signal["spread_type"],
                            entry_net_premium=net_premium,
                            stop_loss_spot=sl,
                            target_spot=target,
                            order_ids=result["order_ids"],
                            lots=lots,
                            leg_ltps=result["leg_ltps"],
                        )

        except Exception as exc:
            print(f"[TradeWindow] Error: {exc}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
