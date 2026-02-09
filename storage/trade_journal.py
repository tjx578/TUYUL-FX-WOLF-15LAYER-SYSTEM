"""
Trade Journal
Immutable trade history for audit.
"""

from datetime import datetime


class TradeJournal:
    def __init__(self):
        self._trades = []

    def record(self, trade: dict):
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            **trade,
        }
        self._trades.append(entry)

    def all(self):
        return list(self._trades)
# Placeholder
