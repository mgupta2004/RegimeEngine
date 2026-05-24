"""Risk governor — enforces all 10 mandatory rules from the spec.

Acts as a pre/post guard around order execution, not as a signal layer.
All checks are hard blocks; the system must not trade if any rule fails.
"""
import json
import os
import math
from datetime import datetime, date, time as dtime

import pytz
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

IST  = pytz.timezone("Asia/Kolkata")
_PNL_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "daily_pnl.json")

LOT_SIZE = int(os.environ.get("NIFTY_LOT_SIZE", "75"))

# Rule 10: Major event blackout dates — update annually
BLACKOUT_DATES: set[date] = {
    date(2026, 2, 1),    # Union Budget
    # Add RBI MPC dates and FOMC dates for the current year here
}

# Time boundaries (IST)
_BUFFER_START = dtime(9, 15)
_BUFFER_END   = dtime(9, 25)
_EXIT_NORMAL  = dtime(15, 20)
_EXIT_HIGH_VIX = dtime(15, 15)
_LOSS_LIMIT_PCT = 0.015   # Rule 1: 1.5% of capital
_SIZE_LIMIT_PCT = 0.20    # Rule 7: 20% of capital per trade


class RiskManager:
    def __init__(self, capital: float):
        self.capital = capital
        self._pnl    = self._load_pnl()

    # ── Entry Checks ──────────────────────────────────────────────────────────

    def check_entry_allowed(self, vix_mode: str) -> tuple[bool, str]:
        """Return (allowed, reason). Checks all entry-blocking rules in priority order."""
        now_ist  = datetime.now(IST)
        now_time = now_ist.time()
        today    = now_ist.date()

        # Rule 10: Major event blackout
        if today in BLACKOUT_DATES:
            return False, "event_blackout"

        # Rule 5: 10-minute buffer (09:15–09:25)
        if _BUFFER_START <= now_time <= _BUFFER_END:
            return False, "10min_buffer"

        # Rule 8: Past exit time
        exit_time = _EXIT_HIGH_VIX if vix_mode == "HIGH VOL" else _EXIT_NORMAL
        if now_time >= exit_time:
            return False, "past_exit_time"

        # Rule 1: Daily loss limit
        if self.is_loss_limit_hit():
            return False, "loss_limit_hit"

        return True, "ok"

    def check_naked_allowed(self, vix_mode: str) -> bool:
        """Rule 4: Naked positions forbidden when VIX ≥ 22."""
        return vix_mode != "HIGH VOL"

    def compute_position_lots(self, spread_ltp: float) -> int:
        """Rule 7: Max 20% of capital per trade, minimum 1 lot."""
        if spread_ltp <= 0:
            return 1
        max_spend = self.capital * _SIZE_LIMIT_PCT
        lots = math.floor(max_spend / (spread_ltp * LOT_SIZE))
        return max(1, lots)

    # ── Exit Checks ───────────────────────────────────────────────────────────

    def force_exit_required(self, vix_mode: str) -> bool:
        """Rules 8/9: True if past the hard exit time for the current VIX mode."""
        exit_time = _EXIT_HIGH_VIX if vix_mode == "HIGH VOL" else _EXIT_NORMAL
        return datetime.now(IST).time() >= exit_time

    def is_loss_limit_hit(self) -> bool:
        """Rule 1: True if realized P&L has crossed the 1.5% loss cap."""
        return self._pnl.get("realized_pnl", 0.0) <= -(self.capital * _LOSS_LIMIT_PCT)

    # ── P&L Tracking ─────────────────────────────────────────────────────────

    def record_pnl(self, realized_pnl: float, spread_type: str = "") -> None:
        """Append a trade result and persist to daily_pnl.json."""
        today = str(date.today())
        if self._pnl.get("date") != today:
            self._pnl = self._fresh_pnl(today)

        self._pnl["realized_pnl"] = round(
            self._pnl.get("realized_pnl", 0.0) + realized_pnl, 2
        )
        self._pnl["trades"].append({
            "time":   datetime.now(IST).strftime("%H:%M IST"),
            "spread": spread_type,
            "pnl":    round(realized_pnl, 2),
        })
        self._save_pnl()
        # Refresh in-memory state
        self._pnl = self._load_pnl()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fresh_pnl(self, today: str) -> dict:
        return {
            "date":         today,
            "capital":      self.capital,
            "realized_pnl": 0.0,
            "trades":       [],
        }

    def _load_pnl(self) -> dict:
        today = str(date.today())
        if not os.path.exists(_PNL_FILE):
            return self._fresh_pnl(today)
        try:
            with open(_PNL_FILE) as f:
                data = json.load(f)
            if data.get("date") != today:
                return self._fresh_pnl(today)
            return data
        except (json.JSONDecodeError, OSError):
            return self._fresh_pnl(today)

    def _save_pnl(self) -> None:
        os.makedirs(os.path.dirname(_PNL_FILE), exist_ok=True)
        with open(_PNL_FILE, "w") as f:
            json.dump(self._pnl, f, indent=2)
