"""Redis -> PostgreSQL write-behind service for durable state backup."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from loguru import logger

from infrastructure.redis_client import get_client
from storage.postgres_client import PostgresClient, pg_client
from storage.redis_client import RedisClient


@runtime_checkable
class AsyncRedisClient(Protocol):
    """Minimal async Redis client interface required by _sync_trade_ledger."""

    async def scan(
        self,
        cursor: int = 0,
        match: str | None = None,
        count: int | None = None,
        **kwargs: Any,
    ) -> tuple[int, list[Any]]: ...

    async def get(self, name: str) -> str | bytes | None: ...


class PersistenceSync:
    """Background sync service for key risk/trade data."""

    def __init__(
        self,
        interval_sec: float = 30.0,
        pg: PostgresClient | None = None,
        redis: RedisClient | None = None,
        async_redis_client: AsyncRedisClient | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._redis = redis or RedisClient()
        self._async_redis_client = async_redis_client
        self._interval_sec = interval_sec
        self._running = False

    async def run(self) -> None:
        """Run periodic sync loop until stopped."""
        if not self._pg.is_available:
            logger.info("PostgreSQL not available; persistence sync disabled")
            return

        self._running = True
        logger.info(f"Persistence sync started (interval={self._interval_sec}s)")

        while self._running:
            try:
                await self._sync_risk_snapshots()
                await self._sync_trade_ledger()
            except Exception as exc:
                logger.error(f"Persistence sync cycle failed: {exc}")
                # Evict dead pool connections so next cycle gets a fresh one
                try:
                    if hasattr(self._pg, "_pool") and self._pg._pool is not None:
                        await self._pg._pool.expire_connections()
                except Exception:
                    pass
            await asyncio.sleep(self._interval_sec)

    async def stop(self) -> None:
        """Stop background sync loop."""
        self._running = False

    async def _sync_risk_snapshots(self) -> None:
        now = datetime.now(UTC)

        drawdown = self._collect_drawdown_state()
        if drawdown:
            await self._pg.execute(
                """
                INSERT INTO risk_snapshots (snapshot_type, account_id, state_data, created_at)
                VALUES ($1, $2, $3::jsonb, $4)
                """,
                "DRAWDOWN",
                drawdown.get("account_id", "default"),
                json.dumps(drawdown),
                now,
            )

        cb = self._collect_circuit_breaker_state()
        if cb:
            await self._pg.execute(
                """
                INSERT INTO risk_snapshots (snapshot_type, account_id, state_data, created_at)
                VALUES ($1, $2, $3::jsonb, $4)
                """,
                "CIRCUIT_BREAKER",
                cb.get("account_id", "default"),
                json.dumps(cb),
                now,
            )

    def _collect_drawdown_state(self) -> dict[str, Any]:
        daily = self._redis.get("wolf15:drawdown:daily")
        weekly = self._redis.get("wolf15:drawdown:weekly")
        total = self._redis.get("wolf15:drawdown:total")
        peak = self._redis.get("wolf15:peak_equity")

        if not any([daily, weekly, total, peak]):
            return {}

        return {
            "account_id": "default",
            "daily_dd": float(daily or 0.0),
            "weekly_dd": float(weekly or 0.0),
            "total_dd": float(total or 0.0),
            "peak_equity": float(peak or 0.0),
            "collected_at": datetime.now(UTC).isoformat(),
        }

    def _collect_circuit_breaker_state(self) -> dict[str, Any]:
        state = self._redis.get("wolf15:circuit_breaker:state")
        data = self._redis.get("wolf15:circuit_breaker:data")
        consecutive = self._redis.get("wolf15:consecutive_losses")

        if not state:
            return {}

        return {
            "account_id": "default",
            "state": state,
            "data": data,
            "consecutive_losses": int(consecutive or 0),
            "collected_at": datetime.now(UTC).isoformat(),
        }

    async def _sync_trade_ledger(self) -> None:
        if self._async_redis_client is not None:
            client: AsyncRedisClient = self._async_redis_client
        else:
            client = await get_client()  # type: ignore[assignment]  # redis.asyncio.Redis ResponseT
        for pattern in ("TRADE:*", "wolf15:TRADE:*"):
            cursor = 0
            while True:
                cursor, keys = await client.scan(cursor=cursor, match=pattern, count=50)
                for key in keys:
                    trade_payload = await client.get(key)
                    if not trade_payload:
                        continue
                    trade_data = json.loads(trade_payload)
                    await self._upsert_trade(trade_data)
                if cursor == 0:
                    break

    async def _upsert_trade(self, trade: dict[str, Any]) -> None:
        trade_id = trade.get("trade_id")
        if not trade_id:
            return

        created_at = _as_datetime(trade.get("created_at"))
        updated_at = _as_datetime(trade.get("updated_at"))
        closed_at = _as_datetime(trade.get("closed_at"))

        await self._pg.execute(
            """
            INSERT INTO trade_history (
                trade_id, signal_id, account_id, pair, direction, status, risk_mode,
                total_risk_percent, total_risk_amount, pnl, close_reason, legs,
                metadata, created_at, updated_at, closed_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12::jsonb,
                $13::jsonb, $14, $15, $16
            )
            ON CONFLICT (trade_id) DO UPDATE SET
                status = EXCLUDED.status,
                pnl = EXCLUDED.pnl,
                close_reason = EXCLUDED.close_reason,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at,
                closed_at = EXCLUDED.closed_at
            """,
            trade_id,
            trade.get("signal_id", ""),
            trade.get("account_id", ""),
            trade.get("pair", ""),
            trade.get("direction", ""),
            trade.get("status", ""),
            trade.get("risk_mode", ""),
            float(trade.get("total_risk_percent", 0.0) or 0.0),
            float(trade.get("total_risk_amount", 0.0) or 0.0),
            trade.get("pnl"),
            trade.get("close_reason"),
            json.dumps(trade.get("legs", [])),
            json.dumps(trade.get("metadata", {})),
            created_at,
            updated_at,
            closed_at,
        )

    async def log_event(
        self,
        event_type: str,
        account_id: str | None = None,
        severity: str = "INFO",
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Write system event directly to PostgreSQL."""
        if not self._pg.is_available:
            return
        await self._pg.execute(
            """
            INSERT INTO system_events (event_type, account_id, severity, payload)
            VALUES ($1, $2, $3, $4::jsonb)
            """,
            event_type,
            account_id,
            severity,
            json.dumps(payload or {}),
        )

    async def recover_from_postgres(self) -> bool:
        """Recover key state from latest PostgreSQL snapshots."""
        if not self._pg.is_available:
            return False

        drawdown_row = await self._pg.fetchrow(
            """
            SELECT state_data FROM risk_snapshots
            WHERE snapshot_type = 'DRAWDOWN'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if drawdown_row:
            drawdown_data = _load_state_json(drawdown_row["state_data"])
            self._redis.set("wolf15:drawdown:daily", str(drawdown_data.get("daily_dd", 0.0)))
            self._redis.set("wolf15:drawdown:weekly", str(drawdown_data.get("weekly_dd", 0.0)))
            self._redis.set("wolf15:drawdown:total", str(drawdown_data.get("total_dd", 0.0)))
            self._redis.set("wolf15:peak_equity", str(drawdown_data.get("peak_equity", 0.0)))

        cb_row = await self._pg.fetchrow(
            """
            SELECT state_data FROM risk_snapshots
            WHERE snapshot_type = 'CIRCUIT_BREAKER'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        if cb_row:
            cb_data = _load_state_json(cb_row["state_data"])
            self._redis.set("wolf15:circuit_breaker:state", cb_data.get("state", "CLOSED"))
            self._redis.set("wolf15:circuit_breaker:data", cb_data.get("data", "|0"))
            self._redis.set(
                "wolf15:consecutive_losses",
                str(cb_data.get("consecutive_losses", 0)),
            )

        trades = await self._pg.fetch(
            """
            SELECT * FROM trade_history
            WHERE status NOT IN ('CLOSED', 'CANCELLED', 'SKIPPED', 'ABORTED')
            ORDER BY created_at DESC
            """
        )
        for trade in trades:
            key = f"wolf15:TRADE:{trade['trade_id']}"
            payload = dict(trade)
            for field, value in list(payload.items()):
                if isinstance(value, datetime):
                    payload[field] = value.isoformat()
            self._redis.set(key, json.dumps(payload))

        # ── Candle history recovery ──────────────────────────────────────
        # When Redis candle lists are empty (post-restart with no WS data),
        # pull recent candles from the ohlc_candles table so the engine has
        # warmup data immediately instead of waiting for live candle completion.
        candle_count = await self._recover_candle_history()

        logger.info(
            "PostgreSQL recovery complete; active trades=%d, candle keys=%d",
            len(trades),
            candle_count,
        )
        return True

    async def _recover_candle_history(self) -> int:
        """Recover candle history from ohlc_candles table into Redis lists.

        Only writes if the target Redis list is empty (avoids overwriting
        fresh data from the ingest warmup path).

        Returns the number of symbol/timeframe combos recovered.
        """
        if not self._pg.is_available:
            return 0

        try:
            rows = await self._pg.fetch(
                """
                SELECT symbol, timeframe, open_time, close_time,
                       open, high, low, close, volume, tick_count
                FROM ohlc_candles
                WHERE open_time > NOW() - INTERVAL '7 days'
                ORDER BY symbol, timeframe, open_time ASC
                """
            )
        except Exception as exc:
            logger.warning("Candle history recovery query failed: %s", exc)
            return 0

        if not rows:
            return 0

        # Group rows by (symbol, timeframe)
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            sym = row["symbol"]
            tf = row["timeframe"]
            candle_dict = {
                "symbol": sym,
                "timeframe": tf,
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "tick_count": row["tick_count"],
                "timestamp": row["open_time"].isoformat()
                if isinstance(row["open_time"], datetime)
                else str(row["open_time"]),
            }
            grouped.setdefault((sym, tf), []).append(json.dumps(candle_dict))

        recovered = 0
        for (sym, tf), candle_jsons in grouped.items():
            key = f"wolf15:candle_history:{sym}:{tf}"
            try:
                existing: int = self._redis.client.llen(key)  # type: ignore[assignment]  # sync Redis
                if existing > 0:
                    continue  # Don't overwrite data already seeded by ingest

                for i in range(0, len(candle_jsons), 50):
                    chunk = candle_jsons[i : i + 50]
                    self._redis.client.rpush(key, *chunk)
                self._redis.client.ltrim(key, -300, -1)
                recovered += 1
                logger.debug("[PG Recovery] %s: %d candles restored", key, len(candle_jsons))
            except Exception as exc:
                logger.warning("[PG Recovery] Failed for %s: %s", key, exc)

        if recovered:
            logger.info("[PG Recovery] Restored candle history for %d symbol/tf combos", recovered)
        return recovered


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(UTC)


def _load_state_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return {}
