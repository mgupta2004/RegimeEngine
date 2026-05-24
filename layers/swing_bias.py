"""Layer 1 — Swing Bias from Kite daily OHLCV.

Run in the evening (after 18:00 IST) to compute the next-day directional lean.
If VIX >= 22, swing signal is bypassed; OI-driven PCR/Max Pain logic
(resolved by layers/oi_scanner.py at runtime) determines bias instead.
"""
import pandas as pd
from data.kite_client import fetch_ohlcv, compute_ema, vix_regime


def compute_swing_bias(df_daily: pd.DataFrame) -> dict:
    """
    Swing signal:
      close > 21 EMA AND close > prior-day high  → LONG  (+1.0)
      close < 21 EMA AND close < prior-day low   → SHORT (+1.0)
      otherwise                                  → SKIP  (0.0)
    """
    if len(df_daily) < 3:
        return {"bias": "SKIP", "score": 0.0, "reason": "insufficient data"}

    closes    = df_daily["close"].tolist()
    ema_vals  = compute_ema(closes, 21)

    last_close = closes[-1]
    last_ema   = ema_vals[-1]
    prev_high  = df_daily["high"].iloc[-2]
    prev_low   = df_daily["low"].iloc[-2]

    if last_close > last_ema and last_close > prev_high:
        return {
            "bias":   "LONG",
            "score":  1.0,
            "reason": f"close {last_close} > EMA {last_ema:.2f} and prev high {prev_high}",
        }
    if last_close < last_ema and last_close < prev_low:
        return {
            "bias":   "SHORT",
            "score":  1.0,
            "reason": f"close {last_close} < EMA {last_ema:.2f} and prev low {prev_low}",
        }
    return {
        "bias":   "SKIP",
        "score":  0.0,
        "reason": f"close {last_close}, EMA {last_ema:.2f}, prev H/L {prev_high}/{prev_low}",
    }


def get_swing_bias() -> dict:
    """Entry point called by signal_engine.

    Returns:
        bias: LONG | SHORT | SKIP
        score: 0.0 | 1.0
        vix_mode: NORMAL | HIGH VOL | LOW VOL
        vix_override: True if HIGH VIX bypassed swing signal
    """
    df_daily = fetch_ohlcv("NSE:NIFTY 50", "day", 32)
    if df_daily.empty:
        return {"bias": "SKIP", "score": 0.0, "vix_mode": "UNKNOWN", "vix_override": False}

    df_vix    = fetch_ohlcv("NSE:INDIA VIX", "day", 5)
    vix_close = df_vix["close"].iloc[-1] if not df_vix.empty else 0.0
    mode      = vix_regime(vix_close)

    if mode == "HIGH VOL":
        return {
            "bias":        "SKIP",
            "score":       0.0,
            "vix_mode":    mode,
            "vix_close":   round(vix_close, 2),
            "vix_override": True,
            "note":        "HIGH VIX: bias determined by PCR/Max Pain in Layer 2",
        }

    swing = compute_swing_bias(df_daily)
    return {
        "bias":        swing["bias"],
        "score":       swing["score"],
        "vix_mode":    mode,
        "vix_close":   round(vix_close, 2),
        "vix_override": False,
        "reason":      swing["reason"],
    }


if __name__ == "__main__":
    result = get_swing_bias()
    print(f"Bias      : {result['bias']}")
    print(f"Score     : {result['score']}")
    print(f"VIX Mode  : {result['vix_mode']} ({result.get('vix_close', 'N/A')})")
    if result.get("vix_override"):
        print(f"Note      : {result['note']}")
    else:
        print(f"Reason    : {result.get('reason', '')}")
