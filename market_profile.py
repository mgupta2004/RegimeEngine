"""Layer 0 — Market Profile structural filter.

Classifies day-type from IB data and determines which strategy set is authorized.
Must be called after 10:15 IST when IB is frozen.
"""
from market_scanner import fetch_ohlcv, classify_ib


def get_market_profile() -> dict:
    """
    Returns:
        day_type: TREND | NORMAL | RANGE | NEUTRAL | UNKNOWN
        authorized: True if directional or condor trading is permitted
        strategy_set: DIRECTIONAL | IRON_CONDOR | SKIP
        score: 0.5 for TREND/NORMAL, 0.0 otherwise
        ib: raw IB dict from classify_ib()
    """
    df_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
    ib = classify_ib(df_15min)

    status = ib.get("status", "NO_DATA_TODAY")
    day_type = ib.get("day_type", "UNKNOWN")

    if status in ("PRE_MARKET", "IB_FORMING", "NO_DATA_TODAY"):
        return {
            "day_type": status,
            "authorized": False,
            "strategy_set": "SKIP",
            "score": 0.0,
            "ib": ib,
        }

    if day_type in ("TREND", "NORMAL"):
        return {
            "day_type": day_type,
            "authorized": True,
            "strategy_set": "DIRECTIONAL",
            "score": 0.5,
            "ib": ib,
        }

    if day_type == "RANGE":
        return {
            "day_type": day_type,
            "authorized": True,
            "strategy_set": "IRON_CONDOR",
            "score": 0.0,
            "ib": ib,
        }

    # NEUTRAL or UNKNOWN → mandatory skip
    return {
        "day_type": day_type,
        "authorized": False,
        "strategy_set": "SKIP",
        "score": 0.0,
        "ib": ib,
    }


if __name__ == "__main__":
    profile = get_market_profile()
    print(f"Day Type     : {profile['day_type']}")
    print(f"Strategy Set : {profile['strategy_set']}")
    print(f"Score        : {profile['score']}")
    print(f"IB           : {profile['ib']}")
