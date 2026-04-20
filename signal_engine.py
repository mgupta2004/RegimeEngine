"""Confluence scorer — aggregates Layers 0–3 and writes open_trade.json.

Run during the primary trade window (10:15–13:00 IST) after IB is frozen.
For the evening pre-computation workflow, run paper_trader.py first to get
swing bias, then call this once market opens and Layer 0 / Layer 2 / Layer 3
data is available.
"""
import os
import json
from datetime import datetime, date

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

IST = pytz.timezone("Asia/Kolkata")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "open_trade.json")


def _determine_spread(bias: str, vix_mode: str, strategy_set: str) -> str:
    if strategy_set == "IRON_CONDOR":
        return "IRON_CONDOR"
    if strategy_set == "SKIP":
        return "NO_TRADE"
    if vix_mode == "HIGH VOL":
        if bias == "LONG":
            return "BULL_PUT"   # credit spread
        if bias == "SHORT":
            return "BEAR_CALL"  # credit spread
        return "NO_TRADE"
    # Normal VIX
    if bias == "LONG":
        return "BULL_CALL"
    if bias == "SHORT":
        return "BEAR_PUT"
    return "NO_TRADE"


def run(poc_level: float = 0.0, mock_vix: float | None = None) -> dict:
    """
    Args:
        poc_level: Point of Control price level for orderflow scorer.
        mock_vix: Override VIX value for testing (e.g. mock_vix=23 to test HIGH VOL path).

    Returns the full signal dict and writes open_trade.json.
    """
    # ── Layer 0: Market Profile ───────────────────────────────────────────────
    from market_profile import get_market_profile
    l0 = get_market_profile()
    print(f"[L0] day_type={l0['day_type']}  strategy={l0['strategy_set']}  score={l0['score']}")

    if l0["strategy_set"] == "SKIP":
        result = _build_result(
            l0=l0, l1=None, l2=None, l3=None,
            signal="SKIP", reason="Layer 0 mandates SKIP"
        )
        _write(result)
        return result

    # ── Layer 1: Swing Bias ───────────────────────────────────────────────────
    from paper_trader import get_swing_bias
    l1 = get_swing_bias()
    if mock_vix is not None:
        from market_scanner import vix_regime
        l1["vix_mode"] = vix_regime(mock_vix)
        l1["vix_close"] = mock_vix
        l1["vix_override"] = mock_vix >= 22
        if l1["vix_override"]:
            l1["bias"] = "SKIP"
            l1["score"] = 0.0
    print(f"[L1] bias={l1['bias']}  vix_mode={l1['vix_mode']}  score={l1['score']}")

    vix_mode = l1["vix_mode"]
    bias     = l1["bias"]

    # ── Layer 2: OI Walls ─────────────────────────────────────────────────────
    from kite_oi_live import get_oi_levels
    l2 = get_oi_levels(vix_mode=vix_mode, bias_hint=bias)
    print(f"[L2] call_wall={l2.get('call_wall')}  put_wall={l2.get('put_wall')}  "
          f"pcr={l2.get('pcr')}  score={l2.get('score')}")

    # In HIGH VIX mode, OI layer determines bias when L1 bypassed
    if vix_mode == "HIGH VOL":
        pcr = l2.get("pcr", 1.0)
        max_pain = l2.get("max_pain", 0)
        spot = l2.get("spot", 0)
        if pcr > 1.20 and max_pain > spot:
            bias = "LONG"
            l1["bias"] = "LONG"
            l1["score"] = 1.0
        elif pcr < 0.80 and max_pain < spot:
            bias = "SHORT"
            l1["bias"] = "SHORT"
            l1["score"] = 1.0
        else:
            bias = "SKIP"

    # Minimum entry condition: L2 score >= 1.0
    if l2.get("score", 0) < 1.0:
        result = _build_result(
            l0=l0, l1=l1, l2=l2, l3=None,
            signal="SKIP", reason="Layer 2 proximity not satisfied"
        )
        _write(result)
        return result

    # ── Layer 3: Orderflow ────────────────────────────────────────────────────
    from kite_orderflow import get_orderflow
    l3 = get_orderflow(poc_level=poc_level)
    print(f"[L3] cvd={l3['cvd_velocity']}  imbalance={l3['imbalance_ratio']}  score={l3['score']}")

    # Minimum entry: at least one L3 trigger (score >= 0.5)
    if l3["score"] < 0.5:
        result = _build_result(
            l0=l0, l1=l1, l2=l2, l3=l3,
            signal="SKIP", reason="No Layer 3 trigger fired"
        )
        _write(result)
        return result

    if bias == "SKIP":
        result = _build_result(
            l0=l0, l1=l1, l2=l2, l3=l3,
            signal="SKIP", reason="Ambiguous bias (no directional conviction)"
        )
        _write(result)
        return result

    # ── All layers satisfied → ENTER ─────────────────────────────────────────
    spread_type = _determine_spread(bias, vix_mode, l0["strategy_set"])
    result = _build_result(l0=l0, l1=l1, l2=l2, l3=l3, signal="ENTER", spread_type=spread_type)
    _write(result)
    return result


def _build_result(l0, l1, l2, l3, signal: str,
                  reason: str = "", spread_type: str = "NO_TRADE") -> dict:
    l0_score = l0["score"] if l0 else 0.0
    l1_score = l1["score"] if l1 else 0.0
    l2_score = l2.get("score", 0.0) if l2 else 0.0
    l3_score = l3["score"] if l3 else 0.0

    key_levels = {}
    if l2:
        key_levels = {
            "call_wall": l2.get("call_wall"),
            "put_wall":  l2.get("put_wall"),
            "max_pain":  l2.get("max_pain"),
            "spot":      l2.get("spot"),
        }

    return {
        "date":        str(date.today()),
        "generated":   datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "bias":        l1["bias"] if l1 else "SKIP",
        "vix_mode":    l1["vix_mode"] if l1 else "UNKNOWN",
        "vix_close":   l1.get("vix_close") if l1 else None,
        "day_type":    l0["day_type"] if l0 else "UNKNOWN",
        "strategy_set": l0["strategy_set"] if l0 else "SKIP",
        "spread_type": spread_type,
        "signal":      signal,
        "reason":      reason,
        "total_score": round(l0_score + l1_score + l2_score + l3_score, 2),
        "layer_scores": {
            "L0": l0_score,
            "L1": l1_score,
            "L2": l2_score,
            "L3": l3_score,
        },
        "key_levels": key_levels,
    }


def _write(result: dict):
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n{'='*50}")
    print(f"  SIGNAL  : {result['signal']}")
    print(f"  SPREAD  : {result['spread_type']}")
    print(f"  SCORE   : {result['total_score']}")
    if result["reason"]:
        print(f"  REASON  : {result['reason']}")
    print(f"{'='*50}")
    print(f"Written → {OUTPUT_FILE}")


if __name__ == "__main__":
    import sys
    poc = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    mock = float(sys.argv[2]) if len(sys.argv) > 2 else None
    run(poc_level=poc, mock_vix=mock)
