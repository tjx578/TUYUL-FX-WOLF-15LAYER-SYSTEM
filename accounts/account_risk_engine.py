"""Per-account allowed risk computation for allocation layer.

This module is account-scoped only. It does not make market direction decisions
and does not execute orders.
"""

from __future__ import annotations

from dataclasses import dataclass

from accounts.account_repository import AccountRiskState


@dataclass(frozen=True)
class AllowedRiskResult:
    account_id: str
    allowed_risk_percent: float
    daily_remaining_percent: float
    total_remaining_percent: float
    phase_multiplier: float


class AccountRiskEngine:
    """Calculate risk budget per account with phase-aware scaling."""

    _PHASE_MULTIPLIER: dict[str, float] = {
        "PHASE1": 1.0,
        "PHASE2": 0.8,
        "FUNDED": 0.6,
    }

    def calculate_allowed_risk(self, account: AccountRiskState) -> AllowedRiskResult:
        """Return allowed risk using daily/total buffers and phase mode.

        Formula:
          allowed = min(daily_remaining, total_remaining, base_risk * phase_multiplier)
        """
        daily_remaining = max(0.0, account.max_daily_loss_percent - account.daily_loss_used_percent)
        total_remaining = max(0.0, account.max_total_loss_percent - account.total_loss_used_percent)

        phase = (account.phase_mode or "FUNDED").upper()
        phase_multiplier = self._PHASE_MULTIPLIER.get(phase, 0.6)
        phase_adjusted_base = max(0.0, account.base_risk_percent * phase_multiplier)

        allowed = min(daily_remaining, total_remaining, phase_adjusted_base)

        return AllowedRiskResult(
            account_id=account.account_id,
            allowed_risk_percent=round(allowed, 4),
            daily_remaining_percent=round(daily_remaining, 4),
            total_remaining_percent=round(total_remaining, 4),
            phase_multiplier=phase_multiplier,
        )
