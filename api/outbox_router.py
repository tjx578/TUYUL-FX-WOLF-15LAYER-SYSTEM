from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.middleware.governance import enforce_write_policy
from storage.postgres_client import pg_client

from .middleware.auth import verify_token

router = APIRouter(
    prefix="/api/v1/outbox",
    tags=["outbox-admin"],
    dependencies=[Depends(verify_token)],
)

RETRY_BATCH_SAFETY_CAP = 200


class RetryOutboxBatchRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=1000)
    status_filter: str = Field(default="PENDING", pattern="^(PENDING|PUBLISHED)$")
    trade_id: str | None = Field(default=None, min_length=1, max_length=100)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)


def _normalize_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        row_dict = cast(dict[str, Any], row)
        return dict(row_dict)
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row}
    return {}


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _serialize_outbox_row(row: Any) -> dict[str, Any]:
    item = _normalize_row(row)
    return {
        "outbox_id": str(item.get("outbox_id") or ""),
        "outbox_key": str(item.get("outbox_key") or ""),
        "trade_id": str(item.get("trade_id") or ""),
        "event_type": str(item.get("event_type") or ""),
        "topic": str(item.get("topic") or ""),
        "status": str(item.get("status") or ""),
        "attempts": int(item.get("attempts") or 0),
        "last_error": item.get("last_error"),
        "next_attempt_at": _to_iso(item.get("next_attempt_at")),
        "published_at": _to_iso(item.get("published_at")),
        "created_at": _to_iso(item.get("created_at")),
        "updated_at": _to_iso(item.get("updated_at")),
    }


def _to_publish_payload(payload: Any) -> dict[str, object]:
    payload_dict = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
    payload_trade = payload_dict.get("trade")
    if isinstance(payload_trade, dict):
        return cast(dict[str, object], payload_trade)
    return cast(dict[str, object], payload_dict)


async def _replay_outbox_row(row: Any) -> dict[str, Any]:
    row_dict = _normalize_row(row)
    outbox_id = str(row_dict.get("outbox_id") or "")

    if str(row_dict.get("status") or "") == "PUBLISHED":
        return {
            "outbox_id": outbox_id,
            "replayed": False,
            "status": "PUBLISHED",
            "reason": "ALREADY_PUBLISHED",
        }

    try:
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update(
            str(row_dict.get("topic") or "trade_lifecycle"),
            _to_publish_payload(row_dict.get("payload") or {}),
        )
        await pg_client.execute(
            """
            UPDATE trade_outbox
            SET status = 'PUBLISHED',
                published_at = NOW(),
                updated_at = NOW(),
                last_error = NULL
            WHERE outbox_id = $1
            """,
            outbox_id,
        )
        return {
            "outbox_id": outbox_id,
            "replayed": True,
            "status": "PUBLISHED",
        }
    except Exception as exc:  # noqa: BLE001
        attempts = int(row_dict.get("attempts", 0) or 0) + 1
        delay = min(300.0, 2 ** min(attempts, 8)) + random.uniform(0.0, 0.25)
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        await pg_client.execute(
            """
            UPDATE trade_outbox
            SET status = 'PENDING',
                attempts = $2,
                last_error = $3,
                next_attempt_at = $4,
                updated_at = NOW()
            WHERE outbox_id = $1
            """,
            outbox_id,
            attempts,
            str(exc)[:2000],
            next_attempt_at,
        )
        return {
            "outbox_id": outbox_id,
            "replayed": False,
            "status": "PENDING",
            "attempts": attempts,
            "next_attempt_at": next_attempt_at.isoformat(),
            "error": str(exc),
        }


@router.get("/pending")
async def list_pending_outbox(
    limit: int = Query(default=100, ge=1, le=500),
    status_filter: str = Query(default="PENDING", pattern="^(PENDING|PUBLISHED)$"),
    trade_id: str | None = Query(default=None, min_length=1),
    event_type: str | None = Query(default=None, min_length=1),
) -> dict[str, Any]:
    """Inspect trade_outbox items for admin troubleshooting."""
    if not pg_client.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL unavailable",
        )

    rows = await pg_client.fetch(
        """
        SELECT outbox_id, outbox_key, trade_id, event_type, topic,
               status, attempts, last_error, next_attempt_at,
               published_at, created_at, updated_at
        FROM trade_outbox
        WHERE status = $1
          AND ($2::text IS NULL OR trade_id = $2)
          AND ($3::text IS NULL OR event_type = $3)
        ORDER BY next_attempt_at ASC, created_at ASC
        LIMIT $4
        """,
        status_filter,
        trade_id,
        event_type,
        limit,
    )

    items = [_serialize_outbox_row(row) for row in rows]

    return {
        "status": status_filter,
        "trade_id": trade_id,
        "event_type": event_type,
        "count": len(items),
        "items": items,
    }


@router.post("/retry/{outbox_id}", dependencies=[Depends(enforce_write_policy)])
async def retry_outbox_event(outbox_id: str) -> dict[str, Any]:
    """Replay one outbox event now; keep retry schedule if publish fails."""
    if not pg_client.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL unavailable",
        )

    row = await pg_client.fetchrow(
        """
        SELECT outbox_id, trade_id, event_type, topic, payload, status, attempts
        FROM trade_outbox
        WHERE outbox_id = $1
        """,
        outbox_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Outbox not found: {outbox_id}")

    return await _replay_outbox_row(row)


@router.post("/retry-batch", dependencies=[Depends(enforce_write_policy)])
async def retry_outbox_batch(body: RetryOutboxBatchRequest) -> dict[str, Any]:
    """Replay pending outbox events in batch with a hard safety cap."""
    if not pg_client.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL unavailable",
        )

    requested_limit = body.limit
    effective_limit = min(requested_limit, RETRY_BATCH_SAFETY_CAP)
    rows = await pg_client.fetch(
        """
        SELECT outbox_id, trade_id, event_type, topic, payload, status, attempts
        FROM trade_outbox
        WHERE status = $1
          AND ($2::text IS NULL OR trade_id = $2)
          AND ($3::text IS NULL OR event_type = $3)
        ORDER BY next_attempt_at ASC, created_at ASC
        LIMIT $4
        """,
        body.status_filter,
        body.trade_id,
        body.event_type,
        effective_limit,
    )

    results: list[dict[str, Any]] = []
    replayed = 0
    failed = 0
    skipped = 0
    for row in rows:
        result = await _replay_outbox_row(row)
        results.append(result)
        if result.get("replayed") is True:
            replayed += 1
        elif result.get("reason") == "ALREADY_PUBLISHED":
            skipped += 1
        else:
            failed += 1

    return {
        "requested_limit": requested_limit,
        "applied_limit": effective_limit,
        "safety_cap": RETRY_BATCH_SAFETY_CAP,
        "capped": requested_limit > RETRY_BATCH_SAFETY_CAP,
        "status_filter": body.status_filter,
        "trade_id": body.trade_id,
        "event_type": body.event_type,
        "count": len(results),
        "replayed": replayed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


@router.get("/{outbox_id}")
async def get_outbox_detail(outbox_id: str) -> dict[str, Any]:
    """Return details for one outbox record."""
    if not pg_client.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL unavailable",
        )

    row = await pg_client.fetchrow(
        """
        SELECT outbox_id, outbox_key, trade_id, event_type, topic,
               payload, status, attempts, last_error, next_attempt_at,
               published_at, created_at, updated_at
        FROM trade_outbox
        WHERE outbox_id = $1
        """,
        outbox_id,
    )

    if row is None:
        raise HTTPException(status_code=404, detail=f"Outbox not found: {outbox_id}")

    item = _serialize_outbox_row(row)
    item["payload"] = _normalize_row(row).get("payload")
    return item
