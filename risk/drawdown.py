"""
Drawdown Monitor - Redis-Persistent High-Water Mark Tracker

Tracks daily, weekly, and total drawdown with Redis persistence.
Survives container restarts and auto-resets on schedule.
Thread-safe with proper locking.
"""

import threading
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from config_loader import load_risk
from storage.redis_client import RedisClient
from utils.timezone_utils import now_utc
from risk.exceptions import DrawdownLimitExceeded


class DrawdownMonitor:
    """
    Redis-backed drawdown monitor with high-water mark tracking.

    Features:
    - Persists daily/weekly/total drawdown to Redis
    - Auto-resets daily drawdown at midnight UTC
    - Auto-resets weekly drawdown on Monday 00:00 UTC
    - Tracks peak equity for proper drawdown calculation
    - Thread-safe with locking
    - Survives container restarts

    Attributes
    ----------
    max_daily_percent : float
        Maximum allowed daily drawdown as decimal (e.g., 0.03 = 3%)
    max_weekly_percent : float
        Maximum allowed weekly drawdown as decimal
    max_total_percent : float
        Maximum allowed total drawdown from peak equity
    """

    def __init__(
        self,
        initial_balance: float,
        max_daily_percent: Optional[float] = None,
        max_weekly_percent: Optional[float] = None,
        max_total_percent: Optional[float] = None
    ):
        """
        Initialize DrawdownMonitor.

        Parameters
        ----------
        initial_balance : float
            Starting account balance for peak equity tracking
        max_daily_percent : float, optional
            Max daily drawdown (loaded from config if None)
        max_weekly_percent : float, optional
            Max weekly drawdown (loaded from config if None)
        max_total_percent : float, optional
            Max total drawdown (loaded from config if None)
        """
        self._lock = threading.Lock()
        self._redis = RedisClient()
        self._config = load_risk()

        # Load limits from config if not provided
        dd_config = self._config["drawdown"]
        self.max_daily_percent = (
            max_daily_percent or dd_config["max_daily_percent"]
        )
        self.max_weekly_percent = (
            max_weekly_percent or dd_config["max_weekly_percent"]
        )
        self.max_total_percent = (
            max_total_percent or dd_config["max_total_percent"]
        )

        # Redis keys
        keys = self._config["redis_keys"]
        self._key_daily = keys["drawdown_daily"]
        self._key_weekly = keys["drawdown_weekly"]
        self._key_total = keys["drawdown_total"]
        self._key_peak = keys["peak_equity"]

        # Load state from Redis or initialize
        self._load_or_initialize(initial_balance)

        logger.info(
            "DrawdownMonitor initialized",
            max_daily_pct=self.max_daily_percent * 100,
            max_weekly_pct=self.max_weekly_percent * 100,
            max_total_pct=self.max_total_percent * 100,
            peak_equity=self._peak_equity,
        )

    def _load_or_initialize(self, initial_balance: float) -> None:
        """Load state from Redis or initialize with defaults."""
        with self._lock:
            # Try to load existing state
            daily = self._redis.get(self._key_daily)
            weekly = self._redis.get(self._key_weekly)
            total = self._redis.get(self._key_total)
            peak = self._redis.get(self._key_peak)

            self._daily_dd = float(daily) if daily else 0.0
            self._weekly_dd = float(weekly) if weekly else 0.0
            self._total_dd = float(total) if total else 0.0
            self._peak_equity = float(peak) if peak else initial_balance

            # Store tracking timestamps
            now = now_utc()
            self._last_daily_reset = now.date()
            self._last_weekly_reset = self._get_week_start(now).date()

            # Persist initial state if new
            if not peak:
                self._persist_state()

    def _get_week_start(self, dt: datetime) -> datetime:
        """Get Monday 00:00 UTC of the week containing dt."""
        days_since_monday = dt.weekday()
        monday = dt.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days_since_monday)
        return monday

    def _persist_state(self) -> None:
        """Persist current state to Redis. Must be called within lock."""
        try:
            self._redis.set(self._key_daily, str(self._daily_dd))
            self._redis.set(self._key_weekly, str(self._weekly_dd))
            self._redis.set(self._key_total, str(self._total_dd))
            self._redis.set(self._key_peak, str(self._peak_equity))
        except Exception as e:
            logger.error(
                "Failed to persist drawdown state to Redis",
                error=str(e)
            )

    def _check_and_reset_daily(self) -> None:
        """Check if we need to reset daily drawdown (midnight UTC)."""
        now = now_utc()
        today = now.date()

        if today != self._last_daily_reset:
            logger.info(
                "Auto-resetting daily drawdown",
                old_value=self._daily_dd,
                date=str(today)
            )
            self._daily_dd = 0.0
            self._last_daily_reset = today
            self._persist_state()

    def _check_and_reset_weekly(self) -> None:
        """Check if we need to reset weekly drawdown (Monday 00:00 UTC)."""
        now = now_utc()
        week_start = self._get_week_start(now).date()

        if week_start != self._last_weekly_reset:
            logger.info(
                "Auto-resetting weekly drawdown",
                old_value=self._weekly_dd,
                week_start=str(week_start)
            )
            self._weekly_dd = 0.0
            self._last_weekly_reset = week_start
            self._persist_state()

    def update(
        self,
        current_equity: float,
        pnl: Optional[float] = None
    ) -> None:
        """
        Update drawdown tracking with current equity or trade P&L.

        Parameters
        ----------
        current_equity : float
            Current account equity
        pnl : float, optional
            Trade P&L if recording a single trade result

        Notes
        -----
        - Updates peak equity if current equity is higher
        - Calculates drawdown from peak
        - Auto-resets daily/weekly counters if needed
        - Persists state to Redis
        """
        with self._lock:
            # Check for auto-resets
            self._check_and_reset_daily()
            self._check_and_reset_weekly()

            # Update peak equity
            if current_equity > self._peak_equity:
                old_peak = self._peak_equity
                self._peak_equity = current_equity
                logger.debug(
                    "New peak equity",
                    old_peak=old_peak,
                    new_peak=self._peak_equity
                )

            # Calculate drawdown from peak
            drawdown = self._peak_equity - current_equity

            # If PNL provided and negative, add to daily/weekly counters
            if pnl is not None and pnl < 0:
                loss = abs(pnl)
                self._daily_dd += loss
                self._weekly_dd += loss

                logger.debug(
                    "Drawdown updated",
                    pnl=pnl,
                    daily_dd=self._daily_dd,
                    weekly_dd=self._weekly_dd,
                    total_dd=drawdown
                )

            # Update total drawdown (from peak)
            self._total_dd = drawdown

            # Persist to Redis
            self._persist_state()

    def get_snapshot(self) -> dict:
        """
        Get current drawdown snapshot.

        Returns
        -------
        dict
            Snapshot with daily/weekly/total drawdown amounts and percentages
        """
        with self._lock:
            # Check for auto-resets before returning snapshot
            self._check_and_reset_daily()
            self._check_and_reset_weekly()

            return {
                "daily_dd_amount": self._daily_dd,
                "weekly_dd_amount": self._weekly_dd,
                "total_dd_amount": self._total_dd,
                "daily_dd_percent": (
                    self._daily_dd / self._peak_equity
                    if self._peak_equity > 0 else 0.0
                ),
                "weekly_dd_percent": (
                    self._weekly_dd / self._peak_equity
                    if self._peak_equity > 0 else 0.0
                ),
                "total_dd_percent": (
                    self._total_dd / self._peak_equity
                    if self._peak_equity > 0 else 0.0
                ),
                "peak_equity": self._peak_equity,
                "max_daily_percent": self.max_daily_percent,
                "max_weekly_percent": self.max_weekly_percent,
                "max_total_percent": self.max_total_percent,
            }

    def is_breached(self) -> bool:
        """
        Check if any drawdown limit is breached.

        Returns
        -------
        bool
            True if any limit is exceeded
        """
        with self._lock:
            self._check_and_reset_daily()
            self._check_and_reset_weekly()

            if self._peak_equity <= 0:
                return False

            daily_pct = self._daily_dd / self._peak_equity
            weekly_pct = self._weekly_dd / self._peak_equity
            total_pct = self._total_dd / self._peak_equity

            breached = (
                daily_pct >= self.max_daily_percent or
                weekly_pct >= self.max_weekly_percent or
                total_pct >= self.max_total_percent
            )

            if breached:
                logger.warning(
                    "Drawdown limit breached",
                    daily_pct=daily_pct * 100,
                    weekly_pct=weekly_pct * 100,
                    total_pct=total_pct * 100,
                    max_daily=self.max_daily_percent * 100,
                    max_weekly=self.max_weekly_percent * 100,
                    max_total=self.max_total_percent * 100,
                )

            return breached

    def check_and_raise(self) -> None:
        """
        Check drawdown and raise exception if breached.

        Raises
        ------
        DrawdownLimitExceeded
            If any drawdown limit is breached
        """
        if self.is_breached():
            snapshot = self.get_snapshot()
            raise DrawdownLimitExceeded(
                f"Drawdown limit exceeded: "
                f"daily={snapshot['daily_dd_percent']*100:.2f}%, "
                f"weekly={snapshot['weekly_dd_percent']*100:.2f}%, "
                f"total={snapshot['total_dd_percent']*100:.2f}%"
            )
