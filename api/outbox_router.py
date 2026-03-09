from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy
from storage.postgres_client import pg_client

router = APIRouter(
    prefix="/api/v1/outbox",
    tags=["outbox-admin"],
    dependencies=[Depends(verify_token)],
)


@router.get("/pending")
async def list_pending_outbox(
    limit: int = Query(default=100, ge=1, le=500),
    status_filter: str = Query(default="PENDING", pattern="^(PENDING|PUBLISHED)$"),
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
        ORDER BY next_attempt_at ASC, created_at ASC
        LIMIT $2
        """,
        status_filter,
        limit,
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "outbox_id": str(row["outbox_id"]),
                "outbox_key": str(row["outbox_key"]),
                "trade_id": str(row["trade_id"]),
                "event_type": str(row["event_type"]),
                "topic": str(row["topic"]),
                "status": str(row["status"]),
                "attempts": int(row["attempts"]),
                "last_error": row["last_error"],
                "next_attempt_at": row["next_attempt_at"].isoformat() if row["next_attempt_at"] else None,
                "published_at": row["published_at"].isoformat() if row["published_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
        )

    return {
        "status": status_filter,
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

    row_dict = cast(dict[str, Any], row)
    if str(row_dict.get("status") or "") == "PUBLISHED":
        return {
            "outbox_id": outbox_id,
            "replayed": False,
            "status": "PUBLISHED",
            "reason": "ALREADY_PUBLISHED",
        }

    payload = cast(dict[str, Any], row_dict.get("payload") or {})
    payload_trade = payload.get("trade")
    publish_payload = cast(dict[str, object], payload_trade) if isinstance(payload_trade, dict) else cast(dict[str, object], payload)

    try:
        from api.ws_routes import publish_live_update  # noqa: PLC0415

        await publish_live_update(str(row_dict.get("topic") or "trade_lifecycle"), publish_payload)
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
