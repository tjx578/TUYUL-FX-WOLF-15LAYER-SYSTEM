"""
Drawdown Monitor
"""

from datetime import datetime


class DrawdownMonitor:
    def __init__(self, max_daily: float, max_total: float):
        self.max_daily = max_daily
        self.max_total = max_total
        self.daily_dd = 0.0
        self.total_dd = 0.0
        self.last_reset = datetime.utcnow().date()

    def update(self, pnl: float):
        today = datetime.utcnow().date()
        if today != self.last_reset:
            self.daily_dd = 0.0
            self.last_reset = today

        if pnl < 0:
            loss = abs(pnl)
            self.daily_dd += loss
            self.total_dd += loss

    def is_breached(self) -> bool:
        return self.daily_dd >= self.max_daily or self.total_dd >= self.max_total
