"""Confluence scorer — aggregates Layers 0–3 and writes state/open_trade.json.

Run during the primary trade window (10:15–13:00 IST) after IB is frozen.
For the evening pre-computation workflow, run layers/swing_bias.py first to
get swing bias, then call this once market opens and all layers are available.
"""
import os
import json
from datetime import datetime, date

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST         = pytz.timezone("Asia/Kolkata")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "open_trade.json")


def _determine_spread(bias: str, vix_mode: str, strategy_set: str) -> str:
    if strategy_set == "IRON_CONDOR":
        return "IRON_CONDOR"
    if strategy_set == "SKIP":
        return "NO_TRADE"
    if vix_mode == "HIGH VOL":
        if bias == "LONG":
            return "BULL_PUT"
        if bias == "SHORT":
            return "BEAR_CALL"
        return "NO_TRADE"
    if bias == "LONG":
        return "BULL_CALL"
    if bias == "SHORT":
        return "BEAR_PUT"
    return "NO_TRADE"


def run() -> dict:
    """Evaluate all four layers and return the consolidated signal dict.

    Writes state/open_trade.json as a side-effect.
    """
    from data.kite_client import fetch_ohlcv
    from data.oi_store import get_prior_snapshot, save_snapshot
    from engine.poc_calculator import compute_poc

    # Fetch 15-min data once; reused by L0 and POC
    df_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
    poc_level = compute_poc(df_15min)

    # ── Layer 0: Market Profile ───────────────────────────────────────────────
    from layers.market_profile import get_market_profile
    l0 = get_market_profile()
    print(f"[L0] day_type={l0['day_type']}  strategy={l0['strategy_set']}  score={l0['score']}")

    if l0["strategy_set"] == "SKIP":
        result = _build_result(l0=l0, l1=None, l2=None, l3=None,
                               signal="SKIP", reason="Layer 0 mandates SKIP")
        _write(result)
        return result

    # ── Layer 1: Swing Bias ───────────────────────────────────────────────────
    from layers.swing_bias import get_swing_bias
    l1       = get_swing_bias()
    vix_mode = l1["vix_mode"]
    bias     = l1["bias"]
    print(f"[L1] bias={l1['bias']}  vix_mode={vix_mode}  score={l1['score']}")

    # ── Layer 2: OI Walls ─────────────────────────────────────────────────────
    from layers.oi_scanner import get_oi_levels
    prior = get_prior_snapshot(minutes_ago=45) or {}
    l2 = get_oi_levels(
        vix_mode=vix_mode,
        bias_hint=bias,
        prev_call_wall_oi=prior.get("call_wall_oi", 0),
        prev_put_wall_oi=prior.get("put_wall_oi", 0),
    )
    # Persist current OI for the next cycle's fresh_build comparison
    save_snapshot(
        call_wall_oi=l2.get("call_wall_oi_raw", 0),
        put_wall_oi=l2.get("put_wall_oi_raw", 0),
    )
    print(f"[L2] call_wall={l2.get('call_wall')}  put_wall={l2.get('put_wall')}  "
          f"pcr={l2.get('pcr')}  fresh={l2.get('fresh_build')}  score={l2.get('score')}")

    # In HIGH VIX mode, OI layer determines bias when L1 bypassed
    if vix_mode == "HIGH VOL":
        pcr      = l2.get("pcr", 1.0)
        max_pain = l2.get("max_pain", 0)
        spot     = l2.get("spot", 0)
        if pcr > 1.20 and max_pain > spot:
            bias = "LONG";  l1["bias"] = "LONG";  l1["score"] = 1.0
        elif pcr < 0.80 and max_pain < spot:
            bias = "SHORT"; l1["bias"] = "SHORT"; l1["score"] = 1.0
        else:
            bias = "SKIP"

    if l2.get("score", 0) < 1.0:
        result = _build_result(l0=l0, l1=l1, l2=l2, l3=None,
                               signal="SKIP", reason="Layer 2 proximity not satisfied")
        _write(result)
        return result

    # ── Layer 3: Orderflow ────────────────────────────────────────────────────
    from layers.orderflow import get_orderflow
    l3 = get_orderflow(poc_level=poc_level)
    print(f"[L3] cvd={l3['cvd_velocity']}  imbalance={l3['imbalance_ratio']}  score={l3['score']}")

    if l3["score"] < 0.5:
        result = _build_result(l0=l0, l1=l1, l2=l2, l3=l3,
                               signal="SKIP", reason="No Layer 3 trigger fired")
        _write(result)
        return result

    if bias == "SKIP":
        result = _build_result(l0=l0, l1=l1, l2=l2, l3=l3,
                               signal="SKIP", reason="Ambiguous bias (no directional conviction)")
        _write(result)
        return result

    # ── All layers satisfied → ENTER ─────────────────────────────────────────
    spread_type = _determine_spread(bias, vix_mode, l0["strategy_set"])
    result = _build_result(l0=l0, l1=l1, l2=l2, l3=l3,
                           signal="ENTER", spread_type=spread_type)
    # Expose expiry for strike_selector
    result["expiry"] = l2.get("expiry", "")
    _write(result)
    return result


def _build_result(l0, l1, l2, l3, signal: str,
                  reason: str = "", spread_type: str = "NO_TRADE") -> dict:
    l0_score = l0["score"]             if l0 else 0.0
    l1_score = l1["score"]             if l1 else 0.0
    l2_score = l2.get("score", 0.0)    if l2 else 0.0
    l3_score = l3["score"]             if l3 else 0.0

    key_levels = {}
    if l2:
        key_levels = {
            "call_wall": l2.get("call_wall"),
            "put_wall":  l2.get("put_wall"),
            "max_pain":  l2.get("max_pain"),
            "spot":      l2.get("spot"),
        }

    return {
        "date":         str(date.today()),
        "generated":    datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "bias":         l1["bias"]     if l1 else "SKIP",
        "vix_mode":     l1["vix_mode"] if l1 else "UNKNOWN",
        "vix_close":    l1.get("vix_close") if l1 else None,
        "day_type":     l0["day_type"]     if l0 else "UNKNOWN",
        "strategy_set": l0["strategy_set"] if l0 else "SKIP",
        "spread_type":  spread_type,
        "signal":       signal,
        "reason":       reason,
        "total_score":  round(l0_score + l1_score + l2_score + l3_score, 2),
        "layer_scores": {"L0": l0_score, "L1": l1_score, "L2": l2_score, "L3": l3_score},
        "key_levels":   key_levels,
    }


def _write(result: dict):
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n{'='*50}")
    print(f"  SIGNAL  : {result['signal']}")
    print(f"  SPREAD  : {result['spread_type']}")
    print(f"  SCORE   : {result['total_score']}")
    if result["reason"]:
        print(f"  REASON  : {result['reason']}")
    print(f"{'='*50}")
    print(f"Written -> {OUTPUT_FILE}")


if __name__ == "__main__":
    run()
