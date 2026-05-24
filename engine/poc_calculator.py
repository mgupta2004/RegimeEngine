"""Derive the Point of Control (POC) from today's 15-min OHLCV data.

POC = price level with the highest traded volume today.
Approximated as the midpoint of the highest-volume 15-min candle.
"""
from datetime import datetime

import pandas as pd
import pytz

IST = pytz.timezone("Asia/Kolkata")


def compute_poc(df_15min: pd.DataFrame) -> float:
    """Return the approximate POC price from today's 15-min candles.

    Falls back to 0.0 if the IB is not yet frozen (fewer than 4 today candles).
    """
    if df_15min.empty or "date" not in df_15min.columns:
        return 0.0

    today    = datetime.now(IST).date()
    today_df = df_15min[df_15min["date"].dt.date == today]

    if len(today_df) < 4:
        return 0.0

    idx_max = today_df["volume"].idxmax()
    row     = today_df.loc[idx_max]
    return round((row["high"] + row["low"]) / 2, 2)
