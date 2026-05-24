 NSE Master Trading Logic — Full System Implementation Plan

 Context

 The RegimeEngine prototype implements all 4 signal layers (L0–L3) and produces open_trade.json
 with an ENTER/SKIP decision. The spec (specs/market-scaner-spec.md) requires a complete system:
 strike selection, order execution, position management, risk governance, and daily cycle automation.

 Three bugs exist in the prototype that must be fixed as part of this refactor:
 1. fresh_build is always False — callers never pass prior OI snapshots to get_oi_levels()
 2. poc_level is a manual argument — no automated POC derivation from market data
 3. Duplicate KiteConnect instances — each of market_scanner.py, kite_oi_live.py, and
 kite_orderflow.py creates its own separate client at import time

 ---
 Target Directory Structure

 RegimeEngine/                          ← run all scripts from here
 │
 ├── data/                              # Kite API access + persistence
 │   ├── __init__.py
 │   ├── kite_client.py                 # NEW — shared KiteConnect singleton
 │   └── oi_store.py                    # NEW — OI snapshot history (fixes fresh_build)
 │
 ├── layers/                            # Signal layers (moved/renamed from root)
 │   ├── __init__.py
 │   ├── market_profile.py              # MOVED from root (no logic change)
 │   ├── swing_bias.py                  # RENAMED from paper_trader.py
 │   ├── oi_scanner.py                  # RENAMED from kite_oi_live.py
 │   └── orderflow.py                   # RENAMED from kite_orderflow.py
 │
 ├── engine/                            # Orchestration + signal scoring
 │   ├── __init__.py
 │   ├── signal_engine.py               # MOVED from root + import updates
 │   ├── poc_calculator.py              # NEW — auto-derive POC from 15-min volume
 │   ├── strike_selector.py             # NEW — pick spread leg strikes
 │   └── risk_manager.py               # NEW — enforce all 10 rules
 │
 ├── execution/                         # Order placement + position lifecycle
 │   ├── __init__.py
 │   ├── order_manager.py               # NEW — paper/live order placement
 │   └── position_manager.py            # NEW — P&L, stop-loss, trailing, hard exit
 │
 ├── automation/                        # Daily cycle runners (scheduled scripts)
 │   ├── __init__.py
 │   ├── evening_runner.py              # NEW — 18:00: token refresh + swing bias pre-compute
 │   ├── morning_monitor.py             # NEW — 09:10: IB observation + CVD warm-up
 │   └── trade_window.py                # NEW — 10:15–13:00: signal → execution loop
 │
 ├── state/                             # JSON inter-session persistence
 │   ├── open_trade.json                # existing (signal_engine output)
 │   ├── oi_history.json                # NEW (written by oi_store.py)
 │   ├── daily_pnl.json                 # NEW (written by risk_manager + position_manager)
 │   └── positions.json                 # NEW (written by position_manager)
 │
 ├── market_scanner.py                  # KEEP at root — scanner skill depends on it
 │   └── (refactored to import get_kite() from data.kite_client)
 ├── kite_login.py                      # KEEP at root — standalone auth script
 ├── specs/                             # unchanged
 └── .env                               # add TRADE_MODE, TRADING_CAPITAL, NIFTY_LOT_SIZE

 ---
 Phase 1: Shared Infrastructure

 data/kite_client.py — Shared KiteConnect Singleton

 Extract common setup from market_scanner.py, kite_oi_live.py, kite_orderflow.py.

 # Public API
 def get_kite() -> KiteConnect: ...          # lazy singleton; reads KITE_API_KEY + ACCESS_TOKEN from .env
 def get_instruments(exchange: str) -> list: ... # cached; one call per exchange per process
 def resolve_token(symbol: str) -> int: ...  # "NSE:NIFTY 50" → 256265
 def get_active_future(exchange: str, name: str) -> str: ...   # nearest expiry futures symbol
 def fetch_ohlcv(symbol: str, interval: str, candles: int) -> pd.DataFrame: ...
 def compute_ema(closes: list, period: int = 21) -> list: ...
 def vix_regime(vix_close: float) -> str: ...  # "LOW VOL" | "NORMAL" | "HIGH VOL"

 INDEX_TOKENS = {"NSE:NIFTY 50": 256265, "NSE:INDIA VIX": 264969}

 Import refactor in existing files (one-line change each):

 ┌──────────────────────┬────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────┐
 │         File         │                         Remove                         │                                           Add                                           │
 ├──────────────────────┼────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
 │ market_scanner.py    │ module-level kite = KiteConnect(...) block (lines      │ from data.kite_client import get_kite, get_instruments, resolve_token, fetch_ohlcv,     │
 │                      │ 11–19)                                                 │ compute_ema, vix_regime                                                                 │
 ├──────────────────────┼────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
 │ layers/oi_scanner.py │ module-level kite = KiteConnect(...) block (lines      │ from data.kite_client import get_kite, get_instruments                                  │
 │                      │ 14–18)                                                 │                                                                                         │
 ├──────────────────────┼────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────┤
 │ layers/orderflow.py  │ kite_tmp = KiteConnect(...) in                         │ from data.kite_client import get_kite, get_instruments                                  │
 │                      │ _resolve_nifty_futures_token()                         │                                                                                         │
 └──────────────────────┴────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────┘

 market_scanner.py keeps all EMA display/IB/scanner logic — only the Kite setup lines change.

 ---
 data/oi_store.py — OI Snapshot History (fixes fresh_build)

 HISTORY_FILE = "state/oi_history.json"

 def save_snapshot(call_wall_oi: float, put_wall_oi: float) -> None:
     # Appends {"timestamp": ISO8601, "call_wall_oi": ..., "put_wall_oi": ...}
     # Prunes entries older than 24 hours

 def get_prior_snapshot(minutes_ago: int = 45) -> dict | None:
     # Returns snapshot closest to `minutes_ago` minutes in the past
     # Returns None if no snapshot exists in [30, 90] minute window

 engine/signal_engine.py change (the only caller of get_oi_levels):

 from data.oi_store import get_prior_snapshot, save_snapshot

 # Before calling get_oi_levels():
 prior = get_prior_snapshot(minutes_ago=45) or {}
 l2 = get_oi_levels(
     vix_mode=vix_mode, bias_hint=bias,
     prev_call_wall_oi=prior.get("call_wall_oi", 0),
     prev_put_wall_oi=prior.get("put_wall_oi", 0),
 )
 # After L2 returns, snapshot current OI for next cycle:
 save_snapshot(l2["call_wall_oi_raw"], l2["put_wall_oi_raw"])

 layers/oi_scanner.py must also return call_wall_oi_raw and put_wall_oi_raw in its dict
 (the raw OI integers, not just the scored booleans).

 ---
 Phase 2: Engine Additions

 engine/poc_calculator.py — Auto-derive POC

 def compute_poc(df_15min: pd.DataFrame) -> float:
     # Filters to today's candles only
     # Returns the midpoint price of the candle with the highest volume
     # Falls back to 0.0 if today has fewer than 4 candles (IB not frozen)

 engine/signal_engine.py change: replace poc_level parameter with auto-computation:

 from engine.poc_calculator import compute_poc
 from data.kite_client import fetch_ohlcv

 def run() -> dict:            # poc_level parameter removed
     df_15min = fetch_ohlcv("NSE:NIFTY 50", "15minute", 50)
     poc_level = compute_poc(df_15min)
     ...
     l3 = get_orderflow(poc_level=poc_level)

 ---
 engine/risk_manager.py — 10-Rule Guard

 BLACKOUT_DATES: set[date] = {
     # Populated manually each year: Union Budget, RBI Policy, FOMC dates
     date(2026, 2, 1),   # Union Budget
     ...
 }

 class RiskManager:
     def __init__(self, capital: float):
         self.capital = capital          # from TRADING_CAPITAL env var
         self._pnl = self._load_pnl()   # reads state/daily_pnl.json

     def check_entry_allowed(self, vix_mode: str) -> tuple[bool, str]:
         # Returns (allowed, reason). Checks in order:
         # 1. date.today() in BLACKOUT_DATES → ("event_blackout", False)
         # 2. current IST time 09:15–09:25 → ("10min_buffer", False)
         # 3. time >= 15:15 if HIGH VOL, >= 15:20 otherwise → ("past_exit_time", False)
         # 4. self._pnl["realized_pnl"] <= -0.015 * self.capital → ("loss_limit_hit", False)
         # 5. All pass → (True, "ok")

     def check_naked_allowed(self, vix_mode: str) -> bool:
         # False if vix_mode == "HIGH VOL" (Rule 4: hedge high VIX)

     def compute_position_lots(self, spread_ltp: float) -> int:
         # lots = floor(capital * 0.20 / (spread_ltp * LOT_SIZE))
         # Capped at 1 lot minimum

     def force_exit_required(self, vix_mode: str) -> bool:
         # True if time >= 15:15 (HIGH VOL) or >= 15:20 (NORMAL)

     def record_pnl(self, realized_pnl: float) -> None:
         # Appends trade to state/daily_pnl.json; resets file if date changed

     def is_loss_limit_hit(self) -> bool:
         return self._pnl["realized_pnl"] <= -0.015 * self.capital

 state/daily_pnl.json schema:
 {
   "date": "2026-05-23",
   "capital": 1000000,
   "realized_pnl": -4500,
   "trades": [{"time": "10:35 IST", "spread": "BULL_CALL", "pnl": -4500}]
 }

 ---
 engine/strike_selector.py — Spread Leg Construction

 LOT_SIZE = int(os.getenv("NIFTY_LOT_SIZE", "75"))

 def select_strikes(
     spread_type: str,    # BULL_CALL | BEAR_PUT | BULL_PUT | BEAR_CALL | IRON_CONDOR
     spot: float,
     call_wall: float | None,
     put_wall: float | None,
     max_pain: float,
     expiry: str,         # "YYYY-MM-DD" from oi_scanner
 ) -> list[dict]:
     # Returns leg specs — does NOT call Kite yet:
     # [{"strike": 24750, "option_type": "CE", "transaction_type": "BUY", "tradingsymbol": "NIFTY...CE"}]

 Strike logic (ATM = round(spot / 50) * 50):

 ┌─────────────┬────────────────────────────────────┬──────────────────────────────────────┬───────────────────┐
 │   Spread    │              Long Leg              │              Short Leg               │       Notes       │
 ├─────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────┤
 │ BULL_CALL   │ ATM CE (BUY)                       │ min(ATM+100, call_wall) CE (SELL)    │ debit, Normal VIX │
 ├─────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────┤
 │ BEAR_PUT    │ ATM PE (BUY)                       │ max(ATM-100, put_wall) PE (SELL)     │ debit, Normal VIX │
 ├─────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────┤
 │ BULL_PUT    │ ATM-150 PE (BUY)                   │ ATM-50 PE (SELL)                     │ credit, High VIX  │
 ├─────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────┤
 │ BEAR_CALL   │ ATM+150 CE (BUY)                   │ ATM+50 CE (SELL)                     │ credit, High VIX  │
 ├─────────────┼────────────────────────────────────┼──────────────────────────────────────┼───────────────────┤
 │ IRON_CONDOR │ ATM+200 CE (BUY), ATM-200 PE (BUY) │ ATM+100 CE (SELL), ATM-100 PE (SELL) │ Range day         │
 └─────────────┴────────────────────────────────────┴──────────────────────────────────────┴───────────────────┘

 Tradingsymbol lookup: scan NFO instruments filtered to name=="NIFTY", expiry==expiry, strike==strike, instrument_type==option_type. Raise ValueError if not found.

 ---
 Phase 3: Execution Layer

 execution/order_manager.py — Paper / Live Orders

 TRADE_MODE = os.getenv("TRADE_MODE", "paper")   # "paper" | "live"

 def place_spread(legs: list[dict], lots: int) -> dict:
     # Paper: logs to state/daily_pnl.json, returns fake order IDs
     # Live: calls get_kite().place_order() per leg
     #   product=MIS (intraday), order_type=LIMIT, price=LTP, exchange=NFO
     # Returns {"order_ids": [...], "mode": "paper"|"live", "legs": [...]}

 def get_ltp(tradingsymbol: str) -> float:
     # kite.ltp(["NFO:<symbol>"])["NFO:<symbol>"]["last_price"]

 def exit_spread(legs: list[dict], order_ids: list[str]) -> dict:
     # Reverses each leg at market price (MARKET order type)
     # Paper: computes exit LTP and returns net P&L

 ---
 execution/position_manager.py — Trade Lifecycle

 POSITIONS_FILE = "state/positions.json"

 class PositionManager:
     def open_position(self, legs: list[dict], spread_type: str,
                       entry_net_premium: float, stop_loss_spot: float,
                       target_spot: float, order_ids: list[str]) -> None:
         # Writes to state/positions.json

     def has_open_position(self) -> bool: ...

     def get_current_pnl(self) -> float:
         # Fetches LTP for all open legs, returns net unrealized P&L in rupees

     def check_stop_loss(self, current_spot: float) -> bool:
         # True if current_spot breached stop_loss_spot (50-pt for Normal, per spec)
         # Also True if spread debit-to-close > 2x credit received (High VIX rule)

     def is_near_max_pain(self, max_pain: float, current_spot: float,
                          threshold: float = 25.0) -> bool: ...

     def close_all(self, reason: str) -> float:
         # Places exit orders via order_manager.exit_spread()
         # Returns realized P&L, clears positions.json, writes to daily_pnl.json

     def stop_loss_for_spread(self, spread_type: str, key_levels: dict) -> tuple[float, float]:
         # Returns (stop_loss_spot, target_spot) per spec rules:
         # Normal: SL = anchor OI wall ± 50 pts; Target = next OI wall or max_pain
         # High VIX: SL tracked by premium (2x credit rule), target = max_pain

 state/positions.json schema:
 {
   "date": "2026-05-23",
   "spread_type": "BULL_CALL",
   "legs": [
     {"tradingsymbol": "NIFTY23MAY24750CE", "transaction_type": "BUY",
      "order_id": "...", "entry_ltp": 120.5, "lots": 1},
     {"tradingsymbol": "NIFTY23MAY24850CE", "transaction_type": "SELL",
      "order_id": "...", "entry_ltp": 62.0, "lots": 1}
   ],
   "entry_net_premium": 58.5,
   "stop_loss_spot": 24700,
   "target_spot": 24850,
   "status": "open"
 }

 ---
 Phase 4: Automation

 automation/trade_window.py — Primary Window (10:15–13:00)

 def run():
     risk = RiskManager(capital=float(os.getenv("TRADING_CAPITAL", "1000000")))
     pm = PositionManager()

     while True:
         now_ist = datetime.now(IST)
         signal = engine.signal_engine.run()          # returns full signal dict
         vix_mode = signal["vix_mode"]

         # Hard exit check first
         if risk.force_exit_required(vix_mode) or risk.is_loss_limit_hit():
             if pm.has_open_position():
                 pnl = pm.close_all("hard_exit")
                 risk.record_pnl(pnl)
             break

         # Monitor open position
         if pm.has_open_position():
             spot = signal["key_levels"].get("spot", 0)
             if pm.check_stop_loss(spot):
                 pnl = pm.close_all("stop_loss")
                 risk.record_pnl(pnl)
             elif pm.is_near_max_pain(signal["key_levels"]["max_pain"], spot):
                 pnl = pm.close_all("target_max_pain")
                 risk.record_pnl(pnl)

         # New entry
         elif signal["signal"] == "ENTER":
             allowed, reason = risk.check_entry_allowed(vix_mode)
             if allowed:
                 legs = strike_selector.select_strikes(
                     spread_type=signal["spread_type"],
                     spot=signal["key_levels"]["spot"],
                     call_wall=signal["key_levels"]["call_wall"],
                     put_wall=signal["key_levels"]["put_wall"],
                     max_pain=signal["key_levels"]["max_pain"],
                     expiry=signal.get("expiry", ""),
                 )
                 lots = risk.compute_position_lots(spread_ltp=_estimate_premium(legs))
                 result = order_manager.place_spread(legs, lots)
                 sl, target = pm.stop_loss_for_spread(signal["spread_type"], signal["key_levels"])
                 pm.open_position(legs, signal["spread_type"],
                                  entry_net_premium=_estimate_premium(legs),
                                  stop_loss_spot=sl, target_spot=target,
                                  order_ids=result["order_ids"])

         time.sleep(300)   # re-evaluate every 5 minutes

 automation/morning_monitor.py — Observation Phase (09:10–10:15)

 def run():
     # 09:10: Start KiteTicker for orderflow warm-up (layers/orderflow.py)
     # 09:15: Print IB high/low as it forms; log CVD direction every 5 mins
     # 10:00: Save OI snapshot to oi_history.json (baseline for fresh_build)
     # 10:15: Print frozen IB + day_type, then exit (trade_window.py takes over)
     # Throughout: Weekday guard at startup (skip weekends)

 automation/evening_runner.py — Evening Phase (post-18:00)

 def run():
     # 1. Remind user to refresh Kite token (kite_login.py must be run manually)
     # 2. swing_bias = layers.swing_bias.get_swing_bias()
     # 3. Write preliminary open_trade.json (bias + vix_mode only, no entry signal yet)
     # 4. Reset state/daily_pnl.json for next trading day
     # 5. Save current OI snapshot as overnight baseline

 ---
 Windows Task Scheduler Registration

 Script: setup_scheduler.bat (created once, run as Administrator):

 schtasks /create /tn "RegimeEngine_Evening" /tr "python D:\Synaptic\MasterTradingLogic\RegimeEngine\automation\evening_runner.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:00
 schtasks /create /tn "RegimeEngine_Morning" /tr "python D:\Synaptic\MasterTradingLogic\RegimeEngine\automation\morning_monitor.py" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:10
 schtasks /create /tn "RegimeEngine_TradeWindow" /tr "python D:\Synaptic\MasterTradingLogic\RegimeEngine\automation\trade_window.py" /sc weekly /d MON,TUE,WED,THU,FRI /st
 10:15

 Each script has a weekday guard and holiday check at startup.

 ---
 .env Additions Required

 # Existing
 KITE_API_KEY=...
 KITE_ACCESS_TOKEN=...
 KITE_API_SECRET=...
 KITE_USER_ID=...
 KITE_USER_PASSWORD=...
 KITE_TOTP_KEY=...

 # New
 TRADE_MODE=paper             # "paper" | "live" — safe default
 TRADING_CAPITAL=1000000      # INR, used for 1.5% loss cap and 20% sizing
 NIFTY_LOT_SIZE=75            # update if SEBI changes contract size

 ---
 Build Sequence

 ┌──────┬──────────────────────────────────────────────────────────────────────────┬────────────────────────────────────────────────────┐
 │ Step │                                 File(s)                                  │                  What it delivers                  │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 1    │ data/__init__.py, data/kite_client.py                                    │ Shared Kite singleton; fixes duplicate connections │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 2    │ Refactor market_scanner.py, kite_oi_live.py, kite_orderflow.py           │ Import from kite_client; no logic change           │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 3    │ Move files to layers/, engine/; add __init__.py files                    │ Package layout; update all imports                 │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 4    │ data/oi_store.py + update engine/signal_engine.py                        │ Fixes fresh_build always-False bug                 │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 5    │ engine/poc_calculator.py + remove poc_level arg from signal_engine.run() │ Auto POC; no manual arg needed                     │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 6    │ engine/risk_manager.py                                                   │ 10 rules enforced; daily_pnl.json written          │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 7    │ engine/strike_selector.py                                                │ Strike selection for all spread types              │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 8    │ execution/order_manager.py (paper mode only)                             │ End-to-end paper trade placement                   │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 9    │ execution/position_manager.py                                            │ Stop-loss, P&L tracking, hard exit                 │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 10   │ automation/trade_window.py                                               │ Full signal→risk→execute loop                      │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 11   │ automation/morning_monitor.py, automation/evening_runner.py              │ Daily cycle                                        │
 ├──────┼──────────────────────────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
 │ 12   │ setup_scheduler.bat                                                      │ Windows Task Scheduler wiring                      │
 └──────┴──────────────────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────┘

 ---
 Verification

 1. Kite singleton: import data.kite_client and layers.oi_scanner in a REPL; confirm only one KiteConnect.__init__ call via logging.
 2. fresh_build fix: run data/oi_store.py standalone, save a snapshot, wait 1 min, save another, call get_prior_snapshot(minutes_ago=1) — confirm it returns the first
 snapshot.
 3. POC calculator: feed it a fabricated 15-min DataFrame with one high-volume candle; confirm it returns that candle's midprice.
 4. Risk manager: construct RiskManager(capital=100000), write a daily_pnl.json with realized_pnl=-1600 (> 1.5% of 100k), call check_entry_allowed()— confirm (False,
 "loss_limit_hit").
 5. Strike selector: given spot=24000, spread_type="BULL_CALL", call_wall=24300, confirm legs hit 24000 CE BUY and 24100 CE SELL (min of ATM+100 vs call_wall).
 6. Paper trade integration: set TRADE_MODE=paper, run automation/trade_window.py after 10:15 IST, confirm state/positions.json and state/daily_pnl.json are written without
 any live Kite orders.
 7. Signal regression: after the refactor, run python -m engine.signal_engine and verify open_trade.json output is identical in schema to what the prototype produced.
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
