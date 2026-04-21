import os
import json
from datetime import datetime, timedelta
import pytz
from kiteconnect import KiteConnect
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

API_KEY     = os.environ.get("KITE_API_KEY", "")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "")

print(API_KEY, ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# ── Instrument Cache ──────────────────────────────────────────────────────────
_instruments_cache: dict = {}

def _get_instruments(exchange: str) -> list:
    if exchange not in _instruments_cache:
        _instruments_cache[exchange] = kite.instruments(exchange)
    return _instruments_cache[exchange]

def get_active_future(exchange: str, name: str) -> str:
    from datetime import date
    instruments = _get_instruments(exchange)
    futures = [
        i for i in instruments
        if i["instrument_type"] == "FUT"
        and i["name"].upper() == name.upper()
        and i["expiry"] >= date.today()
    ]
    if not futures:
        raise ValueError(f"No active futures for {name} on {exchange}")
    futures.sort(key=lambda x: x["expiry"])
    return f"{exchange}:{futures[0]['tradingsymbol']}"

# Static index tokens (never change)
INDEX_TOKENS = {
    "NSE:NIFTY 50":  256265,
    "NSE:INDIA VIX": 264969,
}

def _resolve_token(symbol: str) -> int:
    if symbol in INDEX_TOKENS:
        return INDEX_TOKENS[symbol]
    exchange, tradingsymbol = symbol.split(":", 1)
    instruments = _get_instruments(exchange)
    for i in instruments:
        if i["tradingsymbol"] == tradingsymbol:
            return i["instrument_token"]
    raise ValueError(f"Token not found for {symbol}")

# ── EMA Computation ───────────────────────────────────────────────────────────
def compute_ema(closes: list, period: int = 21) -> list:
    k = 2 / (period + 1)
    ema_values = [closes[0]]
    for c in closes[1:]:
        ema_values.append(c * k + ema_values[-1] * (1 - k))
    return [round(e, 2) for e in ema_values]

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
    elif change_pct < -0.0005:
        return "FALLING"
    return "FLAT"

# ── Fetch Historical Data ─────────────────────────────────────────────────────
def fetch_ohlcv(symbol: str, interval: str, candles: int) -> pd.DataFrame:
    now = datetime.now(IST)
    from_date = now - timedelta(days=2 if interval == "15minute" else 45)

    try:
        token = _resolve_token(symbol)
        data = kite.historical_data(
            instrument_token=token,
            from_date=from_date.strftime("%Y-%m-%d %H:%M:%S"),
            to_date=now.strftime("%Y-%m-%d %H:%M:%S"),
            interval=interval,
            continuous=False,
            oi=False,
        )
        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"])
        return df.tail(candles).reset_index(drop=True)
    except Exception as e:
        print(f"  [ERROR] {symbol} ({interval}): {e}")
        return pd.DataFrame()

# ── IB Classification ─────────────────────────────────────────────────────────
def classify_ib(df_15min: pd.DataFrame) -> dict:
    if df_15min.empty or "date" not in df_15min.columns:
        return {"status": "NO_DATA_TODAY"}

    now_ist = datetime.now(IST)
    today = now_ist.date()

    today_df = df_15min[df_15min["date"].dt.date == today].copy()
    if today_df.empty:
        return {"status": "NO_DATA_TODAY"}

    if now_ist.hour < 9 or (now_ist.hour == 9 and now_ist.minute < 15):
        return {"status": "PRE_MARKET"}

    ib_candles = today_df.head(4)
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
        ib_extension = "BOTH"
        day_type = "NEUTRAL"
    elif upper_ext:
        ib_extension = "UPPER"
        move = post_ib["high"].max() - ib_high
        day_type = "TREND" if move > 1.5 * ib_range else "NORMAL"
    elif lower_ext:
        ib_extension = "LOWER"
        move = ib_low - post_ib["low"].min()
        day_type = "TREND" if move > 1.5 * ib_range else "NORMAL"
    else:
        ib_extension = "NONE"
        day_type = "RANGE"

    return {
        "status": "IB_COMPLETE",
        "ib_high": ib_high,
        "ib_low":  ib_low,
        "ib_range": ib_range,
        "ib_extension": ib_extension,
        "day_type": day_type,
    }

# ── VIX Regime ────────────────────────────────────────────────────────────────
def vix_regime(vix_close: float) -> str:
    if vix_close < 14:
        return "LOW VOL"
    elif vix_close < 22:
        return "NORMAL"
    return "HIGH VOL"

# ── Main Scanner ──────────────────────────────────────────────────────────────
def run_scanner() -> dict:
    crude_symbol  = get_active_future("MCX", "CRUDEOIL")
    usdinr_symbol = get_active_future("NSE", "USDINR")

    instruments = {
        "Nifty 50":  "NSE:NIFTY 50",
        "India VIX": "NSE:INDIA VIX",
        "Crude Oil": crude_symbol,
        "USD/INR":   usdinr_symbol,
    }

    results: dict = {}
    for name, symbol in instruments.items():
        results[name] = {}
        for tf, interval, n_candles in [("intraday", "15minute", 26), ("daily", "day", 30)]:
            df = fetch_ohlcv(symbol, interval, n_candles)
            if df.empty:
                results[name][tf] = None
                continue
            closes = df["close"].tolist()
            ema_vals = compute_ema(closes, 21)
            last = df.iloc[-1]
            results[name][tf] = {
                "timestamp":  str(last["date"]),
                "open":       round(last["open"], 2),
                "high":       round(last["high"], 2),
                "low":        round(last["low"], 2),
                "close":      round(last["close"], 2),
                "volume":     int(last.get("volume", 0)),
                "ema21":      ema_vals[-1],
                "vs_ema":     price_vs_ema(last["close"], ema_vals[-1]),
                "ema_slope":  ema_slope(ema_vals),
            }

    # IB — fetch extra candles to cover full today
    nifty_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
    ib_data = classify_ib(nifty_15min)

    vix_intraday = results["India VIX"].get("intraday")
    vix_close = vix_intraday["close"] if vix_intraday else None
    vix_mode = vix_regime(vix_close) if vix_close else "UNKNOWN"

    _print_tables(results, ib_data, vix_close, vix_mode)

    return {
        "instruments": results,
        "ib": ib_data,
        "vix_close": vix_close,
        "vix_mode": vix_mode,
    }

def _print_tables(results: dict, ib_data: dict, vix_close, vix_mode: str):
    print("\n" + "=" * 74)
    print("  NIFTY MARKET SCANNER")
    print("=" * 74)

    col_w = [14, 9, 9, 9, 9, 9, 7, 9]
    headers = ["Instrument", "Open", "High", "Low", "Close", "21 EMA", "vs EMA", "Slope"]
    fmt = "".join(f"{{:<{w}}}" for w in col_w)

    for label, tf_key in [("INTRADAY (15-min)", "intraday"), ("DAILY", "daily")]:
        print(f"\n── {label} ──")
        print(fmt.format(*headers))
        print("-" * sum(col_w))
        for name, data in results.items():
            d = data.get(tf_key)
            if d:
                row = [name, d["open"], d["high"], d["low"], d["close"], d["ema21"], d["vs_ema"], d["ema_slope"]]
            else:
                row = [name] + ["N/A"] * 7
            print(fmt.format(*[str(x) for x in row]))

    print("\n── NIFTY IB STATUS ──")
    for k, v in ib_data.items():
        print(f"  {k:<18}: {v}")

    if vix_close:
        print(f"\n── VIX REGIME ──")
        print(f"  VIX  : {vix_close}")
        print(f"  Mode : {vix_mode}")

    print(f"\nData as of: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")

if __name__ == "__main__":
    run_scanner()
