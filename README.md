Experiment folder for generating sample code using a spec and skill


  ┌───────────────────┬──────────────┬─────────────────────────────────────────────────────────────────────┐                              │       File        │    Layer     │     Purpose                                                                                  
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤                              │ kite_login.py     │ Prereq       │ Token refresh → writes KITE_ACCESS_TOKEN to .env
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ market_scanner.py │ Data         │ OHLCV + EMA + IB fetch (ported from kite_fetch.md scaffold)         │
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ market_profile.py │ L0           │ IB day-type → DIRECTIONAL / IRON_CONDOR / SKIP + score ±0.5         │
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ paper_trader.py   │ L1           │ EOD swing bias (LONG/SHORT/SKIP); bypassed when VIX ≥ 22            │
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ kite_oi_live.py   │ L2           │ OI walls, PCR, Max Pain, proximity + fresh build scoring (0–2.0)    │
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ kite_orderflow.py │ L3           │ KiteTicker CVD accumulation, imbalance, consistency scoring (0–1.0) │
  ├───────────────────┼──────────────┼─────────────────────────────────────────────────────────────────────┤
  │ signal_engine.py  │ Orchestrator │ Aggregates all layers → ENTER/SKIP + writes open_trade.json         │
  └───────────────────┴──────────────┴─────────────────────────────────────────────────────────────────────┘

  Daily workflow:
  - Evening: python kite_login.py → python paper_trader.py
  - Morning (after 10:15): python signal_engine.py <poc_level>
  - High VIX test: python signal_engine.py 0 23 (passes mock_vix=23)