"""Shared KiteConnect singleton and common data utilities.

All modules import from here instead of creating their own KiteConnect instances.
Token is read from .env (written by kite_login.py via dotenv set_key).
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta, date

import pytz
import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST = pytz.timezone("Asia/Kolkata")

API_KEY      = os.environ.get("KITE_API_KEY", "")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

_log = logging.getLogger(__name__)

# ── Singleton ─────────────────────────────────────────────────────────────────

_kite: KiteConnect | None = None


def get_kite() -> KiteConnect:
    """Return the shared KiteConnect instance, creating it on first call."""
    global _kite
    if _kite is None:
        _log.debug("KiteConnect: initialising singleton")
        _kite = KiteConnect(api_key=API_KEY)
        _kite.set_access_token(ACCESS_TOKEN)
    return _kite


# ── Instrument Cache ──────────────────────────────────────────────────────────

_instruments_cache: dict[str, list] = {}

INDEX_TOKENS: dict[str, int] = {
    "NSE:NIFTY 50":  256265,
    "NSE:INDIA VIX": 264969,
}


def get_instruments(exchange: str) -> list:
    """Return instrument list for exchange, cached for the process lifetime."""
    if exchange not in _instruments_cache:
        _instruments_cache[exchange] = get_kite().instruments(exchange)
    return _instruments_cache[exchange]


def resolve_token(symbol: str) -> int:
    """Resolve 'EXCHANGE:TRADINGSYMBOL' to an instrument token."""
    if symbol in INDEX_TOKENS:
        return INDEX_TOKENS[symbol]
    exchange, tradingsymbol = symbol.split(":", 1)
    for inst in get_instruments(exchange):
        if inst["tradingsymbol"] == tradingsymbol:
            return inst["instrument_token"]
    raise ValueError(f"Token not found for {symbol}")


def get_active_future(exchange: str, name: str) -> str:
    """Return 'EXCHANGE:TRADINGSYMBOL' for the nearest active futures contract."""
    futures = [
        i for i in get_instruments(exchange)
        if i["instrument_type"] == "FUT"
        and i["name"].upper() == name.upper()
        and i["expiry"] >= date.today()
    ]
    if not futures:
        raise ValueError(f"No active futures for {name} on {exchange}")
    futures.sort(key=lambda x: x["expiry"])
    return f"{exchange}:{futures[0]['tradingsymbol']}"


# ── OHLCV Fetch ───────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str, candles: int) -> pd.DataFrame:
    """Fetch historical OHLCV candles from Kite.

    Args:
        symbol:   e.g. "NSE:NIFTY 50"
        interval: "15minute" | "day" | "60minute" etc.
        candles:  number of candles to return (tail)
    """
    now = datetime.now(IST)
    lookback_days = 2 if interval == "15minute" else 45
    from_date = now - timedelta(days=lookback_days)

    try:
        token = resolve_token(symbol)
        data = get_kite().historical_data(
            instrument_token=token,
            from_date=from_date.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=now.strftime("%Y-%m-%d %H:%M:%S"),
            interval=interval,
            continuous=False,
            oi=False,
        )
        df = pd.DataFrame(data)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df.tail(candles).reset_index(drop=True)
    except Exception as exc:
        _log.error("fetch_ohlcv %s (%s): %s", symbol, interval, exc)
        return pd.DataFrame()


# ── EMA Utilities ─────────────────────────────────────────────────────────────

def compute_ema(closes: list, period: int = 21) -> list:
    k = 2 / (period + 1)
    ema_vals = [closes[0]]
    for c in closes[1:]:
        ema_vals.append(c * k + ema_vals[-1] * (1 - k))
    return [round(e, 2) for e in ema_vals]


def price_vs_ema(price: float, ema: float) -> str:
    pct = abs(price - ema) / ema
    if pct <= 0.001:
        return "AT"
    return "ABOVE" if price > ema else "BELOW"


def ema_slope(ema_values: list) -> str:
    if len(ema_values) < 2:
        return "FLAT"
    change_pct = (ema_values[-1] - ema_values[-2]) / ema_values[-2]
    if change_pct > 0.0005:
        return "RISING"
    if change_pct < -0.0005:
        return "FALLING"
    return "FLAT"


# ── VIX Regime ────────────────────────────────────────────────────────────────

def vix_regime(vix_close: float) -> str:
    if vix_close < 14:
        return "LOW VOL"
    if vix_close < 22:
        return "NORMAL"
    return "HIGH VOL"


# ── IB Classification ─────────────────────────────────────────────────────────

def classify_ib(df_15min: pd.DataFrame) -> dict:
    """Classify day type from 15-min candles using Initial Balance logic."""
    if df_15min.empty or "date" not in df_15min.columns:
        return {"status": "NO_DATA_TODAY"}

    now_ist = datetime.now(IST)
    today = now_ist.date()

    today_df = df_15min[df_15min["date"].dt.date == today].copy()
    if today_df.empty:
        return {"status": "NO_DATA_TODAY"}

    if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
        return {"status": "PRE_MARKET"}

    ib_candles = today_df.head(4)   # 09:15–10:15 = 4 × 15-min candles
    if len(ib_candles) < 4:
        return {
            "status": "IB_FORMING",
            "candles_so_far": len(ib_candles),
            "ib_high": round(ib_candles["high"].max(), 2),
            "ib_low":  round(ib_candles["low"].min(), 2),
        }

    ib_high  = round(ib_candles["high"].max(), 2)
    ib_low   = round(ib_candles["low"].min(), 2)
    ib_range = round(ib_high - ib_low, 2)

    post_ib = today_df.iloc[4:]
    if post_ib.empty:
        return {
            "status": "IB_COMPLETE",
            "ib_high": ib_high, "ib_low": ib_low, "ib_range": ib_range,
            "ib_extension": "NONE", "day_type": "UNKNOWN",
        }

    upper_ext = post_ib["high"].max() > ib_high
    lower_ext  = post_ib["low"].min() < ib_low

    if upper_ext and lower_ext:
        ib_extension, day_type = "BOTH", "NEUTRAL"
    elif upper_ext:
        ib_extension = "UPPER"
        move = post_ib["high"].max() - ib_high
        day_type = "TREND" if move > 1.5 * ib_range else "NORMAL"
    elif lower_ext:
        ib_extension = "LOWER"
        move = ib_low - post_ib["low"].min()
        day_type = "TREND" if move > 1.5 * ib_range else "NORMAL"
    else:
        ib_extension, day_type = "NONE", "RANGE"

    return {
        "status": "IB_COMPLETE",
        "ib_high": ib_high,
        "ib_low":  ib_low,
        "ib_range": ib_range,
        "ib_extension": ib_extension,
        "day_type": day_type,
    }
