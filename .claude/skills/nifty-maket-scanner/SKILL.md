---
name: nifty-market-scanner
description: >
  Fetches and displays a raw market data table for Nifty 50 analysis using the Zerodha Kite API.
  Covers Nifty 50 index, India VIX, MCX Crude Oil, and USD/INR — with OHLCV, 21 EMA, and
  day-type classification across both intraday (15-min) and daily timeframes.
  Use this skill whenever the user asks about: current market conditions, Nifty levels, VIX regime,
  macro environment (crude/USDINR), EMA status, day-type (Trend/Range/Neutral), morning briefing,
  pre-market setup, or any phrase like "scan the market", "what's the market doing",
  "check Nifty", "show me the data", or "run the scanner". Trigger even for partial matches.
---

# Nifty Market Scanner Skill

Produces a structured raw data table across four instruments and two timeframes using the Zerodha
Kite API. The output is intentionally unfiltered — no trade signals, no recommendations. The user
interprets the data against their own framework.

---

## Instruments & Kite Symbols

| Instrument     | Kite Symbol         | Exchange  | Notes                          |
|----------------|---------------------|-----------|--------------------------------|
| Nifty 50 Index | `NSE:NIFTY 50`      | NSE       | Spot index price               |
| India VIX      | `NSE:INDIA VIX`     | NSE       | Volatility index               |
| Crude Oil      | `MCX:CRUDEOIL25JUNJUNE` | MCX   | Use nearest active contract    |
| USD/INR        | `NSE:USDINR25JUNJUNE`  | CDS/NSE  | Use nearest active contract    |

> **Active contract lookup**: Crude and USDINR symbols rotate monthly. Always call
> `kite.ltp(["MCX:CRUDEOIL*"])` or check `kite.instruments("MCX")` filtered by
> `instrument_type == "FUT"` and `expiry` nearest to today to resolve the live symbol.
> See `references/kite_instruments.md` for the lookup pattern.

---

## Two Timeframes

| Timeframe   | Interval        | Candles to fetch | Purpose                              |
|-------------|-----------------|------------------|--------------------------------------|
| **Intraday**| `15minute`      | Last 26 candles  | 21 EMA needs 21+ bars; IB detection  |
| **Daily**   | `day`           | Last 30 candles  | Trend context; daily 21 EMA          |

---

## Data Points to Compute Per Instrument

For each instrument × timeframe combination, extract and display:

### Price / OHLCV
- `open`, `high`, `low`, `close` (last completed candle)
- `volume` (where available; index = 0)

### 21 EMA
Formula: EMA(t) = Close(t) × k + EMA(t-1) × (1 − k), where k = 2 / (21 + 1)

```python
def ema21(closes):
    k = 2 / 22
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    return round(ema, 2)
```

Display: `ema21` value + `price_vs_ema` = "ABOVE" | "BELOW" | "AT" (within 0.1%)

### EMA Slope
Compare last two EMA values: "RISING" | "FALLING" | "FLAT" (< 0.05% change)

### For Nifty 50 only — Initial Balance (IB) classification
- IB = first 4 × 15-min candles of the session (09:15–10:15)
- `ib_high`, `ib_low`, `ib_range` (points)
- `ib_extension`: "NONE" | "UPPER" | "LOWER" | "BOTH"
- `day_type`:
  - "TREND" — IB extension ≥ 1 side, price moved > 1.5× IB range from IB boundary
  - "NORMAL" — IB extension on 1 side, moderate move
  - "RANGE" — price contained within IB for most of session
  - "NEUTRAL" — price returned to IB mid after extension (both sides touched)

---

## Output Format

Present as a clean markdown table. Two sections: **Intraday (15-min)** and **Daily**.

### Section 1 — Intraday Snapshot (15-min, last completed candle)

| Instrument  | Open   | High   | Low    | Close  | 21 EMA | vs EMA | EMA Slope |
|-------------|--------|--------|--------|--------|--------|--------|-----------|
| Nifty 50    | ...    | ...    | ...    | ...    | ...    | ABOVE  | RISING    |
| India VIX   | ...    | ...    | ...    | ...    | ...    | BELOW  | FLAT      |
| Crude Oil   | ...    | ...    | ...    | ...    | ...    | ABOVE  | RISING    |
| USD/INR     | ...    | ...    | ...    | ...    | ...    | BELOW  | FALLING   |

### Section 2 — Daily Snapshot (last completed daily candle)

Same columns as above.

### Section 3 — Nifty IB Status (only during market hours 09:15–15:30 IST)

| Field        | Value  |
|--------------|--------|
| IB High      | ...    |
| IB Low       | ...    |
| IB Range     | ... pts|
| IB Extension | UPPER  |
| Day Type     | TREND  |

### Section 4 — VIX Regime

| VIX Level | Regime      |
|-----------|-------------|
| < 14      | LOW VOL     |
| 14–22     | NORMAL      |
| ≥ 22      | HIGH VOL    |

Display current VIX and its regime label prominently.

---

## Python Scaffold

Read `references/kite_fetch.md` for the complete fetch-and-compute script that Claude should
generate or adapt when the user needs runnable code. The scaffold covers:
- Kite session init (assumes `access_token` already in environment or passed in)
- Instrument symbol resolution for active futures contracts
- Historical data fetch with error handling
- EMA computation
- IB classification logic
- Table rendering (pandas or plain print)

---

## Workflow

1. **Check if user wants code or a live pull**
   - If they want runnable Python → generate the script using the scaffold in `references/kite_fetch.md`
   - If they've already run the script and pasted output → parse and display the tables directly

2. **Symbol resolution first** — always resolve active Crude and USDINR contract symbols before
   fetching historical data. Use `kite.instruments()` lookup, not hardcoded expiry strings.

3. **Timezone** — Kite returns IST. All timestamps should be treated as Asia/Kolkata. Do not
   convert unless the user asks.

4. **Market hours awareness**
   - Before 09:15 or after 15:30 IST → IB section is N/A, note this clearly
   - Before 10:15 IST → IB is still forming, mark as "IB FORMING"

5. **Display the tables cleanly** — no signal interpretation, no commentary on what to trade.
   Add a single line at the bottom: `Data as of: <timestamp of last candle fetched>`

---

## Error Handling

| Error                        | Action                                              |
|------------------------------|-----------------------------------------------------|
| Token expired                | Tell user to re-run `kite_login.py` to refresh token|
| Symbol not found (futures)   | Run instruments lookup, show nearest expiry options |
| Insufficient history         | Note how many candles were available, compute EMA on available data |
| Market closed / holiday      | Show last available candle with a "MARKET CLOSED" label |