Here's the full manual workflow. All commands run from the repo root: D:\Synaptic\MasterTradingLogic\RegimeEngine\

  ---
  Daily Manual Workflow

  Step 1 — Evening (once, after 18:00)

  # 1. Refresh Kite access token (opens browser for login)
  python kite_login.py

  # 2. Pre-compute swing bias and reset daily state
  python automation/evening_runner.py

  This writes a preliminary state/open_trade.json with tomorrow's bias + VIX mode.

  ---
  Step 2 — Morning Observation (09:10–10:15)

  # Starts KiteTicker for CVD warm-up, monitors IB as it forms,
  # saves OI baseline at 10:00, then exits at 10:15
  python automation/morning_monitor.py

  This blocks until 10:15 IST, printing IB and CVD updates every 5 minutes. Open a second terminal for Step 3.

  ---
  Step 3 — Trade Window (10:15–13:00+)

  # Full signal → risk → execute loop (paper mode by default)
  python automation/trade_window.py

  This blocks until the hard exit time (15:15 HIGH VOL / 15:20 NORMAL) or until the loss limit is hit.

  ---
  One-Off Diagnostics (run anytime during market hours)

  # Run the market scanner (same as the skill)
  python market_scanner.py

  # Check each layer independently
  python -m layers.market_profile      # L0: day type
  python -m layers.swing_bias          # L1: bias + VIX mode
  python -m layers.oi_scanner          # L2: OI walls, PCR, max pain
  python -m layers.orderflow 60        # L3: collect 60s of CVD ticks

  # Run the full signal engine once (writes state/open_trade.json)
  python -m engine.signal_engine

  ---
  Switching Between Paper and Live

  In your .env file:

  TRADE_MODE=paper    # simulates orders, no real trades
  TRADE_MODE=live     # places real MIS orders via Kite

  Keep TRADE_MODE=paper until you've verified a full signal cycle end-to-end. Check state/positions.json and state/daily_pnl.json after a paper run to confirm the output is
  correct before switching to live.

  ---
  Key Notes

  ---
  One-Off Diagnostics (run anytime during market hours)

  # Run the market scanner (same as the skill)
  python market_scanner.py

  # Check each layer independently
  python -m layers.market_profile      # L0: day type
  python -m layers.swing_bias          # L1: bias + VIX mode
  python -m layers.oi_scanner          # L2: OI walls, PCR, max pain
  python -m layers.orderflow 60        # L3: collect 60s of CVD ticks

  # Run the full signal engine once (writes state/open_trade.json)
  python -m engine.signal_engine

  ---
  Switching Between Paper and Live

  In your .env file:

  TRADE_MODE=paper    # simulates orders, no real trades
  TRADE_MODE=live     # places real MIS orders via Kite

  Keep TRADE_MODE=paper until you've verified a full signal cycle end-to-end. Check state/positions.json and state/daily_pnl.json after a paper run to confirm the output is
  correct before switching to live.

  ---
  Key Notes

  - All scripts must be run from the repo root (not from inside automation/ or engine/) — the package imports resolve relative to root
  - morning_monitor.py and trade_window.py can run in parallel in two separate terminals — start Morning first, then open a second terminal for the Trade Window at 10:15
  - If you skip the morning phase, trade_window.py will still work — it just won't have an OI baseline snapshot, so fresh_build may not fire on the first cycle
