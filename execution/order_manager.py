"""Order placement — paper and live modes.

TRADE_MODE=paper  (default): simulates orders, logs to state/daily_pnl.json.
TRADE_MODE=live:              places real MIS limit orders via Kite.

All spread entries use LIMIT orders at current LTP.
All exits use MARKET orders for immediate fill.
"""
import os
import uuid
from datetime import datetime

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from data.kite_client import get_kite

IST        = pytz.timezone("Asia/Kolkata")
TRADE_MODE = os.environ.get("TRADE_MODE", "paper")
LOT_SIZE   = int(os.environ.get("NIFTY_LOT_SIZE", "75"))


# ── LTP Helper ────────────────────────────────────────────────────────────────

def get_ltp(tradingsymbol: str) -> float:
    """Fetch last traded price for an NFO symbol."""
    key = f"NFO:{tradingsymbol}"
    result = get_kite().ltp([key])
    return result[key]["last_price"]


# ── Place / Exit ──────────────────────────────────────────────────────────────

def place_spread(legs: list[dict], lots: int) -> dict:
    """Place all legs of a spread.

    Args:
        legs: list of dicts from strike_selector.select_strikes()
              Each has: tradingsymbol, exchange, transaction_type, option_type, strike
        lots: number of Nifty lots (quantity = lots × LOT_SIZE)

    Returns:
        {"order_ids": [...], "mode": "paper"|"live", "legs": [...], "leg_ltps": [...]}
    """
    quantity = lots * LOT_SIZE
    order_ids: list[str] = []
    leg_ltps: list[float] = []

    for leg in legs:
        ltp = get_ltp(leg["tradingsymbol"])
        leg_ltps.append(ltp)

        if TRADE_MODE == "live":
            kite = get_kite()
            order_id = kite.place_order(
                tradingsymbol=leg["tradingsymbol"],
                exchange=leg["exchange"],
                transaction_type=leg["transaction_type"],
                quantity=quantity,
                order_type=kite.ORDER_TYPE_LIMIT,
                price=ltp,
                product=kite.PRODUCT_MIS,
                variety=kite.VARIETY_REGULAR,
            )
            order_ids.append(str(order_id))
            print(f"[Live] {leg['transaction_type']} {leg['tradingsymbol']} "
                  f"qty={quantity} @ {ltp}  order_id={order_id}")
        else:
            fake_id = f"PAPER-{uuid.uuid4().hex[:8].upper()}"
            order_ids.append(fake_id)
            print(f"[Paper] {leg['transaction_type']} {leg['tradingsymbol']} "
                  f"qty={quantity} @ {ltp}  order_id={fake_id}")

    return {
        "order_ids": order_ids,
        "mode":      TRADE_MODE,
        "legs":      legs,
        "leg_ltps":  leg_ltps,
        "timestamp": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
    }


def exit_spread(legs: list[dict], order_ids: list[str], lots: int) -> dict:
    """Exit all legs of an open spread.

    Reverses each leg's transaction_type (BUY→SELL, SELL→BUY).
    Uses MARKET orders for immediate fill.

    Returns exit LTPs and realized net premium (positive = profit for credit spreads).
    """
    quantity   = lots * LOT_SIZE
    exit_ltps: list[float] = []
    exit_ids:  list[str]   = []

    reverse = {"BUY": "SELL", "SELL": "BUY"}

    for leg in legs:
        exit_tx = reverse[leg["transaction_type"]]
        ltp     = get_ltp(leg["tradingsymbol"])
        exit_ltps.append(ltp)

        if TRADE_MODE == "live":
            kite = get_kite()
            eid  = kite.place_order(
                tradingsymbol=leg["tradingsymbol"],
                exchange=leg["exchange"],
                transaction_type=exit_tx,
                quantity=quantity,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS,
                variety=kite.VARIETY_REGULAR,
            )
            exit_ids.append(str(eid))
            print(f"[Live-Exit] {exit_tx} {leg['tradingsymbol']} qty={quantity} @ MKT")
        else:
            fake_id = f"PAPER-EXIT-{uuid.uuid4().hex[:8].upper()}"
            exit_ids.append(fake_id)
            print(f"[Paper-Exit] {exit_tx} {leg['tradingsymbol']} qty={quantity} @ {ltp}")

    return {
        "exit_order_ids": exit_ids,
        "exit_ltps":      exit_ltps,
        "timestamp":      datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
    }


def get_order_status(order_id: str) -> dict:
    """Fetch order status from Kite (no-op in paper mode)."""
    if TRADE_MODE == "paper" or order_id.startswith("PAPER"):
        return {"status": "COMPLETE", "mode": "paper"}
    orders = get_kite().orders()
    for o in orders:
        if str(o["order_id"]) == order_id:
            return o
    return {"status": "NOT_FOUND"}
