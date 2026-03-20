"""
Trailing Drawdown Monitor — Phase-aware prop firm drawdown tracking.

Supports trailing drawdown rules used by firms like FundedNext, TopStep,
MyFundedFX where the max drawdown limit moves UP as equity increases,
but never moves back down.

Also supports phase-aware rules:
- Challenge: Fixed drawdown from initial balance
- Verification: Fixed drawdown from initial balance
- Funded: Trailing drawdown from running high-water mark

Authority: risk/ — monitoring and enforcement, no market direction.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import StrEnum

from loguru import logger

from storage.redis_client import RedisClient
from utils.timezone_utils import now_utc


class PropPhase(StrEnum):
    CHALLENGE = "CHALLENGE"
    VERIFICATION = "VERIFICATION"
    FUNDED = "FUNDED"


class DrawdownMode(StrEnum):
    FIXED = "FIXED"  # DD measured from initial balance (never moves)
    TRAILING = "TRAILING"  # DD floor moves up with equity, never down
    SEMI_TRAILING = "SEMI_TRAILING"  # Trailing up to initial balance, then fixed


@dataclass(frozen=True)
class TrailingDrawdownSnapshot:
    """Immutable snapshot of trailing drawdown state."""

    phase: str
    mode: str
    initial_balance: float
    highest_equity: float
    trailing_floor: float  # The moving floor (highest_equity - max_dd_amount)
    current_equity: float
    drawdown_from_floor: float  # Distance from floor to current equity
    drawdown_pct: float  # Drawdown as % of reference
    remaining_before_breach: float  # How much more can be lost
    max_drawdown_amount: float  # The constant DD distance
    is_breached: bool
    locked_floor: bool  # True when trailing floor has reached initial_balance

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "mode": self.mode,
            "initial_balance": self.initial_balance,
            "highest_equity": self.highest_equity,
            "trailing_floor": self.trailing_floor,
            "current_equity": self.current_equity,
            "drawdown_from_floor": self.drawdown_from_floor,
            "drawdown_pct": round(self.drawdown_pct, 4),
            "remaining_before_breach": round(self.remaining_before_breach, 2),
            "max_drawdown_amount": self.max_drawdown_amount,
            "is_breached": self.is_breached,
            "locked_floor": self.locked_floor,
        }


# ── Phase-aware drawdown rules ──────────────────────────────────────

_PHASE_RULES: dict[str, dict[str, DrawdownMode | float]] = {
    # FTMO: Fixed DD in all phases
    "FTMO": {
        PropPhase.CHALLENGE: DrawdownMode.FIXED,
        PropPhase.VERIFICATION: DrawdownMode.FIXED,
        PropPhase.FUNDED: DrawdownMode.FIXED,
    },
    # FundedNext: Trailing in challenge/verification, fixed in funded (Express)
    "FundedNext": {
        PropPhase.CHALLENGE: DrawdownMode.TRAILING,
        PropPhase.VERIFICATION: DrawdownMode.TRAILING,
        PropPhase.FUNDED: DrawdownMode.FIXED,
    },
    # TopStep: Trailing in all phases until floor reaches initial balance
    "TopStep": {
        PropPhase.CHALLENGE: DrawdownMode.SEMI_TRAILING,
        PropPhase.VERIFICATION: DrawdownMode.SEMI_TRAILING,
        PropPhase.FUNDED: DrawdownMode.SEMI_TRAILING,
    },
    # MyFundedFX: Trailing in eval, fixed in funded
    "MyFundedFX": {
        PropPhase.CHALLENGE: DrawdownMode.TRAILING,
        PropPhase.VERIFICATION: DrawdownMode.TRAILING,
        PropPhase.FUNDED: DrawdownMode.FIXED,
    },
    # Default: Fixed in all phases
    "DEFAULT": {
        PropPhase.CHALLENGE: DrawdownMode.FIXED,
        PropPhase.VERIFICATION: DrawdownMode.FIXED,
        PropPhase.FUNDED: DrawdownMode.FIXED,
    },
}


def get_drawdown_mode(firm_name: str, phase: PropPhase) -> DrawdownMode:
    """Resolve drawdown mode for a firm + phase combination."""
    rules = _PHASE_RULES.get(firm_name, _PHASE_RULES["DEFAULT"])
    mode = rules.get(phase, DrawdownMode.FIXED)
    if isinstance(mode, DrawdownMode):
        return mode
    return DrawdownMode.FIXED


_REDIS_TRAILING_DD_PREFIX = "wolf15:risk:trailing_dd:"


class TrailingDrawdownMonitor:
    """Phase-aware trailing drawdown monitor with Redis persistence.

    For TRAILING mode:
    - Max DD amount = initial_balance * max_dd_pct (constant distance)
    - Floor = highest_equity - max_dd_amount (moves up, never down)
    - Breach when current_equity < floor

    For SEMI_TRAILING mode:
    - Same as TRAILING, but once floor reaches initial_balance, it locks
    - After lock, behaves like FIXED from initial_balance

    For FIXED mode:
    - Floor = initial_balance - max_dd_amount (never moves)

    Parameters
    ----------
    account_id : str
        Account identifier.
    firm_name : str
        Prop firm name (FTMO, FundedNext, TopStep, etc.).
    phase : PropPhase
        Current account phase.
    initial_balance : float
        Starting balance for the account/phase.
    max_drawdown_pct : float
        Maximum drawdown as decimal (e.g. 0.10 = 10%).
    max_daily_loss_pct : float
        Maximum daily loss as decimal (e.g. 0.05 = 5%).
    """

    def __init__(
        self,
        account_id: str,
        firm_name: str,
        phase: PropPhase,
        initial_balance: float,
        max_drawdown_pct: float = 0.10,
        max_daily_loss_pct: float = 0.05,
    ) -> None:
        self._account_id = account_id
        self._firm_name = firm_name
        self._phase = phase
        self._initial_balance = initial_balance
        self._max_dd_pct = max_drawdown_pct
        self._max_daily_loss_pct = max_daily_loss_pct
        self._mode = get_drawdown_mode(firm_name, phase)
        self._max_dd_amount = initial_balance * max_drawdown_pct
        self._lock = threading.Lock()
        self._redis = RedisClient()
        self._redis_key = f"{_REDIS_TRAILING_DD_PREFIX}{account_id}"

        # State
        self._highest_equity: float = initial_balance
        self._trailing_floor: float = initial_balance - self._max_dd_amount
        self._current_equity: float = initial_balance
        self._locked_floor: bool = False
        self._daily_loss: float = 0.0
        self._day_start_balance: float = initial_balance
        self._last_reset_date: str = now_utc().strftime("%Y-%m-%d")

        # Load from Redis or initialize
        self._load_or_initialize()

        logger.info(
            "TrailingDrawdownMonitor initialized",
            account_id=account_id,
            firm=firm_name,
            phase=phase.value,
            mode=self._mode.value,
            initial_balance=initial_balance,
            max_dd_pct=f"{max_drawdown_pct * 100:.1f}%",
            trailing_floor=self._trailing_floor,
        )

    def _load_or_initialize(self) -> None:
        """Load state from Redis if available."""
        try:
            raw = self._redis.get(self._redis_key)
            if raw:
                data = json.loads(raw)
                self._highest_equity = data.get("highest_equity", self._initial_balance)
                self._trailing_floor = data.get("trailing_floor", self._trailing_floor)
                self._current_equity = data.get("current_equity", self._initial_balance)
                self._locked_floor = data.get("locked_floor", False)
                self._daily_loss = data.get("daily_loss", 0.0)
                self._day_start_balance = data.get("day_start_balance", self._initial_balance)
                self._last_reset_date = data.get("last_reset_date", self._last_reset_date)
                logger.debug("Loaded trailing DD state from Redis", account_id=self._account_id)
        except Exception as e:
            logger.warning("Failed to load trailing DD state", error=str(e))

    def _persist(self) -> None:
        """Persist current state to Redis."""
        try:
            data = {
                "highest_equity": self._highest_equity,
                "trailing_floor": self._trailing_floor,
                "current_equity": self._current_equity,
                "locked_floor": self._locked_floor,
                "daily_loss": self._daily_loss,
                "day_start_balance": self._day_start_balance,
                "last_reset_date": self._last_reset_date,
                "firm_name": self._firm_name,
                "phase": self._phase.value,
                "mode": self._mode.value,
                "updated_at": now_utc().isoformat(),
            }
            self._redis.set(self._redis_key, json.dumps(data))
        except Exception as e:
            logger.error("Failed to persist trailing DD state", error=str(e))

    def update(self, current_equity: float, pnl: float | None = None) -> TrailingDrawdownSnapshot:
        """Update drawdown tracking with current equity.

        Parameters
        ----------
        current_equity : float
            Current account equity (balance + floating PnL).
        pnl : float, optional
            Closed trade PnL (for daily loss tracking).

        Returns
        -------
        TrailingDrawdownSnapshot
        """
        with self._lock:
            self._current_equity = current_equity
            self._check_daily_reset()

            # Track daily loss from closed PnL
            if pnl is not None and pnl < 0:
                self._daily_loss += abs(pnl)

            # Update highest equity (only on new highs)
            if current_equity > self._highest_equity:
                self._highest_equity = current_equity

            # Recalculate trailing floor based on mode
            self._recalculate_floor()

            self._persist()
            return self.get_snapshot()

    def _recalculate_floor(self) -> None:
        """Recalculate the trailing floor based on drawdown mode."""
        if self._mode == DrawdownMode.FIXED:
            # Floor never moves: initial_balance - max_dd_amount
            self._trailing_floor = self._initial_balance - self._max_dd_amount

        elif self._mode == DrawdownMode.TRAILING:
            # Floor moves up with equity, never down
            new_floor = self._highest_equity - self._max_dd_amount
            self._trailing_floor = max(self._trailing_floor, new_floor)

        elif self._mode == DrawdownMode.SEMI_TRAILING:  # noqa: SIM102
            # Trailing until floor reaches initial_balance, then locks
            if not self._locked_floor:
                new_floor = self._highest_equity - self._max_dd_amount
                self._trailing_floor = max(self._trailing_floor, new_floor)

                # Check if floor has reached or exceeded initial balance
                if self._trailing_floor >= self._initial_balance:
                    self._trailing_floor = self._initial_balance
                    self._locked_floor = True
                    logger.info(
                        "Trailing floor locked at initial balance",
                        account_id=self._account_id,
                        floor=self._trailing_floor,
                    )

    def _check_daily_reset(self) -> None:
        """Reset daily loss counter at midnight UTC."""
        today = now_utc().strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            logger.info(
                "Daily loss reset",
                account_id=self._account_id,
                old_loss=self._daily_loss,
                date=today,
            )
            self._daily_loss = 0.0
            self._day_start_balance = self._current_equity
            self._last_reset_date = today

    def get_snapshot(self) -> TrailingDrawdownSnapshot:
        """Get current trailing drawdown snapshot."""
        drawdown_from_floor = max(0.0, self._trailing_floor - self._current_equity)
        remaining = max(0.0, self._current_equity - self._trailing_floor)

        # Percentage relative to reference point
        reference = self._highest_equity if self._mode != DrawdownMode.FIXED else self._initial_balance
        dd_pct = drawdown_from_floor / reference if reference > 0 else 0.0

        is_breached = self._current_equity < self._trailing_floor

        return TrailingDrawdownSnapshot(
            phase=self._phase.value,
            mode=self._mode.value,
            initial_balance=self._initial_balance,
            highest_equity=self._highest_equity,
            trailing_floor=self._trailing_floor,
            current_equity=self._current_equity,
            drawdown_from_floor=drawdown_from_floor,
            drawdown_pct=dd_pct,
            remaining_before_breach=remaining,
            max_drawdown_amount=self._max_dd_amount,
            is_breached=is_breached,
            locked_floor=self._locked_floor,
        )

    def is_breached(self) -> bool:
        """Check if trailing drawdown limit is breached."""
        with self._lock:
            return self._current_equity < self._trailing_floor

    def is_daily_breached(self) -> bool:
        """Check if daily loss limit is breached."""
        with self._lock:
            if self._day_start_balance <= 0:
                return False
            daily_pct = self._daily_loss / self._day_start_balance
            return daily_pct >= self._max_daily_loss_pct

    def get_daily_loss_snapshot(self) -> dict:
        """Get daily loss tracking info."""
        with self._lock:
            self._check_daily_reset()
            daily_pct = self._daily_loss / self._day_start_balance if self._day_start_balance > 0 else 0.0
            return {
                "daily_loss_amount": self._daily_loss,
                "daily_loss_pct": daily_pct,
                "max_daily_loss_pct": self._max_daily_loss_pct,
                "day_start_balance": self._day_start_balance,
                "remaining": max(0.0, self._max_daily_loss_pct * self._day_start_balance - self._daily_loss),
            }

    def transition_phase(self, new_phase: PropPhase, new_balance: float | None = None) -> None:
        """Handle phase transition (Challenge → Verification → Funded).

        Parameters
        ----------
        new_phase : PropPhase
            New account phase.
        new_balance : float, optional
            New initial balance for the phase (some firms reset balance).
        """
        with self._lock:
            old_phase = self._phase
            self._phase = new_phase
            self._mode = get_drawdown_mode(self._firm_name, new_phase)

            if new_balance is not None:
                self._initial_balance = new_balance
                self._highest_equity = new_balance
                self._max_dd_amount = new_balance * self._max_dd_pct
                self._trailing_floor = new_balance - self._max_dd_amount
                self._locked_floor = False
                self._current_equity = new_balance
                self._daily_loss = 0.0
                self._day_start_balance = new_balance

            self._persist()

            logger.info(
                "Phase transition",
                account_id=self._account_id,
                old_phase=old_phase,
                new_phase=new_phase.value,
                new_mode=self._mode.value,
                new_balance=new_balance,
            )
