"""Script to rewrite propfirm_manager/profiles/base_guard.py cleanly."""
from pathlib import Path

CONTENT = """\
\"\"\"
Base Prop Firm Guard

Abstract base class for all prop-firm guard profiles.
Provides the standard interface:
    check(account_state, trade_risk) -> GuardResult

Authority:
    Dashboard must treat guard result as binding for risk legality.
    Guard result is NOT a market decision -- that is L12 authority.
\"\"\"

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GuardResult:
    \"\"\"Standardised result from a prop-firm guard check.

    Attributes:
        allowed: Whether the trade is permitted.
        code: Machine-readable status code (e.g. ALLOW, DENY_DAILY_DD).
        severity: allow | warn | deny
        details: Optional human-readable explanation.
    \"\"\"

    allowed: bool
    code: str
    severity: str  # "allow" | "warn" | "deny"
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "severity": self.severity,
            "details": self.details,
        }


class BasePropFirmGuard:
    \"\"\"Abstract base for all prop-firm guard profiles.

    Subclasses must override check().

    Args:
        rules: A dict of firm-specific rule parameters.
    \"\"\"

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules: dict[str, Any] = rules or {}

    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
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
"""

target = Path(__file__).resolve().parent.parent / "propfirm_manager" / "profiles" / "base_guard.py"
target.write_text(CONTENT, encoding="utf-8")
print(f"Wrote {target}")
