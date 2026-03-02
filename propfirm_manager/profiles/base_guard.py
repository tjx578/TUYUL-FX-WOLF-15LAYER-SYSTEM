"""
Base Prop Firm Guard

Abstract base class for prop firm rule enforcement.
"""

from abc import ABC, abstractmethod
from typing import Any

from accounts.account_model import RiskSeverity


class GuardResult:
    """Result of a prop firm guard check."""

    def __init__(
        self,
        allowed: bool,
        code: str,
        severity: RiskSeverity,
        details: str,
    ):
        """
        Initialize guard result.

        Args:
            allowed: Whether trade is allowed
            code: Result code (ALLOW, WARN_*, DENY_*)
            severity: Risk severity level
            details: Human-readable explanation
        """
        self.allowed = allowed
        self.code = code
        self.severity = severity
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "allowed": self.allowed,
            "code": self.code,
            "severity": self.severity.value,
            "details": self.details,
        }


class BasePropFirmGuard(ABC):
    """
    Abstract base class for prop firm guards.

    Each prop firm implements this interface to enforce their
    specific rules (DD limits, max open trades, etc.).
    """

    def __init__(self, rules: dict[str, Any]):
        """
        Initialize guard with firm rules.

        Args:
            rules: Dictionary of prop firm rules
        """
        self.rules = rules

    @abstractmethod
    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """
        Evaluate if trade is allowed under prop firm rules.

        Args:
            account_state: Current account state (balance, DD, etc.)
            trade_risk: Proposed trade risk parameters

        Returns:
            GuardResult indicating ALLOW/WARN/DENY
        """
        pass

    # Helper methods for subclasses

    def _allow(self) -> GuardResult:
        """Return ALLOW result."""
        return GuardResult(
            allowed=True,
            code="ALLOW",
            severity=RiskSeverity.SAFE,
            details="Trade allowed - all checks passed",
        )

    def _warn(self, code: str, details: str) -> GuardResult:
        """
        Return WARNING result.

        Args:
            code: Warning code (e.g., WARN_HIGH_DD)
            details: Explanation

        Returns:
            GuardResult with WARNING severity
        """
        return GuardResult(
            allowed=True,
            code=code,
            severity=RiskSeverity.WARNING,
            details=details,
        )

    def _deny(self, code: str, details: str) -> GuardResult:
        """
        Return DENY result.

        Args:
            code: Denial code (e.g., DENY_MAX_DD)
            details: Explanation

        Returns:
            GuardResult with CRITICAL severity
        """
        return GuardResult(
            allowed=False,
            code=code,
            severity=RiskSeverity.CRITICAL,
            details=details,
        )
