"""Risk Manager — Account-level risk governance with dynamic sizing support.

Evaluates whether a trade is allowed given account state, prop-firm rules,
and dynamically computed risk percentage from DynamicPositionSizingEngine.

Authority: RISK ZONE.
           Does NOT decide market direction.
           Does NOT override Layer-12 verdict.
           Treats prop-firm guard result as BINDING for risk legality.
           Dashboard treats this output as binding for position sizing.

Enhancement (Tier 2):
    ✅ Accepts dynamic_risk_percent from DynamicPositionSizingEngine
    ✅ Uses min(dynamic_risk_percent, static_max_risk) as effective risk
    ✅ Backward-compatible: dynamic_risk_percent is Optional with None default
    ✅ Logs which risk source was used (static vs dynamic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFAULT_MAX_RISK_PCT = 0.02      # 2% static default
_DEFAULT_MAX_DAILY_LOSS_PCT = 0.05  # 5% daily drawdown limit
_DEFAULT_MAX_OPEN_TRADES = 5


@dataclass(frozen=True)
class RiskDecision:
    """Immutable risk evaluation result.

    This is a RISK decision, not a MARKET decision.
    trade_allowed = False means risk limits are breached,
    NOT that the market setup is invalid (that's L12's job).
    """

    trade_allowed: bool
    recommended_lot: float
    max_safe_lot: float
    effective_risk_percent: float   # Actual risk % used (static or dynamic)
    risk_source: str                # "STATIC" | "DYNAMIC_PSE" | "DYNAMIC_CLAMPED"
    risk_amount: float              # Dollar amount at risk
    reason: str
    violations: tuple[str, ...]     # All triggered violation codes

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_allowed": self.trade_allowed,
            "recommended_lot": self.recommended_lot,
            "max_safe_lot": self.max_safe_lot,
            "effective_risk_percent": self.effective_risk_percent,
            "risk_source": self.risk_source,
            "risk_amount": self.risk_amount,
            "reason": self.reason,
            "violations": list(self.violations),
        }


class RiskManager:
    """Account-level risk governor with dynamic sizing support.

    Parameters
    ----------
    max_risk_percent : float
        Static maximum risk per trade as fraction. Default 0.02 (2%).
        This is the ABSOLUTE ceiling — dynamic sizing can only go LOWER.
    max_daily_loss_percent : float
        Maximum daily loss as fraction of starting equity. Default 0.05 (5%).
    max_open_trades : int
        Maximum concurrent open positions. Default 5.
    min_lot : float
        Minimum tradeable lot size. Default 0.01.
    lot_step : float
        Lot size granularity. Default 0.01.
    """

    def __init__(
        self,
        max_risk_percent: float = _DEFAULT_MAX_RISK_PCT,
        max_daily_loss_percent: float = _DEFAULT_MAX_DAILY_LOSS_PCT,
        max_open_trades: int = _DEFAULT_MAX_OPEN_TRADES,
        min_lot: float = 0.01,
        lot_step: float = 0.01,
    ) -> None:
        if not 0.0 < max_risk_percent <= 1.0:
            raise ValueError(
                f"max_risk_percent must be in (0, 1], got {max_risk_percent}"
            )
        if not 0.0 < max_daily_loss_percent <= 1.0:
            raise ValueError(
                f"max_daily_loss_percent must be in (0, 1], got {max_daily_loss_percent}"
            )

        self._max_risk_pct = max_risk_percent
        self._max_daily_loss_pct = max_daily_loss_percent
        self._max_open = max_open_trades
        self._min_lot = min_lot
        self._lot_step = lot_step

    def evaluate(  # noqa: PLR0912
        self,
        account_balance: float,
        account_equity: float,
        daily_pnl: float,
        open_trade_count: int,
        stop_loss_pips: float,
        pip_value_per_lot: float,
        dynamic_risk_percent: float | None = None,
    ) -> RiskDecision:
        """Evaluate whether a trade is allowed under risk constraints.

        Args:
            account_balance: Current account balance.
            account_equity: Current account equity (balance + floating P&L).
            daily_pnl: Today's realized + unrealized P&L.
            open_trade_count: Number of currently open positions.
            stop_loss_pips: Distance to stop-loss in pips.
            pip_value_per_lot: Dollar value per pip per standard lot.
            dynamic_risk_percent: Optional risk fraction from
                DynamicPositionSizingEngine.final_fraction.
                If provided, used as risk % (but clamped to static max).
                If None, static max_risk_percent is used.

        Returns:
            RiskDecision with lot sizing and violation details.
        """
        violations: list[str] = []

        # ── Determine effective risk percent ─────────────────────────
        effective_risk_pct, risk_source = self._resolve_risk_percent(
            dynamic_risk_percent
        )

        # ── Daily loss check ─────────────────────────────────────────
        daily_loss_limit = account_balance * self._max_daily_loss_pct
        if daily_pnl < 0 and abs(daily_pnl) >= daily_loss_limit:
            violations.append("DAILY_LOSS_LIMIT_REACHED")

        # ── Daily loss approaching (warning at 80%) ──────────────────
        if daily_pnl < 0 and abs(daily_pnl) >= daily_loss_limit * 0.80:
            if "DAILY_LOSS_LIMIT_REACHED" not in violations:
                violations.append("DAILY_LOSS_LIMIT_WARNING")

        # ── Open trade count ─────────────────────────────────────────
        if open_trade_count >= self._max_open:
            violations.append("MAX_OPEN_TRADES_REACHED")

        # ── Equity depletion ─────────────────────────────────────────
        if account_equity <= 0:
            violations.append("EQUITY_DEPLETED")

        # ── Insufficient equity for any trade ────────────────────────
        if account_balance <= 0:
            violations.append("BALANCE_DEPLETED")

        # ── Zero edge from dynamic sizing ────────────────────────────
        if dynamic_risk_percent is not None and dynamic_risk_percent <= 0.0:
            violations.append("DYNAMIC_RISK_ZERO_EDGE")

        # ── Compute lot sizing ───────────────────────────────────────
        risk_amount = account_equity * effective_risk_pct

        if stop_loss_pips > 0 and pip_value_per_lot > 0:
            raw_lot = risk_amount / (stop_loss_pips * pip_value_per_lot)
            max_safe_lot = self._round_lot_down(raw_lot)
        else:
            max_safe_lot = 0.0
            if stop_loss_pips <= 0:
                violations.append("INVALID_STOP_LOSS")
            if pip_value_per_lot <= 0:
                violations.append("INVALID_PIP_VALUE")

        # ── Minimum lot check ────────────────────────────────────────
        recommended_lot = max_safe_lot
        if recommended_lot < self._min_lot and recommended_lot > 0:
            violations.append("BELOW_MIN_LOT")
            recommended_lot = 0.0  # Cannot trade below minimum

        # ── Final trade_allowed ──────────────────────────────────────
        blocking_violations = {
            "DAILY_LOSS_LIMIT_REACHED",
            "MAX_OPEN_TRADES_REACHED",
            "EQUITY_DEPLETED",
            "BALANCE_DEPLETED",
            "INVALID_STOP_LOSS",
            "INVALID_PIP_VALUE",
            "BELOW_MIN_LOT",
            "DYNAMIC_RISK_ZERO_EDGE",
        }
        has_blocking = bool(set(violations) & blocking_violations)

        if has_blocking:
            reason = f"BLOCKED: {', '.join(v for v in violations if v in blocking_violations)}"
            recommended_lot = 0.0
        elif violations:
            reason = f"WARNING: {', '.join(violations)}"
        else:
            reason = "APPROVED"

        return RiskDecision(
            trade_allowed=not has_blocking,
            recommended_lot=round(recommended_lot, 2),
            max_safe_lot=round(max_safe_lot, 2),
            effective_risk_percent=round(effective_risk_pct, 6),
            risk_source=risk_source,
            risk_amount=round(risk_amount, 2),
            reason=reason,
            violations=tuple(violations),
        )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _resolve_risk_percent(
        self, dynamic_risk_percent: float | None,
    ) -> tuple[float, str]:
        """Resolve effective risk percent from static and dynamic sources.

        Dynamic ALWAYS takes the LOWER of dynamic vs static (safety-first).
        Dynamic can reduce but NEVER amplify beyond static maximum.

        Returns:
            (effective_risk_percent, risk_source_label)
        """
        if dynamic_risk_percent is None:
            return self._max_risk_pct, "STATIC"

        if dynamic_risk_percent <= 0.0:
            # No edge → zero risk
            return 0.0, "DYNAMIC_PSE"

        if dynamic_risk_percent >= self._max_risk_pct:
            # Dynamic wants more than static allows → clamp to static
            return self._max_risk_pct, "DYNAMIC_CLAMPED"

        # Dynamic is within bounds → use it
        return dynamic_risk_percent, "DYNAMIC_PSE"

    def _round_lot_down(self, raw_lot: float) -> float:
        """Round lot size DOWN to nearest lot_step (never round up for safety)."""
        if raw_lot <= 0 or self._lot_step <= 0:
            return 0.0
        steps = int(raw_lot / self._lot_step)
        return round(steps * self._lot_step, 2)
