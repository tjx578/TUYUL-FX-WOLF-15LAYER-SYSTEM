"""
Drawdown Monitor
"""

from datetime import datetime

from utils.timezone_utils import now_utc, now_local


class DrawdownMonitor:
    def __init__(self, max_daily: float, max_total: float):
        self.max_daily = max_daily
        self.max_total = max_total
        self.daily_dd = 0.0
        self.total_dd = 0.0
        self.last_reset = now_local().date()

    def update(self, pnl: float):
        today = now_local().date()
        if today != self.last_reset:
            self.daily_dd = 0.0
            self.last_reset = today

        if pnl < 0:
            loss = abs(pnl)
            self.daily_dd += loss
            self.total_dd += loss

    def is_breached(self) -> bool:
        return self.daily_dd >= self.max_daily or self.total_dd >= self.max_total
# Placeholder
