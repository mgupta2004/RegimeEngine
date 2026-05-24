 RegimeEngine Implementation Plan                                                                                                                                                                                                                                                                                                                                Context                                                                                                                                                                                                                                                                                                                                                         The spec (specs/market-scaner-spec.md) defines a "3+1 Confluence System" for systematic NSE Nifty 50 derivatives trading. The codebase currently has only a skill scaffold     
 (kite_fetch.md) for raw market data display. All four signal-layer modules, the workflow orchestrator, and the signal engine are absent. This plan builds those modules
 incrementally, from data fetching through trade signal generation.

 ---
 Target File Structure

 RegimeEngine/
 ├── kite_login.py           # Token refresh utility (prerequisite for all)
 ├── market_scanner.py       # Market data fetcher (adapted from kite_fetch.md)
 ├── market_profile.py       # Layer 0 — IB classification, day-type gating
 ├── paper_trader.py         # Layer 1 — Swing bias from NSE EOD bhavcopy
 ├── kite_oi_live.py         # Layer 2 — OI walls, PCR, Max Pain, proximity
 ├── kite_orderflow.py       # Layer 3 — CVD velocity, Buy/Sell imbalance
 ├── signal_engine.py        # Confluence scorer → ENTER/SKIP + spread type
 ├── open_trade.json         # Daily output: bias, VIX mode, spread, score
 └── .env                    # KITE_API_KEY, KITE_ACCESS_TOKEN (gitignored)

 ---
 Module-by-Module Plan

 1. kite_login.py — Token Refresh

 - Launch Kite login URL, accept request_token from user input
 - Exchange for access_token via kite.generate_session()
 - Write KITE_ACCESS_TOKEN to .env
 - Reuse: env pattern from kite_fetch.md

 2. market_scanner.py — Market Data Fetcher

 - Direct port of references/kite_fetch.md scaffold into a runnable .py
 - Functions: get_active_future(), fetch_ohlcv(), compute_ema(), price_vs_ema(), ema_slope(), classify_ib(), vix_regime(), run_scanner()
 - Reuse: entire scaffold from kite_fetch.md + kite_instruments.md for caching
 - Outputs: structured dict (consumable by signal_engine.py) + formatted table print

 3. market_profile.py — Layer 0 (IB Structural Filter)

 - Call market_scanner.py's classify_ib() to get day_type
 - Map day_type → strategy authorization:
   - TREND / NORMAL → directional authorized, score += 0.5
   - RANGE → Iron Condor protocol, no directional trades
   - NEUTRAL → SKIP, score = 0
 - Returns: {"day_type": ..., "authorized": bool, "strategy_set": "DIRECTIONAL"|"IRON_CONDOR"|"SKIP", "score": 0.0|0.5}
 - Reuse: classify_ib() from market_scanner.py

 4. paper_trader.py — Layer 1 (Swing Bias)

 - Download NSE bhavcopy CSV from NSE website for prior trading day
 - Parse Nifty 50 OHLC; apply swing signal logic:
   - Close > 21 EMA AND close > prior-day high → Long bias (+1.0)
   - Close < 21 EMA AND close < prior-day low → Short bias (+1.0)
   - Otherwise → Skip (0.0)
 - VIX mode check: if VIX ≥ 22, bypass swing signal, shift to OI-driven PCR/Max Pain logic
 - Returns: {"bias": "LONG"|"SHORT"|"SKIP", "score": 0.0|1.0, "vix_mode": "NORMAL"|"HIGH_VIX"}

 5. kite_oi_live.py — Layer 2 (OI Walls)

 - Fetch option chain for Nifty weekly expiry via kite.instruments("NFO") + kite.ltp()
 - Identify Call Wall (strike with max call OI above spot) and Put Wall (max put OI below spot)
 - Compute:
   - pcr = total put OI / total call OI
   - max_pain = strike minimizing total option writer loss
   - proximity = whether spot is within 75pts (Normal) / 100pts (High VIX) of a wall → score += 1.0
   - fresh_oi_build = wall OI increased vs. prior fetch → score += 1.0
 - High VIX mode: require PCR > 1.20 + Max Pain > spot for bullish, PCR < 0.80 + Max Pain < spot for bearish
 - Returns: {"call_wall": ..., "put_wall": ..., "pcr": ..., "max_pain": ..., "proximity": bool, "fresh_build": bool, "score": 0.0–2.0}

 6. kite_orderflow.py — Layer 3 (Orderflow / CVD)

 - Subscribe to Nifty 50 tick stream via KiteTicker
 - Accumulate Cumulative Volume Delta (CVD): buy volume − sell volume per tick
 - Compute:
   - cvd_velocity: CVD change in last 15 min; "SURGE" if |delta| ≥ 30,000 → score += 1.0
   - imbalance: buy/sell ratio; "3:1" if ratio ≥ 3.0 at wall proximity → score += 1.0
   - cvd_consistency: % of ticks in dominant direction; "SUSTAINED" if > 60% → score += 0.5
   - spot_vs_poc: "ABOVE" adds +0.5 to score
 - Returns: {"cvd_velocity": ..., "imbalance_ratio": ..., "cvd_consistency": ..., "spot_vs_poc": ..., "score": 0.0–1.0}

 7. signal_engine.py — Confluence Scorer

 - Import and call all four layers
 - Aggregate scores per spec:
   - Layer 0: 0 or 0.5
   - Layer 1: 0 or 1.0
   - Layer 2: 0, 1.0, or 2.0 (proximity + fresh build)
   - Layer 3: 0.5 to 1.0
 - Minimum to ENTER: Layer 2 satisfied (≥ 1.0) AND at least one Layer 3 trigger (≥ 0.5)
 - Determine spread type:
   - Normal VIX + LONG → Bull Call Spread
   - Normal VIX + SHORT → Bear Put Spread
   - High VIX + LONG → Bull Put Spread (credit)
   - High VIX + SHORT → Bear Call Spread (credit)
   - RANGE day → Iron Condor
   - NEUTRAL or SKIP → No trade
 - Write open_trade.json:
 {
   "date": "2026-04-20",
   "bias": "LONG",
   "vix_mode": "NORMAL",
   "day_type": "TREND",
   "spread_type": "BULL_CALL",
   "signal": "ENTER",
   "total_score": 3.5,
   "layer_scores": { "L0": 0.5, "L1": 1.0, "L2": 2.0, "L3": 0.5 },
   "key_levels": { "call_wall": 24500, "put_wall": 24000, "max_pain": 24200 }
 }

 ---
 Implementation Order

 1. kite_login.py — prerequisite, needed for all API calls
 2. market_scanner.py — direct port from scaffold; test against live market data
 3. market_profile.py — wraps classify_ib() already in scanner
 4. paper_trader.py — standalone EOD script; runs evening only
 5. kite_oi_live.py — option chain fetch; test with current weekly expiry
 6. kite_orderflow.py — ticker-based; test during market hours
 7. signal_engine.py — orchestrates all layers; writes open_trade.json

 ---
 Risk Rules Not Implemented (Out of Scope)

 Per the spec's 10 risk rules, the following are explicitly excluded from this plan (UI/position management layer, not signal generation):
 - Max daily loss circuit breaker (Rule 1)
 - 3:20 PM hard exit (Rule 8)
 - Position sizing enforcement (Rule 7)

 ---
 Verification

 1. Evening workflow test: Run kite_login.py → paper_trader.py → verify open_trade.json contains bias + vix_mode
 2. Morning data test: During market hours, run market_scanner.py → confirm IB tables print with correct day-type
 3. OI test: Run kite_oi_live.py → verify call/put wall strike identification matches NSE option chain page
 4. Signal integration test: Run signal_engine.py → verify open_trade.json score matches manual Layer 0–3 calculation
 5. High VIX test: Set vix_mock = 23 in signal_engine, verify spread_type switches to credit spread and PCR/Max Pain logic activates