"""
Enhanced prop firm guard with real-time drawdown tracking.
Covers: daily loss, max drawdown, lot limits, position count, weekend gap.
"""

from __future__ import annotations

import time

from dataclasses import dataclass, field
from enum import Enum


class GuardCode(Enum):
    ALLOWED = "ALLOWED"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    LOT_SIZE_EXCEEDED = "LOT_SIZE_EXCEEDED"
    MAX_POSITIONS = "MAX_POSITIONS"
    WEEKEND_LOCKOUT = "WEEKEND_LOCKOUT"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
    NEWS_LOCKOUT = "NEWS_LOCKOUT"


class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"
    CRITICAL = "CRITICAL"


@dataclass
class GuardResult:
    allowed: bool
    code: GuardCode
    severity: Severity
    details: str | None = None
    max_safe_lot: float | None = None
    remaining_daily_risk: float | None = None


@dataclass
class PropFirmProfile:
    name: str
    max_daily_loss_pct: float        # e.g., 5.0 for 5%
    max_total_drawdown_pct: float    # e.g., 10.0 for 10%
    max_lot_per_trade: float         # e.g., 5.0
    max_open_positions: int          # e.g., 10
    min_lot: float = 0.01
    lot_step: float = 0.01
    weekend_close_required: bool = True
    news_buffer_minutes: int = 0     # 0 = no restriction
    trailing_drawdown: bool = False  # Some have trailing max DD
    initial_balance: float | None = None  # For tracking from start


# Preset profiles
FTMO_PROFILE = PropFirmProfile(
    name="FTMO",
    max_daily_loss_pct=5.0,
    max_total_drawdown_pct=10.0,
    max_lot_per_trade=20.0,
    max_open_positions=50,
    weekend_close_required=False,
    trailing_drawdown=False,
)

FUNDED_NEXT_PROFILE = PropFirmProfile(
    name="FundedNext",
    max_daily_loss_pct=5.0,
    max_total_drawdown_pct=10.0,
    max_lot_per_trade=20.0,
    max_open_positions=50,
    weekend_close_required=False,
    trailing_drawdown=True,  # FundedNext uses trailing DD
)


@dataclass
class AccountSnapshot:
    balance: float
    equity: float
    floating_pnl: float
    closed_pnl_today: float
    open_position_count: int
    day_start_balance: float       # Balance at start of trading day (broker timezone!)
    highest_balance: float = 0.0   # For trailing drawdown firms
    timestamp: float = field(default_factory=time.time)

    @property
    def daily_loss(self) -> float:
        """Total daily loss including floating positions."""
        return self.day_start_balance - self.equity

    @property
    def daily_loss_pct(self) -> float:
        if self.day_start_balance == 0:
            return 0.0
        return (self.daily_loss / self.day_start_balance) * 100


class EnhancedPropGuard:
    """
    Real-time prop firm guard.
    Standard interface: check(account_state, trade_risk) -> GuardResult
    """

    def __init__(self, profile: PropFirmProfile):
        self.profile = profile

    def check(self, account: AccountSnapshot, trade_risk_usd: float, lot_size: float) -> GuardResult:
        """
        Main check method. Returns binding result.
        trade_risk_usd: max risk (SL distance * lot * pip value) for proposed trade.
        """

        # 1. Daily loss check (including floating!)
        current_daily_loss_pct = account.daily_loss_pct
        projected_daily_loss = account.daily_loss + trade_risk_usd
        projected_daily_loss_pct = (projected_daily_loss / account.day_start_balance) * 100 if account.day_start_balance > 0 else 0

        # Warning at 80% of limit
        warn_threshold = self.profile.max_daily_loss_pct * 0.80
        block_threshold = self.profile.max_daily_loss_pct * 0.95  # Block at 95% to have buffer

        if projected_daily_loss_pct >= block_threshold:
            remaining = max(0, (self.profile.max_daily_loss_pct / 100 * account.day_start_balance) - account.daily_loss)
            return GuardResult(
                allowed=False,
                code=GuardCode.DAILY_LOSS_LIMIT,
                severity=Severity.BLOCK,
                details=f"Projected daily loss {projected_daily_loss_pct:.2f}% >= {block_threshold:.2f}% block threshold",
                remaining_daily_risk=remaining,
            )

        if current_daily_loss_pct >= warn_threshold:
            remaining = max(0, (self.profile.max_daily_loss_pct / 100 * account.day_start_balance) - account.daily_loss)
            # Allow but warn
            # ...still continue checking other guards

        # 2. Max drawdown check
        if self.profile.trailing_drawdown and self.profile.initial_balance:
            reference = max(account.highest_balance, self.profile.initial_balance)
        elif self.profile.initial_balance:
            reference = self.profile.initial_balance
        else:
            reference = account.day_start_balance

        if reference > 0:
            ((reference - account.equity) / reference) * 100 # type: ignore
            projected_dd_pct = ((reference - (account.equity - trade_risk_usd)) / reference) * 100

            if projected_dd_pct >= self.profile.max_total_drawdown_pct * 0.90:
                return GuardResult(
                    allowed=False,
                    code=GuardCode.MAX_DRAWDOWN,
                    severity=Severity.CRITICAL,
                    details=f"Projected total DD {projected_dd_pct:.2f}% near limit {self.profile.max_total_drawdown_pct:.2f}%",
                )

        # 3. Lot size check
        if lot_size > self.profile.max_lot_per_trade:
            return GuardResult(
                allowed=False,
                code=GuardCode.LOT_SIZE_EXCEEDED,
                severity=Severity.BLOCK,
                details=f"Lot {lot_size} > max {self.profile.max_lot_per_trade}",
                max_safe_lot=self.profile.max_lot_per_trade,
            )

        if lot_size < self.profile.min_lot:
            return GuardResult(
                allowed=False,
                code=GuardCode.LOT_SIZE_EXCEEDED,
                severity=Severity.BLOCK,
                details=f"Lot {lot_size} < min {self.profile.min_lot}",
            )

        # 4. Position count check
        if account.open_position_count >= self.profile.max_open_positions:
            return GuardResult(
                allowed=False,
                code=GuardCode.MAX_POSITIONS,
                severity=Severity.BLOCK,
                details=f"Open positions {account.open_position_count} >= max {self.profile.max_open_positions}",
            )

        # 5. Weekend check
        if self.profile.weekend_close_required and self._is_near_weekend():
            return GuardResult(
                allowed=False,
                code=GuardCode.WEEKEND_LOCKOUT,
                severity=Severity.BLOCK,
                details="Weekend close required -- no new positions after Friday cutoff",
            )

        # All checks passed
        return GuardResult(
            allowed=True,
            code=GuardCode.ALLOWED,
            severity=Severity.INFO,
            details="All prop firm checks passed",
            max_safe_lot=min(lot_size, self.profile.max_lot_per_trade),
        )

    def _is_near_weekend(self) -> bool:
        """Check if we're within 2 hours of market close on Friday."""
        import datetime  # noqa: PLC0415
        now = datetime.datetime.utcnow()  # noqa: DTZ003
        # Market closes Friday ~22:00 UTC
        if now.weekday() == 4 and now.hour >= 20:  # Friday after 20:00 UTC
            return True
        if now.weekday() in (5, 6):  # Saturday/Sunday
            return True
        return False

    def compute_max_safe_lot(
        self,
        account: AccountSnapshot,
        sl_pips: float,
        pip_value_per_lot: float,
    ) -> float:
        """
        Compute the maximum safe lot size given current account state
        and the proposed trade's SL distance.
        """
        if sl_pips <= 0 or pip_value_per_lot <= 0:
            return self.profile.min_lot

        # Remaining daily risk budget
        daily_limit_usd = (self.profile.max_daily_loss_pct / 100) * account.day_start_balance
        remaining_daily = max(0, daily_limit_usd - account.daily_loss)

        # Use 90% of remaining budget as safe margin
        safe_budget = remaining_daily * 0.90

        # Max lot from daily risk
        max_from_daily = safe_budget / (sl_pips * pip_value_per_lot)

        # Cap by profile max
        max_lot = min(max_from_daily, self.profile.max_lot_per_trade)

        # Round down to lot step
        max_lot = max(
            self.profile.min_lot,
            round(max_lot // self.profile.lot_step * self.profile.lot_step, 2),
        )

        return max_lot
