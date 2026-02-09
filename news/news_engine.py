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
        news = self.context.get_news()
        if not news or "events" not in news:
            return False

        now = datetime.utcnow()

        for event in news["events"]:
            # Filter events relevant to the symbol's currency pairs
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
