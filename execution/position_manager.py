"""Position lifecycle manager — open, monitor, close.

Tracks a single intraday spread position via state/positions.json.
P&L is computed live from Kite LTP; realized P&L is written to daily_pnl.json
via risk_manager.record_pnl().
"""
from __future__ import annotations
import json
import os
from datetime import datetime, date

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST             = pytz.timezone("Asia/Kolkata")
_POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "positions.json")
LOT_SIZE        = int(os.environ.get("NIFTY_LOT_SIZE", "75"))

# Stop-loss constants (per spec)
_NORMAL_SL_PTS    = 50   # spot must breach OI wall by 50 pts
_HIGHVIX_SL_MULT  = 2.0  # exit if debit-to-close > 2× credit received
_MAX_PAIN_THRESH  = 25.0  # within 25 pts of max pain → partial profit trigger


class PositionManager:

    # ── Open ──────────────────────────────────────────────────────────────────

    def open_position(
        self,
        legs:               list[dict],
        spread_type:        str,
        entry_net_premium:  float,   # net debit (debit spreads) or credit received
        stop_loss_spot:     float,
        target_spot:        float,
        order_ids:          list[str],
        lots:               int,
        leg_ltps:           list[float],
    ) -> None:
        """Write position to state/positions.json."""
        leg_records = []
        for leg, order_id, ltp in zip(legs, order_ids, leg_ltps):
            leg_records.append({
                "tradingsymbol":    leg["tradingsymbol"],
                "transaction_type": leg["transaction_type"],
                "option_type":      leg["option_type"],
                "strike":           leg["strike"],
                "order_id":         order_id,
                "entry_ltp":        ltp,
                "lots":             lots,
            })

        record = {
            "date":               str(date.today()),
            "spread_type":        spread_type,
            "legs":               leg_records,
            "entry_net_premium":  round(entry_net_premium, 2),
            "stop_loss_spot":     stop_loss_spot,
            "target_spot":        target_spot,
            "status":             "open",
            "opened_at":          datetime.now(IST).strftime("%H:%M IST"),
        }
        self._save(record)
        print(f"[Position] Opened {spread_type}  net_premium={entry_net_premium:.2f}  "
              f"SL_spot={stop_loss_spot}  target={target_spot}")

    # ── Query ─────────────────────────────────────────────────────────────────

    def has_open_position(self) -> bool:
        rec = self._load()
        return rec is not None and rec.get("status") == "open"

    def get_position(self) -> dict | None:
        return self._load()

    def get_current_pnl(self) -> float:
        """Compute unrealized P&L from live LTPs of all open legs."""
        from execution.order_manager import get_ltp
        rec = self._load()
        if not rec:
            return 0.0

        net = 0.0
        for leg in rec["legs"]:
            ltp   = get_ltp(leg["tradingsymbol"])
            qty   = leg["lots"] * LOT_SIZE
            delta = (ltp - leg["entry_ltp"]) * qty
            # BUY leg: profit when price rises; SELL leg: profit when price falls
            net += delta if leg["transaction_type"] == "BUY" else -delta
        return round(net, 2)

    # ── Stop / Target Checks ──────────────────────────────────────────────────

    def check_stop_loss(self, current_spot: float) -> bool:
        """True when stop-loss condition is met.

        Normal VIX: spot breaches the anchor OI wall by more than 50 pts.
        High VIX (credit spread): current debit-to-close > 2× credit received.
        """
        rec = self._load()
        if not rec:
            return False

        spread_type = rec.get("spread_type", "")
        sl_spot     = rec.get("stop_loss_spot", 0)

        if spread_type in ("BULL_PUT", "BEAR_CALL"):
            # High VIX credit spread: premium-based stop
            current_pnl = self.get_current_pnl()
            credit_rcvd = rec.get("entry_net_premium", 0) * rec["legs"][0]["lots"] * LOT_SIZE
            if credit_rcvd > 0 and current_pnl < -(credit_rcvd * _HIGHVIX_SL_MULT):
                return True
        else:
            # Normal VIX: spot-based stop
            if spread_type == "BULL_CALL" and sl_spot and current_spot < sl_spot:
                return True
            if spread_type == "BEAR_PUT"  and sl_spot and current_spot > sl_spot:
                return True

        return False

    def is_near_max_pain(self, max_pain: float, current_spot: float,
                         threshold: float = _MAX_PAIN_THRESH) -> bool:
        return abs(current_spot - max_pain) <= threshold

    def stop_loss_for_spread(
        self, spread_type: str, key_levels: dict
    ) -> tuple[float, float]:
        """Compute (stop_loss_spot, target_spot) per spec rules.

        Normal:   SL = anchor OI wall ± 50 pts; target = max_pain or next wall.
        High VIX: SL is premium-based (handled in check_stop_loss); target = max_pain.
        Returns (0.0, 0.0) if levels are unavailable.
        """
        call_wall = key_levels.get("call_wall") or 0
        put_wall  = key_levels.get("put_wall")  or 0
        max_pain  = key_levels.get("max_pain")  or 0

        if spread_type == "BULL_CALL":
            sl     = put_wall - _NORMAL_SL_PTS if put_wall else 0.0
            target = max_pain or (call_wall - 50 if call_wall else 0.0)
            return sl, target

        if spread_type == "BEAR_PUT":
            sl     = call_wall + _NORMAL_SL_PTS if call_wall else 0.0
            target = max_pain or (put_wall + 50 if put_wall else 0.0)
            return sl, target

        # High VIX credit spreads and Iron Condor — target max_pain; SL premium-based
        return 0.0, float(max_pain)

    # ── Close ─────────────────────────────────────────────────────────────────

    def close_all(self, reason: str, lots: int) -> float:
        """Exit all legs, return realized P&L (negative = loss)."""
        from execution.order_manager import exit_spread, get_ltp

        rec = self._load()
        if not rec:
            return 0.0

        legs      = rec["legs"]
        order_ids = [l["order_id"] for l in legs]

        # Snapshot exit LTPs before placing orders
        exit_result = exit_spread(legs=legs, order_ids=order_ids, lots=lots)
        exit_ltps   = exit_result["exit_ltps"]

        # Compute realized P&L
        realized = 0.0
        for leg, entry_ltp, exit_ltp in zip(legs, [l["entry_ltp"] for l in legs], exit_ltps):
            qty   = leg["lots"] * LOT_SIZE
            delta = (exit_ltp - entry_ltp) * qty
            realized += delta if leg["transaction_type"] == "BUY" else -delta

        print(f"[Position] Closed {rec['spread_type']}  reason={reason}  "
              f"realized_pnl={realized:.2f}")

        # Clear position file
        self._save(None)
        return round(realized, 2)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> dict | None:
        if not os.path.exists(_POSITIONS_FILE):
            return None
        try:
            with open(_POSITIONS_FILE) as f:
                data = json.load(f)
            if not data or data.get("date") != str(date.today()):
                return None
            return data
        except (json.JSONDecodeError, OSError):
            return None

    def _save(self, record: dict | None) -> None:
        os.makedirs(os.path.dirname(_POSITIONS_FILE), exist_ok=True)
        with open(_POSITIONS_FILE, "w") as f:
            json.dump(record or {}, f, indent=2)
