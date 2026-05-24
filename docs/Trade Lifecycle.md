
● ╔══════════════════════════════════════════════════════════════════════════════════════╗
  ║                        REGIME ENGINE — TRADE LIFECYCLE                               ║
  ╚══════════════════════════════════════════════════════════════════════════════════════╝

    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │  EVENING PHASE  (18:00 IST)           evening_runner.py                         │
    │                                                                                  │
    │  kite_login.py ──► writes KITE_ACCESS_TOKEN to .env                             │
    │                                                                                  │
    │  layers/swing_bias.py                                                            │
    │    ├─ fetch daily OHLCV (Kite API)                                               │
    │    ├─ fetch VIX close                                                            │
    │    │                                                                             │
    │    │  VIX ≥ 22?                                                                  │
    │    │  ├─ YES → bias = SKIP  (OI/PCR will decide tomorrow)                        │
    │    │  └─ NO  → close > 21EMA AND close > prev_high? → LONG                      │
    │    │           close < 21EMA AND close < prev_low?  → SHORT                      │
    │    │           else                                  → SKIP                      │
    │    │                                                                             │
    │    └─► state/open_trade.json  { bias, vix_mode, signal: PENDING }               │
    │        state/daily_pnl.json   reset for next day                                 │
    │        state/oi_history.json  overnight OI baseline saved                        │
    └─────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │  MORNING OBSERVATION  (09:10–10:15 IST)    morning_monitor.py                   │
    │                                                                                  │
    │  09:10  KiteTicker starts ──► CVD warm-up begins (layers/orderflow.py)          │
    │                                                                                  │
    │  09:15  IB window opens  ──► 4 × 15-min candles accumulate                      │
    │         Every 5 min: print IB_H / IB_L / CVD direction / spot                   │
    │         ⚠  NO TRADES (Rule 5: 10-min buffer 09:15–09:25)                        │
    │                                                                                  │
    │  10:00  OI snapshot saved to oi_history.json  ◄── baseline for fresh_build      │
    │                                                                                  │
    │  10:15  IB FROZEN  ──► print day_type + IB range + extension                    │
    │         Exit. trade_window.py takes over.                                        │
    └─────────────────────────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
  ╔═════════════════════════════════════════════════════════════════════════════════════╗
  ║  PRIMARY TRADE WINDOW  (10:15–13:00 IST)    trade_window.py  ── every 5 min loop  ║
  ╚═════════════════════════════════════════════════════════════════════════════════════╝
                                            │
                      ┌─────────────────────┘
                      │  START OF EACH LOOP TICK
                      ▼
            ┌──────────────────┐
            │  HARD EXIT CHECK │  risk_manager.force_exit_required()
            │  time ≥ 15:15?   │  (15:15 HIGH VOL / 15:20 NORMAL)
            │  loss ≥ 1.5%?    │  risk_manager.is_loss_limit_hit()
            └──────────────────┘
                   │      │
                YES│      │NO
                   ▼      │
        ┌──────────────┐  │
        │ CLOSE ALL    │  │
        │ reason:      │  │
        │ hard_exit    │  │
        └──────────────┘  │
               │          │
               ▼          ▼
             END    ┌────────────────────┐
                    │ OPEN POSITION?     │  position_manager.has_open_position()
                    └────────────────────┘
                         │        │
                      YES│        │NO
                         │        │
                         ▼        ▼
            ┌──────────────────┐  ┌───────────────────────────────────────────────────┐
            │ POSITION MONITOR │  │ SIGNAL EVALUATION                                 │
            └──────────────────┘  └───────────────────────────────────────────────────┘
                   │                                   │
      ┌────────────┼────────────┐                     │
      │            │            │                     ▼
      ▼            ▼            ▼         ┌─────────────────────────┐
   stop_loss?  near_max    otherwise      │  LAYER 0: Market Profile │
      │         pain?         │           │  classify_ib()           │
      │            │          │           │                          │
      ▼            ▼          ▼           │  day_type?               │
   CLOSE ALL   CLOSE ALL   sleep 5min     │  ├─ TREND/NORMAL → +0.5  │
   reason:     reason:     next tick      │  ├─ RANGE → IRON_CONDOR  │
   stop_loss   target_                   │  └─ NEUTRAL → SKIP ──────┼──► END TICK
               max_pain                  └─────────────────────────┘
      │            │                                  │
      └─────┬──────┘                                  ▼
            │                            ┌─────────────────────────┐
            ▼                            │  LAYER 1: Swing Bias     │
      record_pnl()                       │  swing_bias.get_swing_   │
      daily_pnl.json                     │  bias()                  │
                                         │                          │
                                         │  VIX ≥ 22?               │
                                         │  ├─ YES → bias=SKIP      │
                                         │  │        (L2 decides)   │
                                         │  └─ NO → LONG/SHORT/SKIP │
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  LAYER 2: OI Walls       │
                                         │  oi_scanner.get_oi_      │
                                         │  levels()                │
                                         │                          │
                                         │  read prior OI from      │
                                         │  oi_history.json         │
                                         │                          │
                                         │  ├─ proximity to wall?   │
                                         │  │    ≤75pt NORMAL        │
                                         │  │    ≤100pt HIGH VIX     │  +1.0
                                         │  ├─ fresh OI build?      │  +1.0
                                         │  │    call/put_wall_oi   │
                                         │  │    > prior snapshot   │
                                         │  │                       │
                                         │  VIX ≥ 22?               │
                                         │  ├─ PCR>1.20 AND         │
                                         │  │  maxpain>spot → LONG  │
                                         │  ├─ PCR<0.80 AND         │
                                         │  │  maxpain<spot → SHORT │
                                         │  └─ else → bias=SKIP     │
                                         │                          │
                                         │  score < 1.0?            │
                                         │  └─ SKIP ───────────────┼──► END TICK
                                         └─────────────────────────┘
                                                      │  save_snapshot()
                                                      │  oi_history.json
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  LAYER 3: Orderflow      │
                                         │  orderflow.get_orderflow │
                                         │  (KiteTicker CVD)        │
                                         │                          │
                                         │  ├─ CVD velocity         │
                                         │  │  |Δ| ≥ 30k → +1.0    │
                                         │  ├─ 3:1 imbalance → +1.0 │
                                         │  ├─ CVD >60% consistent  │
                                         │  │  → +0.5               │
                                         │  └─ spot above POC→ +0.5 │
                                         │                          │
                                         │  score < 0.5?            │
                                         │  └─ SKIP ───────────────┼──► END TICK
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  RISK CHECKS             │
                                         │  risk_manager.check_     │
                                         │  entry_allowed()         │
                                         │                          │
                                         │  ✗ blackout date?        │
                                         │  ✗ 09:15–09:25 buffer?   │
                                         │  ✗ past exit time?       │
                                         │  ✗ loss ≥ 1.5%?          │
                                         │                          │
                                         │  any fail → BLOCKED ────┼──► END TICK
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  STRIKE SELECTION        │
                                         │  strike_selector.select_ │
                                         │  strikes()               │
                                         │                          │
                                         │  ATM = round(spot/50)×50 │
                                         │                          │
                                         │  BULL_CALL (Normal/LONG) │
                                         │  BUY  ATM CE             │
                                         │  SELL min(ATM+100,       │
                                         │          call_wall) CE   │
                                         │                          │
                                         │  BEAR_PUT (Normal/SHORT) │
                                         │  BUY  ATM PE             │
                                         │  SELL max(ATM-100,       │
                                         │          put_wall) PE    │
                                         │                          │
                                         │  BULL_PUT (High VIX/LONG)│
                                         │  SELL ATM-50 PE          │
                                         │  BUY  ATM-150 PE         │
                                         │                          │
                                         │  BEAR_CALL(High VIX/SHORT│
                                         │  SELL ATM+50 CE          │
                                         │  BUY  ATM+150 CE         │
                                         │                          │
                                         │  IRON_CONDOR (RANGE day) │
                                         │  SELL ATM+100 CE/PE      │
                                         │  BUY  ATM+200 CE/PE      │
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  POSITION SIZING         │
                                         │  lots = floor(           │
                                         │   capital × 20% /        │
                                         │   (spread_ltp × 75))     │
                                         │  min 1 lot               │
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  ORDER PLACEMENT         │
                                         │  order_manager.place_    │
                                         │  spread()                │
                                         │                          │
                                         │  TRADE_MODE=paper        │
                                         │  └─ log only, fake IDs   │
                                         │                          │
                                         │  TRADE_MODE=live         │
                                         │  └─ kite.place_order()   │
                                         │     MIS LIMIT @ LTP      │
                                         │     per leg              │
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                         ┌─────────────────────────┐
                                         │  COMPUTE STOP & TARGET   │
                                         │  position_manager.stop_  │
                                         │  loss_for_spread()       │
                                         │                          │
                                         │  Normal: SL = OI wall    │
                                         │          ± 50 pts spot   │
                                         │          target = max_   │
                                         │          pain / next wall │
                                         │                          │
                                         │  High VIX: SL = debit-  │
                                         │  to-close > 2× credit   │
                                         │  target = max_pain       │
                                         └─────────────────────────┘
                                                      │
                                                      ▼
                                           positions.json written
                                           ──► loop continues with
                                               POSITION MONITOR path


    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │  POSITION CLOSE PATHS                                                            │
    │                                                                                  │
    │  STOP LOSS                                                                       │
    │    Normal:   spot breaches OI wall by > 50 pts                                  │
    │    High VIX: (exit_LTP - entry_LTP) × qty > 2 × credit_received                │
    │    → MARKET exit all legs immediately                                            │
    │                                                                                  │
    │  TARGET (Max Pain)                                                               │
    │    spot within 25 pts of max_pain → partial profit                              │
    │    → MARKET exit all legs                                                        │
    │                                                                                  │
    │  HARD EXIT (time-based)                                                          │
    │    HIGH VOL mode  → 15:15 IST  (Rule 8: avoid gamma/theta risk overnight)       │
    │    NORMAL mode    → 15:20 IST  (Rule 8)                                         │
    │    → MARKET exit all legs regardless of P&L                                     │
    │                                                                                  │
    │  LOSS LIMIT                                                                      │
    │    realized_pnl ≤ −1.5% of TRADING_CAPITAL                                     │
    │    → exit immediately, no further entries today (Rule 1)                         │
    │                                                                                  │
    │  All paths write realized_pnl to state/daily_pnl.json                           │
    └─────────────────────────────────────────────────────────────────────────────────┘
    │    → MARKET exit all legs                                                        │
    │                                                                                  │
    │  HARD EXIT (time-based)                                                          │
    │    HIGH VOL mode  → 15:15 IST  (Rule 8: avoid gamma/theta risk overnight)       │
    │    NORMAL mode    → 15:20 IST  (Rule 8)                                         │
    │    → MARKET exit all legs regardless of P&L                                     │
    │                                                                                  │
    │  LOSS LIMIT                                                                      │
    │    realized_pnl ≤ −1.5% of TRADING_CAPITAL                                     │
    │    → exit immediately, no further entries today (Rule 1)                         │
    │                                                                                  │
    │  All paths write realized_pnl to state/daily_pnl.json                           │
    └─────────────────────────────────────────────────────────────────────────────────┘

    ┌─────────────────────────────────────────────────────────────────────────────────┐
    │  STATE FILES                          updated by                                 │
    │  state/open_trade.json                signal_engine (every tick)                 │
    │  state/oi_history.json                oi_store (every tick + 10:00 baseline)    │
    │  state/positions.json                 position_manager (open / cleared on close) │
    │  state/daily_pnl.json                 risk_manager (each trade close)            │
    └─────────────────────────────────────────────────────────────────────────────────┘
