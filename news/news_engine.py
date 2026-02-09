"""
News Engine
Determines whether market is locked due to news.
"""

from datetime import datetime, timedelta

from context.live_context_bus import LiveContextBus
from news.news_rules import NEWS_RULES


class NewsEngine:
    def __init__(self):
        self.context = LiveContextBus()

    def is_locked(self, symbol: str) -> bool:
        """
        Check if trading is locked for the given symbol due to news events.

        Parameters
        ----------
        symbol : str
            The trading symbol to check (e.g., 'EURUSD')

        Returns
        -------
        bool
            True if trading should be locked, False otherwise

        Notes
        -----
        Events without an 'affected_pairs' field (or with an empty list) are
        considered to affect all symbols and will be checked for all symbols.
        """
        news = self.context.get_news()
        if not news or "events" not in news:
            return False

        now = datetime.utcnow()

        for event in news["events"]:
            # Filter events relevant to the symbol's currency pairs
            # If affected_pairs is present and non-empty, only check events
            # that explicitly list this symbol. Otherwise, treat event as
            # affecting all symbols.
            affected = event.get("affected_pairs", [])
            if affected and symbol not in affected:
                # Skip events that don't affect this symbol
                continue

            impact = event.get("impact", "LOW").upper()
            rule = NEWS_RULES.get(impact)
            if not rule or not rule["lock"]:
                continue

            event_time = event.get("timestamp")
            if not event_time:
                continue

            start = event_time - timedelta(minutes=rule["pre_minutes"])
            end = event_time + timedelta(minutes=rule["post_minutes"])

            if start <= now <= end:
                return True

        return False
# Placeholder
