"""Account-scoped prop rule firewall.

This module is a legality firewall for account limits only. It has no market
direction authority and does not access the engine pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from accounts.account_repository import AccountRiskState


@dataclass(frozen=True)
class PropTemplate:
    code: str
    max_daily_loss_percent: float
    max_total_loss_percent: float
    max_open_positions: int


@dataclass(frozen=True)
class PropFirewallResult:
    allowed: bool
    mode: str
    allowed_risk_percent: float
    daily_buffer_percent: float
    total_buffer_percent: float
    consistency_remaining_percent: float
    reason: str


class PropRuleFirewall:
    """Computes account-level legal risk budget under prop constraints."""

    DEFAULT_TEMPLATE = PropTemplate(
        code="default",
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        max_open_positions=5,
    )

    TEMPLATES: dict[str, PropTemplate] = {
        "ftmo": PropTemplate(
            "ftmo",
            max_daily_loss_percent=5.0,
            max_total_loss_percent=10.0,
            max_open_positions=5,
        ),
        "fundednext": PropTemplate(
            "fundednext",
            max_daily_loss_percent=4.0,
            max_total_loss_percent=8.0,
            max_open_positions=3,
        ),
    }

    def evaluate(
        self,
        account_state: AccountRiskState,
        requested_risk_percent: float,
    ) -> PropFirewallResult:
        """Evaluate allowed risk for a specific account context."""
        if requested_risk_percent <= 0:
            return PropFirewallResult(
                allowed=False,
                mode="REJECT",
                allowed_risk_percent=0.0,
                daily_buffer_percent=0.0,
                total_buffer_percent=0.0,
                consistency_remaining_percent=0.0,
                reason="REQUESTED_RISK_NON_POSITIVE",
            )

        if account_state.account_locked:
            return PropFirewallResult(
                allowed=False,
                mode="REJECT",
                allowed_risk_percent=0.0,
                daily_buffer_percent=0.0,
                total_buffer_percent=0.0,
                consistency_remaining_percent=0.0,
                reason="ACCOUNT_LOCKED",
            )

        template = get_prop_template(account_state.prop_firm_code)

        daily_cap = min(template.max_daily_loss_percent, account_state.max_daily_loss_percent)
        total_cap = min(template.max_total_loss_percent, account_state.max_total_loss_percent)

        daily_buffer = max(0.0, daily_cap - account_state.daily_loss_used_percent)
        total_buffer = max(0.0, total_cap - account_state.total_loss_used_percent)

        consistency_remaining = max(
            0.0,
            account_state.consistency_limit_percent - account_state.consistency_used_percent,
        )

        allowed_risk = min(account_state.base_risk_percent, daily_buffer, total_buffer)

        if consistency_remaining > 0:
            allowed_risk = min(allowed_risk, consistency_remaining)

        if allowed_risk <= 0:
            return PropFirewallResult(
                allowed=False,
                mode="REJECT",
                allowed_risk_percent=0.0,
                daily_buffer_percent=daily_buffer,
                total_buffer_percent=total_buffer,
                consistency_remaining_percent=consistency_remaining,
                reason="RISK_BUFFER_EXHAUSTED",
            )

        if allowed_risk < account_state.min_safe_risk_percent:
            return PropFirewallResult(
                allowed=False,
                mode="REJECT",
                allowed_risk_percent=allowed_risk,
                daily_buffer_percent=daily_buffer,
                total_buffer_percent=total_buffer,
                consistency_remaining_percent=consistency_remaining,
                reason="BELOW_MIN_SAFE_THRESHOLD",
            )

        mode = "AUTO_REDUCE" if allowed_risk < requested_risk_percent else "NORMAL"
        return PropFirewallResult(
            allowed=True,
            mode=mode,
            allowed_risk_percent=allowed_risk,
            daily_buffer_percent=daily_buffer,
            total_buffer_percent=total_buffer,
            consistency_remaining_percent=consistency_remaining,
            reason="ALLOW" if mode == "NORMAL" else "ALLOW_AUTO_REDUCE",
        )


def get_prop_template(prop_firm_code: str) -> PropTemplate:
    """Resolve prop template by code with safe fallback."""
    code = (prop_firm_code or "").strip().lower()
    return PropRuleFirewall.TEMPLATES.get(code, PropRuleFirewall.DEFAULT_TEMPLATE)


def validate_prop_sovereignty(
    *,
    prop_firm_code: str,
    max_daily_dd_percent: float,
    max_total_dd_percent: float,
    max_positions: int,
) -> tuple[bool, str | None]:
    """Validate account limits never exceed prop-firm template sovereignty."""
    template = get_prop_template(prop_firm_code)
    if max_daily_dd_percent > template.max_daily_loss_percent:
        return (
            False,
            (
                "PROP_SOVEREIGNTY_DAILY_DD: "
                f"account={max_daily_dd_percent:.2f}% > prop={template.max_daily_loss_percent:.2f}%"
            ),
        )
    if max_total_dd_percent > template.max_total_loss_percent:
        return (
            False,
            (
                "PROP_SOVEREIGNTY_TOTAL_DD: "
                f"account={max_total_dd_percent:.2f}% > prop={template.max_total_loss_percent:.2f}%"
            ),
        )
    if max_positions > template.max_open_positions:
        return (
            False,
            (f"PROP_SOVEREIGNTY_MAX_POSITIONS: account={max_positions} > prop={template.max_open_positions}"),
        )
    return True, None
