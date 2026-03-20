"""
Dead Letter Queue for rejected / duplicate ticks.

Instead of silently discarding rejected ticks, this module pushes them into a
Redis Stream (``ingest:tick:dlq``) so they can be inspected, replayed, or
analysed offline.

Design:
- Async push (non-blocking); if Redis is unavailable the tick is still logged.
- Each DLQ entry carries: symbol, price, timestamp, reason, raw payload hash.
- Stream is capped at ``maxlen`` to prevent unbounded growth.
- A convenience ``drain()`` async generator is provided for consumer tooling.

Zone: ingest/ — no analysis or execution side effects.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

__all__ = ["TickDeadLetterQueue", "init_dlq", "get_dlq", "_reset_dlq", "DLQ_STREAM_KEY", "DLQ_MAX_LEN"]

# Redis key & retention
DLQ_STREAM_KEY = "ingest:tick:dlq"
DLQ_MAX_LEN = 50_000  # approx cap — Redis MAXLEN is approximate by default


class TickDeadLetterQueue:
    """Async dead-letter queue backed by a Redis Stream."""

    def __init__(self, redis: Redis, *, stream_key: str = DLQ_STREAM_KEY, maxlen: int = DLQ_MAX_LEN) -> None:
        super().__init__()
        self._redis = redis
        self._stream_key = stream_key
        self._maxlen = maxlen

    # ── Produce ───────────────────────────────────────────────────

    async def push(
        self,
        *,
        symbol: str,
        price: float,
        exchange_ts: float,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Push a rejected tick onto the DLQ stream.

        Returns the Redis stream message ID on success, or None if the push
        failed (logged but not raised — DLQ must never block ingest).
        """
        payload: dict[str, str] = {
            "symbol": symbol,
            "price": str(price),
            "exchange_ts": str(exchange_ts),
            "reason": reason,
            "ingest_ts": str(time.time()),
            "payload_hash": hashlib.sha256(
                f"{symbol}:{price}:{exchange_ts}".encode()
            ).hexdigest()[:16],
        }
        if details:
            payload["details"] = json.dumps(details, default=str)

        try:
            msg_id: bytes | str = await self._redis.xadd(
                self._stream_key,
                payload,  # type: ignore[arg-type]
                maxlen=self._maxlen,
                approximate=True,
            )
            return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        except Exception:
            logger.warning(
                "DLQ push failed — tick dropped",
                extra={"symbol": symbol, "reason": reason},
                exc_info=True,
            )
            return None

    # ── Consume (for analysis tooling) ────────────────────────────

    async def length(self) -> int:
        """Return approximate number of entries in the DLQ stream."""
        try:
            return await self._redis.xlen(self._stream_key)
        except Exception:
            return 0

    async def peek(self, count: int = 10) -> list[dict[str, Any]]:
        """Return the *count* oldest DLQ entries without consuming them."""
        try:
            raw = await self._redis.xrange(self._stream_key, count=count)
            return [
                {"id": mid.decode() if isinstance(mid, bytes) else mid, **{
                    (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                    for k, v in fields.items()
                }}
                for mid, fields in raw
            ]
        except Exception:
            logger.warning("DLQ peek failed", exc_info=True)
            return []

    async def trim(self, maxlen: int | None = None) -> None:
        """Manually trim the DLQ stream to *maxlen* entries."""
        target = maxlen if maxlen is not None else self._maxlen
        try:
            await self._redis.xtrim(self._stream_key, maxlen=target, approximate=True)
        except Exception:
            logger.warning("DLQ trim failed", exc_info=True)


# ── Module-level singleton (set during startup) ──────────────────
_dlq_instance: TickDeadLetterQueue | None = None


def init_dlq(redis: Redis) -> TickDeadLetterQueue:
    """Initialise and return the global DLQ singleton."""
    global _dlq_instance
    _dlq_instance = TickDeadLetterQueue(redis)
    return _dlq_instance


def get_dlq() -> TickDeadLetterQueue | None:
    """Return the current DLQ singleton, or None if not initialised."""
    return _dlq_instance


def _reset_dlq() -> None:
    """Reset the DLQ singleton to None. **Test-only helper.**"""
    global _dlq_instance
    _dlq_instance = None
