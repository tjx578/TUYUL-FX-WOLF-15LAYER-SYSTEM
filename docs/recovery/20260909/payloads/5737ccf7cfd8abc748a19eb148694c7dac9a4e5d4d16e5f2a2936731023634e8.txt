"""
TUYUL FX Wolf-15 — Risk Event Log Routes
=========================================
NEW ENDPOINT:
  GET /api/v1/risk/events          → Risk event log (blocked trades, SL breach, news lock)
  GET /api/v1/risk/{account_id}/snapshot  → (already exists, kept for completeness)
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, Query

from api.auth import verify_token
from infrastructure.redis_url import get_redis_url

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1",
    tags=["risk-events"],
    dependencies=[Depends(verify_token)],
)


def _get_redis() -> Optional[redis_lib.Redis]:
    url = get_redis_url()
    try:
        r = redis_lib.from_url(url, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


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
    r = _get_redis()
    events: list[dict] = []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    if r:
        try:
            pattern = (
                f"RISK_EVENT:{account_id}:*"
                if account_id
                else "RISK_EVENT:*"
            )
            for key in r.scan_iter(pattern):
                raw = r.get(key)
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


# ─── Endpoint: Risk Snapshot per account ─────────────────────────────────────

@router.get("/risk/{account_id}/snapshot")
async def risk_snapshot(account_id: str) -> dict:
    """
    Current risk state snapshot for an account.
    Frontend: Risk Monitor page → DrawdownGauge, CircuitBreaker badge.
    """
    r = _get_redis()
    snapshot: dict = {}

    if r:
        try:
            raw = r.get(f"RISK:SNAPSHOT:{account_id}")
            if raw:
                snapshot = json.loads(raw)
        except Exception as exc:
            logger.warning("Risk snapshot Redis error: %s", exc)

    # Fallback structure if nothing in Redis
    if not snapshot:
        snapshot = {
            "account_id": account_id,
            "daily_dd_percent": 0.0,
            "daily_dd_limit": 5.0,
            "total_dd_percent": 0.0,
            "open_risk_percent": 0.0,
            "open_trades": 0,
            "circuit_breaker": "CLOSED",
            "severity": "SAFE",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    snapshot["account_id"] = account_id
    return snapshot
