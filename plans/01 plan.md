 Current State: What's Built

  The prototype covers the full signal pipeline but stops at open_trade.json. It does not execute, manage, or govern trades.

  ┌───────────────────┬────────────────────┬────────────────────────┐
  │       File        │       Layer        │         Status         │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ kite_login.py     │ Auth               │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ market_scanner.py │ Data/infra         │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ market_profile.py │ L0 — IB Day Type   │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ paper_trader.py   │ L1 — Swing Bias    │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ kite_oi_live.py   │ L2 — OI Walls      │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ kite_orderflow.py │ L3 — CVD/Orderflow │ ✅ Complete            │
  ├───────────────────┼────────────────────┼────────────────────────┤
  │ signal_engine.py  │ Orchestrator       │ ✅ Produces ENTER/SKIP │
  └───────────────────┴────────────────────┴────────────────────────┘

  ---
  Gaps vs. Spec

  Critical gaps (system can't trade without these):

  1. Fresh OI Build is always False — get_oi_levels() accepts prev_call_wall_oi / prev_put_wall_oi but callers never pass them. There's no OI snapshot history.
  2. No strike selection — when ENTER fires, nobody picks actual strikes for the spread legs.
  3. No order execution — no Kite place_order() calls for the spread.
  4. No risk governor — the 10 mandatory risk rules (1.5% daily loss cap, 3:20 PM hard exit, 09:15–09:25 buffer, 20% sizing cap, event blackouts) exist only in the spec.
  5. No position manager — no trailing stops, no P&L tracking, no re-evaluation of open legs.
  6. No daily cycle automation — the evening/morning/window phases run manually.

  Secondary gaps:
  - No POC computation (currently a manual poc_level argument)
  - No event blackout calendar (Rule 10)
  - Orderflow 60s warm-up on first call is fragile in live use

  ---
  Proposed Architecture

  RegimeEngine/
  │
  ├── data/                          # Kite API access layer
  │   ├── kite_client.py             # (refactor market_scanner.py) — single KiteConnect singleton
  │   ├── oi_store.py                # NEW — persists hourly OI snapshots to oi_history.json
  │   └── bhavcopy.py                # NEW — extracted from paper_trader.py
  │
  ├── layers/                        # Signal layers (mostly existing)
  │   ├── market_profile.py          # L0 — unchanged
  │   ├── swing_bias.py              # L1 — rename from paper_trader.py
  │   ├── oi_scanner.py              # L2 — thin rename; reads prev OI from oi_store
  │   └── orderflow.py               # L3 — rename from kite_orderflow.py
  │
  ├── engine/
  │   ├── signal_engine.py           # existing — unchanged orchestrator
  │   ├── strike_selector.py         # NEW — given bias+spread type, picks ATM/OTM strikes
  │   ├── strategy_builder.py        # NEW — constructs the 2-leg spread payload
  │   └── risk_manager.py            # NEW — enforces all 10 rules as pre/post guards
  │
  ├── execution/
  │   ├── order_manager.py           # NEW — kite.place_order() wrappers, idempotent
  │   └── position_manager.py        # NEW — tracks open legs, P&L, trailing stops
  │
  ├── automation/
  │   ├── evening_runner.py          # NEW — 18:00 cron: token refresh + swing bias
  │   ├── morning_monitor.py         # NEW — 09:15 loop: IB watch, CVD direction, OI
  │   └── trade_window.py            # NEW — 10:15–13:00: drives signal_engine → execution
  │
  ├── state/                         # JSON persistence (inter-session)
  │   ├── open_trade.json            # existing
  │   ├── daily_pnl.json             # NEW — running P&L, loss circuit breaker state
  │   └── oi_history.json            # NEW — hourly OI snapshots for fresh_build detection
  │
  ├── kite_login.py                  # unchanged
  └── market_scanner.py              # keep for market scanner skill; kite_client.py replaces its internals

  ---
  Key Design Decisions

  1. risk_manager.py as a guard, not a layer
  It wraps execution calls, not signal calls. Before any place_order(), it checks:
  - Daily P&L < 1.5% loss (from daily_pnl.json)
  - Time not in 09:15–09:25 buffer
  - Time not past 15:20 (15:15 for High VIX)
  - VIX > 22 → naked position rejected
  - Position size ≤ 20% of capital
  - Event blackout date → SKIP

  2. oi_store.py fixes the fresh_build bug
  A background loop (or called from morning_monitor.py) saves a timestamped OI snapshot every 30 minutes to oi_history.json. oi_scanner.py reads the snapshot from 30–60 mins
  ago for delta comparison. This makes fresh_build work correctly.

  3. strike_selector.py logic
  ATM = round(spot / 50) * 50       # nearest 50-point strike
  BULL_CALL : buy ATM CE, sell ATM+100 CE
  BEAR_PUT  : buy ATM PE, sell ATM-100 PE
  BULL_PUT  : sell ATM-50 PE, buy ATM-150 PE   (High VIX credit)
  BEAR_CALL : sell ATM+50 CE, buy ATM+150 CE   (High VIX credit)
  IRON_CONDOR: sell ATM+100 CE / ATM-100 PE, wings at ±150

  4. automation/ is Windows Task Scheduler driven
  Three tasks scheduled via schtasks (or APScheduler embedded):
  - 18:00 IST → evening_runner.py (token + swing bias)
  - 09:10 IST → morning_monitor.py (starts KiteTicker, monitors IB)
  - 10:15 IST → trade_window.py (calls signal_engine.run() → execution loop)

  5. Paper vs. Live mode
  order_manager.py takes a mode: Literal["paper", "live"] flag from env. In paper mode it logs to daily_pnl.json without calling Kite. This makes testing safe.
  BULL_CALL : buy ATM CE, sell ATM+100 CE
  BEAR_PUT  : buy ATM PE, sell ATM-100 PE
  BULL_PUT  : sell ATM-50 PE, buy ATM-150 PE   (High VIX credit)
  BEAR_CALL : sell ATM+50 CE, buy ATM+150 CE   (High VIX credit)
  IRON_CONDOR: sell ATM+100 CE / ATM-100 PE, wings at ±150

  4. automation/ is Windows Task Scheduler driven
  Three tasks scheduled via schtasks (or APScheduler embedded):
  - 18:00 IST → evening_runner.py (token + swing bias)
  - 09:10 IST → morning_monitor.py (starts KiteTicker, monitors IB)
  - 10:15 IST → trade_window.py (calls signal_engine.run() → execution loop)

  5. Paper vs. Live mode
  order_manager.py takes a mode: Literal["paper", "live"] flag from env. In paper mode it logs to daily_pnl.json without calling Kite. This makes testing safe.

  ---
  Build Sequence

  1. data/kite_client.py — deduplicate KiteConnect setup (currently repeated in 3 files)
  2. data/oi_store.py — fix the fresh_build gap
  3. engine/strike_selector.py + engine/strategy_builder.py
  4. engine/risk_manager.py — the 10 rules
  5. execution/order_manager.py (paper mode first)
  6. execution/position_manager.py
  7. automation/ — daily cycle runners
  8. Rename paper_trader.py → layers/swing_bias.py, kite_orderflow.py → layers/orderflow.py etc.

  Want me to start on any of these modules? The highest-leverage first step is kite_client.py (removes code duplication) followed immediately by oi_store.py (fixes the broken
  fresh_build detection).
