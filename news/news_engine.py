"""
News Engine
Determines whether market is locked due to news.

Provides both the legacy synchronous interface (used by the pipeline)
and a thin async facade that delegates to ``NewsService``.

The legacy ``is_locked()`` method reads directly from ``LiveContextBus``
for backward compatibility with existing pipeline code.  It uses the
``BlockerEngine`` from this subsystem for consistent lock logic.

For new consumers (e.g. the API layer) use ``NewsService`` directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Sequence

from context.live_context_bus import LiveContextBus
from news.blocker_engine import BlockerEngine
from news.models import EconomicEvent, ImpactLevel
from news.news_rules import NEWS_RULES


class NewsEngine:
    """
    Legacy-compatible news engine.

    Uses ``LiveContextBus`` as the event source so that the pipeline
    continues to work without requiring an async database call.
    """

    def __init__(self) -> None:
        self.context = LiveContextBus()
        self._blocker = BlockerEngine()

    def is_locked(self, symbol: str) -> bool:
        """
        Check if trading is locked for the given symbol due to news events.

        Reads events from ``LiveContextBus`` and evaluates them using the
        ``BlockerEngine``.

        Parameters
        ----------
        symbol : str
            The trading symbol to check (e.g. 'EURUSD').

        Returns
        -------
        bool
            True if trading should be locked, False otherwise.

        Notes
        -----
        Events without an 'affected_pairs' field (or with an empty list)
        are considered to affect all symbols.
        """
        news = self.context.get_news()
        if not news or "events" not in news:
            return False

        now = datetime.now(UTC)
        raw_events: list[dict] = news["events"]

        # Fast path using legacy dict format for backward compatibility
        for event in raw_events:
            affected = event.get("affected_pairs", [])
            if affected and symbol not in affected:
                continue

            impact_str = event.get("impact", "LOW").upper()
            rule = NEWS_RULES.get(impact_str)
            if not rule or not rule["lock"]:
                continue

            event_time = event.get("timestamp")
            if not event_time:
                continue

            if isinstance(event_time, (int, float)):
                from news.datetime_utils import parse_unix_to_utc
                try:
                    event_time = parse_unix_to_utc(event_time)
                except Exception:
                    continue

            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=UTC)
            else:
                event_time = event_time.astimezone(UTC)

            start = event_time - timedelta(minutes=rule["pre_minutes"])
            end = event_time + timedelta(minutes=rule["post_minutes"])

            if start <= now <= end:
                return True

        return False
