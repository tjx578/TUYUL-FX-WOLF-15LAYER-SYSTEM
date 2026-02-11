"""
Risk Engine - Lot Calculator with Prop Firm Integration

Calculates position size based on:
- Account balance
- Risk percentage
- Stop loss distance
- Pair pip value
- Drawdown multiplier
- Prop firm rules

Formula: lot = risk_amount / (sl_distance × pip_value)
"""

from typing import Dict, List, Optional

from loguru import logger

from dashboard.backend.schemas import (
    AccountState,
    Layer12Signal,
    RiskCalculationResult,
    RiskMode,
    RiskSeverity,
)
from propfirm_manager.profile_manager import PropFirmManager
from risk.risk_multiplier import RiskMultiplier


# Pip value lookup (for 1 standard lot)
PIP_VALUES: Dict[str, float] = {
    "XAUUSD": 0.10,      # Gold
    "EURUSD": 10.0,      # Euro
    "GBPUSD": 10.0,      # Pound
    "USDJPY": 6.50,      # Yen
    "USDCHF": 10.0,      # Swiss Franc
    "AUDUSD": 10.0,      # Aussie Dollar
    "NZDUSD": 10.0,      # Kiwi Dollar
    "USDCAD": 10.0,      # Canadian Dollar
}


class RiskEngine:
    """
    Risk and lot size calculator with prop firm validation.

    Integrates:
        - risk/risk_multiplier.py for DD-based adjustment
        - propfirm_manager for rule validation
    """

    def __init__(self):
        """Initialize risk engine."""
        self.risk_multiplier = RiskMultiplier()

    def calculate_lot(
        self,
        signal: Layer12Signal,
        account_state: AccountState,
        risk_percent: float,
        prop_firm_code: str,
        risk_mode: RiskMode = RiskMode.FIXED,
        split_ratios: Optional[List[float]] = None,
    ) -> RiskCalculationResult:
        """
        Calculate recommended lot size with prop firm validation.

        Args:
            signal: Layer 12 signal (entry, SL, TP)
            account_state: Current account state
            risk_percent: Base risk percentage per trade
            prop_firm_code: Prop firm profile code
            risk_mode: FIXED or SPLIT
            split_ratios: For SPLIT mode, e.g., [0.5, 0.3, 0.2]

        Returns:
            RiskCalculationResult with lot recommendation
        """
        # Get pip value for pair
        pip_value = PIP_VALUES.get(signal.pair, 10.0)

        # Calculate SL distance in pips
        sl_distance = self._calculate_sl_distance(
            signal.entry, signal.stop_loss, signal.direction, signal.pair
        )

        if sl_distance <= 0:
            return RiskCalculationResult(
                trade_allowed=False,
                recommended_lot=0.0,
                max_safe_lot=0.0,
                risk_used_percent=0.0,
                daily_dd_after=account_state.daily_dd_percent,
                total_dd_after=account_state.total_dd_percent,
                severity=RiskSeverity.CRITICAL,
                reason="Invalid SL distance (zero or negative)",
            )

        # Apply drawdown multiplier
        # Convert total_dd_percent (percentage) to fraction for multiplier
        dd_level = account_state.total_dd_percent / 100.0
        multiplier = self.risk_multiplier.calculate(dd_level)
        adjusted_risk_percent = risk_percent * multiplier

        logger.debug(
            f"Risk adjustment: base={risk_percent:.2f}% | "
            f"multiplier={multiplier:.2f} | "
            f"adjusted={adjusted_risk_percent:.2f}%"
        )

        # Calculate risk amount
        risk_amount = account_state.balance * (adjusted_risk_percent / 100)

        # Calculate lot size
        # lot = risk_amount / (sl_distance × pip_value)
        lot = risk_amount / (sl_distance * pip_value)

        # Handle split risk mode
        split_lots = None
        if risk_mode == RiskMode.SPLIT and split_ratios:
            split_lots = [lot * ratio for ratio in split_ratios]
            _total_lot = lot  # Keep total lot same for validation
        else:
            _total_lot = lot

        # Project drawdown after trade loss
        daily_dd_after = account_state.daily_dd_percent + adjusted_risk_percent
        total_dd_after = account_state.total_dd_percent + adjusted_risk_percent

        # Validate with prop firm guard
        try:
            manager = PropFirmManager.for_account(account_state.account_id)
        except (FileNotFoundError, ValueError) as e:
            # Fail-safe: if prop firm guard can't load, DENY by default
            logger.error(f"Prop firm manager load failed: {e}")
            return RiskCalculationResult(
                trade_allowed=False,
                recommended_lot=0.0,
                max_safe_lot=0.0,
                risk_used_percent=0.0,
                daily_dd_after=daily_dd_after,
                total_dd_after=total_dd_after,
                severity=RiskSeverity.CRITICAL,
                reason=f"Prop firm guard unavailable: {e}",
            )

        # Prepare state and risk dicts for guard
        account_state_dict = {
            "daily_dd_percent": account_state.daily_dd_percent,
            "total_dd_percent": account_state.total_dd_percent,
            "open_trades": account_state.open_trades,
            "balance": account_state.balance,
        }

        trade_risk_dict = {
            "risk_percent": adjusted_risk_percent,
            "daily_dd_after": daily_dd_after,
            "total_dd_after": total_dd_after,
        }

        guard_result = manager.evaluate_trade(
            account_state_dict, trade_risk_dict
        )

        # Determine severity
        if not guard_result.allowed:
            severity = RiskSeverity.CRITICAL
        elif guard_result.severity.value == "WARNING":
            severity = RiskSeverity.WARNING
        else:
            severity = RiskSeverity.SAFE

        return RiskCalculationResult(
            trade_allowed=guard_result.allowed,
            recommended_lot=round(lot, 2),
            max_safe_lot=round(lot, 2),
            risk_used_percent=adjusted_risk_percent,
            daily_dd_after=daily_dd_after,
            total_dd_after=total_dd_after,
            severity=severity,
            reason=guard_result.details,
            split_lots=[round(sl, 2) for sl in split_lots] if split_lots else None,
        )

    def _calculate_sl_distance(
        self, entry: float, stop_loss: float, direction: str, pair: str
    ) -> float:
        """
        Calculate stop loss distance in pips.

        Args:
            entry: Entry price
            stop_loss: Stop loss price
            direction: BUY or SELL
            pair: Trading pair (for pip calculation)

        Returns:
            Distance in pips
        """
        if direction == "BUY":
            # For BUY: SL is below entry
            distance = abs(entry - stop_loss)
        else:  # SELL
            # For SELL: SL is above entry
            distance = abs(stop_loss - entry)

        # Convert to pips based on pair type
        # JPY pairs: 1 pip = 0.01 (2 decimal places)
        # Other pairs: 1 pip = 0.0001 (4 decimal places)
        if "JPY" in pair.upper():
            return distance * 100  # JPY pairs
        else:
            return distance * 10000  # Standard pairs
