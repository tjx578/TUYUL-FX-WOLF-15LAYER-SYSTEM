"""
Calendar API Routes
Economic calendar endpoints — advisory only, no execution authority.
"""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from infrastructure.redis_client import get_async_redis

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/calendar",
    tags=["calendar"],
)


async def _get_news_service():
    """Build a per-request NewsService backed by async Redis."""
    from news.repository import NewsRepository
    from news.services.news_service import NewsService

    r: aioredis.Redis = await get_async_redis()
    repo = NewsRepository(redis_client=r)
    return NewsService(repository=repo)


async def _is_news_locked_manual(r: aioredis.Redis) -> tuple[bool, str | None]:
    """Return (locked, reason) for the manual Redis override key."""
    with contextlib.suppress(Exception):
        raw = await r.get("NEWS_LOCK:STATE")
        if raw:
            data = json.loads(raw)
            return data.get("locked", False), data.get("reason")
    return False, None


@router.get("")
async def get_calendar(
    date: str | None = Query(default=None, description="YYYY-MM-DD, default today"),
    impact: str | None = Query(default=None, pattern="^(HIGH|MEDIUM|LOW|HOLIDAY)?$"),
    currency: str | None = Query(default=None),
) -> dict[str, Any]:
    """Fetch economic calendar events."""
    service = await _get_news_service()
    r: aioredis.Redis = await get_async_redis()

    date_str = date or datetime.now(UTC).strftime("%Y-%m-%d")

    events = await service.get_day_events(date_str)
    events_dicts = [e.to_dict() for e in events]

    if impact:
        events_dicts = [e for e in events_dicts if e.get("impact") == impact]
    if currency:
        events_dicts = [
            e for e in events_dicts if e.get("currency", "").upper() == currency.upper()
        ]

    events_dicts.sort(key=lambda e: e.get("datetime_utc") or "")

    now = datetime.now(UTC)
    for ev in events_dicts:
        ts_str = ev.get("datetime_utc")
        if ts_str and not ev.get("is_timeless"):
            try:
                ts = datetime.fromisoformat(ts_str)
                diff_minutes = (ts - now).total_seconds() / 60
                ev["minutes_away"] = round(diff_minutes)
                ev["is_imminent"] = -5 <= diff_minutes <= 60 and ev.get("impact") == "HIGH"
            except (ValueError, TypeError):
                ev["minutes_away"] = None
                ev["is_imminent"] = False
        else:
            ev["minutes_away"] = None
            ev["is_imminent"] = False

    locked, lock_reason = await _is_news_locked_manual(r)
    high_count = len([e for e in events_dicts if e.get("impact") == "HIGH"])

    return {
        "date": date_str,
        "total": len(events_dicts),
        "high_impact_count": high_count,
        "news_lock": {"active": locked, "reason": lock_reason},
        "events": events_dicts,
    }


@router.get("/upcoming")
async def upcoming_events(
    hours: int = Query(default=4, ge=1, le=24),
    impact: str | None = Query(default="HIGH"),
) -> dict[str, Any]:
    """Events in the next N hours for warning/lock advisory."""
    service = await _get_news_service()
    now = datetime.now(UTC)

    min_impact = impact or "LOW"
    events = await service.get_upcoming_events(
        lookahead_hours=hours, min_impact=min_impact, now=now
    )

    upcoming_dicts: list[dict[str, Any]] = []
    for ev in events:
        d = ev.to_dict()
        if ev.datetime_utc:
            d["minutes_away"] = round((ev.datetime_utc - now).total_seconds() / 60)
        else:
            d["minutes_away"] = None
        upcoming_dicts.append(d)

    return {
        "hours_ahead": hours,
        "impact_filter": impact,
        "count": len(upcoming_dicts),
        "events": upcoming_dicts,
        "has_high_impact": any(e.get("impact") == "HIGH" for e in upcoming_dicts),
    }


@router.get("/blocker")
async def blocker_status(
    symbol: str | None = Query(default=None, description="FX pair, e.g. EURUSD"),
) -> dict[str, Any]:
    """Return the current blocker status for a symbol (or globally)."""
    service = await _get_news_service()
    r: aioredis.Redis = await get_async_redis()

    status = await service.get_blocker_status(symbol=symbol)
    manual_locked, manual_reason = await _is_news_locked_manual(r)

    result = status.to_dict()
    if manual_locked and not result["is_locked"]:
        result["is_locked"] = True
        result["lock_reason"] = f"Manual lock: {manual_reason or 'No reason given'}"

    return result


@router.get("/health")
async def calendar_source_health() -> dict[str, Any]:
    """Return health records for all calendar data sources."""
    service = await _get_news_service()
    health = await service.get_source_health()
    return {
        "sources": health,
        "checked_at": datetime.now(UTC).isoformat(),
    }


class NewsLockRequest(BaseModel):
    reason: str | None = "Manual lock"
    duration_minutes: int | None = 60


@router.post(
    "/news-lock/enable",
    dependencies=[Depends(verify_token), Depends(enforce_write_policy)],
)
async def enable_news_lock(req: NewsLockRequest) -> dict[str, Any]:
    """Activate manual news lock; blocks new trades during high-impact events."""
    r: aioredis.Redis = await get_async_redis()
    lock_data = {
        "locked": True,
        "reason": req.reason,
        "enabled_at": datetime.now(UTC).isoformat(),
        "expires_at": (
            datetime.now(UTC) + timedelta(minutes=req.duration_minutes or 60)
        ).isoformat(),
    }
    try:
        await r.set(
            "NEWS_LOCK:STATE",
            json.dumps(lock_data),
            ex=(req.duration_minutes or 60) * 60,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Redis error: {exc}") from exc
    return {"news_lock": True, **lock_data}


@router.post(
    "/news-lock/disable",
    dependencies=[Depends(verify_token), Depends(enforce_write_policy)],
)
async def disable_news_lock() -> dict[str, Any]:
    """Remove manual news lock."""
    r: aioredis.Redis = await get_async_redis()
    try:
        await r.delete("NEWS_LOCK:STATE")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Redis error: {exc}") from exc
    return {"news_lock": False, "disabled_at": datetime.now(UTC).isoformat()}


@router.get("/news-lock/status")
async def news_lock_status() -> dict[str, Any]:
    """Current manual news lock state."""
    r: aioredis.Redis = await get_async_redis()
    locked, reason = await _is_news_locked_manual(r)
    return {
        "news_lock": locked,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
    }
