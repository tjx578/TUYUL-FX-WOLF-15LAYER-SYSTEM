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
    details: dict[str, Any] = field(default_factory=lambda: {})


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_compliance(account_state: dict[str, Any], trade_risk: dict[str, Any]) -> ComplianceResult:
    if not account_state:
        return ComplianceResult(False, "ACCOUNT_STATE_MISSING", "critical")

    balance = _to_float(account_state.get("balance"), 0.0)
    equity = _to_float(account_state.get("equity"), 0.0)
    if balance <= 0.0 or equity <= 0.0:
        return ComplianceResult(
            False,
            "ACCOUNT_VALUE_INVALID",
            "critical",
            {"balance": balance, "equity": equity},
        )

    compliance_mode = _to_bool(account_state.get("compliance_mode"), True)
    if not compliance_mode:
        return ComplianceResult(False, "COMPLIANCE_MODE_OFF", "critical")

    if _to_bool(account_state.get("account_locked"), False):
        return ComplianceResult(False, "ACCOUNT_LOCKED", "critical")

    system_state = str(account_state.get("system_state", "NORMAL")).upper()
    if system_state in {"LOCKDOWN", "HALTED", "KILL_SWITCH"}:
        return ComplianceResult(
            False,
            "SYSTEM_LOCKDOWN",
            "critical",
            {"system_state": system_state},
        )

    if _to_bool(account_state.get("circuit_breaker"), False):
        return ComplianceResult(False, "CIRCUIT_BREAKER_OPEN", "critical")

    daily_dd = _to_float(account_state.get("daily_dd_percent"), 0.0)
    daily_cap = _to_float(account_state.get("max_daily_dd_percent"), 0.0)
    if daily_cap > 0:
        daily_ratio = daily_dd / daily_cap
        if daily_ratio >= 1.0:
            return ComplianceResult(
                False,
                "DAILY_DD_LIMIT_BREACH",
                "critical",
                {"daily_dd_percent": daily_dd, "max_daily_dd_percent": daily_cap},
            )
        if daily_ratio >= 0.9:
            return ComplianceResult(
                False,
                "DAILY_DD_NEAR_LIMIT",
                "warning",
                {"daily_dd_percent": daily_dd, "max_daily_dd_percent": daily_cap},
            )

    total_dd = _to_float(account_state.get("total_dd_percent"), 0.0)
    total_cap = _to_float(account_state.get("max_total_dd_percent"), 0.0)
    if total_cap > 0:
        total_ratio = total_dd / total_cap
        if total_ratio >= 1.0:
            return ComplianceResult(
                False,
                "TOTAL_DD_LIMIT_BREACH",
                "critical",
                {"total_dd_percent": total_dd, "max_total_dd_percent": total_cap},
            )
        if total_ratio >= 0.9:
            return ComplianceResult(
                False,
                "TOTAL_DD_NEAR_LIMIT",
                "warning",
                {"total_dd_percent": total_dd, "max_total_dd_percent": total_cap},
            )

    open_trades = _to_int(account_state.get("open_trades"), 0)
    max_open_trades = _to_int(account_state.get("max_concurrent_trades"), 0)
    if max_open_trades > 0 and open_trades >= max_open_trades:
        return ComplianceResult(
            False,
            "MAX_OPEN_TRADES_REACHED",
            "warning",
            {"open_trades": open_trades, "max_concurrent_trades": max_open_trades},
        )

    if trade_risk:
        risk_percent = _to_float(trade_risk.get("risk_percent"), 0.0)
        max_risk_percent = _to_float(account_state.get("max_risk_per_trade_percent"), 5.0)
        if max_risk_percent > 0 and risk_percent > max_risk_percent:
            return ComplianceResult(
                False,
                "TRADE_RISK_TOO_HIGH",
                "warning",
                {"risk_percent": risk_percent, "max_risk_per_trade_percent": max_risk_percent},
            )

    return ComplianceResult(True, "OK", "info")
