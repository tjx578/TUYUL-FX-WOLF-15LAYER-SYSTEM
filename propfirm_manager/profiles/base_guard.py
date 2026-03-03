"""
Base Prop Firm Guard — abstract interface for all prop firm guards.
"""
from abc import ABC, abstractmethod
from typing import Any

from accounts.account_model import RiskSeverity


class GuardResult:
    def __init__(self, allowed: bool, code: str, severity: RiskSeverity, details: str):
        self.allowed = allowed
        self.code = code
        self.severity = severity
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "code": self.code, "severity": self.severity.value, "details": self.details}


class BasePropFirmGuard(ABC):
    def __init__(self, rules: dict[str, Any]):
        self.rules = rules

    @abstractmethod
    def check(self, account_state: dict[str, Any], trade_risk: dict[str, Any]) -> GuardResult: ...

    def _deny(self, code: str, details: str) -> GuardResult:
        from accounts.account_model import RiskSeverity  # noqa: PLC0415
        return GuardResult(allowed=False, code=code, severity=RiskSeverity.CRITICAL, details=details)

    def _warn(self, code: str, details: str) -> GuardResult:
        from accounts.account_model import RiskSeverity  # noqa: PLC0415
        return GuardResult(allowed=True, code=code, severity=RiskSeverity.WARNING, details=details)

    def _allow(self) -> GuardResult:
        from accounts.account_model import RiskSeverity  # noqa: PLC0415
        return GuardResult(allowed=True, code="ALLOW", severity=RiskSeverity.SAFE, details="Trade approved")
"""
Base Prop Firm Guard

Abstract base class for all prop-firm guard profiles.
Provides the standard interface:
    check(account_state, trade_risk) -> GuardResult
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GuardResult:
    """Standardised result from a prop-firm guard check.

    Attributes:
        allowed: Whether the trade is permitted.
        code: Machine-readable status code (e.g. "ALLOW", "DENY_DAILY_DD").
        severity: "allow" | "warn" | "deny".
        details: Optional human-readable explanation.
    """

    allowed: bool
    code: str
    severity: str  # "allow" | "warn" | "deny"
    details: str = ""


class BasePropFirmGuard:
    """Abstract base for all prop-firm guard profiles.

    Subclasses must override ``check()``.

    Args:
        rules: A dict of firm-specific rule parameters loaded from a
               profile config (e.g. max_daily_dd_percent, max_open_trades).
    """

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules: dict[str, Any] = rules or {}

    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """Evaluate a prospective trade against firm rules.

        Must be overridden by every concrete guard.
        """
        raise NotImplementedError("Subclasses must implement check()")

    # ── helper factories ────────────────────────────────────────────

    @staticmethod
    def _allow() -> GuardResult:
        return GuardResult(allowed=True, code="ALLOW", severity="allow")

    @staticmethod
    def _deny(code: str, details: str = "") -> GuardResult:
        return GuardResult(allowed=False, code=code, severity="deny", details=details)

    @staticmethod
    def _warn(code: str, details: str = "") -> GuardResult:
        return GuardResult(allowed=True, code=code, severity="warn", details=details)
