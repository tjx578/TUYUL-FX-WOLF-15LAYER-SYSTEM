"""
Risk Engine v2 — Account Governor

Single entry-point for trade risk evaluation.
Does NOT: determine BUY/SELL, modify SL/TP, read market structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger

from risk.exceptions import (
    InvalidPositionSize,
    RiskCalculationError,
)
from risk.open_risk_tracker import OpenRiskTracker, OpenTrade
from risk.risk_profile import RiskMode, RiskProfile, load_risk_profile
from risk.risk_manager import RiskManager


class RiskVerdict(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass
class RiskEvalResult:
    verdict: RiskVerdict
    deny_code: Optional[str] = None
    lots: list[dict] | None = None
    risk_amount: float = 0.0
    open_risk_after: float = 0.0
    open_trades_after: int = 0
    details: dict | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict == RiskVerdict.ALLOW


@dataclass
class SignalInput:
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    rr_ratio: float
    trade_id: str
    sl_distance_2: Optional[float] = None


class RiskEngineV2:
    """Account Governor — evaluates trade risk and returns ALLOW/DENY."""

    def __init__(self, account_id: str, risk_manager: Optional[RiskManager] = None) -> None:
        self._account_id = account_id
        self._rm = risk_manager or RiskManager.get_instance()
        self._tracker = OpenRiskTracker(account_id)

    def evaluate(self, signal: SignalInput, vix_level: Optional[float] = None, session: Optional[str] = None) -> RiskEvalResult:
        """Evaluate a trading signal against all risk constraints."""
        profile = load_risk_profile(self._account_id)

        # Step 1: Circuit breaker / drawdown check
        if not self._rm.is_trading_allowed(category="forex"):
            logger.warning("Trade DENIED: circuit breaker or drawdown", account_id=self._account_id, trade_id=signal.trade_id)
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="CIRCUIT_BREAKER",
                details={"reason": "Circuit breaker OPEN or drawdown breached", "snapshot": self._rm.get_risk_snapshot(vix_level, session)},
            )

        # Step 2: Open trades limit
        tracker_snapshot = self._tracker.get_snapshot()
        current_open = tracker_snapshot["open_trade_count"]
        if current_open >= profile.max_open_trades:
            logger.warning("Trade DENIED: max open trades reached", account_id=self._account_id, current=current_open, max_allowed=profile.max_open_trades)
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="MAX_OPEN_TRADES",
                open_trades_after=current_open,
                details={"reason": f"Open trades {current_open} >= max {profile.max_open_trades}", "open_trades": tracker_snapshot},
            )

        # Step 3: Calculate lot(s)
        try:
            lots = self._calculate_lots(signal=signal, profile=profile, vix_level=vix_level, session=session)
        except (InvalidPositionSize, RiskCalculationError) as exc:
            logger.warning("Trade DENIED: position sizing failed", account_id=self._account_id, error=str(exc))
            return RiskEvalResult(verdict=RiskVerdict.DENY, deny_code="POSITION_SIZING_FAILED", details={"reason": str(exc)})

        # Step 4: Prop firm compliance
        total_risk_amount = sum(lot["risk_amount"] for lot in lots)
        snapshot = self._rm.get_risk_snapshot(vix_level, session)
        balance = snapshot["balance"]
        effective_risk_pct = total_risk_amount / balance if balance > 0 else 0.0
        compliance = self._rm.check_prop_firm_compliance({"risk_percent": effective_risk_pct, "rr_ratio": signal.rr_ratio})
        if not compliance["compliant"]:
            logger.warning("Trade DENIED: prop firm violation", account_id=self._account_id, violations=compliance["violations"])
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="PROP_FIRM_VIOLATION",
                lots=lots,
                risk_amount=total_risk_amount,
                details={"reason": "Prop firm rule violation", "violations": compliance["violations"]},
            )

        # Step 5: Final lot check
        total_lot = sum(lot["lot_size"] for lot in lots)
        if total_lot <= 0:
            return RiskEvalResult(verdict=RiskVerdict.DENY, deny_code="LOT_SIZE_ZERO", details={"reason": "Calculated lot size is zero"})

        # Step 6: Projected open risk
        current_risk = tracker_snapshot["open_risk_amount"]
        projected_risk = current_risk + total_risk_amount

        logger.info("Trade ALLOWED", account_id=self._account_id, trade_id=signal.trade_id, symbol=signal.symbol, risk_mode=profile.risk_mode.value, lots=[lot["lot_size"] for lot in lots], total_risk=total_risk_amount, projected_open_risk=projected_risk)

        return RiskEvalResult(
            verdict=RiskVerdict.ALLOW,
            lots=lots,
            risk_amount=total_risk_amount,
            open_risk_after=projected_risk,
            open_trades_after=current_open + 1,
            details={"profile": profile.to_dict(), "risk_snapshot": snapshot, "compliance": compliance, "projected_open_risk": projected_risk},
        )

    def _calculate_lots(self, signal: SignalInput, profile: RiskProfile, vix_level: Optional[float], session: Optional[str]) -> list[dict]:
        if profile.risk_mode == RiskMode.FIXED:
            position = self._rm.calculate_position(
                entry_price=signal.entry_price, stop_loss_price=signal.stop_loss, pair=signal.symbol,
                risk_percent=profile.risk_per_trade / 100.0, vix_level=vix_level, session=session,
            )
            position["entry_number"] = 1
            return [position]

        # SPLIT mode: 2 entries
        ratio_1, ratio_2 = profile.split_ratio
        position_1 = self._rm.calculate_position(
            entry_price=signal.entry_price, stop_loss_price=signal.stop_loss, pair=signal.symbol,
            risk_percent=(profile.risk_per_trade / 100.0) * ratio_1, vix_level=vix_level, session=session,
        )
        position_1["entry_number"] = 1
        position_1["split_ratio"] = ratio_1

        sl_2 = signal.stop_loss
        if signal.sl_distance_2 is not None:
            sl_2 = signal.entry_price - signal.sl_distance_2 if signal.direction == "BUY" else signal.entry_price + signal.sl_distance_2

        position_2 = self._rm.calculate_position(
            entry_price=signal.entry_price, stop_loss_price=sl_2, pair=signal.symbol,
            risk_percent=(profile.risk_per_trade / 100.0) * ratio_2, vix_level=vix_level, session=session,
        )
        position_2["entry_number"] = 2
        position_2["split_ratio"] = ratio_2

        return [position_1, position_2]

    def register_intended_trade(self, signal: SignalInput, lots: list[dict]) -> None:
        for lot in lots:
            trade = OpenTrade(
                trade_id=signal.trade_id, symbol=signal.symbol, lot_size=lot["lot_size"],
                sl_distance_pips=lot["pips_at_risk"],
                pip_value=lot["risk_amount"] / (lot["lot_size"] * lot["pips_at_risk"]) if lot["lot_size"] > 0 and lot["pips_at_risk"] > 0 else 0.0,
                risk_amount=lot["risk_amount"], entry_number=lot.get("entry_number", 1),
            )
            self._tracker.add_trade(trade)

    def close_trade(self, trade_id: str, entry_number: int = 1) -> None:
        self._tracker.remove_trade(trade_id, entry_number)

    def get_account_snapshot(self, vix_level: Optional[float] = None, session: Optional[str] = None) -> dict:
        profile = load_risk_profile(self._account_id)
        risk_snapshot = self._rm.get_risk_snapshot(vix_level, session)
        open_snapshot = self._tracker.get_snapshot()
        return {
            "account_id": self._account_id,
            "profile": profile.to_dict(),
            "risk": risk_snapshot,
            "open_risk": open_snapshot,
            "trading_allowed": self._rm.is_trading_allowed(category="forex"),
        }
