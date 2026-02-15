"""
Day rollover handler for prop firm daily loss tracking.
Resets day_start_balance at broker server midnight.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

logger = logging.getLogger("tuyul.dashboard.rollover")

# Most MT5 brokers use EET (UTC+2) or EEST (UTC+3)
BROKER_TZ_OFFSET_HOURS = 2  # EET


class DayRolloverManager:
    """
    Tracks broker server day boundaries.
    Calls account_state_provider.reset_day_start_balance() at rollover.
    """

    def __init__(self, tz_offset_hours: int = BROKER_TZ_OFFSET_HOURS):
        self._tz = timezone(timedelta(hours=tz_offset_hours))
        self._last_broker_date: str | None = None

    def check_rollover(self, account_provider) -> bool:
        """
        Call this periodically (e.g., every pipeline cycle).
        Returns True if a rollover occurred and balance was reset.
        """
        now_broker = datetime.now(self._tz)
        today_str = now_broker.strftime("%Y-%m-%d")

        if self._last_broker_date is None:
            # First run — initialize
            self._last_broker_date = today_str
            logger.info(f"Day rollover initialized: broker date = {today_str}")
            return False

        if today_str != self._last_broker_date:
            # New broker day!
            logger.info(
                f"BROKER DAY ROLLOVER: {self._last_broker_date} → {today_str}"
            )
            self._last_broker_date = today_str
            account_provider.reset_day_start_balance()
            return True

        return False

    @property
    def current_broker_date(self) -> str:
        return datetime.now(self._tz).strftime("%Y-%m-%d")

    @property
    def broker_time(self) -> str:
        return datetime.now(self._tz).strftime("%H:%M:%S")
