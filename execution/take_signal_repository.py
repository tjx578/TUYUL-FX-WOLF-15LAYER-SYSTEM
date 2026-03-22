"""
Take-Signal Repository — P1-1
==============================
Persistence layer for take-signal operational binding records.

Uses PostgreSQL (via asyncpg) as durable store with Redis as fast-path cache.
Falls back to in-memory store when PostgreSQL is unavailable (dev/test).

Zone: persistence — no market logic, no verdict mutation.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from execution.take_signal_models import (
    TakeSignalRecord,
    TakeSignalStatus,
    is_terminal,
    validate_transition,
)

_REDIS_PREFIX = "take_signal:"
_REDIS_IDEMPOTENCY_PREFIX = "take_signal:idem:"
_REDIS_TTL_SEC = 60 * 60 * 24 * 7  # 7 days


class TakeSignalRepository:
    """Manages take-signal record persistence.

    Dual-write: PostgreSQL (durable) + Redis (fast lookup/idempotency).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # In-memory fallback when both PG and Redis are unavailable
        self._memory: dict[str, dict[str, Any]] = {}
        self._idem_index: dict[str, str] = {}  # request_id -> take_id

    # ── Create ────────────────────────────────────────────────────────────────

    async def create(self, record: TakeSignalRecord) -> TakeSignalRecord:
        """Persist a new take-signal record.

        Returns the existing record if the request_id already exists (idempotent).
        Raises ValueError if request_id exists but payload differs.
        """
        existing = await self.get_by_request_id(record.request_id)
        if existing is not None:
            if (
                existing.signal_id != record.signal_id
                or existing.account_id != record.account_id
                or existing.ea_instance_id != record.ea_instance_id
            ):
                raise ValueError(
                    f"Idempotency conflict: request_id={record.request_id} "
                    f"already bound to take_id={existing.take_id} with different payload"
                )
            return existing

        data = record.model_dump(mode="json")

        # PostgreSQL durable write
        await self._pg_insert(data)

        # Redis fast-path cache
        self._redis_set(record.take_id, data)
        self._redis_set_idempotency(record.request_id, record.take_id)

        # In-memory fallback
        with self._lock:
            self._memory[record.take_id] = data
            self._idem_index[record.request_id] = record.take_id

        logger.info(
            "[TakeSignalRepo] Created take_id=%s request_id=%s signal=%s account=%s",
            record.take_id,
            record.request_id,
            record.signal_id,
            record.account_id,
        )
        return record

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, take_id: str) -> TakeSignalRecord | None:
        """Get a take-signal record by take_id."""
        # Try Redis first
        data = self._redis_get(take_id)
        if data is not None:
            return TakeSignalRecord.model_validate(data)

        # Try PostgreSQL
        data = await self._pg_fetch_one(take_id)
        if data is not None:
            self._redis_set(take_id, data)
            return TakeSignalRecord.model_validate(data)

        # In-memory fallback
        with self._lock:
            mem = self._memory.get(take_id)
            if mem is not None:
                return TakeSignalRecord.model_validate(mem)

        return None

    async def get_by_request_id(self, request_id: str) -> TakeSignalRecord | None:
        """Get a take-signal record by idempotency request_id."""
        # Try Redis idempotency index
        take_id = self._redis_get_idempotency(request_id)
        if take_id is not None:
            return await self.get(take_id)

        # Try PostgreSQL
        data = await self._pg_fetch_by_request_id(request_id)
        if data is not None:
            rec = TakeSignalRecord.model_validate(data)
            self._redis_set(rec.take_id, data)
            self._redis_set_idempotency(request_id, rec.take_id)
            return rec

        # In-memory fallback
        with self._lock:
            tid = self._idem_index.get(request_id)
            if tid is not None:
                mem = self._memory.get(tid)
                if mem is not None:
                    return TakeSignalRecord.model_validate(mem)

        return None

    # ── Update Status ─────────────────────────────────────────────────────────

    async def transition(
        self,
        take_id: str,
        new_status: TakeSignalStatus,
        *,
        reason: str | None = None,
        firewall_result_id: str | None = None,
        execution_intent_id: str | None = None,
    ) -> TakeSignalRecord:
        """Transition a take-signal record to a new status.

        Validates the transition against the state machine.
        Raises InvalidTakeSignalTransition if forbidden.
        Raises KeyError if take_id not found.
        """
        record = await self.get(take_id)
        if record is None:
            raise KeyError(f"take_id={take_id} not found")

        current = record.status
        if current == new_status and is_terminal(current):
            # Replay-safe: terminal → same terminal is a no-op
            return record

        validate_transition(current, new_status)

        now = datetime.now(UTC).isoformat()
        updates: dict[str, Any] = {
            "status": new_status.value,
            "updated_at": now,
        }
        if reason is not None:
            updates["status_reason"] = reason
        if firewall_result_id is not None:
            updates["firewall_result_id"] = firewall_result_id
        if execution_intent_id is not None:
            updates["execution_intent_id"] = execution_intent_id

        # Apply updates
        data = record.model_dump(mode="json")
        data.update(updates)

        # PostgreSQL durable write
        await self._pg_update(take_id, updates)

        # Redis cache
        self._redis_set(take_id, data)

        # In-memory
        with self._lock:
            if take_id in self._memory:
                self._memory[take_id].update(updates)

        updated = TakeSignalRecord.model_validate(data)
        logger.info(
            "[TakeSignalRepo] Transition take_id=%s %s -> %s reason=%s",
            take_id,
            current.value,
            new_status.value,
            reason,
        )
        return updated

    # ── PostgreSQL Persistence ────────────────────────────────────────────────

    async def _pg_insert(self, data: dict[str, Any]) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                INSERT INTO take_signal_records (
                    take_id, request_id, signal_id, account_id, ea_instance_id,
                    operator, reason, status, strategy_profile_id, metadata,
                    created_at, updated_at, status_reason,
                    firewall_result_id, execution_intent_id
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (request_id) DO NOTHING
                """,
                data["take_id"],
                data["request_id"],
                data["signal_id"],
                data["account_id"],
                data["ea_instance_id"],
                data["operator"],
                data["reason"],
                data["status"],
                data.get("strategy_profile_id"),
                json.dumps(data.get("metadata")) if data.get("metadata") else None,
                data["created_at"],
                data["updated_at"],
                data.get("status_reason"),
                data.get("firewall_result_id"),
                data.get("execution_intent_id"),
            )
        except Exception:
            logger.warning("[TakeSignalRepo] PG insert failed", exc_info=True)

    async def _pg_update(self, take_id: str, updates: dict[str, Any]) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            set_clauses = []
            args: list[Any] = []
            idx = 1
            for col, val in updates.items():
                set_clauses.append(f"{col} = ${idx}")
                args.append(val)
                idx += 1
            args.append(take_id)
            query = f"UPDATE take_signal_records SET {', '.join(set_clauses)} WHERE take_id = ${idx}"
            await pg_client.execute(query, *args)
        except Exception:
            logger.warning("[TakeSignalRepo] PG update failed", exc_info=True)

    async def _pg_fetch_one(self, take_id: str) -> dict[str, Any] | None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return None
            row = await pg_client.fetchrow("SELECT * FROM take_signal_records WHERE take_id = $1", take_id)
            return dict(row) if row else None
        except Exception:
            logger.warning("[TakeSignalRepo] PG fetch failed", exc_info=True)
            return None

    async def _pg_fetch_by_request_id(self, request_id: str) -> dict[str, Any] | None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return None
            row = await pg_client.fetchrow("SELECT * FROM take_signal_records WHERE request_id = $1", request_id)
            return dict(row) if row else None
        except Exception:
            logger.warning("[TakeSignalRepo] PG fetch by request_id failed", exc_info=True)
            return None

    # ── Redis Cache Layer ─────────────────────────────────────────────────────

    def _redis_set(self, take_id: str, data: dict[str, Any]) -> None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                f"{_REDIS_PREFIX}{take_id}",
                json.dumps(data),
                ex=_REDIS_TTL_SEC,
            )
        except Exception:
            pass

    def _redis_get(self, take_id: str) -> dict[str, Any] | None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            raw = redis_client.client.get(f"{_REDIS_PREFIX}{take_id}")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str) and raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    def _redis_set_idempotency(self, request_id: str, take_id: str) -> None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                f"{_REDIS_IDEMPOTENCY_PREFIX}{request_id}",
                take_id,
                ex=_REDIS_TTL_SEC,
            )
        except Exception:
            pass

    def _redis_get_idempotency(self, request_id: str) -> str | None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            raw = redis_client.client.get(f"{_REDIS_IDEMPOTENCY_PREFIX}{request_id}")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            return raw if isinstance(raw, str) and raw else None
        except Exception:
            return None

    # ── Schema Bootstrap ──────────────────────────────────────────────────────

    @staticmethod
    async def ensure_table() -> None:
        """Create the take_signal_records table if it does not exist."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS take_signal_records (
                    take_id             TEXT PRIMARY KEY,
                    request_id          TEXT NOT NULL UNIQUE,
                    signal_id           TEXT NOT NULL,
                    account_id          TEXT NOT NULL,
                    ea_instance_id      TEXT NOT NULL,
                    operator            TEXT NOT NULL,
                    reason              TEXT NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'PENDING',
                    strategy_profile_id TEXT,
                    metadata            JSONB,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    status_reason       TEXT,
                    firewall_result_id  TEXT,
                    execution_intent_id TEXT
                )
                """
            )
            await pg_client.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_take_signal_signal_id
                ON take_signal_records (signal_id)
                """
            )
            await pg_client.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_take_signal_account_id
                ON take_signal_records (account_id)
                """
            )
        except Exception:
            logger.warning("[TakeSignalRepo] Table creation failed", exc_info=True)
