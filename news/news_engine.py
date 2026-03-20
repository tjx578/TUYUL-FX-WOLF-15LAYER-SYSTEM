"""
News Engine
Determines whether market is locked due to news and provides
sentiment-enriched market context.

Provides both the legacy synchronous interface (used by the pipeline)
and sentiment-enriched advisory data that flows into LiveContextBus
for confidence adjustment and position sizing influence.

The legacy ``is_locked()`` method reads directly from ``LiveContextBus``
for backward compatibility with existing pipeline code.  It uses the
``BlockerEngine`` from this subsystem for consistent lock logic.

The ``get_sentiment_adjustment()`` method provides advisory confidence
adjustment based on news sentiment. This NEVER overrides L12 verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from context.live_context_bus import LiveContextBus
from news.blocker_engine import BlockerEngine
from news.news_rules import NEWS_RULES
from news.sentiment.aggregator import SentimentAggregator


class NewsEngine:
    """
    Legacy-compatible news engine.

    Uses ``LiveContextBus`` as the event source so that the pipeline
    continues to work without requiring an async database call.
    """

    def __init__(self) -> None:
        self.context = LiveContextBus()
        self._blocker = BlockerEngine()
        self._aggregator = SentimentAggregator()

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

            event_time = event_time.replace(tzinfo=UTC) if event_time.tzinfo is None else event_time.astimezone(UTC)

            start = event_time - timedelta(minutes=rule["pre_minutes"])
            end = event_time + timedelta(minutes=rule["post_minutes"])

            if start <= now <= end:
                return True

        return False

    def get_sentiment_adjustment(
        self,
        symbol: str,
    ) -> dict:
        """
        Get sentiment-based confidence adjustment for a trading symbol.

        Returns an advisory payload for confidence adjustment and position
        sizing influence. This NEVER overrides L12 verdict — it is purely
        informational.

        Parameters
        ----------
        symbol : str
            The trading symbol (e.g. 'EURUSD').

        Returns
        -------
        dict
            {
                "sentiment_score": float,      # -1.0 to +1.0
                "sentiment_label": str,         # "bullish", "bearish", "neutral"
                "confidence_modifier": float,   # 0.85 to 1.0 (multiplier)
                "position_size_modifier": float, # 0.5 to 1.0 (multiplier)
                "article_count": int,
                "method": str,
            }
        """
        news = self.context.get_news()
        articles = []
        if news:
            articles = news.get("articles", [])

        if not articles:
            return {
                "sentiment_score": 0.0,
                "sentiment_label": "neutral",
                "confidence_modifier": 1.0,
                "position_size_modifier": 1.0,
                "article_count": 0,
                "method": "none",
            }

        snapshot = self._aggregator.aggregate(articles)
        score, conf = self._aggregator.score_for_symbol(snapshot, symbol)

        # Compute advisory modifiers
        # Strong adverse sentiment → reduce confidence and position size
        # Strong favorable sentiment → maintain full confidence
        abs_score = abs(score)

        # Confidence modifier: reduce when sentiment is strongly adverse
        confidence_modifier = 1.0
        if abs_score > 0.5 and conf > 0.3:
            confidence_modifier = max(0.85, 1.0 - (abs_score * 0.15))

        # Position size modifier: reduce in high-sentiment environments
        # regardless of direction (volatility concern)
        position_size_modifier = 1.0
        if abs_score > 0.6 and conf > 0.4:
            position_size_modifier = max(0.5, 1.0 - (abs_score * 0.3))

        return {
            "sentiment_score": score,
            "sentiment_label": snapshot.overall_label,
            "confidence_modifier": round(confidence_modifier, 4),
            "position_size_modifier": round(position_size_modifier, 4),
            "article_count": snapshot.article_count,
            "method": snapshot.method,
            "by_currency": {
                k: {
                    "score": v.net_score,
                    "label": v.label,
                    "count": v.article_count,
                }
                for k, v in snapshot.by_currency.items()
            },
        }
