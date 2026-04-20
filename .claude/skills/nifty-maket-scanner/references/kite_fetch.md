# Kite Fetch Reference — Python Scaffold

Full script template for fetching market data via the Zerodha Kite Connect API and computing
the 21 EMA + IB classification for the Nifty Market Scanner skill.

---

## Prerequisites

```bash
pip install kiteconnect pandas tabulate pytz
```

Assumes `access_token` is already generated (via `kite_login.py` or stored in env).

---

## Complete Script

```python
import os
import math
from datetime import datetime, timedelta
import pytz
from kiteconnect import KiteConnect
import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────
API_KEY    = os.environ.get("KITE_API_KEY", "your_api_key")
ACCESS_TOKEN = os.environ.get("KITE_ACCESS_TOKEN", "your_access_token")

IST = pytz.timezone("Asia/Kolkata")

# ── Init ─────────────────────────────────────────────────────────────────────
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# ── Symbol Resolution ─────────────────────────────────────────────────────────
def get_active_future(exchange: str, name: str) -> str:
    """Return the tradingsymbol of the nearest-expiry futures contract."""
    instruments = kite.instruments(exchange)
    futures = [
        i for i in instruments
        if i["instrument_type"] == "FUT"
        and i["name"].upper() == name.upper()
    ]
    if not futures:
        raise ValueError(f"No futures found for {name} on {exchange}")
    # Sort by expiry ascending, pick nearest
    futures.sort(key=lambda x: x["expiry"])
    nearest = futures[0]
    return f"{exchange}:{nearest['tradingsymbol']}"

CRUDE_SYMBOL  = get_active_future("MCX", "CRUDEOIL")
USDINR_SYMBOL = get_active_future("NSE", "USDINR")   # NSE CDS segment

INSTRUMENTS = {
    "Nifty 50":  "NSE:NIFTY 50",
    "India VIX": "NSE:INDIA VIX",
    "Crude Oil": CRUDE_SYMBOL,
    "USD/INR":   USDINR_SYMBOL,
}

# ── EMA Computation ───────────────────────────────────────────────────────────
def compute_ema(closes: list, period: int = 21) -> list:
    """Returns list of EMA values, same length as closes."""
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
    """
    interval: "15minute" | "day"
    candles: number of candles to fetch
    Returns DataFrame with columns: date, open, high, low, close, volume
    """
    now = datetime.now(IST)

    if interval == "15minute":
        # 26 candles × 15min ≈ ~7 trading hours; fetch last 2 days to be safe
        from_date = now - timedelta(days=2)
    else:
        # Daily: fetch last 45 calendar days to ensure 30 trading days
        from_date = now - timedelta(days=45)

    try:
        exchange, tradingsymbol = symbol.split(":", 1)
        # Get instrument token
        instruments = kite.instruments(exchange)
        token = next(
            (i["instrument_token"] for i in instruments
             if i["tradingsymbol"] == tradingsymbol),
            None
        )
        if token is None:
            # Fallback for indices
            ltp_data = kite.ltp([symbol])
            token = ltp_data[symbol]["instrument_token"]

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
        print(f"  [ERROR] Could not fetch {symbol} ({interval}): {e}")
        return pd.DataFrame()

# ── IB Classification (Nifty only, intraday) ──────────────────────────────────
def classify_ib(df_15min: pd.DataFrame) -> dict:
    """
    Takes 15-min candles for today. Returns IB stats and day-type.
    IB = first 4 candles of session (09:15–10:15 IST).
    """
    now_ist = datetime.now(IST)
    today = now_ist.date()

    # Filter today's candles
    today_df = df_15min[df_15min["date"].dt.date == today].copy()

    if today_df.empty:
        return {"status": "NO_DATA_TODAY"}

    session_start = today_df["date"].min()
    market_open = session_start.replace(hour=9, minute=15, second=0)

    # Market hasn't opened yet
    if now_ist.replace(tzinfo=None) < market_open.replace(tzinfo=None):
        return {"status": "PRE_MARKET"}

    # IB candles: 09:15, 09:30, 09:45, 10:00
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

    # Post-IB candles
    post_ib = today_df.iloc[4:]
    if post_ib.empty:
        return {
            "status": "IB_COMPLETE",
            "ib_high": ib_high, "ib_low": ib_low, "ib_range": ib_range,
            "ib_extension": "NONE", "day_type": "UNKNOWN (no post-IB data)"
        }

    upper_ext = post_ib["high"].max() > ib_high
    lower_ext  = post_ib["low"].min() < ib_low

    if upper_ext and lower_ext:
        ib_extension = "BOTH"
        day_type = "NEUTRAL"
    elif upper_ext:
        ib_extension = "UPPER"
        # Check if move is substantial (> 1.5× IB range)
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
    else:
        return "HIGH VOL ⚠️"

# ── Main ──────────────────────────────────────────────────────────────────────
def run_scanner():
    results = {}

    for name, symbol in INSTRUMENTS.items():
        print(f"Fetching {name} ({symbol})...")
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
                "timestamp": str(last["date"]),
                "open":  round(last["open"], 2),
                "high":  round(last["high"], 2),
                "low":   round(last["low"], 2),
                "close": round(last["close"], 2),
                "volume": int(last.get("volume", 0)),
                "ema21": ema_vals[-1],
                "vs_ema": price_vs_ema(last["close"], ema_vals[-1]),
                "ema_slope": ema_slope(ema_vals),
            }

    # IB for Nifty intraday
    nifty_15min_df = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)  # extra candles for today
    ib_data = classify_ib(nifty_15min_df)

    # ── Print Tables ────────────────────────────────────────────────────────
    print("\n" + "="*70)
    print("NIFTY MARKET SCANNER")
    print("="*70)

    for section_label, tf_key in [("INTRADAY (15-min)", "intraday"), ("DAILY", "daily")]:
        print(f"\n── {section_label} ──")
        headers = ["Instrument", "Open", "High", "Low", "Close", "21 EMA", "vs EMA", "Slope"]
        rows = []
        for name in INSTRUMENTS:
            d = results[name].get(tf_key)
            if d:
                rows.append([
                    name, d["open"], d["high"], d["low"], d["close"],
                    d["ema21"], d["vs_ema"], d["ema_slope"]
                ])
            else:
                rows.append([name] + ["N/A"] * 7)

        # Simple tabular print
        col_w = [14, 9, 9, 9, 9, 9, 7, 8]
        fmt = "".join(f"{{:<{w}}}" for w in col_w)
        print(fmt.format(*headers))
        print("-" * sum(col_w))
        for row in rows:
            print(fmt.format(*[str(x) for x in row]))

    # IB Section
    print("\n── NIFTY IB STATUS ──")
    for k, v in ib_data.items():
        print(f"  {k:<18}: {v}")

    # VIX Regime
    vix_close = results["India VIX"].get("intraday", {})
    if vix_close:
        regime = vix_regime(vix_close["close"])
        print(f"\n── VIX REGIME ──")
        print(f"  VIX : {vix_close['close']}")
        print(f"  Mode: {regime}")

    # Timestamp
    print(f"\nData as of: {datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}")

if __name__ == "__main__":
    run_scanner()
```

---

## Environment Variables

Set these before running:

```bash
export KITE_API_KEY="xxxxxxxx"
export KITE_ACCESS_TOKEN="yyyyyyyyyyyyyyy"
```

Or load from a `.env` file using `python-dotenv`.

---

## Notes

- **Index instrument tokens**: Nifty 50 and India VIX don't appear in `kite.instruments("NSE")`
  the normal way. Use `kite.ltp(["NSE:NIFTY 50"])` to get the token, or hardcode:
  - Nifty 50 token: `256265`
  - India VIX token: `264969`

- **MCX Crude volume**: Available and meaningful. USDINR volume on CDS is also available.

- **Holidays / market closed**: `kite.historical_data()` simply returns no candles for closed
  days. The `df.tail(n)` call will just return the last available trading day's data.