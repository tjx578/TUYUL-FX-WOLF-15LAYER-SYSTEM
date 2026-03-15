"""
Risk Engine v2 - Account Governor

Single entry-point for trade risk evaluation.
Does NOT: determine BUY/SELL, modify SL/TP, read market structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from risk.correlation_guard import CorrelationGuard, CorrelationVerdict
from risk.exceptions import (
    InvalidPositionSize,
    RiskCalculationError,
)
from risk.open_risk_tracker import OpenRiskTracker, OpenTrade
from risk.risk_manager import RiskManager
from risk.risk_profile import RiskMode, RiskProfile, load_risk_profile


class RiskVerdict(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass
class RiskEvalResult:
    verdict: RiskVerdict
    deny_code: str | None = None
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
    sl_distance_2: float | None = None


class RiskEngineV2:
    """Account Governor - evaluates trade risk and returns ALLOW/DENY."""

    def __init__(
        self,
        account_id: str,
        risk_manager: RiskManager | None = None,
        correlation_guard: CorrelationGuard | None = None,
    ) -> None:
        self._account_id = account_id
        self._rm = risk_manager or RiskManager.get_instance()
        self._tracker = OpenRiskTracker(account_id)
        self._corr_guard = correlation_guard

    def evaluate(
        self, signal: SignalInput, vix_level: float | None = None, session: str | None = None
    ) -> RiskEvalResult:
        """Evaluate a trading signal against all risk constraints."""
        profile = load_risk_profile(self._account_id)

        # Step 1: Circuit breaker / drawdown check
        if not self._rm.is_trading_allowed(category="forex"):
            logger.warning(
                "Trade DENIED: circuit breaker or drawdown",
                account_id=self._account_id,
                trade_id=signal.trade_id,
            )
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="CIRCUIT_BREAKER",
                details={
                    "reason": "Circuit breaker OPEN or drawdown breached",
                    "snapshot": self._rm.get_risk_snapshot(vix_level, session),
                },
            )

        # Step 2: Open trades limit
        tracker_snapshot = self._tracker.get_snapshot()
        current_open = tracker_snapshot["open_trade_count"]
        if current_open >= profile.max_open_trades:
            logger.warning(
                "Trade DENIED: max open trades reached",
                account_id=self._account_id,
                current=current_open,
                max_allowed=profile.max_open_trades,
            )
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="MAX_OPEN_TRADES",
                open_trades_after=current_open,
                details={
                    "reason": f"Open trades {current_open} >= max {profile.max_open_trades}",
                    "open_trades": tracker_snapshot,
                },
            )

        # Step 3: Correlation risk guard (atomic enforcement)
        if self._corr_guard is not None:
            snapshot_snap = self._rm.get_risk_snapshot(vix_level, session)
            equity = snapshot_snap.get("equity", snapshot_snap.get("balance", 0))
            # Estimate risk amount from profile (rough pre-sizing estimate)
            estimated_risk = equity * (profile.risk_per_trade / 100.0) if equity > 0 else 0.0
            corr_result = self._corr_guard.evaluate(
                proposed_symbol=signal.symbol,
                proposed_direction=signal.direction,
                proposed_risk_amount=estimated_risk,
                open_trades=tracker_snapshot.get("trades", []),
                account_equity=equity,
            )
            if corr_result.verdict == CorrelationVerdict.BLOCK:
                logger.warning(
                    "Trade DENIED: correlation risk",
                    account_id=self._account_id,
                    symbol=signal.symbol,
                    correlated=corr_result.correlated_symbols,
                    combined_exposure=corr_result.combined_exposure,
                    max_corr=corr_result.max_correlation,
                )
                return RiskEvalResult(
                    verdict=RiskVerdict.DENY,
                    deny_code="CORRELATION_RISK",
                    details={
                        "reason": corr_result.reason,
                        "correlation_guard": corr_result.to_dict(),
                    },
                )

        # Step 4: Calculate lot(s)
        try:
            lots = self._calculate_lots(signal=signal, profile=profile, vix_level=vix_level, session=session)
        except (InvalidPositionSize, RiskCalculationError) as exc:
            logger.warning("Trade DENIED: position sizing failed", account_id=self._account_id, error=str(exc))
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="POSITION_SIZING_FAILED",
                details={"reason": str(exc)},
            )

        # Step 5: Prop firm compliance
        total_risk_amount = sum(lot["risk_amount"] for lot in lots)
        snapshot = self._rm.get_risk_snapshot(vix_level, session)
        balance = snapshot["balance"]
        effective_risk_pct = total_risk_amount / balance if balance > 0 else 0.0
        compliance = self._rm.check_prop_firm_compliance(
            {"risk_percent": effective_risk_pct, "rr_ratio": signal.rr_ratio}
        )
        if not compliance["compliant"]:
            logger.warning(
                "Trade DENIED: prop firm violation",
                account_id=self._account_id,
                violations=compliance["violations"],
            )
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="PROP_FIRM_VIOLATION",
                lots=lots,
                risk_amount=total_risk_amount,
                details={
                    "reason": "Prop firm rule violation",
                    "violations": compliance["violations"],
                },
            )

        # Step 6: Final lot check
        total_lot = sum(lot["lot_size"] for lot in lots)
        if total_lot <= 0:
            return RiskEvalResult(
                verdict=RiskVerdict.DENY,
                deny_code="LOT_SIZE_ZERO",
                details={"reason": "Calculated lot size is zero"},
            )

        # Step 7: Projected open risk
        current_risk = tracker_snapshot["open_risk_amount"]
        projected_risk = current_risk + total_risk_amount

        logger.info(
            "Trade ALLOWED",
            account_id=self._account_id,
            trade_id=signal.trade_id,
            symbol=signal.symbol,
            risk_mode=profile.risk_mode.value,
            lots=[lot["lot_size"] for lot in lots],
            total_risk=total_risk_amount,
            projected_open_risk=projected_risk,
        )

        return RiskEvalResult(
            verdict=RiskVerdict.ALLOW,
            lots=lots,
            risk_amount=total_risk_amount,
            open_risk_after=projected_risk,
            open_trades_after=current_open + 1,
            details={
                "profile": profile.to_dict(),
                "risk_snapshot": snapshot,
                "compliance": compliance,
                "projected_open_risk": projected_risk,
            },
        )

    def _calculate_lots(
        self,
        signal: SignalInput,
        profile: RiskProfile,
        vix_level: float | None,
        session: str | None,
    ) -> list[dict]:
        if profile.risk_mode == RiskMode.FIXED:
            position = self._rm.calculate_position(
                entry_price=signal.entry_price,
                stop_loss_price=signal.stop_loss,
                pair=signal.symbol,
                risk_percent=profile.risk_per_trade / 100.0,
                vix_level=vix_level,
                session=session,
            )
            position["entry_number"] = 1
            return [position]

        # SPLIT mode: 2 entries
        ratio_1, ratio_2 = profile.split_ratio
        position_1 = self._rm.calculate_position(
            entry_price=signal.entry_price,
            stop_loss_price=signal.stop_loss,
            pair=signal.symbol,
            risk_percent=(profile.risk_per_trade / 100.0) * ratio_1,
            vix_level=vix_level,
            session=session,
        )
        position_1["entry_number"] = 1
        position_1["split_ratio"] = ratio_1

        sl_2 = signal.stop_loss
        if signal.sl_distance_2 is not None:
            sl_2 = (
                signal.entry_price - signal.sl_distance_2
                if signal.direction == "BUY"
                else signal.entry_price + signal.sl_distance_2
            )

        position_2 = self._rm.calculate_position(
            entry_price=signal.entry_price,
            stop_loss_price=sl_2,
            pair=signal.symbol,
            risk_percent=(profile.risk_per_trade / 100.0) * ratio_2,
            vix_level=vix_level,
            session=session,
        )
        position_2["entry_number"] = 2
        position_2["split_ratio"] = ratio_2

        return [position_1, position_2]

    def _calculate_pip_value(self, lot_size: float, pips_at_risk: float, risk_amount: float) -> float:
        """
        Calculate pip value from position parameters.

        Args:
            lot_size: Position size in lots
            pips_at_risk: Stop loss distance in pips
            risk_amount: Total risk amount in account currency

        Returns:
            Pip value per lot, or 0.0 if calculation would divide by zero
        """
        if lot_size > 0 and pips_at_risk > 0:
            return risk_amount / (lot_size * pips_at_risk)
        return 0.0

    def register_intended_trade(self, signal: SignalInput, lots: list[dict]) -> None:
        for lot in lots:
            pip_value = self._calculate_pip_value(lot["lot_size"], lot["pips_at_risk"], lot["risk_amount"])
            trade = OpenTrade(
                trade_id=signal.trade_id,
                symbol=signal.symbol,
                lot_size=lot["lot_size"],
                sl_distance_pips=lot["pips_at_risk"],
                pip_value=pip_value,
                risk_amount=lot["risk_amount"],
                entry_number=lot.get("entry_number", 1),
            )
            self._tracker.add_trade(trade)

    def close_trade(self, trade_id: str, entry_number: int = 1) -> None:
        self._tracker.remove_trade(trade_id, entry_number)

    def get_account_snapshot(self, vix_level: float | None = None, session: str | None = None) -> dict:
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
