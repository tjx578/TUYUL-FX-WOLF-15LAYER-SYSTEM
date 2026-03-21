"""FTMO prop firm guard.

Supports both v1 (flat rules) and v2 (nested plans/phases) YAML formats.
"""

from __future__ import annotations

from typing import Any

from propfirm_manager.profiles.base_guard import BasePropFirmGuard, GuardResult


class FTMOGuard(BasePropFirmGuard):
    """FTMO prop firm rule enforcement."""

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """
        Initialize guard with flat or v2-structured rules.

        Args:
            rules: Flat rules dict (v1) or dict that may contain nested
                   v2 structure. In v2, ``default_rules`` is extracted
                   and used as the effective flat rules.
        """
        super().__init__(self._normalise(rules or {}))

    @staticmethod
    def _normalise(rules: dict[str, Any]) -> dict[str, Any]:
        """Extract flat rules from v1 or v2 rule dict."""
        if "default_rules" in rules:
            return dict(rules["default_rules"])
        return rules

    def check(self, account_state: dict[str, Any], trade_risk: dict[str, Any]) -> GuardResult:
        open_trades = account_state.get("open_trades", 0)
        daily_dd_after = trade_risk.get("daily_dd_after", 0)
        total_dd_after = trade_risk.get("total_dd_after", 0)
        risk_percent = trade_risk.get("risk_percent", 0)

        max_daily_dd = self.rules.get("max_daily_dd_percent", 5.0)
        max_total_dd = self.rules.get("max_total_dd_percent", 10.0)
        max_risk_per_trade = self.rules.get("max_risk_per_trade_percent", 1.0)
        max_open = self.rules.get("max_open_trades", 1)

        if open_trades >= max_open:
            return self._deny(
                "DENY_MAX_OPEN_TRADES",
                f"Max {max_open} open trade(s) allowed, currently {open_trades}",
            )
        if risk_percent > max_risk_per_trade:
            return self._deny(
                "DENY_RISK_PER_TRADE",
                f"Risk {risk_percent:.2f}% exceeds max {max_risk_per_trade}%",
            )
        if daily_dd_after > max_daily_dd:
            return self._deny(
                "DENY_DAILY_DD",
                f"Daily DD would reach {daily_dd_after:.2f}%, max {max_daily_dd}%",
            )
        if total_dd_after > max_total_dd:
            return self._deny(
                "DENY_TOTAL_DD",
                f"Total DD would reach {total_dd_after:.2f}%, max {max_total_dd}%",
            )

        # Warning thresholds (80% of limits)
        warn_daily = max_daily_dd * 0.8
        warn_total = max_total_dd * 0.8

        if daily_dd_after >= warn_daily:
            return self._warn(
                "WARN_HIGH_DAILY_DD",
                f"Daily DD would be {daily_dd_after:.2f}%, approaching limit of {max_daily_dd}%",
            )
        if total_dd_after >= warn_total:
            return self._warn(
                "WARN_HIGH_TOTAL_DD",
                f"Total DD would be {total_dd_after:.2f}%, approaching limit of {max_total_dd}%",
            )

        return self._allow()
