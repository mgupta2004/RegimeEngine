"""Strike selector — picks spread leg strikes given signal output.

Returns a list of leg specs (no Kite calls). The tradingsymbol is resolved
from the NFO instruments list via data.kite_client.get_instruments().
"""
from __future__ import annotations
import os
from datetime import date as date_type

from data.kite_client import get_instruments

LOT_SIZE = int(os.environ.get("NIFTY_LOT_SIZE", "75"))


def _atm(spot: float) -> int:
    """Round spot to nearest 50-point Nifty strike."""
    return int(round(spot / 50) * 50)


def _find_tradingsymbol(strike: int, option_type: str, expiry: date_type) -> str:
    """Look up the NFO tradingsymbol for a given Nifty strike/option/expiry."""
    for inst in get_instruments("NFO"):
        if (
            inst["name"] == "NIFTY"
            and inst["instrument_type"] == option_type
            and inst["strike"] == strike
            and inst["expiry"] == expiry
        ):
            return inst["tradingsymbol"]
    raise ValueError(
        f"No NFO instrument found: NIFTY {option_type} {strike} expiry={expiry}"
    )


def _leg(strike: int, option_type: str, transaction_type: str, expiry: date_type) -> dict:
    return {
        "strike":           strike,
        "option_type":      option_type,
        "transaction_type": transaction_type,   # "BUY" | "SELL"
        "tradingsymbol":    _find_tradingsymbol(strike, option_type, expiry),
        "exchange":         "NFO",
    }


def select_strikes(
    spread_type: str,
    spot:        float,
    call_wall:   float | None,
    put_wall:    float | None,
    max_pain:    float,
    expiry:      str,           # "YYYY-MM-DD"
) -> list[dict]:
    """Return leg specs for the given spread type.

    Legs do NOT include quantity (set by risk_manager.compute_position_lots).

    Strike logic:
        ATM = round(spot / 50) * 50
        BULL_CALL  : BUY ATM CE,       SELL min(ATM+100, call_wall) CE
        BEAR_PUT   : BUY ATM PE,       SELL max(ATM-100, put_wall) PE
        BULL_PUT   : BUY ATM-150 PE,   SELL ATM-50 PE        (High VIX credit)
        BEAR_CALL  : BUY ATM+150 CE,   SELL ATM+50 CE        (High VIX credit)
        IRON_CONDOR: BUY ATM+200 CE,   SELL ATM+100 CE,
                     BUY ATM-200 PE,   SELL ATM-100 PE
    """
    exp_date = date_type.fromisoformat(expiry)
    atm      = _atm(spot)

    if spread_type == "BULL_CALL":
        short_strike = int(min(atm + 100, call_wall)) if call_wall else atm + 100
        short_strike = int(round(short_strike / 50) * 50)
        return [
            _leg(atm,          "CE", "BUY",  exp_date),
            _leg(short_strike,  "CE", "SELL", exp_date),
        ]

    if spread_type == "BEAR_PUT":
        short_strike = int(max(atm - 100, put_wall)) if put_wall else atm - 100
        short_strike = int(round(short_strike / 50) * 50)
        return [
            _leg(atm,          "PE", "BUY",  exp_date),
            _leg(short_strike,  "PE", "SELL", exp_date),
        ]

    if spread_type == "BULL_PUT":
        return [
            _leg(atm - 150, "PE", "BUY",  exp_date),
            _leg(atm - 50,  "PE", "SELL", exp_date),
        ]

    if spread_type == "BEAR_CALL":
        return [
            _leg(atm + 150, "CE", "BUY",  exp_date),
            _leg(atm + 50,  "CE", "SELL", exp_date),
        ]

    if spread_type == "IRON_CONDOR":
        return [
            _leg(atm + 200, "CE", "BUY",  exp_date),
            _leg(atm + 100, "CE", "SELL", exp_date),
            _leg(atm - 200, "PE", "BUY",  exp_date),
            _leg(atm - 100, "PE", "SELL", exp_date),
        ]

    raise ValueError(f"Unknown spread_type: {spread_type!r}")
