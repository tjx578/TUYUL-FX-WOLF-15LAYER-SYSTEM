"""Real-PostgreSQL smoke tests for Strategy Lifecycle V2 persistence.

These tests are deliberately opt-in. They must never use a developer or
production database merely because ``DATABASE_URL`` happens to be present.
CI enables them against its disposable PostgreSQL 16 service after applying
the Alembic migration chain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from json import dumps, loads
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from contracts.strategy_5scr_lifecycle_v2 import (
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)
from storage.strategy_5scr_lifecycle_v2_repository import (
    LIFECYCLE_TABLE,
    LINK_TABLE,
    StrategyLifecycleV2Repository,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_OPENED_AT = datetime(2026, 7, 29, 15, 0, tzinfo=UTC)


def _repository(postgres: PoolBackedPostgres) -> StrategyLifecycleV2Repository:
    """Adapt the production-like test pool at one explicit type boundary."""

    return StrategyLifecycleV2Repository(pg=cast(Any, postgres))


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


async def _cleanup(postgres: PoolBackedPostgres, *lifecycle_ids: str) -> None:
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
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
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
    postgres: PoolBackedPostgres,
) -> None:
    """execution_authority must be a schema invariant, not a Python default.

    A Python-only default can be bypassed by any future writer; a CHECK cannot.
    """
    repository = _repository(postgres)
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
    postgres: PoolBackedPostgres,
    *,
    symbol: str,
    at: datetime,
    direction: str = "BUY",
) -> None:
    """Insert one delivered pressure event the shadow worker will pick up."""
    event_id = uuid4()
    transport_lifecycle_id = f"5scr-admission:{uuid4().hex}"
    # Repeated transport emissions retain the same canonical anchor.  A new
    # random clean-block id here would be a material lineage change and would
    # invalidate the restart-parity scenario this helper exists to prove.
    source_clean_block_id = f"clean-{symbol}-anchor"
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
        "pair_admission_id": transport_lifecycle_id,
        "pair_admission_status": "GRANTED",
        "pair_admission_rule_version": "5scr.pair-admission.raw-ledger.v2",
        "pair_admission_granted_at_utc": at.isoformat(),
        "pair_admission_expires_at_utc": (at + timedelta(minutes=15)).isoformat(),
        "pair_admission_source_ledger_hash": "sha256:" + uuid4().hex + uuid4().hex,
        "source_clean_block_id": source_clean_block_id,
        "lifecycle_id": transport_lifecycle_id,
    }
    await postgres.execute(
        """
        INSERT INTO pressure_outbox (
            id, event_id, event_type, schema_version, symbol,
            lifecycle_id, lifecycle_sequence, source_clean_block_id,
            signal_valid_at, payload, payload_hash, status
        )
        VALUES ($1, $2, 'signal_pressure_state_json', '1.0.0', $3,
                $4, 1, $5, $6, $7::jsonb, $8, 'PUBLISHED')
        """,
        uuid4(),
        event_id,
        symbol,
        transport_lifecycle_id,
        source_clean_block_id,
        at,
        dumps(payload),
        uuid4().hex + uuid4().hex[:32],
    )
    await postgres.execute(
        "INSERT INTO strategy_5scr_inbox (event_id, payload_hash, status) VALUES ($1, $2, 'RECEIVED')",
        event_id,
        uuid4().hex + uuid4().hex[:32],
    )


async def _episode_state(postgres: PoolBackedPostgres, symbol: str) -> dict[str, Any]:
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


async def _purge_symbol(postgres: PoolBackedPostgres, symbol: str) -> None:
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


async def _restore_shadow_check(postgres: PoolBackedPostgres) -> None:
    """Put the real CHECK back, whatever state the test left behind.

    ``DROP ... IF EXISTS`` first: if installing a weakened CHECK failed, an
    unconditional DROP in a ``finally`` would raise and leave the table with no
    shadow-only constraint at all, silently poisoning every later test.
    """
    await postgres.execute(f"ALTER TABLE {LIFECYCLE_TABLE} DROP CONSTRAINT IF EXISTS ck_5scr_lifecycle_v2_shadow_only")
    await postgres.execute(
        f"ALTER TABLE {LIFECYCLE_TABLE} ADD CONSTRAINT ck_5scr_lifecycle_v2_shadow_only "
        "CHECK (execution_authority = false)"
    )


async def test_readiness_turns_red_when_the_shadow_check_is_dropped(
    postgres: PoolBackedPostgres,
) -> None:
    """A database that lost the guarantee must not report ready.

    Asserted by removing the constraint on a real database and restoring it,
    so the negative path is proven rather than assumed.
    """
    repository = _repository(postgres)
    assert not any((await repository.schema_status()).values())

    await postgres.execute(f"ALTER TABLE {LIFECYCLE_TABLE} DROP CONSTRAINT IF EXISTS ck_5scr_lifecycle_v2_shadow_only")
    try:
        degraded = await repository.schema_status()
        assert degraded["missing_constraints"] == ("ck_5scr_lifecycle_v2_shadow_only",)
        assert degraded["missing_tables"] == ()
        assert degraded["missing_indexes"] == ()
    finally:
        await _restore_shadow_check(postgres)

    assert not any((await repository.schema_status()).values())


async def test_readiness_rejects_a_same_named_check_with_a_weakened_definition(
    postgres: PoolBackedPostgres,
) -> None:
    """Restoring the name but not the meaning must still read as missing."""
    repository = _repository(postgres)

    await postgres.execute(f"ALTER TABLE {LIFECYCLE_TABLE} DROP CONSTRAINT IF EXISTS ck_5scr_lifecycle_v2_shadow_only")
    try:
        # Same name, same table, but it no longer forbids anything.
        await postgres.execute(
            f"ALTER TABLE {LIFECYCLE_TABLE} ADD CONSTRAINT ck_5scr_lifecycle_v2_shadow_only "
            "CHECK (execution_authority IS NOT NULL)"
        )
        degraded = await repository.schema_status()
        assert degraded["missing_constraints"] == ("ck_5scr_lifecycle_v2_shadow_only",)
    finally:
        await _restore_shadow_check(postgres)

    assert not any((await repository.schema_status()).values())


async def test_readiness_rejects_a_check_widened_with_or_true(
    postgres: PoolBackedPostgres,
) -> None:
    """The definition still contains the fragment but forbids nothing.

    This also pins the expected normalized definition against what this
    PostgreSQL actually renders: if the two ever disagree, the assertion that
    readiness is green *before* the tampering fails first.
    """
    repository = _repository(postgres)
    assert not any((await repository.schema_status()).values())

    try:
        await postgres.execute(
            f"ALTER TABLE {LIFECYCLE_TABLE} DROP CONSTRAINT IF EXISTS ck_5scr_lifecycle_v2_shadow_only"
        )
        await postgres.execute(
            f"ALTER TABLE {LIFECYCLE_TABLE} ADD CONSTRAINT ck_5scr_lifecycle_v2_shadow_only "
            "CHECK ((execution_authority = false) OR true)"
        )
        degraded = await repository.schema_status()
        assert degraded["missing_constraints"] == ("ck_5scr_lifecycle_v2_shadow_only",)

        # Prove it really was toothless: the row the real CHECK forbids inserts.
        lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
        await repository.upsert_lifecycle(_lifecycle(lifecycle_id))
        await postgres.execute(
            f"UPDATE {LIFECYCLE_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        await _cleanup(postgres, lifecycle_id)
    finally:
        await _restore_shadow_check(postgres)

    assert not any((await repository.schema_status()).values())


async def test_restart_recovery_matches_a_continuous_run_on_real_postgres(
    postgres: PoolBackedPostgres,
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
            repository=_repository(postgres),
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

        assert continuous is not None
        assert restarted is not None
        assert restarted == continuous, "restarted run diverged from the continuous run"
        assert continuous["event_count"] == len(offsets)
        assert continuous["execution_authority"] is False
        # Continuity tracked every event; nothing material changed after opening.
        assert continuous["last_continuity_event_at"] == _OPENED_AT + timedelta(seconds=offsets[-1])
        assert continuous["last_material_event_at"] == _OPENED_AT

        # Exactly one episode per symbol -- no duplicate opened on restart.
        for symbol in (continuous_symbol, restarted_symbol):
            count = await postgres.fetchrow(f"SELECT count(*) AS n FROM {LIFECYCLE_TABLE} WHERE symbol = $1", symbol)
            assert count is not None
            assert count["n"] == 1, f"{symbol} produced {count['n']} episodes"
    finally:
        await _purge_symbol(postgres, continuous_symbol)
        await _purge_symbol(postgres, restarted_symbol)


async def test_persist_rolls_back_lifecycle_when_real_postgres_rejects_link(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
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
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
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
