"""
FTMO Prop Firm Guard

Enforces FTMO-specific rules:
- Max 5% daily drawdown
- Max 10% total drawdown
- Max 1% risk per trade
- Max 1 open trade at a time
"""

from typing import Any

from propfirm_manager.profiles.base_guard import (
    BasePropFirmGuard,
    GuardResult,
)


class FTMOGuard(BasePropFirmGuard):
    """FTMO prop firm rule enforcement."""

    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """
        Evaluate trade against FTMO rules.

        Args:
            account_state: {
                "daily_dd_percent": float,
                "total_dd_percent": float,
                "open_trades": int,
                "balance": float,
            }
            trade_risk: {
                "risk_percent": float,
                "daily_dd_after": float,
                "total_dd_after": float,
            }

        Returns:
            GuardResult
        """
        # Extract values
        open_trades = account_state.get("open_trades", 0)
        daily_dd_after = trade_risk.get("daily_dd_after", 0)
        total_dd_after = trade_risk.get("total_dd_after", 0)
        risk_percent = trade_risk.get("risk_percent", 0)

        # Get limits from rules
        max_daily_dd = self.rules["max_daily_dd_percent"]
        max_total_dd = self.rules["max_total_dd_percent"]
        max_risk_per_trade = self.rules["max_risk_per_trade_percent"]
        max_open = self.rules["max_open_trades"]

        # Check 1: Max open trades
        if open_trades >= max_open:
            return self._deny(
                "DENY_MAX_OPEN_TRADES",
                f"Max {max_open} open trade(s) allowed, currently {open_trades} open",
            )

        # Check 2: Risk per trade
        if risk_percent > max_risk_per_trade:
            return self._deny(
                "DENY_RISK_PER_TRADE", f"Risk {risk_percent:.2f}% exceeds max {max_risk_per_trade}%"
            )

        # Check 3: Daily DD projection
        if daily_dd_after > max_daily_dd:
            return self._deny(
                "DENY_DAILY_DD", f"Daily DD would reach {daily_dd_after:.2f}%, max {max_daily_dd}%"
            )

        # Check 4: Total DD projection
        if total_dd_after > max_total_dd:
            return self._deny(
                "DENY_TOTAL_DD", f"Total DD would reach {total_dd_after:.2f}%, max {max_total_dd}%"
            )

        # Check 5: Warning thresholds (80% of limits)
        warn_daily_threshold = max_daily_dd * 0.8
        warn_total_threshold = max_total_dd * 0.8

        if daily_dd_after >= warn_daily_threshold:
            return self._warn(
                "WARN_HIGH_DAILY_DD",
                f"Daily DD would be {daily_dd_after:.2f}%, approaching limit of {max_daily_dd}%",
            )

        if total_dd_after >= warn_total_threshold:
            return self._warn(
                "WARN_HIGH_TOTAL_DD",
                f"Total DD would be {total_dd_after:.2f}%, approaching limit of {max_total_dd}%",
            )

        # All checks passed
        return self._allow()
