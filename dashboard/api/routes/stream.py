"""
SSE streaming route for L12 verdicts.

The dashboard consumes verdicts **read-only**. This endpoint pushes
the latest Layer-12 verdicts every second. It never accepts decisions
from the client (constitutional boundary: dashboard cannot override L12).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

# ---------------------------------------------------------------------------
#  Verdict cache – thin abstraction over Redis / in-memory store
# ---------------------------------------------------------------------------

async def get_latest_verdicts() -> list[dict[str, Any]]:
    """
    Return the most recent L12 verdicts from the cache layer.

    Current implementation: tries Redis first, falls back to an
    in-memory snapshot.  Replace the body once your Redis client
    is wired in.
    """
    try:
        # --- Redis path (preferred) ---
        from dashboard.api.deps import (
            get_redis,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType] # noqa: WPS433
        )

        redis: Redis = await get_redis()  # type: ignore[assignment]
        raw = await redis.get("l12:verdicts:latest") # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        if raw is not None:
            data: str | bytes = raw if isinstance(raw, (str, bytes)) else str(raw) # pyright: ignore[reportUnknownArgumentType]
            return json.loads(data)
    except Exception:
        logger.debug("Redis unavailable – falling back to in-memory cache")

    # --- In-memory fallback (populated by verdict ingest worker) ---
    try:
        from dashboard.api.state import verdict_cache  # noqa: WPS433

        return list(verdict_cache.values())
    except ImportError:
        pass

    return []


# ---------------------------------------------------------------------------
#  SSE generator
# ---------------------------------------------------------------------------

async def _verdict_event_generator(
    request: Request,
    interval: float = 1.0,
) -> AsyncGenerator[str, None]:
    """
    Yield SSE frames containing the latest L12 verdicts.

    Stops cleanly when the client disconnects.
    """
    logger.info("SSE client connected: %s", request.client)

    try:
        while True:
            # Respect client disconnect
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", request.client)
                break

            verdicts = await get_latest_verdicts()

            # SSE format: "data: <json>\n\n"
            payload = json.dumps(verdicts, default=str)
            yield f"data: {payload}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", request.client)


# ---------------------------------------------------------------------------
#  Route
# ---------------------------------------------------------------------------

@router.get(
    "/stream/verdicts",
    summary="Live L12 verdict stream (SSE)",
    description=(
        "Server-Sent Events endpoint that pushes the latest Layer-12 "
        "verdicts every ~1 s. Dashboard is a **read-only** consumer; "
        "it MUST NOT send decisions back through this channel."
    ),
)
async def stream_verdicts(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _verdict_event_generator(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )
