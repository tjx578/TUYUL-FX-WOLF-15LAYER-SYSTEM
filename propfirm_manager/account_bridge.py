"""Account bridge — populates AccountRiskState from resolved prop firm rules.

Zone: propfirm_manager/ — governance/risk, no market decision authority.

This module is the canonical bridge between the prop firm rule layer and the
account-scoped runtime state.  Call :func:`populate_account_risk_state` when
creating or loading an account to ensure all prop firm limits are correctly
reflected in the in-memory state consumed by the risk firewall and pipeline.
"""

from __future__ import annotations

from accounts.account_repository import AccountRiskState
from propfirm_manager.resolved_rules import ResolvedPropRules


def populate_account_risk_state(
    resolved_rules: ResolvedPropRules,
    account_id: str,
    balance: float,
    equity: float,
    *,
    base_risk_percent: float = 1.0,
    daily_loss_used_percent: float = 0.0,
    total_loss_used_percent: float = 0.0,
    open_trades_count: int = 0,
    account_locked: bool = False,
    circuit_breaker_open: bool = False,
) -> AccountRiskState:
    """Build a fully-populated :class:`AccountRiskState` from resolved rules.

    This is the ONLY place where ``ResolvedPropRules`` fields are mapped to
    ``AccountRiskState`` fields, ensuring a single, auditable bridge point.

    The ``base_risk_percent`` is capped at
    ``resolved_rules.max_risk_per_trade_percent`` so the account can never
    request more risk than the prop firm allows.

    Args:
        resolved_rules: Fully resolved prop firm rules for this account's
            firm / plan / phase.
        account_id: Unique account identifier string.
        balance: Current account balance in the account currency.
        equity: Current account equity (balance + floating P&L).
        base_risk_percent: Desired default risk per trade as a percentage of
            balance.  Capped at ``resolved_rules.max_risk_per_trade_percent``.
        daily_loss_used_percent: Percentage of the daily loss allowance already
            consumed today.
        total_loss_used_percent: Percentage of the total loss allowance already
            consumed since account inception / reset.
        open_trades_count: Number of trades currently open on this account.
        account_locked: Whether the account is in a hard-locked state.
        circuit_breaker_open: Whether the circuit breaker is currently tripped.

    Returns:
        Immutable :class:`AccountRiskState` with all prop firm fields set.
    """
    effective_base_risk = min(base_risk_percent, resolved_rules.max_risk_per_trade_percent)

    return AccountRiskState(
        account_id=account_id,
        prop_firm_code=resolved_rules.firm_code,
        balance=balance,
        equity=equity,
        base_risk_percent=effective_base_risk,
        max_daily_loss_percent=resolved_rules.max_daily_dd_percent,
        max_total_loss_percent=resolved_rules.max_total_dd_percent,
        daily_loss_used_percent=daily_loss_used_percent,
        total_loss_used_percent=total_loss_used_percent,
        consistency_limit_percent=resolved_rules.consistency_rule_percent,
        phase_mode=resolved_rules.phase.upper(),
        max_concurrent_trades=resolved_rules.max_open_trades,
        open_trades_count=open_trades_count,
        news_lock=resolved_rules.news_restriction,
        account_locked=account_locked,
        circuit_breaker_open=circuit_breaker_open,
    )
