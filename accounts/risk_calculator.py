"""Account-scoped risk calculator.

Computes allowed risk and recommended lot size for a specific account.
No signal-direction authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from accounts.account_repository import AccountRiskState
from accounts.prop_rule_engine import PropFirewallResult, PropRuleFirewall


@dataclass(frozen=True)
class AccountRiskDecision:
    account_id: str
    trade_allowed: bool
    status: str
    recommended_risk_percent: float
    risk_amount: float
    recommended_lot: float
    max_safe_lot: float
    daily_buffer_percent: float
    total_buffer_percent: float
    consistency_remaining_percent: float
    reason: str


class AccountScopedRiskEngine:
    """Per-account risk engine with prop firewall integration."""

    MIN_LOT = 0.01
    MAX_LOT = 100.0

    def __init__(self, firewall: PropRuleFirewall | None = None) -> None:
        self._firewall = firewall or PropRuleFirewall()

    def evaluate_trade(
        self,
        *,
        account_state: AccountRiskState,
        requested_risk_percent: float,
        stop_loss_pips: float,
        pip_value_per_lot: float,
        risk_multiplier: float = 1.0,
    ) -> AccountRiskDecision:
        """Evaluate trade risk and produce account-scoped lot recommendation."""
        if stop_loss_pips <= 0 or pip_value_per_lot <= 0:
            return AccountRiskDecision(
                account_id=account_state.account_id,
                trade_allowed=False,
                status="REJECT",
                recommended_risk_percent=0.0,
                risk_amount=0.0,
                recommended_lot=0.0,
                max_safe_lot=0.0,
                daily_buffer_percent=0.0,
                total_buffer_percent=0.0,
                consistency_remaining_percent=0.0,
                reason="INVALID_SL_OR_PIP_VALUE",
            )

        requested = max(0.0, requested_risk_percent * max(0.0, risk_multiplier))
        firewall_result = self._firewall.evaluate(account_state, requested)

        if not firewall_result.allowed:
            return self._build_reject_decision(account_state, firewall_result)

        risk_amount = account_state.equity * firewall_result.allowed_risk_percent / 100.0
        raw_lot = risk_amount / (stop_loss_pips * pip_value_per_lot)
        lot = self._clamp_lot(raw_lot)

        return AccountRiskDecision(
            account_id=account_state.account_id,
            trade_allowed=True,
            status=firewall_result.mode,
            recommended_risk_percent=round(firewall_result.allowed_risk_percent, 4),
            risk_amount=round(risk_amount, 2),
            recommended_lot=lot,
            max_safe_lot=lot,
            daily_buffer_percent=round(firewall_result.daily_buffer_percent, 4),
            total_buffer_percent=round(firewall_result.total_buffer_percent, 4),
            consistency_remaining_percent=round(firewall_result.consistency_remaining_percent, 4),
            reason=firewall_result.reason,
        )

    def _build_reject_decision(
        self,
        account_state: AccountRiskState,
        firewall_result: PropFirewallResult,
    ) -> AccountRiskDecision:
        return AccountRiskDecision(
            account_id=account_state.account_id,
            trade_allowed=False,
            status="REJECT",
            recommended_risk_percent=round(firewall_result.allowed_risk_percent, 4),
            risk_amount=0.0,
            recommended_lot=0.0,
            max_safe_lot=0.0,
            daily_buffer_percent=round(firewall_result.daily_buffer_percent, 4),
            total_buffer_percent=round(firewall_result.total_buffer_percent, 4),
            consistency_remaining_percent=round(firewall_result.consistency_remaining_percent, 4),
            reason=firewall_result.reason,
        )

    def _clamp_lot(self, lot: float) -> float:
        bounded = max(self.MIN_LOT, min(self.MAX_LOT, lot))
        return int(bounded * 100) / 100.0
