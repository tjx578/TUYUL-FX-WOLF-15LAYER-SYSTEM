"""Deprecated compatibility wrapper for L6 risk analysis.

Canonical implementation lives at ``analysis.layers.L6_risk.L6RiskAnalyzer``.
This adapter keeps legacy imports working while enforcing a single L6 logic
path across the codebase.
"""

from __future__ import annotations

import warnings
from datetime import UTC, datetime
from typing import Any

from analysis.layers.L6_risk import L6RiskAnalyzer

__all__ = ["analyze_risk", "L6RiskAnalyzer"]

_L6_DEPRECATION = (
    "analysis.l6_risk is deprecated; use analysis.layers.L6_risk.L6RiskAnalyzer"
)


def _to_account_state(market_data: dict[str, Any], account_state: dict[str, Any] | None) -> dict[str, Any]:
    acc = dict(account_state or {})
    if "vol_cluster" not in acc:
        acc["vol_cluster"] = str(market_data.get("volatility_level", "NORMAL"))
    return acc


def _to_rr(trade_params: dict[str, Any] | None) -> float:
    trade = trade_params or {}
    return float(trade.get("rr_ratio", 2.0))


def analyze_risk(
    market_data: dict[str, Any],
    account_state: dict[str, Any] | None = None,
    trade_params: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compatibility API for legacy callers.

    The ``now`` parameter is accepted for backward compatibility only.
    """
    _ = now or datetime.now(UTC)
    warnings.warn(_L6_DEPRECATION, DeprecationWarning, stacklevel=2)

    analyzer = L6RiskAnalyzer()
    result = analyzer.analyze(
        rr=_to_rr(trade_params),
        account_state=_to_account_state(market_data, account_state),
    )
    return result
