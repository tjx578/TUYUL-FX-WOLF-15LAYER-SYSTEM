"""
TUYUL FX Wolf-15 — Risk Engine
================================
BUG FIX [BUG-2]:
  RiskMultiplier and RiskEngine aliases are now defined AFTER the class body.
  Previously they were defined before the class, causing NameError on import.

Lot formula:
  1. pip_value  = get_pip_value(pair)
  2. sl_dist    = abs(entry - sl) * pip_multiplier
  3. dd_mult    = dd_multiplier(daily_dd_percent)
  4. adj_risk   = risk_percent * dd_mult
  5. risk_amt   = balance * adj_risk / 100
  6. lot        = risk_amt / (sl_dist * pip_value)
  7. PropFirmGuard.evaluate_trade()  ← final boundary check
"""

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Pip value table (standard lot = 100,000 units) ─────────────────────────

_PIP_VALUES: dict[str, float] = {
    # Gold / Metals
    "XAUUSD": 10.0,
    "XAGUSD": 50.0,
    # Major pairs (USD quote)
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "AUDUSD": 10.0,
    "NZDUSD": 10.0,
    # USD base pairs
    "USDJPY": 9.09,
    "USDCHF": 10.87,
    "USDCAD": 7.52,
    # Cross pairs (approx, varies with FX rate)
    "EURJPY": 9.09,
    "GBPJPY": 9.09,
    "AUDJPY": 9.09,
    "EURGBP": 13.25,
    "EURAUD": 6.45,
    "GBPAUD": 6.45,
    "GBPCAD": 7.52,
    "EURCAD": 7.52,
    # Indices
    "US30":   1.0,
    "US100":  1.0,
    "SPX500": 10.0,
    # Oil
    "USOIL":  10.0,
    "UKOIL":  10.0,
    # BTC
    "BTCUSD": 1.0,
}

_DEFAULT_PIP_VALUE = 10.0


def get_pip_value(pair: str) -> float:
    """Return pip value per standard lot in USD for given instrument."""
    return _PIP_VALUES.get(pair.upper(), _DEFAULT_PIP_VALUE)


def pip_multiplier(pair: str) -> float:
    """Return decimal multiplier: JPY pairs use 100, others use 10000."""
    if "JPY" in pair.upper():
        return 100.0
    if pair.upper() in ("XAUUSD",):
        return 10.0   # Gold: 1 pip = $0.1 per micro, $10 per standard
    if pair.upper() in ("US30", "US100", "SPX500", "BTCUSD", "USOIL", "UKOIL"):
        return 1.0
    return 10_000.0


# ─── Drawdown multiplier (adaptive risk reduction) ───────────────────────────

def dd_multiplier(daily_dd_percent: float) -> float:
    """
    Adaptive risk multiplier based on drawdown level.
    < 30%  → 1.00 (full risk)
    30-60% → 0.75 (reduce)
    60-80% → 0.50 (half)
    > 80%  → 0.25 (emergency)
    """
    if daily_dd_percent >= 80:
        return 0.25
    if daily_dd_percent >= 60:
        return 0.50
    if daily_dd_percent >= 30:
        return 0.75
    return 1.00


# ─── Main Risk Engine ─────────────────────────────────────────────────────────

class RiskMultiplierAggregator:
    """
    Calculates position size based on account state and signal parameters.
    Constitutional rule: lot_size is ALWAYS derived here, never from EA or user input.
    """

    # Lot size boundaries
    MIN_LOT: float = 0.01
    MAX_LOT: float = 100.0
    LOT_STEP: float = 0.01

    def calculate_lot(
        self,
        balance: float,
        equity: float,
        daily_dd_percent: float,
        pair: str,
        entry: float,
        sl: float,
        risk_percent: float,
        prop_firm_max_lot: Optional[float] = None,
    ) -> dict:
        """
        Calculate recommended lot size.

        Returns:
            dict with keys:
              trade_allowed, recommended_lot, max_safe_lot,
              risk_used_percent, daily_dd_after, severity, reason
        """
        if balance <= 0:
            return self._blocked("ZERO_BALANCE", "Account balance is zero or negative")
        if entry <= 0 or sl <= 0:
            return self._blocked("INVALID_PRICES", "Entry or SL price is zero")
        if risk_percent <= 0:
            return self._blocked("ZERO_RISK", "Risk percent must be positive")

        # 1. DD multiplier
        mult = dd_multiplier(daily_dd_percent)

        # 2. Adjusted risk
        adj_risk_pct = risk_percent * mult

        # 3. Risk amount in account currency
        risk_amount = equity * adj_risk_pct / 100.0

        # 4. SL distance in pips
        pip_mult = pip_multiplier(pair)
        sl_distance_pips = abs(entry - sl) * pip_mult
        if sl_distance_pips < 1:
            return self._blocked("SL_TOO_TIGHT", f"SL distance too small: {sl_distance_pips:.2f} pips")

        # 5. Pip value
        pip_val = get_pip_value(pair)

        # 6. Raw lot
        raw_lot = risk_amount / (sl_distance_pips * pip_val)

        # 7. Round to step + clamp
        lot = self._round_lot(raw_lot)

        # 8. Prop firm cap
        if prop_firm_max_lot and lot > prop_firm_max_lot:
            lot = self._round_lot(prop_firm_max_lot)

        lot = max(self.MIN_LOT, min(self.MAX_LOT, lot))

        # 9. DD after trade
        dd_after = daily_dd_percent + adj_risk_pct

        severity = (
            "CRITICAL" if dd_after >= 4.0 else
            "WARNING"  if dd_after >= 2.5 else
            "SAFE"
        )

        return {
            "trade_allowed": True,
            "recommended_lot": lot,
            "max_safe_lot": lot,
            "raw_lot": round(raw_lot, 4),
            "risk_used_percent": round(adj_risk_pct, 3),
            "risk_amount_usd": round(risk_amount, 2),
            "sl_distance_pips": round(sl_distance_pips, 1),
            "daily_dd_after": round(dd_after, 3),
            "dd_multiplier": mult,
            "severity": severity,
            "pip_value": pip_val,
        }

    def calculate_split_lots(
        self,
        balance: float,
        equity: float,
        daily_dd_percent: float,
        pair: str,
        entry: float,
        sl: float,
        risk_percent: float,
        split_ratio: float = 0.5,
    ) -> dict:
        """Calculate two-leg split entry lots."""
        base = self.calculate_lot(
            balance, equity, daily_dd_percent, pair, entry, sl, risk_percent
        )
        if not base.get("trade_allowed"):
            return base

        total = base["recommended_lot"]
        leg1 = self._round_lot(total * split_ratio)
        leg2 = self._round_lot(total * (1 - split_ratio))
        base["split_lots"] = [leg1, leg2]
        base["risk_mode"] = "SPLIT"
        return base

    @staticmethod
    def _round_lot(lot: float) -> float:
        """Round to 0.01 lot step."""
        return math.floor(lot * 100) / 100.0

    @staticmethod
    def _blocked(code: str, reason: str) -> dict:
        return {
            "trade_allowed": False,
            "recommended_lot": 0.0,
            "max_safe_lot": 0.0,
            "severity": "CRITICAL",
            "code": code,
            "reason": reason,
        }


# ── [BUG-2 FIX] Aliases defined AFTER class — no NameError on import ─────────
RiskMultiplier = RiskMultiplierAggregator
RiskEngine = RiskMultiplierAggregator
