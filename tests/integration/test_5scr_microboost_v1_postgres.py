"""Disposable-PostgreSQL gates for durable Microboost pulse/state P2."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from analysis.strategy_5scr_v3.pressure.live_outbox_adapter import LivePressureOutboxAdapter
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository
from storage.strategy_5scr_microboost_v1_repository import (
    PULSE_EVENT_TABLE,
    STATE_TABLE,
    StrategyMicroboostV1Repository,
)
from tests.pressure_emission_v3_helpers import live_envelope, load_fixture

if TYPE_CHECKING:
    from contracts.strategy_5scr_pressure_emission_v3 import CanonicalPressureEmissionV3
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

START = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def _repository(postgres: PoolBackedPostgres) -> StrategyMicroboostV1Repository:
    return StrategyMicroboostV1Repository(pg=cast(Any, postgres))


def _lifecycle_repository(postgres: PoolBackedPostgres) -> StrategyLifecycleV2Repository:
    return StrategyLifecycleV2Repository(pg=cast(Any, postgres))


def _emission(
    *,
    at: datetime = START,
    detected: bool = True,
    ticks: int = 7,
    block: str = "CHFJPY:clean:block-a",
) -> CanonicalPressureEmissionV3:
    payload = load_fixture("live_equivalents", "equivalent_chfjpy.json")
    payload.update(
        {
            "signal_valid_time_utc": at.isoformat(),
            "microboost_detected": detected,
            "effective_ticks": ticks,
            "source_clean_block_id": block,
            "pair_admission_granted_at_utc": START.isoformat(),
            "pair_admission_expires_at_utc": (START + timedelta(minutes=15)).isoformat(),
        }
    )
    return LivePressureOutboxAdapter().normalize(live_envelope(payload))


def _lifecycle(lifecycle_id: str, *, state: str = "ANALYSIS_OPEN") -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id=lifecycle_id,
        symbol="CHFJPY",
        state=cast(Any, state),
        direction_state="SELL",
        opened_at_utc=START,
        last_event_at_utc=START + timedelta(minutes=10),
        last_continuity_event_at_utc=START + timedelta(minutes=10),
        last_material_event_at_utc=START,
        material_state_hash="a" * 64,
        event_count=3,
        clean_block_count=1,
    )


async def _seed(
    postgres: PoolBackedPostgres,
    lifecycle_id: str,
    emissions: tuple[CanonicalPressureEmissionV3, ...],
    *,
    lifecycle_state: str = "ANALYSIS_OPEN",
) -> None:
    repository = _lifecycle_repository(postgres)
    await repository.upsert_lifecycle(_lifecycle(lifecycle_id, state=lifecycle_state))
    for index, emission in enumerate(emissions):
        inserted = await repository.link_event(
            StrategyLifecycleEventLink(
                strategy_lifecycle_id=lifecycle_id,
                pressure_event_id=emission.identity.transport_event_id,
                transport_lifecycle_id=f"transport:{lifecycle_id}",
                source_clean_block_id=emission.source_lineage.source_clean_block_id,
                linked_at_utc=emission.time.event_time_utc,
                link_reason="EPISODE_OPENED" if index == 0 else "EPISODE_CONTINUED",
            )
        )
        assert inserted


async def _cleanup(postgres: PoolBackedPostgres, *lifecycle_ids: str) -> None:
    ids = list(lifecycle_ids)
    await postgres.execute(
        f"DELETE FROM {PULSE_EVENT_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )
    await postgres.execute(
        f"DELETE FROM {STATE_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )
    await postgres.execute(
        "DELETE FROM strategy_5scr_lifecycle_event_links_v2 WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )
    await postgres.execute(
        "DELETE FROM strategy_5scr_analysis_lifecycles_v2 WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )


async def test_schema_ready_and_database_enforces_shadow_only(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    emission = _emission()
    await _seed(postgres, lifecycle_id, (emission,))
    try:
        status = await _repository(postgres).schema_status()
        assert status.ready, status
        result = await _repository(postgres).process_emission(emission)
        assert result.status == "PERSISTED"

        with pytest.raises(postgres.check_violation_error) as pulse_grant:
            await postgres.execute(
                f"UPDATE {PULSE_EVENT_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(pulse_grant.value, "constraint_name", None) == ("ck_5scr_microboost_pulse_shadow_only_v1")

        with pytest.raises(postgres.check_violation_error) as state_grant:
            await postgres.execute(
                f"UPDATE {STATE_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(state_grant.value, "constraint_name", None) == ("ck_5scr_microboost_state_shadow_only_v1")
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_no_canonical_lifecycle_link_creates_no_state(
    postgres: PoolBackedPostgres,
) -> None:
    emission = _emission()
    result = await _repository(postgres).process_emission(emission)

    assert result.status == "REJECTED"
    assert result.reason_code == "NO_CANONICAL_LIFECYCLE_LINK"
    row = await postgres.fetchrow(
        f"SELECT count(*) AS count FROM {STATE_TABLE} WHERE last_source_event_id = $1",
        emission.identity.transport_event_id,
    )
    assert row is not None and row["count"] == 0


async def test_restart_duplicate_and_material_reinforcement_are_exactly_once(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    formed = _emission()
    sticky = _emission(at=START + timedelta(seconds=30))
    reinforced = _emission(at=START + timedelta(seconds=120), ticks=25)
    await _seed(postgres, lifecycle_id, (formed, sticky, reinforced))
    try:
        first_repository = _repository(postgres)
        first = await first_repository.process_emission(formed)
        carried = await first_repository.process_emission(sticky)
        assert first.status == "PERSISTED"
        assert carried.status == "NO_CHANGE"

        restarted = _repository(postgres)
        duplicate = await restarted.process_emission(sticky)
        final = await restarted.process_emission(reinforced)
        assert duplicate.status == "DUPLICATE"
        assert duplicate.reason_code == "SOURCE_EVENT_ALREADY_OBSERVED"
        assert final.status == "PERSISTED"

        state = await restarted.load_state(lifecycle_id)
        assert state is not None
        assert state.independent_pulse_count == 1
        assert state.reinforcement_count == 1
        assert state.observed_snapshot_count == 3
        assert state.carried_snapshot_count == 1
        assert state.last_source_event_id == reinforced.identity.transport_event_id

        rows = await postgres.fetch(
            f"SELECT transition FROM {PULSE_EVENT_TABLE} "
            "WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at, pulse_event_id",
            lifecycle_id,
        )
        assert [row["transition"] for row in rows] == ["FORMED", "REINFORCED"]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_concurrent_duplicate_delivery_is_serialized(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    emission = _emission()
    await _seed(postgres, lifecycle_id, (emission,))
    try:
        results = await asyncio.gather(
            _repository(postgres).process_emission(emission),
            _repository(postgres).process_emission(emission),
        )
        assert sorted(item.status for item in results) == ["DUPLICATE", "PERSISTED"]

        counts = await postgres.fetchrow(
            f"""
            SELECT
                (SELECT count(*) FROM {PULSE_EVENT_TABLE}
                  WHERE strategy_lifecycle_id = $1) AS pulses,
                (SELECT independent_pulse_count FROM {STATE_TABLE}
                  WHERE strategy_lifecycle_id = $1) AS independent_pulses,
                (SELECT observed_snapshot_count FROM {STATE_TABLE}
                  WHERE strategy_lifecycle_id = $1) AS observations
            """,
            lifecycle_id,
        )
        assert counts is not None
        assert dict(counts) == {"pulses": 1, "independent_pulses": 1, "observations": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_concurrent_ttl_boundary_emits_one_expiry_without_rearming(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    formed = _emission()
    first_boundary = _emission(at=START + timedelta(seconds=120))
    second_boundary = _emission(at=START + timedelta(seconds=121))
    repeated = _emission(at=START + timedelta(seconds=122))
    await _seed(postgres, lifecycle_id, (formed, first_boundary, second_boundary, repeated))
    try:
        repository = _repository(postgres)
        assert (await repository.process_emission(formed)).status == "PERSISTED"
        await postgres.execute(
            f"UPDATE {STATE_TABLE} SET expires_at = $2 WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
            START + timedelta(seconds=60),
        )

        results = await asyncio.gather(
            _repository(postgres).process_emission(first_boundary),
            _repository(postgres).process_emission(second_boundary),
        )
        assert sum(item.status == "PERSISTED" for item in results) == 1
        assert (await _repository(postgres).process_emission(repeated)).status == "NO_CHANGE"

        rows = await postgres.fetch(
            f"SELECT transition FROM {PULSE_EVENT_TABLE} "
            "WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at, pulse_event_id",
            lifecycle_id,
        )
        assert [row["transition"] for row in rows] == ["FORMED", "EXPIRED"]
        state = await repository.load_state(lifecycle_id)
        assert state is not None
        assert state.state == "EXPIRED"
        assert state.independent_pulse_count == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_reordered_batch_matches_forward_replay(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    emissions = (
        _emission(),
        _emission(at=START + timedelta(seconds=30)),
        _emission(at=START + timedelta(seconds=120), ticks=25),
    )
    await _seed(postgres, lifecycle_id, emissions)
    try:
        repository = _repository(postgres)
        await repository.process_batch(emissions)
        forward_state = await repository.load_state(lifecycle_id)
        forward_pulses = await postgres.fetch(
            f"SELECT pulse_event_id, transition, evidence_hash FROM {PULSE_EVENT_TABLE} "
            "WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at, pulse_event_id",
            lifecycle_id,
        )

        await _cleanup(postgres, lifecycle_id)
        await _seed(postgres, lifecycle_id, emissions)
        await _repository(postgres).process_batch(tuple(reversed(emissions)))
        reordered_state = await _repository(postgres).load_state(lifecycle_id)
        reordered_pulses = await postgres.fetch(
            f"SELECT pulse_event_id, transition, evidence_hash FROM {PULSE_EVENT_TABLE} "
            "WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at, pulse_event_id",
            lifecycle_id,
        )

        assert reordered_state == forward_state
        assert [dict(row) for row in reordered_pulses] == [dict(row) for row in forward_pulses]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_lifecycle_cannot_resurrect_microboost_state(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    emission = _emission()
    await _seed(postgres, lifecycle_id, (emission,), lifecycle_state="INVALIDATED")
    try:
        result = await _repository(postgres).process_emission(emission)
        assert result.status == "REJECTED"
        assert result.reason_code == "TERMINAL_LIFECYCLE"
        assert await _repository(postgres).load_state(lifecycle_id) is None
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_state_failure_rolls_back_new_pulse(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    emission = _emission()
    suffix = uuid4().hex
    function_name = f"test_microboost_state_failure_{suffix}"
    trigger_name = f"test_microboost_state_failure_{suffix}"
    await _seed(postgres, lifecycle_id, (emission,))
    await postgres.execute(
        f"""
        CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'forced state failure';
        END
        $$
        """
    )
    await postgres.execute(
        f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON {STATE_TABLE} FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    try:
        with pytest.raises(Exception, match="forced state failure"):
            await _repository(postgres).process_emission(emission)
        row = await postgres.fetchrow(
            f"SELECT count(*) AS count FROM {PULSE_EVENT_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert row is not None and row["count"] == 0
        assert await _repository(postgres).load_state(lifecycle_id) is None
    finally:
        await postgres.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {STATE_TABLE}")
        await postgres.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_rejects_weakened_shadow_constraint(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT ck_5scr_microboost_state_shadow_only_v1")
    try:
        await postgres.execute(
            f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT ck_5scr_microboost_state_shadow_only_v1 "
            "CHECK (execution_authority IS NOT NULL)"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert "ck_5scr_microboost_state_shadow_only_v1:definition" in status.invalid_constraints
    finally:
        await postgres.execute(
            f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT IF EXISTS ck_5scr_microboost_state_shadow_only_v1"
        )
        await postgres.execute(
            f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT ck_5scr_microboost_state_shadow_only_v1 "
            "CHECK (execution_authority IS FALSE)"
        )
    assert (await repository.schema_status()).ready


async def test_readiness_rejects_required_column_shape_drift(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP COLUMN active_block_id")
    try:
        missing = await repository.schema_status()
        assert f"{STATE_TABLE}.active_block_id" in missing.missing_columns
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ADD COLUMN active_block_id text")

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN current_effective_ticks TYPE bigint")
    try:
        wrong_type = await repository.schema_status()
        assert f"{STATE_TABLE}.current_effective_ticks:type=bigint" in wrong_type.invalid_columns
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN current_effective_ticks TYPE integer")

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN observed_snapshot_count DROP NOT NULL")
    try:
        nullable = await repository.schema_status()
        assert f"{STATE_TABLE}.observed_snapshot_count:nullable=true" in nullable.invalid_columns
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN observed_snapshot_count SET NOT NULL")

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN execution_authority SET DEFAULT true")
    try:
        wrong_default = await repository.schema_status()
        assert f"{STATE_TABLE}.execution_authority:default=true" in wrong_default.invalid_columns
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ALTER COLUMN execution_authority SET DEFAULT false")

    assert (await repository.schema_status()).ready


async def test_readiness_rejects_missing_true_and_not_valid_constraint(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    constraint = "ck_5scr_microboost_state_name_v1"
    canonical = "state IN ('NONE','ACTIVE','WEAKENING','INVALIDATED','EXPIRED')"

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT {constraint}")
    try:
        missing = await repository.schema_status()
        assert constraint in missing.missing_constraints

        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT {constraint} CHECK (TRUE)")
        check_true = await repository.schema_status()
        assert f"{constraint}:definition" in check_true.invalid_constraints

        await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT {constraint} CHECK ({canonical}) NOT VALID")
        not_valid = await repository.schema_status()
        assert f"{constraint}:not_validated" in not_valid.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT {constraint} CHECK ({canonical})")

    assert (await repository.schema_status()).ready


async def test_readiness_rejects_missing_and_wrong_primary_key_type(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    constraint = "strategy_5scr_microboost_states_v1_pkey"

    await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT {constraint}")
    try:
        missing = await repository.schema_status()
        assert constraint in missing.missing_constraints

        await postgres.execute(f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT {constraint} UNIQUE (strategy_lifecycle_id)")
        wrong_type = await repository.schema_status()
        assert f"{constraint}:type" in wrong_type.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {STATE_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {STATE_TABLE} ADD CONSTRAINT {constraint} PRIMARY KEY (strategy_lifecycle_id)"
        )

    assert (await repository.schema_status()).ready


async def test_readiness_rejects_missing_and_partial_dedupe_index(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    index = "uq_5scr_microboost_pulse_dedupe_v1"

    await postgres.execute(f"DROP INDEX {index}")
    try:
        missing = await repository.schema_status()
        assert index in missing.missing_indexes

        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {PULSE_EVENT_TABLE} (dedupe_key) WHERE transition = 'FORMED'"
        )
        partial = await repository.schema_status()
        assert f"{index}:predicate" in partial.invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX IF EXISTS {index}")
        await postgres.execute(f"CREATE UNIQUE INDEX {index} ON {PULSE_EVENT_TABLE} (dedupe_key)")

    assert (await repository.schema_status()).ready
