"""Layer 2 — Open Interest walls, PCR, Max Pain, proximity scoring.

Fetches the Nifty weekly option chain and identifies institutional walls.
Scores confluence based on proximity to wall and fresh OI build.
In HIGH VIX mode, also enforces PCR + Max Pain directional conditions.
"""
import os
from datetime import date, timedelta
from kiteconnect import KiteConnect
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY      = os.environ.get("KITE_API_KEY", "")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# ── Instrument helpers ────────────────────────────────────────────────────────
_nfo_cache: list | None = None

def _get_nfo_instruments() -> list:
    global _nfo_cache
    if _nfo_cache is None:
        _nfo_cache = kite.instruments("NFO")
    return _nfo_cache


def _nearest_weekly_expiry() -> date:
    """Return the nearest Thursday expiry on or after today."""
    today = date.today()
    days_ahead = (3 - today.weekday()) % 7  # 3 = Thursday
    if days_ahead == 0 and today.weekday() == 3:
        days_ahead = 0
    return today + timedelta(days=days_ahead)


def _get_nifty_option_strikes(expiry: date) -> list:
    """Return all Nifty option instruments for the given expiry."""
    instruments = _get_nfo_instruments()
    return [
        i for i in instruments
        if i["name"] == "NIFTY"
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] == expiry
    ]

# ── OI Snapshot ───────────────────────────────────────────────────────────────
def _fetch_oi_snapshot(option_strikes: list) -> dict:
    """
    Fetch LTP + OI for all strikes.
    Returns: {strike: {"CE": {ltp, oi}, "PE": {ltp, oi}}}
    """
    tokens = [f"NFO:{i['tradingsymbol']}" for i in option_strikes]
    # Kite ltp() accepts max 500 symbols; Nifty option chain is ~100-200 strikes
    chunk_size = 400
    ltp_data = {}
    for i in range(0, len(tokens), chunk_size):
        ltp_data.update(kite.ltp(tokens[i:i + chunk_size]))

    chain: dict = {}
    for instrument in option_strikes:
        sym = f"NFO:{instrument['tradingsymbol']}"
        quote = ltp_data.get(sym, {})
        strike = instrument["strike"]
        opt_type = instrument["instrument_type"]  # CE or PE
        if strike not in chain:
            chain[strike] = {}
        chain[strike][opt_type] = {
            "ltp": quote.get("last_price", 0),
            "oi":  quote.get("oi", 0),
        }
    return chain


def _get_spot() -> float:
    ltp = kite.ltp(["NSE:NIFTY 50"])
    return ltp["NSE:NIFTY 50"]["last_price"]

# ── OI Analysis ───────────────────────────────────────────────────────────────
def _find_walls(chain: dict, spot: float) -> dict:
    """Identify Call Wall (max CE OI above spot) and Put Wall (max PE OI below spot)."""
    call_strikes = {k: v["CE"]["oi"] for k, v in chain.items() if k > spot and "CE" in v}
    put_strikes  = {k: v["PE"]["oi"] for k, v in chain.items() if k < spot and "PE" in v}

    call_wall = max(call_strikes, key=call_strikes.get) if call_strikes else None
    put_wall  = max(put_strikes,  key=put_strikes.get)  if put_strikes  else None

    return {
        "call_wall": call_wall,
        "call_wall_oi": call_strikes.get(call_wall, 0),
        "put_wall": put_wall,
        "put_wall_oi": put_strikes.get(put_wall, 0),
    }


def _compute_pcr(chain: dict) -> float:
    total_put_oi  = sum(v["PE"]["oi"] for v in chain.values() if "PE" in v)
    total_call_oi = sum(v["CE"]["oi"] for v in chain.values() if "CE" in v)
    if total_call_oi == 0:
        return 0.0
    return round(total_put_oi / total_call_oi, 3)


def _compute_max_pain(chain: dict) -> float:
    """Max pain: strike at which total option writer loss is minimised."""
    strikes = sorted(chain.keys())
    min_pain = float("inf")
    max_pain_strike = strikes[0]

    for test_strike in strikes:
        loss = 0.0
        for strike, data in chain.items():
            if "CE" in data:
                # Call writer loses when test_strike > strike
                loss += max(0, test_strike - strike) * data["CE"]["oi"]
            if "PE" in data:
                # Put writer loses when test_strike < strike
                loss += max(0, strike - test_strike) * data["PE"]["oi"]
        if loss < min_pain:
            min_pain = loss
            max_pain_strike = test_strike

    return max_pain_strike

# ── Main Entry Point ──────────────────────────────────────────────────────────
def get_oi_levels(vix_mode: str = "NORMAL", bias_hint: str = "SKIP",
                  prev_call_wall_oi: float = 0, prev_put_wall_oi: float = 0) -> dict:
    """
    Args:
        vix_mode: "NORMAL" | "HIGH VOL"
        bias_hint: "LONG" | "SHORT" | "SKIP" (from Layer 1, used for High VIX check)
        prev_call_wall_oi / prev_put_wall_oi: OI from prior fetch to detect fresh build

    Returns:
        call_wall, put_wall, pcr, max_pain, proximity (bool), fresh_build (bool),
        score (0.0–2.0), high_vix_bias_confirmed (bool)
    """
    expiry = _nearest_weekly_expiry()
    strikes = _get_nifty_option_strikes(expiry)
    if not strikes:
        return {"error": f"No option data for expiry {expiry}", "score": 0.0}

    chain = _fetch_oi_snapshot(strikes)
    spot  = _get_spot()

    walls    = _find_walls(chain, spot)
    pcr      = _compute_pcr(chain)
    max_pain = _compute_max_pain(chain)

    call_wall = walls["call_wall"]
    put_wall  = walls["put_wall"]

    # Proximity threshold: 75pts Normal, 100pts High VIX
    prox_threshold = 100 if vix_mode == "HIGH VOL" else 75
    near_call = call_wall and abs(spot - call_wall) <= prox_threshold
    near_put  = put_wall  and abs(spot - put_wall)  <= prox_threshold
    proximity = bool(near_call or near_put)

    # Fresh OI build: compare against prior snapshot if provided
    fresh_call_build = walls["call_wall_oi"] > prev_call_wall_oi if prev_call_wall_oi else False
    fresh_put_build  = walls["put_wall_oi"]  > prev_put_wall_oi  if prev_put_wall_oi  else False
    fresh_build = fresh_call_build or fresh_put_build

    score = 0.0
    if proximity:
        score += 1.0
    if fresh_build:
        score += 1.0

    # High VIX directional confirmation
    high_vix_bias_confirmed = False
    if vix_mode == "HIGH VOL":
        bullish_ok = pcr > 1.20 and max_pain > spot
        bearish_ok = pcr < 0.80 and max_pain < spot
        high_vix_bias_confirmed = (bias_hint == "LONG" and bullish_ok) or \
                                   (bias_hint == "SHORT" and bearish_ok)

    return {
        "expiry":      str(expiry),
        "spot":        round(spot, 2),
        "call_wall":   call_wall,
        "put_wall":    put_wall,
        "pcr":         pcr,
        "max_pain":    max_pain,
        "proximity":   proximity,
        "fresh_build": fresh_build,
        "score":       score,
        "high_vix_bias_confirmed": high_vix_bias_confirmed,
    }


if __name__ == "__main__":
    result = get_oi_levels()
    for k, v in result.items():
        print(f"  {k:<28}: {v}")
