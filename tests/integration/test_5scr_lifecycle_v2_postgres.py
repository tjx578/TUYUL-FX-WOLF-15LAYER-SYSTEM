"""Real-PostgreSQL smoke tests for Strategy Lifecycle V2 persistence.

These tests are deliberately opt-in. They must never use a developer or
production database merely because ``DATABASE_URL`` happens to be present.
CI enables them against its disposable PostgreSQL 16 service after applying
the Alembic migration chain.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib import import_module
from json import dumps, loads
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from contracts.strategy_5scr_lifecycle_v2 import (
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)
from storage.strategy_5scr_lifecycle_v2_repository import (
    LIFECYCLE_TABLE,
    LINK_TABLE,
    StrategyLifecycleV2Repository,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"
_OPENED_AT = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)


class _PoolBackedPostgres:
    """Production-like pool semantics backed by disposable PostgreSQL."""

    def __init__(self, pool: Any, foreign_key_violation_error: type[Exception]) -> None:
        self._pool = pool
        self.foreign_key_violation_error = foreign_key_violation_error
        #: Set by the fixture once asyncpg is imported.
        self.check_violation_error: type[Exception] = Exception

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as connection:
            return str(await connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        async with self._pool.acquire() as connection:
            return list(await connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection


@pytest_asyncio.fixture
async def postgres() -> AsyncIterator[_PoolBackedPostgres]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 to use a disposable PostgreSQL database")

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL")

    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires the asyncpg dependency")

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    try:
        backend = _PoolBackedPostgres(pool, asyncpg.ForeignKeyViolationError)
        backend.check_violation_error = asyncpg.CheckViolationError
        yield backend
    finally:
        await pool.close()


def _lifecycle(lifecycle_id: str) -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id=lifecycle_id,
        symbol="CHFJPY",
        state="ANALYSIS_OPEN",
        direction_state="BUY",
        opened_at_utc=_OPENED_AT,
        last_event_at_utc=_OPENED_AT + timedelta(seconds=2),
        last_continuity_event_at_utc=_OPENED_AT + timedelta(seconds=2),
        last_material_event_at_utc=_OPENED_AT + timedelta(seconds=1),
        material_state_hash="a" * 64,
        event_count=2,
        clean_block_count=1,
        watch_count=1,
    )


def _link(
    lifecycle_id: str,
    *,
    pressure_event_id: str,
    transport_lifecycle_id: str,
) -> StrategyLifecycleEventLink:
    return StrategyLifecycleEventLink(
        strategy_lifecycle_id=lifecycle_id,
        pressure_event_id=pressure_event_id,
        transport_lifecycle_id=transport_lifecycle_id,
        source_clean_block_id="clean-block-integration",
        source_watch_id=None,
        linked_at_utc=_OPENED_AT + timedelta(seconds=2),
        link_reason="EPISODE_OPENED",
    )


async def _cleanup(postgres: _PoolBackedPostgres, *lifecycle_ids: str) -> None:
    ids = list(lifecycle_ids)
    await postgres.execute(
        f"DELETE FROM {LINK_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )
    await postgres.execute(
        f"DELETE FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )


async def test_uuid_and_replay_ids_round_trip_through_real_postgres(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = StrategyLifecycleV2Repository(pg=postgres)  # type: ignore[arg-type]
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    lifecycle = _lifecycle(lifecycle_id)
    uuid_event_id = str(uuid4())
    replay_event_id = f"sha256:{uuid4().hex}"

    try:
        assert await repository.schema_status() == {
            "missing_tables": (),
            "missing_indexes": (),
            "missing_columns": (),
            "missing_constraints": (),
        }
        assert await repository.persist(
            lifecycle,
            _link(
                lifecycle_id,
                pressure_event_id=uuid_event_id,
                transport_lifecycle_id="transport-live",
            ),
        )
        stale_lifecycle = lifecycle.model_copy(
            update={
                "state": "TRANSITION_PENDING",
                "direction_state": "CONFLICT",
                "last_event_at_utc": lifecycle.last_event_at_utc + timedelta(seconds=30),
                "last_continuity_event_at_utc": lifecycle.last_continuity_event_at_utc + timedelta(seconds=30),
                "last_material_event_at_utc": lifecycle.last_material_event_at_utc + timedelta(seconds=30),
                "material_state_hash": "c" * 64,
                "event_count": 999,
            }
        )
        assert not await repository.persist(
            stale_lifecycle,
            _link(
                lifecycle_id,
                pressure_event_id=uuid_event_id,
                transport_lifecycle_id="transport-live",
            ),
        )
        assert not await repository.link_event(
            _link(
                lifecycle_id,
                pressure_event_id=uuid_event_id,
                transport_lifecycle_id="transport-live",
            )
        )
        assert await repository.link_event(
            _link(
                lifecycle_id,
                pressure_event_id=replay_event_id,
                transport_lifecycle_id="transport-replay",
            )
        )

        recovered = await repository.active_lifecycle("chfjpy")
        assert recovered == lifecycle

        type_row = await postgres.fetchrow(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = $1
              AND column_name = 'pressure_event_id'
            """,
            LINK_TABLE,
        )
        assert type_row is not None
        assert type_row["data_type"] == "text"

        event_rows = await postgres.fetch(
            f"""
            SELECT pressure_event_id
            FROM {LINK_TABLE}
            WHERE strategy_lifecycle_id = $1
            ORDER BY pressure_event_id
            """,
            lifecycle_id,
        )
        assert {row["pressure_event_id"] for row in event_rows} == {
            uuid_event_id,
            replay_event_id,
        }
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_shadow_only_is_enforced_by_the_database(
    postgres: _PoolBackedPostgres,
) -> None:
    """execution_authority must be a schema invariant, not a Python default.

    A Python-only default can be bypassed by any future writer; a CHECK cannot.
    """
    repository = StrategyLifecycleV2Repository(pg=postgres)  # type: ignore[arg-type]
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"

    try:
        await repository.upsert_lifecycle(_lifecycle(lifecycle_id))

        column = await postgres.fetchrow(
            """
            SELECT column_default, is_nullable, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = $1
              AND column_name = 'execution_authority'
            """,
            LIFECYCLE_TABLE,
        )
        assert column is not None, "execution_authority column is missing"
        assert column["data_type"] == "boolean"
        assert column["is_nullable"] == "NO"
        assert "false" in str(column["column_default"]).lower()

        stored = await postgres.fetchrow(
            f"SELECT execution_authority FROM {LIFECYCLE_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert stored is not None and stored["execution_authority"] is False

        # The database itself must refuse to grant execution authority.
        with pytest.raises(postgres.check_violation_error) as granted:
            await postgres.execute(
                f"UPDATE {LIFECYCLE_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(granted.value, "constraint_name", None) == "ck_5scr_lifecycle_v2_shadow_only"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def _seed_pressure_event(
    postgres: _PoolBackedPostgres,
    *,
    symbol: str,
    at: datetime,
    direction: str = "BUY",
) -> None:
    """Insert one delivered pressure event the shadow worker will pick up."""
    event_id = uuid4()
    transport_lifecycle_id = f"transport-{symbol}-{uuid4().hex[:8]}"
    payload = {
        "event": "signal_pressure_state_json",
        "symbol": symbol,
        "raw_direction": direction,
        "pressure_seen": True,
        "pressure_event_count": 3,
        "valid_for_execution": False,
        "is_final_signal": False,
        "final_direction": "WAIT",
        "promotion_stage": "PRESSURE_ONLY",
    }
    await postgres.execute(
        """
        INSERT INTO pressure_outbox (
            id, event_id, event_type, schema_version, symbol,
            lifecycle_id, lifecycle_sequence, source_clean_block_id,
            signal_valid_at, payload, payload_hash, status
        )
        VALUES ($1, $2, 'signal_pressure_state_json', '1.0.0', $3,
                $4, 1, NULL, $5, $6::jsonb, $7, 'PUBLISHED')
        """,
        uuid4(),
        event_id,
        symbol,
        transport_lifecycle_id,
        at,
        dumps(payload),
        uuid4().hex + uuid4().hex[:32],
    )
    await postgres.execute(
        "INSERT INTO strategy_5scr_inbox (event_id, payload_hash, status) VALUES ($1, $2, 'RECEIVED')",
        event_id,
        uuid4().hex + uuid4().hex[:32],
    )


async def _episode_state(postgres: _PoolBackedPostgres, symbol: str) -> dict[str, Any]:
    row = await postgres.fetchrow(
        f"""
        SELECT state, direction_state, opened_at, last_event_at,
               last_continuity_event_at, last_material_event_at,
               event_count, clean_block_count, watch_count, execution_authority
        FROM {LIFECYCLE_TABLE}
        WHERE symbol = $1
        """,
        symbol,
    )
    assert row is not None, f"no episode persisted for {symbol}"
    return dict(row)


async def _purge_symbol(postgres: _PoolBackedPostgres, symbol: str) -> None:
    await postgres.execute(
        f"DELETE FROM {LINK_TABLE} WHERE strategy_lifecycle_id IN "
        f"(SELECT strategy_lifecycle_id FROM {LIFECYCLE_TABLE} WHERE symbol = $1)",
        symbol,
    )
    await postgres.execute(f"DELETE FROM {LIFECYCLE_TABLE} WHERE symbol = $1", symbol)
    await postgres.execute(
        "DELETE FROM strategy_5scr_inbox WHERE event_id IN (SELECT event_id FROM pressure_outbox WHERE symbol = $1)",
        symbol,
    )
    await postgres.execute("DELETE FROM pressure_outbox WHERE symbol = $1", symbol)


async def test_restart_recovery_matches_a_continuous_run_on_real_postgres(
    postgres: _PoolBackedPostgres,
) -> None:
    """Drive the real worker down both paths and compare the resulting episodes.

    Persisting a hand-built snapshot and reading it back would only prove a
    round-trip. This folds the same event sequence twice through
    ``LifecycleV2ShadowRunner``: once continuously, once split across a fresh
    runner that must recover from the database. Only the symbol and the derived
    lifecycle id may differ.
    """
    runtime = import_module("services.pressure_outbox.lifecycle_shadow_worker")
    config = runtime.LifecycleV2RuntimeConfig(
        enabled=True,
        shadow_only=True,
        dual_write_enabled=True,
        metrics_enabled=False,
        max_continuity_gap_seconds=900,
        batch_size=100,
    )
    continuous_symbol = "EURCHF"
    restarted_symbol = "EURNZD"
    offsets = (0, 120, 240, 360)

    def _runner() -> Any:
        return runtime.LifecycleV2ShadowRunner(
            repository=StrategyLifecycleV2Repository(pg=postgres),  # type: ignore[arg-type]
            config=config,
        )

    try:
        await _purge_symbol(postgres, continuous_symbol)
        await _purge_symbol(postgres, restarted_symbol)

        # Continuous: one runner folds every event.
        for offset in offsets:
            await _seed_pressure_event(postgres, symbol=continuous_symbol, at=_OPENED_AT + timedelta(seconds=offset))
        assert await _runner().poll_once() == len(offsets)
        continuous = await _episode_state(postgres, continuous_symbol)

        # Restarted: first half, then a brand-new runner for the second half.
        for offset in offsets[:2]:
            await _seed_pressure_event(postgres, symbol=restarted_symbol, at=_OPENED_AT + timedelta(seconds=offset))
        assert await _runner().poll_once() == 2

        for offset in offsets[2:]:
            await _seed_pressure_event(postgres, symbol=restarted_symbol, at=_OPENED_AT + timedelta(seconds=offset))
        # A fresh instance holds no in-process state; it must recover from
        # PostgreSQL before folding, or it would open a duplicate episode.
        assert await _runner().poll_once() == 2
        restarted = await _episode_state(postgres, restarted_symbol)

        assert restarted == continuous, "restarted run diverged from the continuous run"
        assert continuous["event_count"] == len(offsets)
        assert continuous["execution_authority"] is False
        # Continuity tracked every event; nothing material changed after opening.
        assert continuous["last_continuity_event_at"] == _OPENED_AT + timedelta(seconds=offsets[-1])
        assert continuous["last_material_event_at"] == _OPENED_AT

        # Exactly one episode per symbol -- no duplicate opened on restart.
        for symbol in (continuous_symbol, restarted_symbol):
            count = await postgres.fetchrow(f"SELECT count(*) AS n FROM {LIFECYCLE_TABLE} WHERE symbol = $1", symbol)
            assert count["n"] == 1, f"{symbol} produced {count['n']} episodes"
    finally:
        await _purge_symbol(postgres, continuous_symbol)
        await _purge_symbol(postgres, restarted_symbol)


async def test_persist_rolls_back_lifecycle_when_real_postgres_rejects_link(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = StrategyLifecycleV2Repository(pg=postgres)  # type: ignore[arg-type]
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    missing_lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    lifecycle = _lifecycle(lifecycle_id)
    invalid_link = _link(
        missing_lifecycle_id,
        pressure_event_id=str(uuid4()),
        transport_lifecycle_id="transport-fk-failure",
    )

    try:
        with pytest.raises(postgres.foreign_key_violation_error):
            await repository.persist(lifecycle, invalid_link)

        row = await postgres.fetchrow(
            f"""
            SELECT strategy_lifecycle_id
            FROM {LIFECYCLE_TABLE}
            WHERE strategy_lifecycle_id = $1
            """,
            lifecycle_id,
        )
        assert row is None
    finally:
        await _cleanup(postgres, lifecycle_id, missing_lifecycle_id)


async def test_unlinked_inbox_read_preserves_transport_ownership(
    postgres: _PoolBackedPostgres,
) -> None:
    repository = StrategyLifecycleV2Repository(pg=postgres)  # type: ignore[arg-type]
    outbox_id = uuid4()
    event_id = uuid4()
    transport_lifecycle_id = f"transport-integration-{uuid4().hex}"
    payload = {
        "event": "signal_pressure_state_json",
        "event_id": str(event_id),
        "lifecycle_id": transport_lifecycle_id,
        "lifecycle_sequence": 1,
        "symbol": "CHFJPY",
        "raw_direction": "BUY",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "final_direction": "WAIT",
        "promotion_stage": "PRESSURE_ONLY",
    }

    try:
        await postgres.execute(
            """
            INSERT INTO pressure_outbox (
                id, event_id, event_type, schema_version, symbol,
                lifecycle_id, lifecycle_sequence, source_clean_block_id,
                signal_valid_at, payload, payload_hash, status
            )
            VALUES (
                $1, $2, 'signal_pressure_state_json', '1.0.0', 'CHFJPY',
                $3, 1, 'clean-block-integration', $4, $5::jsonb, $6, 'PUBLISHED'
            )
            """,
            outbox_id,
            event_id,
            transport_lifecycle_id,
            _OPENED_AT,
            dumps(payload),
            "b" * 64,
        )
        await postgres.execute(
            """
            INSERT INTO strategy_5scr_inbox (event_id, payload_hash, status)
            VALUES ($1, $2, 'RECEIVED')
            """,
            event_id,
            "b" * 64,
        )

        rows = await repository.fetch_unlinked_events(limit=10)
        row = next(item for item in rows if item["event_id"] == event_id)
        stored_payload = row["payload"]
        normalized_payload = loads(stored_payload) if isinstance(stored_payload, str) else stored_payload
        assert normalized_payload == payload
        assert row["lifecycle_id"] == transport_lifecycle_id

        transport_state = await postgres.fetchrow(
            """
            SELECT
                o.status AS outbox_status,
                o.locked_at,
                o.locked_by,
                o.lease_expires_at,
                i.status AS inbox_status,
                i.processed_at,
                i.result_id,
                i.last_error
            FROM pressure_outbox o
            JOIN strategy_5scr_inbox i ON i.event_id = o.event_id
            WHERE o.event_id = $1
            """,
            event_id,
        )
        assert transport_state is not None
        assert dict(transport_state) == {
            "outbox_status": "PUBLISHED",
            "locked_at": None,
            "locked_by": None,
            "lease_expires_at": None,
            "inbox_status": "RECEIVED",
            "processed_at": None,
            "result_id": None,
            "last_error": None,
        }
        assert (
            await postgres.fetchrow(
                f"SELECT pressure_event_id FROM {LINK_TABLE} WHERE pressure_event_id = $1",
                str(event_id),
            )
            is None
        )
    finally:
        await postgres.execute("DELETE FROM strategy_5scr_inbox WHERE event_id = $1", event_id)
        await postgres.execute("DELETE FROM pressure_outbox WHERE event_id = $1", event_id)
