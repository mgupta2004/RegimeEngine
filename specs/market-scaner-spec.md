Strategic Investment Framework: Systematic Derivatives Trading & Market Structure

1. The Architecture of Multi-Layer Signal Confluence

In the institutional derivatives landscape of the NSE Nifty 50, "alpha" is not the product of isolated indicators but the result of a rigorous multi-layer filtration protocol. This framework mandates the confluence of four independent data streams—Open Interest (OI), Orderflow, Market Profile, and Swing Signals—to isolate high-conviction trades from pervasive market noise. By synthesizing these disparate streams, the system moves beyond speculative bias into a regime of evidence-based execution, where trade authorization only occurs when structural, directional, and transactional data align.

The "3+1 Confluence System" organizes these streams into a professional hierarchy, assigning quantitative weights to ensure that capital is only committed during periods of maximum institutional alignment.

The 3+1 Confluence Hierarchy

Layer	Component	Data Source	Primary Analytical Function	Signal Weighting & Scoring
Layer 0	Market Profile	market_profile.py	Structural filter; day-type classification (Trend, Normal, Range).	Gatekeeper: Authorizes directional or neutral strategy sets (+0.5 if aligned).
Layer 1	Swing Bias	paper_trader.py	Establishes the core directional lean (Long/Short/Skip).	Core: +1.0 strength if bias is satisfied.
Layer 2	OI Levels	kite_oi_live.py	Identifies institutional "walls" and strike-wise proximity.	Conviction: +1.0 for Proximity; +1.0 for Fresh OI Build.
Layer 3	Orderflow	kite_orderflow.py	Measures real-time Buy/Sell Imbalances and CVD Velocity.	Trigger: +0.5 (Spot vs. POC) to +1.0 (CVD/Imbalance).

Note: A minimum score comprising Layer 2 satisfaction plus at least one Layer 3 trigger is required to fire an ENTER signal.

Layer 0: The Market Profile Pre-Filter

Layer 0 serves as the foundational structural audit. The framework utilizes the Initial Balance (IB)—defined by the high/low of the first hour of trade (09:15–10:15)—to classify the day-type.

* Trend / Normal Days: Characterized by IB extensions. These regimes authorize directional momentum strategies and add +0.5 to signal strength.
* Range / Double Distribution Days: Indicate a market in balance with multiple Points of Control (POC). Directional signals are suppressed in favor of Iron Condor protocols.
* Neutral Days: Market at full equilibrium. The system mandates a complete "SKIP" to preserve capital.

Once the IB is "frozen" at 10:15, the structural boundaries for the day are non-negotiable, dictating whether the strategist adopts a directional or non-directional posture.


--------------------------------------------------------------------------------


2. Volatility Regimes: Strategic Adaptation to India VIX

Volatility is the primary determinant of instrument selection and risk exposure. The framework pivots between "Normal" and "High VIX" modes to optimize Greek exposure, transitioning from Delta-heavy strategies to Theta-dominant alpha generation as the India VIX expands.

Strategic Pivot: VIX < 22 vs. VIX ≥ 22

* Normal Mode (VIX < 22): The system relies on the prior evening's "Swing Bias" computed from EOD bhavcopy data via paper_trader.py. Instrument selection favors debit spreads (Bull Call/Bear Put), where risk is capped at the premium paid.
* High VIX Mode (VIX ≥ 22): Traditional swing signals are bypassed. The system shifts to credit spreads to exploit elevated premiums and Impeding Volatility Crush (IV Crush). Theta decay becomes the primary alpha driver as price ranges expand.

High VIX Mode: OI Structure Logic

In high-volatility environments, institutional positioning—not historical patterns—governs the directional lean. The system mandates strict Put-Call Ratio (PCR) and Max Pain alignment:

* Bullish Bias: Requires PCR > 1.20 AND Max Pain > Spot.
* Bearish Bias: Requires PCR < 0.80 AND Max Pain < Spot.
* Proximity Rule: In High VIX, the spot price must be within 100 points of a key OI wall. This wider berth (compared to the 75-point Normal rule) accounts for increased Average True Range (ATR) while maintaining a strict entry discipline.

Technical triggers are required to confirm these institutional anchors before execution.


--------------------------------------------------------------------------------


3. Execution Triggers: Orderflow and Institutional Positioning

Orderflow and Open Interest (OI) represent the "Ground Truth" of institutional activity. Option writers, typically institutional participants, define the boundaries of price movement; their activity reveals the levels where "smart money" is actively defending its capital.

Layer 3: Orderflow and Institutional Absorption

Orderflow is the final confirmation required for execution. The framework identifies three "VERY STRONG" triggers that signify institutional commitment:

* CVD Velocity (+/- 30k Units): A surge of 30,000 units in Cumulative Volume Delta within 15 minutes indicates a breakout surge or distribution acceleration.
* 3:1 Buy/Sell Imbalances: A 3:1 volume dominance at support/resistance levels confirms Institutional Absorption, where the limit order book is successfully absorbing aggressive market orders.
* CVD Trend Consistency: Sustained control is confirmed when >60% of recent ticks move in a consistent direction.

OI Walls: Fresh Build and Unwinding

The market is bounded by "Call Walls" (Resistance) and "Put Walls" (Support).

* Fresh OI Build (+1.0 weight): New money entering a wall hardens the level. A fresh Call build above spot confirms a supply cap.
* OI Unwinding: Writers abandoning a wall (e.g., Call OI reduction) signals that resistance is collapsing, often preceding a bullish breakout.
* POC Alignment (+0.5 weight): Price holding above the Point of Control (POC) confirms that market consensus has shifted in favor of buyers.

These triggers link technical activity directly to strategy selection.


--------------------------------------------------------------------------------


4. Tactical Strategy Playbook: Directional and Neutral Frameworks

Strategic "edge" is derived from matching the correct Greek exposure—Theta (time) vs. Delta (direction)—to the identified market profile.

Directional Spreads (Normal VIX < 22)

* Bull Call / Bear Put Spreads:
  * Market Condition: Trend/Normal Day + Signal Bias (L1).
  * Entry Trigger: Layer 2 proximity + Layer 3 (CVD/Imbalance) confluence.
  * Stop Loss: 50-point spot breach beyond the anchor OI wall.
  * Target: Next major OI wall or Max Pain strike.

High VIX Credit Spreads (VIX ≥ 22)

* Bull Put / Bear Call Spreads:
  * Market Condition: High VIX Mode + Institutional PCR/Max Pain alignment.
  * Execution Mandate: Same-day expiry only. These are entered to harvest rapid Theta decay.
  * Hard Exit Rule: All positions must be closed by 3:15 PM to eliminate catastrophic overnight gap risk and gamma exposure.
  * Stop Loss: Close if the debit to buy back the spread exceeds 2x the credit received.

The Iron Condor Protocol

* Market Condition: Range / Double Distribution days (VIX < 16 ideal).
* Logic: Simultaneously sell OTM Calls above resistance and OTM Puts below support.
* Structure: Buy protective wings 100–150 points further out to cap maximum loss.
* Profit Engine: Time decay. Target 50–60% of the total credit received.

Operation rigor in managing these positions is maintained through a strict daily cycle.


--------------------------------------------------------------------------------


5. Operational Workflow: The Institutional Daily Cycle

Rigorous process prevents emotional decision-making. The daily cycle ensures that every trade is a product of the system, not the trader's intuition.

Daily Workflow Checklist

1. Evening Phase (Post-18:00):
  * Refresh Kite token via kite_login.py.
  * Compute next-day signals via paper_trader.py using NSE bhavcopy.
  * Generate open_trade.json containing bias, VIX mode, and required spread structure.
2. Morning Observation (09:15–10:15): The "No Trade Zone." Monitor IB formation, CVD direction, and whether price respects OI walls.
3. Primary Trade Window (10:15–13:00): Execute entries based on Layer 2 and Layer 3 confluence. Monitor IB breakouts/breakdowns as "very strong" trend confirmations.
4. Afternoon Management: Trail stop losses. If CVD reverses or OI walls shift significantly, reassess and take partial profits at Max Pain.
5. Exit Protocol:
  * High VIX Mode: Hard exit by 15:15.
  * Standard Mode: All intraday positions closed by 15:20 to avoid liquidity risk.


--------------------------------------------------------------------------------


6. Risk Governance and Capital Protection

Risk management is the non-negotiable "Circuit Breaker" of this framework. Adherence to these rules is mandatory for systemic integrity.

The 10 Mandatory Risk Rules

1. Rule 1: Max Daily Loss 1.5%: Total account loss of 1.5% in a session mandates an immediate cessation of all trading activities.
2. Rule 2: Mandatory Stop Loss: No position is initiated without a pre-calculated exit price for both the spot and the spread.
3. Rule 3: Respect Skip Signals: If the system issues a "SKIP" (Neutral day or ambiguous OI), trading is prohibited.
4. Rule 4: Hedge High VIX: Naked options are strictly forbidden when VIX > 22. Protective legs are mandatory.
5. Rule 5: The 10-Minute Buffer: No execution between 09:15–09:25 to allow for institutional order flow absorption.
6. Rule 6: No Revenge Trading: A hit stop-loss terminates the trade. Doubling down or emotional re-entry is prohibited.
7. Rule 7: Position Sizing: No single trade shall exceed 20% of trading capital on a margin basis.
8. Rule 8: Strict 3:20 PM Exit: All intraday positions must be cleared to avoid end-of-session volatility and liquidity dries.
9. Rule 9: Data Over Opinion: Trust the signal layers. Personal "feelings" or market "hunches" are not valid inputs.
10. Rule 10: Major Event Blackouts: Trading is suspended during the Union Budget, RBI Policy announcements, and FOMC meetings.

Strategic Philosophy: Trust the data-driven signals over personal opinion. Long-term performance is the byproduct of discipline, not prediction. Adherence to this framework ensures the trader operates with the clarity and rigor of an institutional participant.
