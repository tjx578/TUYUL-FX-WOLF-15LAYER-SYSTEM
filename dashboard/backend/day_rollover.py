"""
Day rollover handler for prop firm daily loss tracking.
Resets day_start_balance at broker server midnight.
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

logger = logging.getLogger("tuyul.dashboard.rollover")

BROKER_TZ_OFFSET_HOURS = 2  # EET (most MT5 brokers)


class DayRolloverManager:
    """Tracks broker server day boundaries."""

    def __init__(self, tz_offset_hours: int = BROKER_TZ_OFFSET_HOURS) -> None:
        self._tz = timezone(timedelta(hours=tz_offset_hours))
        self._last_broker_date: str | None = None

    def check_rollover(self, account_provider) -> bool:
        """Call periodically. Returns True if rollover occurred."""
        today_str = datetime.now(self._tz).strftime("%Y-%m-%d")

        if self._last_broker_date is None:
            self._last_broker_date = today_str
            logger.info("Day rollover initialized: broker date = %s", today_str)
            return False

        if today_str != self._last_broker_date:
            logger.info(
                "BROKER DAY ROLLOVER: %s → %s",
                self._last_broker_date, today_str,
            )
            self._last_broker_date = today_str
            account_provider.reset_day_start_balance()
            return True

        return False

    @property
    def current_broker_date(self) -> str:
        return datetime.now(self._tz).strftime("%Y-%m-%d")
