from __future__ import annotations

import asyncio
import contextlib
import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from loguru import logger

from infrastructure.redis_client import get_client
from storage.postgres_client import PostgresClient, pg_client

TRADE_OUTBOX_STREAM = "trade:outbox"
TRADE_OUTBOX_GROUP = "trade-outbox-workers"


@dataclass(frozen=True)
class OutboxEvent:
    outbox_id: str
    trade_id: str
    event_type: str
    topic: str
    payload: dict[str, Any]


class TradeOutboxWorker:
    """Separate outbox worker for re-delivery and durable DB-backed retries."""

    def __init__(
        self,
        *,
        consumer_name: str = "worker-1",
        poll_interval_sec: float = 1.0,
        max_batch: int = 50,
        pg: PostgresClient | None = None,
    ) -> None:
        super().__init__()
        self._consumer_name = consumer_name
        self._poll_interval = poll_interval_sec
        self._max_batch = max_batch
        self._pg = pg or pg_client
        self._stopped = asyncio.Event()

    async def stop(self) -> None:
        self._stopped.set()

    async def run(self) -> None:
        redis = await get_client()
        await self._ensure_group(redis)

        while not self._stopped.is_set():
            processed = 0
            with contextlib.suppress(Exception):
                processed += await self._consume_stream(redis)
            with contextlib.suppress(Exception):
                processed += await self._relay_db_pending()

            if processed == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval)

    async def _ensure_group(self, redis: Any) -> None:
        try:
            await redis.xgroup_create(
                TRADE_OUTBOX_STREAM,
                TRADE_OUTBOX_GROUP,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                logger.warning("Outbox worker group init failed: {}", exc)

    async def _consume_stream(self, redis: Any) -> int:
        items = await redis.xreadgroup(
            TRADE_OUTBOX_GROUP,
            self._consumer_name,
            {TRADE_OUTBOX_STREAM: ">"},
            count=self._max_batch,
            block=1000,
        )
        if not items:
            return 0

        processed = 0
        for stream_name, entries in items:
            _ = stream_name
            for entry_id, fields in entries:
                event = self._parse_stream_event(fields)
                if event is None:
                    await redis.xack(TRADE_OUTBOX_STREAM, TRADE_OUTBOX_GROUP, entry_id)
                    await redis.xdel(TRADE_OUTBOX_STREAM, entry_id)
                    continue

                ok, err = await self._deliver_event(event)
                if ok:
                    await self._mark_db_published(event)
                else:
                    await self._mark_db_retry(event, err)

                await redis.xack(TRADE_OUTBOX_STREAM, TRADE_OUTBOX_GROUP, entry_id)
                await redis.xdel(TRADE_OUTBOX_STREAM, entry_id)
                processed += 1

        return processed

    _db_table_missing_warned: bool = False

    async def _relay_db_pending(self) -> int:
        if not self._pg.is_available:
            return 0

        try:
            rows = await self._pg.fetch(
                """
                SELECT outbox_id, trade_id, event_type, topic, payload
                FROM trade_outbox
                WHERE status = 'PENDING'
                  AND next_attempt_at <= NOW()
                ORDER BY created_at ASC
                LIMIT $1
                """,
                self._max_batch,
            )
        except Exception as exc:
            if "does not exist" in str(exc):
                if not self._db_table_missing_warned:
                    logger.warning(
                        "trade_outbox table missing — run 'alembic upgrade head'. "
                        "DB-backed outbox relay disabled until table is created."
                    )
                    self._db_table_missing_warned = True
                return 0
            raise

        processed = 0
        for row in rows:
            event = OutboxEvent(
                outbox_id=str(row["outbox_id"]),
                trade_id=str(row["trade_id"]),
                event_type=str(row["event_type"]),
                topic=str(row["topic"]),
                payload=dict(row["payload"] or {}),
            )
            ok, err = await self._deliver_event(event)
            if ok:
                await self._mark_db_published(event)
            else:
                await self._mark_db_retry(event, err)
            processed += 1

        return processed

    async def _deliver_event(self, event: OutboxEvent) -> tuple[bool, str | None]:
        try:
            from api.ws_routes import publish_live_update  # noqa: PLC0415

            payload_obj = event.payload.get("trade")
            payload = (
                cast(dict[str, Any], payload_obj)
                if isinstance(payload_obj, dict)
                else event.payload
            )
            await publish_live_update(event.topic, cast(dict[str, object], payload))
            return True, None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Outbox delivery failed outbox_id={} topic={} error={}",
                event.outbox_id,
                event.topic,
                exc,
            )
            return False, str(exc)

    async def _mark_db_published(self, event: OutboxEvent) -> None:
        if not self._pg.is_available:
            return
        await self._pg.execute(
            """
            UPDATE trade_outbox
            SET status = 'PUBLISHED',
                published_at = NOW(),
                updated_at = NOW(),
                last_error = NULL
            WHERE outbox_id = $1
            """,
            event.outbox_id,
        )

    async def _mark_db_retry(self, event: OutboxEvent, error: str | None) -> None:
        if not self._pg.is_available:
            return

        row_raw = await self._pg.fetchrow(
            "SELECT attempts FROM trade_outbox WHERE outbox_id = $1",
            event.outbox_id,
        )
        row = cast(dict[str, Any], row_raw) if isinstance(row_raw, dict) else {}
        attempts = int(row.get("attempts", 0) or 0) + 1
        base = min(300, 2 ** min(attempts, 8))
        jitter = random.uniform(0.0, max(0.1, base * 0.2))
        next_attempt = datetime.now(UTC) + timedelta(seconds=(base + jitter))

        await self._pg.execute(
            """
            UPDATE trade_outbox
            SET attempts = $2,
                next_attempt_at = $3,
                updated_at = NOW(),
                last_error = $4
            WHERE outbox_id = $1
            """,
            event.outbox_id,
            attempts,
            next_attempt,
            (error or "DELIVERY_FAILED")[:2000],
        )

    @staticmethod
    def _parse_stream_event(fields: dict[str, Any]) -> OutboxEvent | None:
        raw = fields.get("event")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        if not isinstance(raw, str) or not raw.strip():
            return None

        try:
            obj = json.loads(raw)
        except Exception:  # noqa: BLE001
            return None

        if not isinstance(obj, dict):
            return None

        obj_dict = cast(dict[str, Any], obj)
        payload_raw = obj_dict.get("payload")
        payload = cast(dict[str, Any], payload_raw) if isinstance(payload_raw, dict) else {}
        trade_obj = payload.get("trade")
        trade_dict = cast(dict[str, Any], trade_obj) if isinstance(trade_obj, dict) else {}
        trade_id = str(payload.get("trade_id") or trade_dict.get("trade_id") or "")

        return OutboxEvent(
            outbox_id=str(obj_dict.get("outbox_id") or ""),
            trade_id=trade_id,
            event_type=str(obj_dict.get("event_type") or ""),
            topic=str(obj_dict.get("topic") or "trade_lifecycle"),
            payload=payload,
        )
