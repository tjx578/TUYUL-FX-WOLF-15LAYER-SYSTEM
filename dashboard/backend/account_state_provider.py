"""
Account state provider — fetches real account info from MT5 or broker API.
Dashboard authority: only this module knows the actual balance/equity.
"""

from __future__ import annotations  # noqa: I001

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("tuyul.dashboard.account")


@dataclass
class AccountState:
    """Immutable snapshot of account at a point in time."""
    balance: float
    equity: float
    margin: float
    free_margin: float
    floating_pnl: float
    open_position_count: int
    day_start_balance: float
    highest_balance: float
    currency: str = "USD"
    timestamp: float = field(default_factory=time.time)

    @property
    def daily_loss(self) -> float:
        return max(0.0, self.day_start_balance - self.equity)

    @property
    def daily_loss_pct(self) -> float:
        if self.day_start_balance <= 0:
            return 0.0
        return (self.daily_loss / self.day_start_balance) * 100.0

    @property
    def margin_level_pct(self) -> float:
        if self.margin <= 0:
            return float("inf")
        return (self.equity / self.margin) * 100.0


class AccountStateProvider:
    """
    Provides real account state from MT5.
    Caches with short TTL to avoid excessive broker calls.
    Falls back gracefully if MT5 is unavailable.
    """

    CACHE_TTL_SECONDS = 2.0  # refresh every 2 seconds max

    def __init__(self):
        self._cache: AccountState | None = None
        self._cache_time: float = 0.0
        self._day_start_balance: float | None = None
        self._highest_balance: float = 0.0
        self._mt5_available: bool = False

        try:
            import MetaTrader5 as mt5  # pyright: ignore[reportMissingImports] # noqa: N813, PLC0415
            self._mt5 = mt5
            self._mt5_available = True
        except ImportError:
            self._mt5 = None
            logger.warning("MetaTrader5 not available — using fallback mode")

    def get_state(self) -> AccountState | None:
        """
        Get current account state.
        Returns cached value if within TTL.
        Returns None if MT5 is unavailable.
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < self.CACHE_TTL_SECONDS:
            return self._cache

        if not self._mt5_available or self._mt5 is None:
            logger.warning("MT5 not available for account state")
            return self._cache  # return stale cache or None

        try:
            info = self._mt5.account_info()
            if info is None:
                logger.error("MT5 account_info() returned None")
                return self._cache

            # Track day start balance (reset at broker day rollover)
            if self._day_start_balance is None:
                self._day_start_balance = info.balance
                logger.info(f"Day start balance initialized: {info.balance}")

            # Track highest balance for trailing DD firms
            self._highest_balance = max(self._highest_balance, info.balance)

            # Count open positions
            positions = self._mt5.positions_total()

            state = AccountState(
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                floating_pnl=info.profit,
                open_position_count=positions if positions else 0,
                day_start_balance=self._day_start_balance, # pyright: ignore[reportArgumentType]
                highest_balance=self._highest_balance,
                currency=info.currency,
            )

            self._cache = state
            self._cache_time = now
            return state

        except Exception as e:
            logger.error(f"Failed to get account state: {e}")
            return self._cache

    def reset_day_start_balance(self, balance: float | None = None) -> None:
        """
        Call at broker day rollover to reset daily tracking.
        If balance is None, uses current balance from MT5.
        """
        if balance is not None:
            self._day_start_balance = balance
        elif self._cache:
            self._day_start_balance = self._cache.balance
        logger.info(f"Day start balance reset to: {self._day_start_balance}")

    def force_refresh(self) -> AccountState | None:
        """Force bypass cache."""
        self._cache_time = 0.0
        return self.get_state()
