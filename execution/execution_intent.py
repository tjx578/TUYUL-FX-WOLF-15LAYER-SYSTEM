"""
Execution Intent and Lifecycle — P1-5
=======================================
Canonical execution intent record with full lifecycle persistence.

Intent truth and execution truth are separated but linked:
  - Intent: what was requested (from verdict + take-signal + firewall)
  - Execution: what actually happened (from broker/EA feedback)

States: INTENT_CREATED → ORDER_PLACED → ACKNOWLEDGED → FILLED
        ↘ REJECTED / CANCELLED / EXPIRED / UNRESOLVED

Provenance from signal/verdict/take/firewall is attached to every record.

Zone: execution — blind order placement authority, no strategy logic.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

# ── Execution Lifecycle States ────────────────────────────────────────────────


class ExecutionLifecycleState(StrEnum):
    """Canonical execution lifecycle states."""

    INTENT_CREATED = "INTENT_CREATED"
    ORDER_PLACED = "ORDER_PLACED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNRESOLVED = "UNRESOLVED"


TERMINAL_EXECUTION_STATES: frozenset[ExecutionLifecycleState] = frozenset(
    {
        ExecutionLifecycleState.REJECTED,
        ExecutionLifecycleState.FILLED,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.EXPIRED,
    }
)

VALID_EXECUTION_TRANSITIONS: dict[ExecutionLifecycleState, frozenset[ExecutionLifecycleState]] = {
    ExecutionLifecycleState.INTENT_CREATED: frozenset(
        {
            ExecutionLifecycleState.ORDER_PLACED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.EXPIRED,
        }
    ),
    ExecutionLifecycleState.ORDER_PLACED: frozenset(
        {
            ExecutionLifecycleState.ACKNOWLEDGED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.EXPIRED,
            ExecutionLifecycleState.UNRESOLVED,
        }
    ),
    ExecutionLifecycleState.ACKNOWLEDGED: frozenset(
        {
            ExecutionLifecycleState.PARTIALLY_FILLED,
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.EXPIRED,
            ExecutionLifecycleState.UNRESOLVED,
        }
    ),
    ExecutionLifecycleState.PARTIALLY_FILLED: frozenset(
        {
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.UNRESOLVED,
        }
    ),
    ExecutionLifecycleState.FILLED: frozenset(),
    ExecutionLifecycleState.REJECTED: frozenset(),
    ExecutionLifecycleState.CANCELLED: frozenset(),
    ExecutionLifecycleState.EXPIRED: frozenset(),
    ExecutionLifecycleState.UNRESOLVED: frozenset(
        {
            # Unresolved can be resolved to any terminal state after reconciliation
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.EXPIRED,
        }
    ),
}


class InvalidExecutionTransition(Exception):  # noqa: N818
    def __init__(self, from_state: ExecutionLifecycleState, to_state: ExecutionLifecycleState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Forbidden execution transition: {from_state} -> {to_state}")


def validate_execution_transition(
    from_state: ExecutionLifecycleState,
    to_state: ExecutionLifecycleState,
) -> None:
    allowed = VALID_EXECUTION_TRANSITIONS.get(from_state, frozenset())
    if to_state not in allowed:
        raise InvalidExecutionTransition(from_state, to_state)


# ── Execution Intent Record ──────────────────────────────────────────────────


class ExecutionIntentRecord(BaseModel):
    """Canonical record of an execution intent with full provenance."""

    model_config = ConfigDict(extra="forbid")

    execution_intent_id: str = Field(..., description="Unique execution intent ID")
    idempotency_key: str = Field(..., description="Correlation/idempotency key")

    # Provenance chain
    take_id: str = Field(..., description="Source take-signal ID")
    signal_id: str = Field(..., description="Source L12 signal ID")
    firewall_id: str = Field(..., description="Firewall result ID")
    account_id: str = Field(..., description="Target account ID")

    # Order details (from signal, not computed here)
    symbol: str = Field(default="")
    direction: str = Field(default="")
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit_1: float | None = None
    lot_size: float | None = None

    # Lifecycle
    state: ExecutionLifecycleState = ExecutionLifecycleState.INTENT_CREATED
    state_reason: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Execution truth (populated by broker/EA feedback)
    broker_order_id: str | None = None
    fill_price: float | None = None
    fill_time: str | None = None
    slippage: float | None = None
    actual_lot_size: float | None = None
    rejection_code: str | None = None


class ExecutionIntentResponse(BaseModel):
    """API-facing execution intent view."""

    model_config = ConfigDict(extra="forbid")

    execution_intent_id: str
    take_id: str
    signal_id: str
    firewall_id: str
    account_id: str
    symbol: str
    direction: str
    state: ExecutionLifecycleState
    state_reason: str | None = None
    created_at: str
    updated_at: str
    broker_order_id: str | None = None
    fill_price: float | None = None
    slippage: float | None = None


# ── Repository ────────────────────────────────────────────────────────────────


class ExecutionIntentRepository:
    """Persistence for execution intent records."""

    def __init__(self) -> None:
        self._memory: dict[str, dict[str, Any]] = {}
        self._idem_index: dict[str, str] = {}

    async def create(self, record: ExecutionIntentRecord) -> ExecutionIntentRecord:
        """Create or return existing (idempotent by idempotency_key)."""
        existing = await self.get_by_idempotency_key(record.idempotency_key)
        if existing is not None:
            return existing

        data = record.model_dump(mode="json")
        await self._pg_insert(data)
        self._cache_set(record.execution_intent_id, data)
        self._memory[record.execution_intent_id] = data
        self._idem_index[record.idempotency_key] = record.execution_intent_id

        logger.info(
            "[ExecIntentRepo] Created %s for take=%s signal=%s",
            record.execution_intent_id,
            record.take_id,
            record.signal_id,
        )
        return record

    async def get(self, execution_intent_id: str) -> ExecutionIntentRecord | None:
        cached = self._cache_get(execution_intent_id)
        if cached:
            return ExecutionIntentRecord.model_validate(cached)

        pg_data = await self._pg_fetch(execution_intent_id)
        if pg_data:
            self._cache_set(execution_intent_id, pg_data)
            return ExecutionIntentRecord.model_validate(pg_data)

        mem = self._memory.get(execution_intent_id)
        return ExecutionIntentRecord.model_validate(mem) if mem else None

    async def get_by_idempotency_key(self, key: str) -> ExecutionIntentRecord | None:
        eid = self._idem_index.get(key)
        if eid:
            return await self.get(eid)

        pg_data = await self._pg_fetch_by_idem(key)
        if pg_data:
            rec = ExecutionIntentRecord.model_validate(pg_data)
            self._idem_index[key] = rec.execution_intent_id
            self._cache_set(rec.execution_intent_id, pg_data)
            return rec
        return None

    async def transition(
        self,
        execution_intent_id: str,
        new_state: ExecutionLifecycleState,
        *,
        reason: str | None = None,
        broker_order_id: str | None = None,
        fill_price: float | None = None,
        fill_time: str | None = None,
        slippage: float | None = None,
        actual_lot_size: float | None = None,
        rejection_code: str | None = None,
    ) -> ExecutionIntentRecord:
        """Transition execution intent to a new lifecycle state."""
        record = await self.get(execution_intent_id)
        if record is None:
            raise KeyError(f"execution_intent_id={execution_intent_id} not found")

        current = record.state
        if current == new_state and new_state in TERMINAL_EXECUTION_STATES:
            return record  # replay-safe

        validate_execution_transition(current, new_state)

        now = datetime.now(UTC).isoformat()
        updates: dict[str, Any] = {"state": new_state.value, "updated_at": now}
        if reason is not None:
            updates["state_reason"] = reason
        if broker_order_id is not None:
            updates["broker_order_id"] = broker_order_id
        if fill_price is not None:
            updates["fill_price"] = fill_price
        if fill_time is not None:
            updates["fill_time"] = fill_time
        if slippage is not None:
            updates["slippage"] = slippage
        if actual_lot_size is not None:
            updates["actual_lot_size"] = actual_lot_size
        if rejection_code is not None:
            updates["rejection_code"] = rejection_code

        data = record.model_dump(mode="json")
        data.update(updates)

        await self._pg_update(execution_intent_id, updates)
        self._cache_set(execution_intent_id, data)
        self._memory[execution_intent_id] = data

        logger.info(
            "[ExecIntentRepo] Transition %s: %s -> %s reason=%s",
            execution_intent_id,
            current.value,
            new_state.value,
            reason,
        )
        return ExecutionIntentRecord.model_validate(data)

    async def list_by_state(
        self,
        state: ExecutionLifecycleState,
    ) -> list[ExecutionIntentRecord]:
        """List all execution intents in the given state (for reconciliation)."""
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if pg_client.is_available:
                rows = await pg_client.fetch(
                    "SELECT * FROM execution_intents WHERE state = $1",
                    state.value,
                )
                return [ExecutionIntentRecord.model_validate(dict(r)) for r in rows]
        except Exception:
            pass

        return [ExecutionIntentRecord.model_validate(v) for v in self._memory.values() if v.get("state") == state.value]

    # ── PostgreSQL ────────────────────────────────────────────────────────────

    async def _pg_insert(self, data: dict[str, Any]) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                INSERT INTO execution_intents (
                    execution_intent_id, idempotency_key, take_id, signal_id,
                    firewall_id, account_id, symbol, direction,
                    entry_price, stop_loss, take_profit_1, lot_size,
                    state, state_reason, created_at, updated_at,
                    broker_order_id, fill_price, fill_time, slippage,
                    actual_lot_size, rejection_code
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                data["execution_intent_id"],
                data["idempotency_key"],
                data["take_id"],
                data["signal_id"],
                data["firewall_id"],
                data["account_id"],
                data.get("symbol", ""),
                data.get("direction", ""),
                data.get("entry_price"),
                data.get("stop_loss"),
                data.get("take_profit_1"),
                data.get("lot_size"),
                data["state"],
                data.get("state_reason"),
                data["created_at"],
                data["updated_at"],
                data.get("broker_order_id"),
                data.get("fill_price"),
                data.get("fill_time"),
                data.get("slippage"),
                data.get("actual_lot_size"),
                data.get("rejection_code"),
            )
        except Exception:
            logger.warning("[ExecIntentRepo] PG insert failed", exc_info=True)

    async def _pg_update(self, eid: str, updates: dict[str, Any]) -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            parts, args = [], []
            for i, (col, val) in enumerate(updates.items(), 1):
                parts.append(f"{col} = ${i}")
                args.append(val)
            args.append(eid)
            await pg_client.execute(
                f"UPDATE execution_intents SET {', '.join(parts)} WHERE execution_intent_id = ${len(args)}",
                *args,
            )
        except Exception:
            logger.warning("[ExecIntentRepo] PG update failed", exc_info=True)

    async def _pg_fetch(self, eid: str) -> dict[str, Any] | None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return None
            row = await pg_client.fetchrow(
                "SELECT * FROM execution_intents WHERE execution_intent_id = $1",
                eid,
            )
            return dict(row) if row else None
        except Exception:
            return None

    async def _pg_fetch_by_idem(self, key: str) -> dict[str, Any] | None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return None
            row = await pg_client.fetchrow(
                "SELECT * FROM execution_intents WHERE idempotency_key = $1",
                key,
            )
            return dict(row) if row else None
        except Exception:
            return None

    # ── Redis Cache ───────────────────────────────────────────────────────────

    def _cache_set(self, eid: str, data: dict[str, Any]) -> None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            redis_client.client.set(
                f"exec_intent:{eid}",
                json.dumps(data),
                ex=60 * 60 * 24 * 7,
            )
        except Exception:
            pass

    def _cache_get(self, eid: str) -> dict[str, Any] | None:
        try:
            from storage.redis_client import redis_client  # noqa: PLC0415

            raw = redis_client.client.get(f"exec_intent:{eid}")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            if isinstance(raw, str) and raw:
                return json.loads(raw)
        except Exception:
            pass
        return None

    # ── Table Bootstrap ───────────────────────────────────────────────────────

    @staticmethod
    async def ensure_table() -> None:
        try:
            from storage.postgres_client import pg_client  # noqa: PLC0415

            if not pg_client.is_available:
                return
            await pg_client.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_intents (
                    execution_intent_id TEXT PRIMARY KEY,
                    idempotency_key     TEXT NOT NULL UNIQUE,
                    take_id             TEXT NOT NULL,
                    signal_id           TEXT NOT NULL,
                    firewall_id         TEXT NOT NULL,
                    account_id          TEXT NOT NULL,
                    symbol              TEXT NOT NULL DEFAULT '',
                    direction           TEXT NOT NULL DEFAULT '',
                    entry_price         DOUBLE PRECISION,
                    stop_loss           DOUBLE PRECISION,
                    take_profit_1       DOUBLE PRECISION,
                    lot_size            DOUBLE PRECISION,
                    state               TEXT NOT NULL DEFAULT 'INTENT_CREATED',
                    state_reason        TEXT,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL,
                    broker_order_id     TEXT,
                    fill_price          DOUBLE PRECISION,
                    fill_time           TEXT,
                    slippage            DOUBLE PRECISION,
                    actual_lot_size     DOUBLE PRECISION,
                    rejection_code      TEXT
                )
                """
            )
            await pg_client.execute("CREATE INDEX IF NOT EXISTS idx_exec_intent_take_id ON execution_intents (take_id)")
            await pg_client.execute("CREATE INDEX IF NOT EXISTS idx_exec_intent_state ON execution_intents (state)")
            await pg_client.execute(
                "CREATE INDEX IF NOT EXISTS idx_exec_intent_account ON execution_intents (account_id)"
            )
        except Exception:
            logger.warning("[ExecIntentRepo] Table creation failed", exc_info=True)
