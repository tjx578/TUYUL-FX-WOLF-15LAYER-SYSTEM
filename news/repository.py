"""
NewsRepository — Redis cache + optional Postgres persistence.

Responsibilities
----------------
- Store/retrieve day event snapshots in Redis (primary cache).
- Store/retrieve day metadata (fetched_at, source) for staleness detection.
- Store/retrieve blocker status snapshots in Redis.
- Store/retrieve source health records in Redis.
- Store upcoming events in parameterised cache keys.
- Best-effort Postgres upsert using canonical_id (fire-and-forget on error).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from news.models import EconomicEvent

logger = logging.getLogger(__name__)

# ── Redis key templates ────────────────────────────────────────────────────────
_DAY_KEY = "news:day:{date}"
_DAY_META_KEY = "news:day_meta:{date}"
_BLOCKER_KEY = "news:blocker:{symbol}"
_HEALTH_KEY = "news:health:{source}"
_UPCOMING_KEY = "news:upcoming:{lookahead_h}h:{min_impact}"

_DAY_TTL = 3600 * 6  # 6 hours
_BLOCKER_TTL = 60 * 5  # 5 minutes
_HEALTH_TTL = 60 * 30  # 30 minutes
_UPCOMING_TTL = 60 * 10  # 10 minutes


def _events_to_json(events: list[EconomicEvent]) -> str:
    return json.dumps([e.to_dict() for e in events])


def _events_from_json(raw: str) -> list[dict[str, Any]]:
    return json.loads(raw)


class NewsRepository:
    """
    Thin cache/persistence layer over Redis (async) and optionally Postgres.

    Parameters
    ----------
    redis_client : Any
        An async Redis client (e.g. redis.asyncio.Redis).
    pg_pool : Any | None
        An asyncpg connection pool for Postgres upserts (optional).
    """

    def __init__(self, redis_client: Any, pg_pool: Any = None) -> None:
        self._redis = redis_client
        self._pg = pg_pool

    # ── Day snapshot ──────────────────────────────────────────────────────────

    async def get_day_events_raw(self, date_str: str) -> list[dict[str, Any]] | None:
        """Return cached raw event dicts for *date_str*, or None on cache miss."""
        try:
            raw = await self._redis.get(_DAY_KEY.format(date=date_str))
            if raw:
                return _events_from_json(raw)
        except Exception:
            logger.exception("Redis get_day_events_raw failed for %s", date_str)
        return None

    async def set_day_events(self, date_str: str, events: list[EconomicEvent]) -> None:
        """Cache *events* for *date_str*."""
        try:
            await self._redis.set(
                _DAY_KEY.format(date=date_str),
                _events_to_json(events),
                ex=_DAY_TTL,
            )
        except Exception:
            logger.exception("Redis set_day_events failed for %s", date_str)

    # ── Day metadata (staleness) ───────────────────────────────────────────────

    async def get_day_meta(self, date_str: str) -> dict[str, Any] | None:
        """Return stored day metadata or None."""
        try:
            raw = await self._redis.get(_DAY_META_KEY.format(date=date_str))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Redis get_day_meta failed for %s", date_str)
        return None

    async def set_day_meta(self, date_str: str, meta: dict[str, Any]) -> None:
        """Store day metadata."""
        try:
            await self._redis.set(
                _DAY_META_KEY.format(date=date_str),
                json.dumps(meta),
                ex=_DAY_TTL,
            )
        except Exception:
            logger.exception("Redis set_day_meta failed for %s", date_str)

    # ── Blocker status ─────────────────────────────────────────────────────────

    async def get_blocker_status(self, symbol: str) -> dict[str, Any] | None:
        """Return cached blocker status dict or None."""
        try:
            raw = await self._redis.get(_BLOCKER_KEY.format(symbol=symbol or "ALL"))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Redis get_blocker_status failed for %s", symbol)
        return None

    async def set_blocker_status(self, symbol: str, status_dict: dict[str, Any]) -> None:
        """Cache blocker status dict."""
        try:
            await self._redis.set(
                _BLOCKER_KEY.format(symbol=symbol or "ALL"),
                json.dumps(status_dict),
                ex=_BLOCKER_TTL,
            )
        except Exception:
            logger.exception("Redis set_blocker_status failed for %s", symbol)

    # ── Source health ──────────────────────────────────────────────────────────

    async def get_source_health(self, source: str) -> dict[str, Any] | None:
        """Return cached source health record or None."""
        try:
            raw = await self._redis.get(_HEALTH_KEY.format(source=source))
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Redis get_source_health failed for %s", source)
        return None

    async def set_source_health(self, source: str, health: dict[str, Any]) -> None:
        """Cache source health record."""
        try:
            await self._redis.set(
                _HEALTH_KEY.format(source=source),
                json.dumps(health),
                ex=_HEALTH_TTL,
            )
        except Exception:
            logger.exception("Redis set_source_health failed for %s", source)

    # ── Upcoming events ────────────────────────────────────────────────────────

    async def get_upcoming_raw(self, lookahead_hours: int, min_impact: str) -> list[dict[str, Any]] | None:
        """Return cached upcoming events or None."""
        key = _UPCOMING_KEY.format(lookahead_h=lookahead_hours, min_impact=min_impact)
        try:
            raw = await self._redis.get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.exception("Redis get_upcoming_raw failed")
        return None

    async def set_upcoming(
        self,
        lookahead_hours: int,
        min_impact: str,
        events: list[EconomicEvent],
    ) -> None:
        """Cache upcoming events."""
        key = _UPCOMING_KEY.format(lookahead_h=lookahead_hours, min_impact=min_impact)
        try:
            await self._redis.set(
                key,
                _events_to_json(events),
                ex=_UPCOMING_TTL,
            )
        except Exception:
            logger.exception("Redis set_upcoming failed")

    # ── Postgres best-effort upsert ────────────────────────────────────────────

    async def upsert_events(self, events: list[EconomicEvent]) -> None:
        """
        Best-effort upsert of *events* into Postgres.

        Silently logs and returns on any error — Postgres is
        non-critical write-behind storage.
        """
        if not self._pg:
            return

        for event in events:
            try:
                await self._upsert_one(event)
            except Exception:
                logger.exception("Postgres upsert failed for canonical_id=%s", event.canonical_id)

    async def _upsert_one(self, event: EconomicEvent) -> None:
        """Upsert a single event into the economic_events table."""
        async with self._pg.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO economic_events (
                    event_id, canonical_id, source, source_confidence,
                    title, currency, country, impact, impact_score,
                    date, time, datetime_utc, timezone_source, is_timeless,
                    actual, forecast, previous, better_direction,
                    event_url, status, affected_pairs, fetched_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $14, $15, $16, $17, $18,
                    $19, $20, $21::jsonb, $22
                )
                ON CONFLICT (canonical_id)
                WHERE source_confidence IN ('high', 'medium')
                DO UPDATE SET
                    actual        = EXCLUDED.actual,
                    forecast      = EXCLUDED.forecast,
                    previous      = EXCLUDED.previous,
                    status        = EXCLUDED.status,
                    fetched_at    = EXCLUDED.fetched_at
                """,
                event.event_id,
                event.canonical_id,
                event.source,
                event.source_confidence.value,
                event.title,
                event.currency,
                event.country,
                event.impact.value,
                event.impact_score,
                event.date,
                event.time,
                event.datetime_utc,
                event.timezone_source,
                event.is_timeless,
                event.actual,
                event.forecast,
                event.previous,
                event.better_direction,
                event.event_url,
                event.status.value,
                json.dumps(event.affected_pairs),
                event.fetched_at or datetime.now(UTC),
            )
