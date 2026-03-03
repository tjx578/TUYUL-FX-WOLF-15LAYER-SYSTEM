"""Global compliance guard for orchestrator service.

This module evaluates account-level legality only and never computes market
direction, preserving constitutional authority boundaries.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ComplianceResult:
    allowed: bool
    code: str
    severity: str = "info"
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_compliance(account_state: dict[str, Any], trade_risk: dict[str, Any]) -> ComplianceResult:
    if not account_state:
        return ComplianceResult(False, "ACCOUNT_STATE_MISSING", "critical")
    if not trade_risk:
        return ComplianceResult(False, "TRADE_RISK_MISSING", "critical")
    return ComplianceResult(True, "OK")
