"""Layer 2 — Open Interest walls, PCR, Max Pain, proximity scoring.

Fetches the Nifty weekly option chain and identifies institutional walls.
Scores confluence based on proximity to wall and fresh OI build.
In HIGH VIX mode, also enforces PCR + Max Pain directional conditions.
"""
from datetime import date
from data.kite_client import get_kite, get_instruments


# ── Instrument helpers ────────────────────────────────────────────────────────

def _nearest_weekly_expiry() -> date:
    """Return nearest active Nifty weekly expiry from the instruments list."""
    today    = date.today()
    expiries = sorted({
        i["expiry"] for i in get_instruments("NFO")
        if i["name"] == "NIFTY"
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] >= today
    })
    if not expiries:
        raise RuntimeError("No upcoming Nifty option expiries found in NFO instruments")
    weekly = [e for e in expiries if (e - today).days <= 7]
    return weekly[0] if weekly else expiries[0]


def _get_nifty_option_strikes(expiry: date) -> list:
    return [
        i for i in get_instruments("NFO")
        if i["name"] == "NIFTY"
        and i["instrument_type"] in ("CE", "PE")
        and i["expiry"] == expiry
    ]


# ── OI Snapshot ───────────────────────────────────────────────────────────────

def _fetch_oi_snapshot(option_strikes: list) -> dict:
    """Return {strike: {"CE": {ltp, oi}, "PE": {ltp, oi}}}."""
    kite   = get_kite()
    tokens = [f"NFO:{i['tradingsymbol']}" for i in option_strikes]
    quote_data: dict = {}
    for i in range(0, len(tokens), 500):
        quote_data.update(kite.quote(tokens[i:i + 500]))

    chain: dict = {}
    for instrument in option_strikes:
        sym      = f"NFO:{instrument['tradingsymbol']}"
        q        = quote_data.get(sym, {})
        strike   = instrument["strike"]
        opt_type = instrument["instrument_type"]
        chain.setdefault(strike, {})[opt_type] = {
            "ltp": q.get("last_price", 0),
            "oi":  q.get("oi", 0),
        }
    return chain


def _get_spot() -> float:
    ltp = get_kite().ltp(["NSE:NIFTY 50"])
    return ltp["NSE:NIFTY 50"]["last_price"]


# ── OI Analysis ───────────────────────────────────────────────────────────────

def _find_walls(chain: dict, spot: float) -> dict:
    call_strikes = {k: v["CE"]["oi"] for k, v in chain.items() if k > spot and "CE" in v}
    put_strikes  = {k: v["PE"]["oi"] for k, v in chain.items() if k < spot and "PE" in v}

    call_wall = max(call_strikes, key=call_strikes.get) if call_strikes else None
    put_wall  = max(put_strikes,  key=put_strikes.get)  if put_strikes  else None

    return {
        "call_wall":    call_wall,
        "call_wall_oi": call_strikes.get(call_wall, 0),
        "put_wall":     put_wall,
        "put_wall_oi":  put_strikes.get(put_wall, 0),
    }


def _compute_pcr(chain: dict) -> float:
    total_put  = sum(v["PE"]["oi"] for v in chain.values() if "PE" in v)
    total_call = sum(v["CE"]["oi"] for v in chain.values() if "CE" in v)
    return round(total_put / total_call, 3) if total_call else 0.0


def _compute_max_pain(chain: dict) -> float:
    strikes  = sorted(chain.keys())
    min_pain = float("inf")
    result   = strikes[0]
    for test in strikes:
        loss = sum(
            max(0, test - s) * d["CE"]["oi"] for s, d in chain.items() if "CE" in d
        ) + sum(
            max(0, s - test) * d["PE"]["oi"] for s, d in chain.items() if "PE" in d
        )
        if loss < min_pain:
            min_pain, result = loss, test
    return result


# ── Main Entry Point ──────────────────────────────────────────────────────────

def get_oi_levels(
    vix_mode:          str   = "NORMAL",
    bias_hint:         str   = "SKIP",
    prev_call_wall_oi: float = 0,
    prev_put_wall_oi:  float = 0,
) -> dict:
    """
    Args:
        vix_mode: "NORMAL" | "HIGH VOL"
        bias_hint: "LONG" | "SHORT" | "SKIP"
        prev_call_wall_oi / prev_put_wall_oi: OI from prior snapshot for fresh_build detection

    Returns:
        call_wall, put_wall, pcr, max_pain, proximity, fresh_build,
        score (0.0–2.0), high_vix_bias_confirmed,
        call_wall_oi_raw, put_wall_oi_raw  ← for oi_store.save_snapshot()
    """
    expiry  = _nearest_weekly_expiry()
    strikes = _get_nifty_option_strikes(expiry)
    print(f"[L2] expiry={expiry}  strikes_found={len(strikes)}")
    if not strikes:
        return {"error": f"No option data for expiry {expiry}", "score": 0.0}

    chain    = _fetch_oi_snapshot(strikes)
    spot     = _get_spot()
    walls    = _find_walls(chain, spot)
    pcr      = _compute_pcr(chain)
    max_pain = _compute_max_pain(chain)

    call_wall    = walls["call_wall"]
    put_wall     = walls["put_wall"]
    call_wall_oi = walls["call_wall_oi"]
    put_wall_oi  = walls["put_wall_oi"]

    prox_threshold = 100 if vix_mode == "HIGH VOL" else 75
    near_call  = call_wall is not None and abs(spot - call_wall) <= prox_threshold
    near_put   = put_wall  is not None and abs(spot - put_wall)  <= prox_threshold
    proximity  = bool(near_call or near_put)

    fresh_call = call_wall_oi > prev_call_wall_oi if prev_call_wall_oi else False
    fresh_put  = put_wall_oi  > prev_put_wall_oi  if prev_put_wall_oi  else False
    fresh_build = fresh_call or fresh_put

    score = 0.0
    if proximity:
        score += 1.0
    if fresh_build:
        score += 1.0

    high_vix_bias_confirmed = False
    if vix_mode == "HIGH VOL":
        bullish_ok = pcr > 1.20 and max_pain > spot
        bearish_ok = pcr < 0.80 and max_pain < spot
        high_vix_bias_confirmed = (
            (bias_hint == "LONG"  and bullish_ok) or
            (bias_hint == "SHORT" and bearish_ok)
        )

    return {
        "expiry":                 str(expiry),
        "spot":                   round(spot, 2),
        "call_wall":              call_wall,
        "put_wall":               put_wall,
        "pcr":                    pcr,
        "max_pain":               max_pain,
        "proximity":              proximity,
        "fresh_build":            fresh_build,
        "score":                  score,
        "high_vix_bias_confirmed": high_vix_bias_confirmed,
        # Raw OI integers for oi_store.save_snapshot()
        "call_wall_oi_raw":       call_wall_oi,
        "put_wall_oi_raw":        put_wall_oi,
    }


if __name__ == "__main__":
    result = get_oi_levels()
    for k, v in result.items():
        print(f"  {k:<28}: {v}")
