"""
Trade Journal
Immutable trade history for audit.
"""

from datetime import datetime

from utils.timezone_utils import now_utc


class TradeJournal:
    def __init__(self):
        self._trades = []

    def record(self, trade: dict):
        entry = {
            "timestamp": now_utc().isoformat(),
            **trade,
        }
        self._trades.append(entry)

    def all(self):
        return list(self._trades)
# Placeholder
