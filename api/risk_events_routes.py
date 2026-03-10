"""
TUYUL FX Wolf-15 — Risk Event Log Routes
=========================================
ENDPOINT:
  GET /api/v1/risk/events          → Risk event log (blocked trades, SL breach, news lock)
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis as redis_lib
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from api.middleware.auth import verify_token
from infrastructure.redis_client import get_async_redis

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["risk-events"],
    dependencies=[Depends(verify_token)],
)


def _get_redis() -> None:
    """DEPRECATED — use ``get_async_redis`` FastAPI dependency instead."""
    raise NotImplementedError(
        "_get_redis() is removed. Inject via Depends(get_async_redis)."
    )


# ─── Risk Event types ─────────────────────────────────────────────────────────

RISK_EVENT_TYPES = (
    "TRADE_BLOCKED",
    "SL_BREACH",
    "NEWS_LOCK",
    "CIRCUIT_BREAKER_OPEN",
    "CIRCUIT_BREAKER_CLOSE",
    "DAILY_LIMIT_HIT",
    "TOTAL_LIMIT_HIT",
    "PROP_FIRM_VIOLATION",
    "LOT_CAP_APPLIED",
    "DD_MULTIPLIER_APPLIED",
)


# ─── Endpoint: Risk Events Log ────────────────────────────────────────────────

@router.get("/risk/events")
async def risk_events(
    account_id: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    hours_back: int = Query(default=24, ge=1, le=168),
) -> dict:
    """
    Risk event log for the Risk Monitor page.
    Events written to Redis by RiskEngine, PropFirmGuard, CircuitBreaker.

    Frontend: Risk Monitor page → Risk Event Log panel
    """
    r: aioredis.Redis = await get_async_redis()
    events: list[dict] = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    try:
        pattern = (
            f"RISK_EVENT:{account_id}:*"
            if account_id
            else "RISK_EVENT:*"
        )
        async for key in r.scan_iter(pattern):
            raw = await r.get(key)
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Filter by event_type
            if event_type and ev.get("type") != event_type:
                continue

            # Filter by time
            ts_str = ev.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except ValueError:
                    pass

            events.append(ev)
    except Exception as exc:
        logger.warning("Redis risk events scan failed: %s", exc)

    # Sort newest first
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    events = events[:limit]

    # Summary counts
    summary: dict[str, int] = {}
    for ev in events:
        t = ev.get("type", "UNKNOWN")
        summary[t] = summary.get(t, 0) + 1

    return {
        "account_id": account_id,
        "hours_back": hours_back,
        "total": len(events),
        "summary": summary,
        "events": events,
    }


# ─── Helper: Write a risk event (called by RiskEngine / PropFirmGuard) ────────

def write_risk_event(
    r: redis_lib.Redis,
    account_id: str,
    event_type: str,
    severity: str,
    message: str,
    metadata: Optional[dict] = None,
) -> None:
    """
    Called internally by risk components to log events.
    Key format: RISK_EVENT:{account_id}:{timestamp_ms}
    """
    now = datetime.now(timezone.utc)
    event_id = f"{account_id}:{int(now.timestamp() * 1000)}"
    event = {
        "event_id": event_id,
        "account_id": account_id,
        "type": event_type,
        "severity": severity,
        "message": message,
        "metadata": metadata or {},
        "timestamp": now.isoformat(),
    }
    try:
        r.set(f"RISK_EVENT:{event_id}", json.dumps(event), ex=604800)  # 7 days
    except Exception as exc:
        logger.warning("Failed to write risk event: %s", exc)


# NOTE: GET /api/v1/risk/{account_id}/snapshot is served by risk/risk_router.py
# (handler: get_account_snapshot via RiskEngineV2). Do NOT re-define it here.
