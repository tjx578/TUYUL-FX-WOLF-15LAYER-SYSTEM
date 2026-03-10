"""Economic calendar ingestion via news provider chain (Forex Factory first)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from context.live_context_bus import LiveContextBus
from news.models import EconomicEvent
from news.repository import NewsRepository
from news.services.news_service import NewsService


class CalendarNewsIngestor:
    """
    Poll economic calendar events through the `news/` provider chain.

    This ingestor is advisory-only and has no execution authority.
    """

    def __init__(self, redis_client: Any) -> None:
        super().__init__()
        self._repo = NewsRepository(redis_client)
        self._service = NewsService(self._repo)
        self._context_bus = LiveContextBus()
        self._stop_event = asyncio.Event()

        self._enabled = os.getenv("NEWS_INGEST_ENABLED", "true").lower() == "true"
        self._poll_interval = int(os.getenv("NEWS_POLL_INTERVAL_SEC", "300"))
        self._provider = os.getenv("NEWS_PROVIDER", "forexfactory")

    async def stop(self) -> None:
        """Signal the polling loop to stop gracefully."""
        self._stop_event.set()

    async def _fetch_window_events(self) -> list[EconomicEvent]:
        now = datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        today_events = await self._service.get_day_events(today)
        tomorrow_events = await self._service.get_day_events(tomorrow)

        combined = today_events + tomorrow_events
        dedup: dict[str, EconomicEvent] = {}
        for event in combined:
            key = event.canonical_id or event.event_id
            dedup[key] = event
        return list(dedup.values())

    @staticmethod
    def _to_legacy_event(event: EconomicEvent) -> dict[str, Any]:
        return {
            "event": event.title,
            "country": event.country or "",
            "currency": event.currency,
            "impact": event.impact.value.lower(),
            "timestamp": event.datetime_utc,
            "datetime_utc": event.datetime_utc.isoformat() if event.datetime_utc else None,
            "affected_pairs": event.affected_pairs,
            "actual": event.actual,
            "forecast": event.forecast,
            "previous": event.previous,
            "source": event.source,
        }

    async def run(self) -> None:
        """Main polling loop."""
        if not self._enabled:
            logger.warning("Calendar news ingestion disabled by NEWS_INGEST_ENABLED")
            return

        logger.info(
            "Calendar news poller started (interval=%ss, provider=%s)",
            self._poll_interval,
            self._provider,
        )

        while not self._stop_event.is_set():
            try:
                events = await self._fetch_window_events()
                payload = {
                    "events": [self._to_legacy_event(event) for event in events],
                    "source": "news_provider_chain",
                    "provider": self._provider,
                    "count": len(events),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
                self._context_bus.update_news(payload)
                logger.info("Economic calendar updated via provider chain: {} events", len(events))
            except Exception as exc:
                logger.error(f"Calendar news poll failed: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
            except TimeoutError:
                continue
