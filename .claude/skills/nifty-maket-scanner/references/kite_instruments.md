# Kite Instruments Reference — Active Contract Resolution

## Problem
MCX Crude Oil and NSE USD/INR futures symbols rotate every month (e.g., `CRUDEOIL25JUNJUNE`,
`USDINR25JUNJUNE`). Hardcoding these breaks every expiry cycle.

## Solution: Dynamic Resolution

```python
def get_active_future(kite, exchange: str, name: str) -> str:
    """Returns 'EXCHANGE:TRADINGSYMBOL' for nearest-expiry futures contract."""
    from datetime import date
    instruments = kite.instruments(exchange)
    futures = [
        i for i in instruments
        if i["instrument_type"] == "FUT"
        and i["name"].upper() == name.upper()
        and i["expiry"] >= date.today()   # exclude expired contracts
    ]
    if not futures:
        raise ValueError(f"No active futures found for {name} on {exchange}")
    futures.sort(key=lambda x: x["expiry"])
    return f"{exchange}:{futures[0]['tradingsymbol']}"

# Usage
crude  = get_active_future(kite, "MCX",  "CRUDEOIL")   # e.g. "MCX:CRUDEOIL25JULJUL"
usdinr = get_active_future(kite, "NSE",  "USDINR")     # e.g. "NSE:USDINR25JULJUN"
```

## Common Name Strings (case-insensitive)

| Instrument | Exchange | `name` field  |
|------------|----------|---------------|
| Crude Oil  | MCX      | `CRUDEOIL`    |
| USD/INR    | NSE      | `USDINR`      |

## Index Instrument Tokens (hardcoded — these never change)

| Instrument | Token  | Symbol          |
|------------|--------|-----------------|
| Nifty 50   | 256265 | NSE:NIFTY 50    |
| India VIX  | 264969 | NSE:INDIA VIX   |
| Bank Nifty | 260105 | NSE:NIFTY BANK  |

Use these tokens directly with `kite.historical_data(instrument_token=256265, ...)` to avoid
the instruments lookup overhead for indices.

## Cache Instruments to Avoid Rate Limits

`kite.instruments()` returns ~100k rows and counts against API rate limits. Cache it:

```python
import json, os
from datetime import date

CACHE_FILE = f"/tmp/kite_instruments_{date.today()}.json"

def get_instruments_cached(kite, exchange):
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            all_instruments = json.load(f)
    else:
        all_instruments = {}

    if exchange not in all_instruments:
        all_instruments[exchange] = kite.instruments(exchange)
        with open(CACHE_FILE, "w") as f:
            json.dump(all_instruments, f, default=str)

    return all_instruments[exchange]
```