"""
Broker Executor — Dumb execution layer.

This module handles order placement only. It does NOT compute market direction,
override Layer-12 verdicts, or make risk decisions. All state/risk comes from
the dashboard; all authority comes from the constitution (Layer-12).
"""

from __future__ import annotations

from typing import Any

from risk.prop_firm import BasePropFirmGuard, GuardResult

__all__ = ["BrokerExecutor"]


class BrokerExecutor:
    """Stateless executor that places orders based on dashboard instructions.

    The executor receives fully-resolved trade instructions (lot size, SL, TP
    already computed by dashboard + prop-firm guard) and simply forwards them
    to the broker API.  It never re-evaluates market conditions or risk.
    """

    def __init__(self, guard: BasePropFirmGuard | None = None) -> None: # type: ignore
        self._guard = guard

    def preflight_check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """Run prop-firm guard before placing an order (advisory only).

        The dashboard is the authority; this is a last-resort safety net.
        """
        if self._guard is None:
            return GuardResult(allowed=True, code="NO_GUARD", severity="info")
        return self._guard.check(account_state, trade_risk)
