"""
Base Prop Firm Guard — abstract interface for all prop-firm guard profiles.
Provides the standard interface:
    check(account_state, trade_risk) -> GuardResult
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GuardResult:
    allowed: bool
    code: str
    severity: str  # "allow" | "warn" | "deny"
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "code": self.code, "severity": self.severity, "details": self.details}


class BasePropFirmGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.rules: dict[str, Any] = rules or {}

    def check(self, account_state: dict[str, Any], trade_risk: dict[str, Any]) -> GuardResult:
        raise NotImplementedError("Subclasses must implement check()")

    @staticmethod
    def _allow() -> GuardResult:
        return GuardResult(allowed=True, code="ALLOW", severity="allow")

    @staticmethod
    def _deny(code: str, details: str = "") -> GuardResult:
        return GuardResult(allowed=False, code=code, severity="deny", details=details)

    @staticmethod
    def _warn(code: str, details: str = "") -> GuardResult:
        return GuardResult(allowed=True, code=code, severity="warn", details=details)
