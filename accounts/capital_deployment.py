"""Capital deployment readiness and usable capital computation.

Zone: accounts/ — pure account-scoped computation, no execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReadinessResult:
    """Per-account readiness assessment for capital deployment."""

    account_id: str
    readiness_score: float  # 0.0 – 1.0
    usable_capital: float  # USD available for new trades
    eligibility_flags: dict[str, bool]
    lock_reasons: list[str]


def compute_readiness_score(
    *,
    compliance_mode: bool,
    circuit_breaker: bool,
    daily_dd_percent: float,
    max_daily_dd_percent: float,
    total_dd_percent: float,
    max_total_dd_percent: float,
    open_trades: int,
    max_concurrent_trades: int,
    news_lock: bool = False,
    account_locked: bool = False,
) -> float:
    """Return 0.0–1.0 readiness score.

    Weights:
      40% — daily DD headroom
      30% — total DD headroom
      20% — trade slot availability
      10% — compliance / circuit breaker / locks
    """
    if account_locked or circuit_breaker:
        return 0.0

    # Daily DD headroom (40%)
    if max_daily_dd_percent > 0:
        daily_ratio = daily_dd_percent / max_daily_dd_percent
        daily_score = max(0.0, 1.0 - daily_ratio)
    else:
        daily_score = 1.0

    # Total DD headroom (30%)
    if max_total_dd_percent > 0:
        total_ratio = total_dd_percent / max_total_dd_percent
        total_score = max(0.0, 1.0 - total_ratio)
    else:
        total_score = 1.0

    # Trade slot availability (20%)
    slot_score = max(0.0, 1.0 - open_trades / max_concurrent_trades) if max_concurrent_trades > 0 else 0.0

    # Compliance / lock penalties (10%)
    compliance_score = 1.0
    if not compliance_mode:
        compliance_score -= 0.5
    if news_lock:
        compliance_score -= 0.5
    compliance_score = max(0.0, compliance_score)

    raw = (daily_score * 0.40) + (total_score * 0.30) + (slot_score * 0.20) + (compliance_score * 0.10)
    return round(min(1.0, max(0.0, raw)), 4)


def compute_usable_capital(
    *,
    equity: float,
    balance: float,
    daily_dd_percent: float,
    max_daily_dd_percent: float,
    total_dd_percent: float,
    max_total_dd_percent: float,
    open_risk_percent: float = 0.0,
) -> float:
    """Return maximum USD capital deployable without breaching DD limits.

    Takes the minimum of:
      - daily DD headroom in USD
      - total DD headroom in USD
    Less any currently open risk.
    """
    base = max(equity, balance)
    if base <= 0:
        return 0.0

    daily_headroom_pct = max(0.0, max_daily_dd_percent - daily_dd_percent)
    total_headroom_pct = max(0.0, max_total_dd_percent - total_dd_percent)
    headroom_pct = min(daily_headroom_pct, total_headroom_pct)

    usable_pct = max(0.0, headroom_pct - open_risk_percent)
    return round(base * usable_pct / 100.0, 2)


def compute_eligibility_flags(
    *,
    compliance_mode: bool,
    circuit_breaker: bool,
    account_locked: bool,
    news_lock: bool,
    ea_connected: bool,
    data_source: str,
    daily_dd_percent: float,
    max_daily_dd_percent: float,
    total_dd_percent: float,
    max_total_dd_percent: float,
    open_trades: int,
    max_concurrent_trades: int,
) -> dict[str, bool]:
    """Return eligibility flags for capital deployment."""
    daily_ok = max_daily_dd_percent <= 0 or daily_dd_percent < (max_daily_dd_percent * 0.9)
    total_ok = max_total_dd_percent <= 0 or total_dd_percent < (max_total_dd_percent * 0.9)
    slots_ok = max_concurrent_trades <= 0 or open_trades < max_concurrent_trades

    return {
        "compliance_ok": compliance_mode,
        "circuit_breaker_ok": not circuit_breaker,
        "not_locked": not account_locked,
        "no_news_lock": not news_lock,
        "daily_dd_ok": daily_ok,
        "total_dd_ok": total_ok,
        "slots_available": slots_ok,
        "ea_linked": ea_connected and data_source == "EA",
    }


def compute_lock_reasons(eligibility: dict[str, bool]) -> list[str]:
    """Return human-readable lock reasons from eligibility flags."""
    reasons: list[str] = []
    if not eligibility.get("compliance_ok", True):
        reasons.append("Compliance mode disabled")
    if not eligibility.get("circuit_breaker_ok", True):
        reasons.append("Circuit breaker OPEN")
    if not eligibility.get("not_locked", True):
        reasons.append("Account locked")
    if not eligibility.get("no_news_lock", True):
        reasons.append("News lock active")
    if not eligibility.get("daily_dd_ok", True):
        reasons.append("Daily DD near limit (>90%)")
    if not eligibility.get("total_dd_ok", True):
        reasons.append("Total DD near limit (>90%)")
    if not eligibility.get("slots_available", True):
        reasons.append("No trade slots available")
    return reasons


def build_readiness(
    account_id: str,
    payload: dict[str, Any],
    *,
    equity: float,
    balance: float,
    max_daily_dd_percent: float,
    max_total_dd_percent: float,
    max_concurrent_trades: int,
    prop_firm: bool = False,
) -> ReadinessResult:
    """Build full readiness result from account data + Redis payload."""
    daily_dd = float(payload.get("daily_dd_percent", 0.0) or 0.0)
    total_dd = float(payload.get("total_dd_percent", 0.0) or 0.0)
    open_risk = float(payload.get("open_risk_percent", 0.0) or 0.0)
    open_trades = int(payload.get("open_trades", 0) or 0)
    circuit_breaker = bool(int(payload.get("circuit_breaker", 0) or 0))
    news_lock = bool(int(payload.get("news_lock", 0) or 0))
    account_locked = bool(int(payload.get("account_locked", 0) or 0))
    compliance_mode = bool(int(payload.get("compliance_mode", 1) or 1))
    ea_connected = bool(int(payload.get("ea_connected", 0) or 0))
    data_source = str(payload.get("data_source", "MANUAL"))

    score = compute_readiness_score(
        compliance_mode=compliance_mode,
        circuit_breaker=circuit_breaker,
        daily_dd_percent=daily_dd,
        max_daily_dd_percent=max_daily_dd_percent,
        total_dd_percent=total_dd,
        max_total_dd_percent=max_total_dd_percent,
        open_trades=open_trades,
        max_concurrent_trades=max_concurrent_trades,
        news_lock=news_lock,
        account_locked=account_locked,
    )

    usable = compute_usable_capital(
        equity=equity,
        balance=balance,
        daily_dd_percent=daily_dd,
        max_daily_dd_percent=max_daily_dd_percent,
        total_dd_percent=total_dd,
        max_total_dd_percent=max_total_dd_percent,
        open_risk_percent=open_risk,
    )

    eligibility = compute_eligibility_flags(
        compliance_mode=compliance_mode,
        circuit_breaker=circuit_breaker,
        account_locked=account_locked,
        news_lock=news_lock,
        ea_connected=ea_connected,
        data_source=data_source,
        daily_dd_percent=daily_dd,
        max_daily_dd_percent=max_daily_dd_percent,
        total_dd_percent=total_dd,
        max_total_dd_percent=max_total_dd_percent,
        open_trades=open_trades,
        max_concurrent_trades=max_concurrent_trades,
    )

    locks = compute_lock_reasons(eligibility)

    return ReadinessResult(
        account_id=account_id,
        readiness_score=score,
        usable_capital=usable,
        eligibility_flags=eligibility,
        lock_reasons=locks,
    )
