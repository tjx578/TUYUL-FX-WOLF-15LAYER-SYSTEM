"""
Aqua Funded Prop Firm Guard

Enforces Aqua Funded general trading rules:
- No hard numeric DD or risk limits are defined in this general-rules profile.
- When numeric risk keys are present in the rules they are honoured;
  otherwise sensible safe defaults are used.
- Characteristics from the Aqua Funded general trading rules:
    - EAs and trade copiers are allowed.
    - No lot size limits.
    - Overnight and weekend holding allowed.
    - Hedging (same account) and Martingale strategies permitted.
    - Stop loss is not required.

Supports both v1 (flat rules) and v2 (nested default_rules) YAML formats.
"""

from __future__ import annotations

from typing import Any

from propfirm_manager.profiles.base_guard import (
    BasePropFirmGuard,
    GuardResult,
)


class AquafundedGuard(BasePropFirmGuard):
    """Aqua Funded prop firm rule enforcement."""

    # Fallback defaults used when the profile does not supply numeric limits.
    # These are deliberately permissive (100%) rather than copying another
    # firm's hard caps.  The Aqua Funded general-rules profile only publishes
    # qualitative trading rules (EAs allowed, no lot limits, etc.) and does
    # not define numeric daily/total DD or per-trade risk thresholds.  Using
    # 100% ensures that the guard never incorrectly rejects trades due to
    # absent configuration, while still correctly enforcing any explicit
    # limits that may be added to the profile in the future.
    _DEFAULT_MAX_DAILY_DD: float = 100.0
    _DEFAULT_MAX_TOTAL_DD: float = 100.0
    _DEFAULT_MAX_RISK_PER_TRADE: float = 100.0
    _DEFAULT_MAX_OPEN_TRADES: int = 0  # 0 = unlimited

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        """
        Initialize guard with flat or v2-structured rules.

        Args:
            rules: Flat rules dict (v1) or dict that may contain nested
                   v2 structure.  In v2, ``default_rules`` is extracted
                   and used as the effective flat rules.  Safe to pass
                   an empty dict or ``None`` when the profile only
                   defines ``general_trading_rules`` metadata.
        """
        super().__init__(self._normalise(rules or {}))

    @staticmethod
    def _normalise(rules: dict[str, Any]) -> dict[str, Any]:
        """Extract flat rules from v1 or v2 rule dict."""
        if "default_rules" in rules:
            return dict(rules["default_rules"])
        return rules

    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """
        Evaluate trade against Aqua Funded rules.

        Numeric limits from the profile are honoured when present.
        When a limit is absent the permissive class-level default is used
        so that a general-rules-only profile never incorrectly blocks trades.

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
        open_trades: int = account_state.get("open_trades", 0)
        daily_dd_after: float = trade_risk.get("daily_dd_after", 0.0)
        total_dd_after: float = trade_risk.get("total_dd_after", 0.0)
        risk_percent: float = trade_risk.get("risk_percent", 0.0)

        max_daily_dd: float = float(
            self.rules.get("max_daily_dd_percent", self._DEFAULT_MAX_DAILY_DD)
        )
        max_total_dd: float = float(
            self.rules.get("max_total_dd_percent", self._DEFAULT_MAX_TOTAL_DD)
        )
        max_risk_per_trade: float = float(
            self.rules.get("max_risk_per_trade_percent", self._DEFAULT_MAX_RISK_PER_TRADE)
        )
        max_open: int = int(
            self.rules.get("max_open_trades", self._DEFAULT_MAX_OPEN_TRADES)
        )

        # Only enforce open-trade cap when a finite limit is configured.
        if max_open > 0 and open_trades >= max_open:
            return self._deny(
                "DENY_MAX_OPEN_TRADES",
                f"Max {max_open} open trade(s) allowed, currently {open_trades} open",
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

        # Only warn when limits are finite (< 100) to avoid noise on
        # permissive defaults.
        if max_daily_dd < 100.0:
            warn_daily = max_daily_dd * 0.8
            if daily_dd_after >= warn_daily:
                return self._warn(
                    "WARN_HIGH_DAILY_DD",
                    f"Daily DD would be {daily_dd_after:.2f}%, approaching limit of {max_daily_dd}%",
                )

        if max_total_dd < 100.0:
            warn_total = max_total_dd * 0.8
            if total_dd_after >= warn_total:
                return self._warn(
                    "WARN_HIGH_TOTAL_DD",
                    f"Total DD would be {total_dd_after:.2f}%, approaching limit of {max_total_dd}%",
                )

        return self._allow()
