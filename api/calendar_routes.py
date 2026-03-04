"""
TUYUL FX Wolf-15 — Economic Calendar Routes
=============================================
NEW ENDPOINTS:
  GET /api/v1/calendar                    → Today's economic events
  GET /api/v1/calendar/upcoming           → Upcoming events within N hours
  POST /api/v1/calendar/news-lock/enable  → Toggle news lock
  POST /api/v1/calendar/news-lock/disable → Remove news lock
  GET /api/v1/calendar/news-lock/status   → Current news lock state

Data source: Finnhub API (FINNHUB_API_KEY already in .env)
Fallback: Mock data when API unavailable (dev mode)
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

try:
    import httpx  # noqa: F401
    _httpx_available = True
except ImportError:
    _httpx_available = False

import contextlib

from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from infrastructure.redis_client import get_async_redis

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/calendar",
    tags=["calendar"],
)

from ingest.finnhub_key_manager import finnhub_keys as _finnhub_keys  # noqa: E402

FINNHUB_API_KEY = _finnhub_keys.current_key()
FINNHUB_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
CACHE_TTL_SECONDS = 900  # 15 minutes


def _get_redis() -> None:
    """DEPRECATED — use ``get_async_redis`` dependency instead."""
    raise NotImplementedError(
        "_get_redis() is removed. Inject via Depends(get_async_redis)."
    )


# ─── Mock events for dev mode ─────────────────────────────────────────────────

def _mock_events(date_str: str) -> list[dict[str, Any]]:
    return [
        {
            "event_id": "mock_001",
            "event": "Non-Farm Payrolls",
            "country": "US",
            "currency": "USD",
            "impact": "HIGH",
            "time_utc": f"{date_str}T12:30:00Z",
            "actual": None,
            "estimate": "200K",
            "prev": "187K",
            "unit": "K",
        },
        {
            "event_id": "mock_002",
            "event": "CPI m/m",
            "country": "US",
            "currency": "USD",
            "impact": "HIGH",
            "time_utc": f"{date_str}T12:30:00Z",
            "actual": None,
            "estimate": "0.3%",
            "prev": "0.4%",
            "unit": "%",
        },
        {
            "event_id": "mock_003",
            "event": "BOE Rate Decision",
            "country": "GB",
            "currency": "GBP",
            "impact": "HIGH",
            "time_utc": f"{date_str}T11:00:00Z",
            "actual": None,
            "estimate": "5.25%",
            "prev": "5.25%",
            "unit": "%",
        },
        {
            "event_id": "mock_004",
            "event": "EUR PMI Manufacturing",
            "country": "EU",
            "currency": "EUR",
            "impact": "MEDIUM",
            "time_utc": f"{date_str}T08:30:00Z",
            "actual": None,
            "estimate": "47.5",
            "prev": "46.0",
            "unit": "",
        },
    ]


async def _fetch_finnhub_calendar(date_str: str) -> list[dict[str, Any]]:
    """Fetch economic calendar from Finnhub API."""
    if not _httpx_available:
        logger.warning("httpx not installed — using mock calendar data")
        return _mock_events(date_str)

    api_key = _finnhub_keys.current_key()
    if not api_key:
        logger.warning("FINNHUB_API_KEY not set — using mock calendar data")
        return _mock_events(date_str)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                FINNHUB_CALENDAR_URL,
                params={"from": date_str, "to": date_str, "token": api_key},
            )
            resp.raise_for_status()
            _finnhub_keys.report_success(api_key)
            data = resp.json()

        events = []
        for ev in data.get("economicCalendar", []):
            impact = _map_finnhub_impact(ev.get("impact", ""))
            events.append({
                "event_id": str(ev.get("id", "")),
                "event": ev.get("event", ""),
                "country": ev.get("country", ""),
                "currency": ev.get("currency", ""),
                "impact": impact,
                "time_utc": ev.get("time", ""),
                "actual": ev.get("actual"),
                "estimate": ev.get("estimate"),
                "prev": ev.get("prev"),
                "unit": ev.get("unit", ""),
            })
        return events

    except Exception as exc:
        # Report failure to key manager for potential rotation
        if hasattr(exc, "response"):
            _finnhub_keys.report_failure(api_key, getattr(exc.response, "status_code", 0))  # type: ignore[union-attr]
        logger.warning("Finnhub calendar fetch failed: %s — using mock data", exc)
        return _mock_events(date_str)


def _map_finnhub_impact(impact_raw: str) -> str:
    mapping = {"3": "HIGH", "2": "MEDIUM", "1": "LOW", "0": "HOLIDAY"}
    return mapping.get(str(impact_raw), "LOW")


async def _is_news_locked(r: aioredis.Redis) -> tuple[bool, str | None]:
    """Return (locked, reason)."""
    with contextlib.suppress(Exception):
        raw = await r.get("NEWS_LOCK:STATE")
        if raw:
            data = json.loads(raw)
            return data.get("locked", False), data.get("reason")
    return False, None


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("")
async def get_calendar(
    date: str | None = Query(default=None, description="YYYY-MM-DD, default today"),
    impact: str | None = Query(default=None, pattern="^(HIGH|MEDIUM|LOW|HOLIDAY)?$"),
    currency: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Fetch economic calendar events.
    Frontend: Calendar page
    """
    r: aioredis.Redis = await get_async_redis()
    date_str = date or datetime.now(UTC).strftime("%Y-%m-%d")
    cache_key = f"CALENDAR:{date_str}"

    # Cache check
    events: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        cached = await r.get(cache_key)
        if cached is not None and isinstance(cached, str):
            events = json.loads(cached)  # type: ignore[assignment]

    # Fetch if not cached
    if not events:
        events = await _fetch_finnhub_calendar(date_str)
        if events:
            with contextlib.suppress(Exception):
                await r.set(cache_key, json.dumps(events), ex=CACHE_TTL_SECONDS)

    # Apply filters
    if impact:
        events = [e for e in events if e.get("impact") == impact]
    if currency:
        events = [e for e in events if e.get("currency", "").upper() == currency.upper()]

    # Sort by time
    events_typed: list[dict[str, Any]] = list(events)
    events_typed.sort(key=lambda e: e.get("time_utc", ""))
    events = events_typed

    # News lock status
    locked, lock_reason = await _is_news_locked(r)

    # Mark events within 30 min window
    now = datetime.now(UTC)
    for ev in events:
        ts_str = ev.get("time_utc", "")
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                diff_minutes = (ts - now).total_seconds() / 60
                ev["minutes_away"] = round(diff_minutes)
                ev["is_imminent"] = -5 <= diff_minutes <= 60 and ev.get("impact") == "HIGH"
            except ValueError:
                ev["minutes_away"] = None
                ev["is_imminent"] = False

    high_count = len([e for e in events if e.get("impact") == "HIGH"])

    return {
        "date": date_str,
        "total": len(events),
        "high_impact_count": high_count,
        "news_lock": {"active": locked, "reason": lock_reason},
        "events": events,
    }


@router.get("/upcoming")
async def upcoming_events(
    hours: int = Query(default=4, ge=1, le=24),
    impact: str | None = Query(default="HIGH"),
) -> dict[str, Any]:
    """
    Events in the next N hours — used for news lock warnings.
    Frontend: Signal Queue + Overview page → warning banner
    """
    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff = now + timedelta(hours=hours)

    r: aioredis.Redis = await get_async_redis()

    upcoming: list[dict[str, Any]] = []
    for date_str in [today_str, tomorrow_str]:
        cache_key = f"CALENDAR:{date_str}"
        events: list[dict[str, Any]] = []
        with contextlib.suppress(Exception):
            cached = await r.get(cache_key)
            if cached is not None and isinstance(cached, str):
                events = json.loads(cached)
        if not events:
            events = await _fetch_finnhub_calendar(date_str)

        for ev in events:
            ts_str = ev.get("time_utc", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if now <= ts <= cutoff and (not impact or ev.get("impact") == impact):
                    diff_minutes = round((ts - now).total_seconds() / 60)
                    upcoming.append({**ev, "minutes_away": diff_minutes})
            except ValueError:
                continue

    upcoming.sort(key=lambda e: e.get("minutes_away", 999))

    return {
        "hours_ahead": hours,
        "impact_filter": impact,
        "count": len(upcoming),
        "events": upcoming,
        "has_high_impact": any(e.get("impact") == "HIGH" for e in upcoming),
    }


# ─── News Lock routes ─────────────────────────────────────────────────────────

class NewsLockRequest(BaseModel):
    reason: str | None = "Manual lock"
    duration_minutes: int | None = 60


@router.post("/news-lock/enable", dependencies=[Depends(verify_token), Depends(enforce_write_policy)])
async def enable_news_lock(req: NewsLockRequest) -> dict[str, Any]:
    """Activate news lock — blocks new trades during high-impact events."""
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
        await r.set("NEWS_LOCK:STATE", json.dumps(lock_data), ex=(req.duration_minutes or 60) * 60)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Redis error: {exc}") from exc
    return {"news_lock": True, **lock_data}


@router.post("/news-lock/disable", dependencies=[Depends(verify_token), Depends(enforce_write_policy)])
async def disable_news_lock() -> dict[str, Any]:
    """Remove news lock."""
    r: aioredis.Redis = await get_async_redis()
    try:
        await r.delete("NEWS_LOCK:STATE")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Redis error: {exc}") from exc
    return {"news_lock": False, "disabled_at": datetime.now(UTC).isoformat()}


@router.get("/news-lock/status")
async def news_lock_status() -> dict[str, Any]:
    r: aioredis.Redis = await get_async_redis()
    locked, reason = await _is_news_locked(r)
    return {
        "news_lock": locked,
        "reason": reason,
        "timestamp": datetime.now(UTC).isoformat(),
    }
