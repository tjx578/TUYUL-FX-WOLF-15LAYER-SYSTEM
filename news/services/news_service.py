"""
NewsService — orchestrates the provider chain and caching layer.

Design
------
- **First-provider-wins**: iterates the provider chain in order and
  returns the first non-empty result.  Remaining providers are not called.
- Runs `deduplicate_events()` on the winning provider result before
  caching or persisting.
- Uses Redis for day snapshots, blocker status, source health, and
  parameterised upcoming queries.
- Supports stale-day refresh via day metadata and a configurable threshold.
- Persists to Postgres as best-effort (fire-and-forget on error).
- Calendar/news remains **advisory only** — this service has no
  execution authority.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from news.blocker_engine import BlockerEngine
from news.dedup import deduplicate_events
from news.exceptions import (
    NoProvidersConfiguredError,
    ProviderParseError,
    ProviderUnavailableError,
)
from news.models import BlockerStatus, EconomicEvent, ImpactLevel
from news.provider_protocol import NewsProvider
from news.provider_selector import build_provider_chain
from news.repository import NewsRepository

logger = logging.getLogger(__name__)

# Staleness threshold in seconds (default: 1 hour)
_STALENESS_THRESHOLD_SEC = int(os.getenv("NEWS_STALENESS_THRESHOLD_SEC", "3600"))


class NewsService:
    """
    Service layer for the economic calendar subsystem.

    Parameters
    ----------
    repository : NewsRepository
        The cache/persistence layer.
    provider_chain : list[NewsProvider] | None
        Explicit provider chain (overrides env-based selection in tests).
    blocker_engine : BlockerEngine | None
        Custom blocker engine (overrides default in tests).
    """

    def __init__(
        self,
        repository: NewsRepository,
        provider_chain: list[NewsProvider] | None = None,
        blocker_engine: BlockerEngine | None = None,
    ) -> None:
        self._repo = repository
        self._blocker = blocker_engine or BlockerEngine()
        self._provider_chain = provider_chain  # None = lazy-build from env

    def _get_provider_chain(self) -> list[NewsProvider]:
        """Return the configured provider chain, building from env if needed."""
        if self._provider_chain is not None:
            return self._provider_chain
        try:
            return build_provider_chain()
        except NoProvidersConfiguredError:
            logger.info("NEWS_PROVIDER=off — no providers configured")
            return []

    # ── Day events ─────────────────────────────────────────────────────────────

    async def get_day_events(
        self,
        date_str: str,
        *,
        force_refresh: bool = False,
    ) -> list[EconomicEvent]:
        """
        Return economic events for *date_str*.

        Cache hit: return cached events immediately (unless force_refresh or stale).
        Cache miss / stale: run the provider chain (first-provider-wins),
        deduplicate, cache, and optionally persist.
        """
        if not force_refresh:
            # Check staleness
            meta = await self._repo.get_day_meta(date_str)
            if meta:
                fetched_at_str = meta.get("fetched_at", "")
                if fetched_at_str:
                    try:
                        fetched_dt = datetime.fromisoformat(fetched_at_str)
                        age_secs = (datetime.now(UTC) - fetched_dt).total_seconds()
                        if age_secs < _STALENESS_THRESHOLD_SEC:
                            cached = await self._repo.get_day_events_raw(date_str)
                            if cached is not None:
                                return self._hydrate_events(cached)
                    except ValueError:
                        pass

        # Fetch from provider chain
        events = await self._fetch_from_providers(date_str)

        if events:
            events = deduplicate_events(events)
            await self._repo.set_day_events(date_str, events)
            await self._repo.set_day_meta(
                date_str,
                {
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "source": events[0].source if events else "unknown",
                    "count": len(events),
                },
            )
            # Best-effort Postgres persistence
            await self._repo.upsert_events(events)

        return events

    async def _fetch_from_providers(self, date_str: str) -> list[EconomicEvent]:
        """
        Run the provider chain (first-provider-wins policy).

        Returns the first non-empty result.  Logs failures and
        continues to the next provider.
        """
        chain = self._get_provider_chain()
        if not chain:
            return []

        winning_provider: str | None = None
        for provider in chain:
            try:
                events = await provider.fetch_day(date_str)
                if events:
                    winning_provider = provider.name
                    logger.info(
                        "Provider '%s' returned %d events for %s",
                        provider.name, len(events), date_str,
                    )
                    await self._record_source_health(provider.name, success=True)
                    return events
                # Provider returned empty — try next
                logger.debug("Provider '%s' returned 0 events for %s", provider.name, date_str)
            except (ProviderUnavailableError, ProviderParseError) as exc:
                logger.warning("Provider '%s' failed: %s", provider.name, exc)
                await self._record_source_health(provider.name, success=False, error=str(exc))
                continue
            except Exception as exc:
                logger.exception("Provider '%s' unexpected error: %s", provider.name, exc)
                await self._record_source_health(provider.name, success=False, error=str(exc))
                continue

        logger.warning("All providers exhausted for %s — returning empty", date_str)
        return []

    # ── Blocker status ─────────────────────────────────────────────────────────

    async def get_blocker_status(
        self,
        symbol: str | None = None,
        *,
        now: datetime | None = None,
    ) -> BlockerStatus:
        """
        Evaluate and return the current blocker status.

        Uses today's (and if near midnight, tomorrow's) events.
        """
        now = now or datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        # Gather events for today and tomorrow
        today_events = await self.get_day_events(today)
        tomorrow_events = await self.get_day_events(tomorrow)
        all_events = today_events + tomorrow_events

        status = self._blocker.evaluate(all_events, symbol=symbol, now=now)

        # Cache the status dict
        await self._repo.set_blocker_status(
            symbol or "ALL", status.to_dict()
        )

        return status

    async def is_locked(self, symbol: str | None = None) -> bool:
        """Boolean shortcut — True if trading is currently locked for *symbol*."""
        status = await self.get_blocker_status(symbol=symbol)
        return status.is_locked

    # ── Upcoming events ────────────────────────────────────────────────────────

    async def get_upcoming_events(
        self,
        lookahead_hours: int = 4,
        min_impact: str = "HIGH",
        *,
        now: datetime | None = None,
    ) -> list[EconomicEvent]:
        """
        Return events within the next *lookahead_hours* hours at or above
        *min_impact*.
        """
        now = now or datetime.now(UTC)
        cutoff = now + timedelta(hours=lookahead_hours)

        today = now.strftime("%Y-%m-%d")
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

        # Try cache first
        cached_raw = await self._repo.get_upcoming_raw(lookahead_hours, min_impact)
        if cached_raw is not None:
            return self._hydrate_events(cached_raw)

        today_events = await self.get_day_events(today)
        tomorrow_events = await self.get_day_events(tomorrow)
        all_events = today_events + tomorrow_events

        # Filter by time window and impact
        min_score = self._impact_score_for(min_impact)
        upcoming = [
            e for e in all_events
            if not e.is_timeless
            and e.datetime_utc is not None
            and now <= e.datetime_utc <= cutoff
            and e.impact_score >= min_score
        ]
        upcoming.sort(key=lambda e: e.datetime_utc or datetime.max.replace(tzinfo=UTC))

        await self._repo.set_upcoming(lookahead_hours, min_impact, upcoming)
        return upcoming

    # ── Source health ──────────────────────────────────────────────────────────

    async def get_source_health(self) -> dict[str, Any]:
        """Return health records for all known providers."""
        # Provider names are pulled from the actual provider classes to avoid drift
        from news.providers.forexfactory_json_provider import ForexFactoryJsonProvider
        from news.providers.forexfactory_xml_provider import ForexFactoryXmlProvider
        from news.providers.finnhub_provider import FinnhubProvider
        from news.providers.forexfactory_html_provider import ForexFactoryHtmlProvider

        known_providers = [
            ForexFactoryJsonProvider.name,
            ForexFactoryXmlProvider.name,
            FinnhubProvider.name,
            ForexFactoryHtmlProvider.name,
        ]
        result: dict[str, Any] = {}
        for name in known_providers:
            health = await self._repo.get_source_health(name)
            if health:
                result[name] = health
        return result

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _record_source_health(
        self,
        source: str,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Update the source health record in Redis."""
        health: dict[str, Any] = {
            "source": source,
            "last_checked": datetime.now(UTC).isoformat(),
            "last_success": datetime.now(UTC).isoformat() if success else None,
            "last_error": error,
            "healthy": success,
        }
        await self._repo.set_source_health(source, health)

    @staticmethod
    def _hydrate_events(raw_list: list[dict[str, Any]]) -> list[EconomicEvent]:
        """Reconstruct EconomicEvent objects from cached raw dicts."""
        from datetime import datetime
        from news.models import EconomicEvent, EventStatus, ImpactLevel, SourceConfidence

        events: list[EconomicEvent] = []
        for d in raw_list:
            dt_utc: datetime | None = None
            if d.get("datetime_utc"):
                try:
                    dt_utc = datetime.fromisoformat(d["datetime_utc"])
                except ValueError:
                    pass

            fetched: datetime | None = None
            if d.get("fetched_at"):
                try:
                    fetched = datetime.fromisoformat(d["fetched_at"])
                except ValueError:
                    pass

            events.append(EconomicEvent(
                event_id=d.get("event_id", ""),
                canonical_id=d.get("canonical_id", ""),
                source=d.get("source", ""),
                source_confidence=SourceConfidence(d.get("source_confidence", "medium")),
                title=d.get("title", ""),
                currency=d.get("currency", ""),
                country=d.get("country"),
                impact=ImpactLevel(d.get("impact", "UNKNOWN")),
                impact_score=d.get("impact_score", 0),
                date=d.get("date", ""),
                time=d.get("time", ""),
                datetime_utc=dt_utc,
                timezone_source=d.get("timezone_source", "America/New_York"),
                is_timeless=d.get("is_timeless", False),
                actual=d.get("actual"),
                forecast=d.get("forecast"),
                previous=d.get("previous"),
                better_direction=d.get("better_direction"),
                event_url=d.get("event_url"),
                status=EventStatus(d.get("status", "SCHEDULED")),
                affected_pairs=d.get("affected_pairs", []),
                fetched_at=fetched,
            ))
        return events

    @staticmethod
    def _impact_score_for(min_impact: str) -> int:
        """Return numeric score for a minimum impact filter string."""
        from news.impact_mapper import impact_score, map_ff_impact
        return impact_score(map_ff_impact(min_impact))
