"""Resolved prop firm rules — single source of truth for a specific account context.

Zone: propfirm_manager/ — governance/risk, no market decision authority.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedPropRules:
    """Fully resolved prop firm rules for a specific account + plan + phase.

    This is the SINGLE SOURCE OF TRUTH for all prop firm rules consumed by
    Guard, Firewall, L5, Pipeline, and Dashboard.

    Instances are immutable (``frozen=True``) so they can be safely shared
    across threads without defensive copying.
    """

    firm_code: str
    firm_name: str
    plan_code: str
    plan_display_name: str
    phase: str  # "challenge" | "verification" | "funded"
    initial_balance: float
    currency: str

    # Drawdown rules
    max_daily_dd_percent: float
    max_total_dd_percent: float
    drawdown_mode: str  # "FIXED" | "TRAILING" | "SEMI_TRAILING"

    # Profit & consistency
    profit_target_percent: float
    consistency_rule_percent: float
    min_trading_days: int

    # Risk limits
    max_risk_per_trade_percent: float
    max_open_trades: int
    min_rr_required: float

    # Restrictions
    news_restriction: bool
    weekend_holding: bool

    # Features
    allow_scaling: bool
    allow_split_risk: bool
