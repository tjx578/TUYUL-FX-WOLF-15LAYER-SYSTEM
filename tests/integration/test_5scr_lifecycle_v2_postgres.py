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
        yield _PoolBackedPostgres(pool, asyncpg.ForeignKeyViolationError)
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
        }
        assert await repository.persist(
            lifecycle,
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
