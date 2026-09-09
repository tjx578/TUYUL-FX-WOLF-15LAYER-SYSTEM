"""Disposable-PostgreSQL gates for durable ContextEpoch P3."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from contracts.strategy_5scr_context_epoch_v1 import (
    ContextCandleAuthorityV1,
    MaterialContextEvidenceV1,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from storage.observer_export_outbox import ObserverExportOutboxRepository
from storage.strategy_5scr_context_epoch_v1_repository import (
    EPOCH_TABLE,
    TRANSITION_TABLE,
    StrategyContextEpochV1Repository,
)
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

START = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _repository(postgres: PoolBackedPostgres) -> StrategyContextEpochV1Repository:
    return StrategyContextEpochV1Repository(pg=cast(Any, postgres))


def _lifecycle_repository(postgres: PoolBackedPostgres) -> StrategyLifecycleV2Repository:
    return StrategyLifecycleV2Repository(pg=cast(Any, postgres))


def _candle(timeframe: str, *, variant: str = "a") -> ContextCandleAuthorityV1:
    if timeframe == "D1":
        open_at = START - timedelta(days=1, hours=12)
        close_at = START - timedelta(hours=12)
    else:
        open_at = START - timedelta(hours=8)
        close_at = START - timedelta(hours=4)
    return ContextCandleAuthorityV1(
        candle_id=f"EURUSD:{timeframe}:{variant}",
        symbol="EURUSD",
        timeframe=cast(Any, timeframe),
        open_time_utc=open_at,
        close_time_utc=close_at,
        complete=True,
        provider="XM",
        provider_timestamp_semantics="PERIOD_OPEN",
        provider_session_lineage_valid=True,
        structural_authority=True,
    )


def _evidence(
    sequence: int,
    *,
    bias: str = "BULLISH",
    variant: str = "a",
    deployment: str = "deploy-a",
    complete: bool = True,
) -> MaterialContextEvidenceV1:
    event_id = f"context-event-{uuid4().hex}-{sequence}"
    d1 = _candle("D1", variant=variant)
    if not complete:
        d1 = d1.model_copy(update={"complete": False})
    return MaterialContextEvidenceV1(
        source_pressure_event_id=event_id,
        source_event_ids=(event_id,),
        symbol="EURUSD",
        observed_at_utc=START + timedelta(seconds=sequence),
        d1_candles=(d1,),
        h4_candles=(_candle("H4", variant=variant),),
        daily_bias=bias,
        h4_structure="BULLISH_EXPANSION",
        price_location="DISCOUNT",
        liquidity_state="SELLSIDE_SWEPT",
        direction_domain="BUY_ONLY",
        allowed_routes=("CONTINUATION",),
        blocked_routes=("REVERSAL",),
        target_map_version="targets-v1",
        structural_invalidation_version="invalidation-v1",
        source_deployment_id=deployment,
        source_replica_id=f"replica-{sequence}",
        reference_price=1.1 + sequence / 1_000_000,
        microboost_evidence_hash=f"sha256:{sequence:064x}",
    )


def _lifecycle(lifecycle_id: str, *, state: str = "ANALYSIS_OPEN") -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id=lifecycle_id,
        symbol="EURUSD",
        state=cast(Any, state),
        direction_state="BUY",
        opened_at_utc=START - timedelta(minutes=10),
        last_event_at_utc=START + timedelta(hours=1),
        last_continuity_event_at_utc=START + timedelta(hours=1),
        last_material_event_at_utc=START,
        material_state_hash="c" * 64,
        event_count=3,
        clean_block_count=1,
    )


async def _seed(
    postgres: PoolBackedPostgres,
    lifecycle_id: str,
    evidence_items: tuple[MaterialContextEvidenceV1, ...],
    *,
    state: str = "ANALYSIS_OPEN",
) -> None:
    repository = _lifecycle_repository(postgres)
    await repository.upsert_lifecycle(_lifecycle(lifecycle_id, state=state))
    for index, evidence in enumerate(evidence_items):
        inserted = await repository.link_event(
            StrategyLifecycleEventLink(
                strategy_lifecycle_id=lifecycle_id,
                pressure_event_id=evidence.source_pressure_event_id,
                transport_lifecycle_id=f"transport:{lifecycle_id}",
                source_clean_block_id=f"raw-block-{lifecycle_id}",
                linked_at_utc=evidence.observed_at_utc,
                link_reason="EPISODE_OPENED" if index == 0 else "EPISODE_CONTINUED",
            )
        )
        assert inserted


async def _cleanup(postgres: PoolBackedPostgres, *lifecycle_ids: str) -> None:
    ids = list(lifecycle_ids)
    await postgres.execute(
        f"DELETE FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
        ids,
    )
    await postgres.execute(
        f"DELETE FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = ANY($1::text[])",
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


async def test_schema_ready_and_database_enforces_shadow_only(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    evidence = _evidence(1)
    await _seed(postgres, lifecycle_id, (evidence,))
    try:
        status = await _repository(postgres).schema_status()
        assert status.ready, status
        assert (await _repository(postgres).process_evidence(evidence)).status == "PERSISTED"

        with pytest.raises(postgres.check_violation_error) as epoch_grant:
            await postgres.execute(
                f"UPDATE {EPOCH_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(epoch_grant.value, "constraint_name", None) == "ck_5scr_context_epoch_shadow_only_v1"

        with pytest.raises(postgres.check_violation_error) as transition_grant:
            await postgres.execute(
                f"UPDATE {TRANSITION_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(transition_grant.value, "constraint_name", None) == ("ck_5scr_context_transition_shadow_only_v1")
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_missing_lifecycle_link_and_invalid_candle_fail_closed(postgres: PoolBackedPostgres) -> None:
    unlinked = _evidence(1)
    result = await _repository(postgres).process_evidence(unlinked)
    assert (result.status, result.reason_code) == ("REJECTED", "NO_CANONICAL_LIFECYCLE_LINK")

    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    invalid = _evidence(2, complete=False)
    await _seed(postgres, lifecycle_id, (invalid,))
    try:
        result = await _repository(postgres).process_evidence(invalid)
        assert (result.status, result.reason_code) == (
            "WAITING_CONTEXT_EVIDENCE",
            "SOURCE_CANDLE_INCOMPLETE",
        )
        counts = await postgres.fetchrow(
            f"SELECT (SELECT count(*) FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1) AS epochs, "
            f"(SELECT count(*) FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1) AS transitions",
            lifecycle_id,
        )
        assert counts is not None
        assert dict(counts) == {"epochs": 0, "transitions": 0}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_hundred_lineage_refreshes_keep_one_epoch(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    evidence_items = tuple(_evidence(index + 1, deployment=f"deploy-{index}") for index in range(100))
    await _seed(postgres, lifecycle_id, evidence_items)
    try:
        results = await _repository(postgres).process_batch(evidence_items)
        assert results[0].status == "PERSISTED"
        assert all(result.status == "NO_CHANGE" for result in results[1:])
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1
        assert history[0].state_version == 100
        counts = await postgres.fetchrow(
            f"SELECT (SELECT count(*) FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1) AS epochs, "
            f"(SELECT count(*) FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1) AS transitions",
            lifecycle_id,
        )
        assert counts is not None and dict(counts) == {"epochs": 1, "transitions": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_a_b_a_restart_and_duplicate_preserve_three_epoch_identities(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    a1 = _evidence(1, bias="BULLISH", variant="a")
    b = _evidence(2, bias="BEARISH", variant="b")
    a2 = _evidence(3, bias="BULLISH", variant="a")
    await _seed(postgres, lifecycle_id, (a1, b, a2))
    try:
        repository = _repository(postgres)
        assert (await repository.process_evidence(a1)).status == "PERSISTED"
        assert (await StrategyContextEpochV1Repository(pg=cast(Any, postgres)).process_evidence(b)).status == (
            "PERSISTED"
        )
        assert (await _repository(postgres).process_evidence(b)).status == "DUPLICATE"
        assert (await _repository(postgres).process_evidence(a2)).status == "PERSISTED"

        history = await _repository(postgres).load_history(lifecycle_id)
        assert [epoch.epoch_sequence for epoch in history] == [1, 2, 3]
        assert len({epoch.context_epoch_id for epoch in history}) == 3
        assert history[0].material_context_hash == history[2].material_context_hash
        assert history[0].context_epoch_id != history[2].context_epoch_id
        assert [epoch.state for epoch in history] == ["SUPERSEDED", "SUPERSEDED", "ACTIVE"]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_context_material_transitions_publish_source_verbatim_shadow_events(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    first = _evidence(1, bias="BULLISH", variant="observer-a")
    second = _evidence(2, bias="BEARISH", variant="observer-b")
    await _seed(postgres, lifecycle_id, (first, second))
    export = ObserverExportOutboxRepository(pg=cast(Any, postgres))
    repository = StrategyContextEpochV1Repository(
        pg=cast(Any, postgres),
        observer_export_repository=export,
    )
    try:
        opened = await repository.process_evidence(first)
        transitioned = await repository.process_evidence(second)
        replay = await repository.process_evidence(second)
        rows = await export.read_stream(f"analysis-lifecycle:{lifecycle_id}")

        assert opened.status == "PERSISTED"
        assert transitioned.status == "PERSISTED"
        assert replay.status == "DUPLICATE"
        assert len(rows) == 2
        assert [row.envelope.payload.body["transition_reason"] for row in rows] == [
            "OPENED",
            "MATERIAL_CONTEXT_CHANGED",
        ]
        assert rows[0].envelope.payload.body["previous_epoch_id"] is None
        assert rows[1].envelope.payload.body["previous_epoch_id"] == opened.epoch.context_epoch_id
        assert all(row.envelope.source.service.endswith("-shadow") for row in rows)
        assert all(row.envelope.payload.body["execution_authority"] is False for row in rows)
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_same_source_lineage_drift_is_quarantined_without_mutating_durable_evidence(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    original = _evidence(1)
    drifted = original.model_copy(
        update={
            "source_deployment_id": "deploy-drifted",
            "observed_at_utc": original.observed_at_utc + timedelta(seconds=1),
        }
    )
    await _seed(postgres, lifecycle_id, (original,))
    try:
        opened = await _repository(postgres).process_evidence(original)
        assert opened.status == "PERSISTED" and opened.epoch is not None

        rejected = await _repository(postgres).process_evidence(drifted)
        assert (rejected.status, rejected.reason_code) == (
            "QUARANTINED_CONTEXT_EVIDENCE",
            "SOURCE_EVENT_CONTEXT_EVIDENCE_DRIFT",
        )
        row = await postgres.fetchrow(
            f"SELECT evidence_hash, evidence_payload->>'source_deployment_id' AS deployment "
            f"FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        counts = await postgres.fetchrow(
            f"SELECT (SELECT count(*) FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1) AS epochs, "
            f"(SELECT count(*) FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1) AS transitions",
            lifecycle_id,
        )
        assert row is not None
        assert dict(row) == {"evidence_hash": opened.epoch.evidence_hash, "deployment": "deploy-a"}
        assert counts is not None and dict(counts) == {"epochs": 1, "transitions": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_concurrent_same_transition_creates_one_successor(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    initial = _evidence(1)
    changed = _evidence(2, bias="BEARISH", variant="b")
    await _seed(postgres, lifecycle_id, (initial, changed))
    try:
        assert (await _repository(postgres).process_evidence(initial)).status == "PERSISTED"
        results = await asyncio.gather(
            _repository(postgres).process_evidence(changed),
            _repository(postgres).process_evidence(changed),
        )
        assert sorted(result.status for result in results) == ["DUPLICATE", "PERSISTED"]
        rows = await postgres.fetch(
            f"SELECT epoch_sequence, state FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1 ORDER BY epoch_sequence",
            lifecycle_id,
        )
        transitions = await postgres.fetchrow(
            f"SELECT count(*) AS count FROM {TRANSITION_TABLE} "
            "WHERE strategy_lifecycle_id = $1 AND reason = 'MATERIAL_CONTEXT_CHANGED'",
            lifecycle_id,
        )
        assert [dict(row) for row in rows] == [
            {"epoch_sequence": 1, "state": "SUPERSEDED"},
            {"epoch_sequence": 2, "state": "ACTIVE"},
        ]
        assert transitions is not None and transitions["count"] == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_transition_failure_rolls_back_epoch_change(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    evidence = _evidence(1)
    function_name = f"test_context_transition_failure_{uuid4().hex}"
    trigger_name = function_name
    await _seed(postgres, lifecycle_id, (evidence,))
    await postgres.execute(
        f"""
        CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'forced context transition failure';
        END
        $$
        """
    )
    await postgres.execute(
        f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON {TRANSITION_TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    try:
        with pytest.raises(Exception, match="forced context transition failure"):
            await _repository(postgres).process_evidence(evidence)
        assert await _repository(postgres).load_latest(lifecycle_id) is None
    finally:
        await postgres.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {TRANSITION_TABLE}")
        await postgres.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_lifecycle_closes_active_epoch_and_cannot_resurrect(postgres: PoolBackedPostgres) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    opened = _evidence(1)
    terminal = _evidence(2, complete=False)
    later = _evidence(3, bias="BEARISH", variant="b")
    await _seed(postgres, lifecycle_id, (opened, terminal, later))
    try:
        assert (await _repository(postgres).process_evidence(opened)).status == "PERSISTED"
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 SET state = 'INVALIDATED' WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert (await _repository(postgres).process_evidence(terminal)).status == "PERSISTED"
        rejected = await _repository(postgres).process_evidence(later)
        assert (rejected.status, rejected.reason_code) == ("DUPLICATE", "CONTEXT_ALREADY_TERMINAL")
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1 and history[0].state == "TERMINAL"
        rows = await postgres.fetch(
            f"SELECT reason FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at",
            lifecycle_id,
        )
        assert [row["reason"] for row in rows] == ["OPENED", "LIFECYCLE_TERMINAL"]
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize("terminal_mode", ("same", "late"))
async def test_terminal_lifecycle_closes_epoch_with_nonadvancing_context_cursor(
    postgres: PoolBackedPostgres,
    terminal_mode: str,
) -> None:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    late = _evidence(1)
    opened_evidence = _evidence(2)
    later = _evidence(3, bias="BEARISH", variant="b")
    terminal_evidence = opened_evidence if terminal_mode == "same" else late
    await _seed(postgres, lifecycle_id, (late, opened_evidence, later))
    try:
        opened = await _repository(postgres).process_evidence(opened_evidence)
        assert opened.status == "PERSISTED" and opened.epoch is not None
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 SET state = 'INVALIDATED' WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )

        terminal = await _repository(postgres).process_evidence(terminal_evidence)
        assert terminal.status == "PERSISTED"
        assert terminal.epoch is not None and terminal.epoch.state == "TERMINAL"
        assert terminal.epoch.closed_at_utc == START + timedelta(hours=1)
        assert terminal.epoch.last_source_event_id == opened.epoch.last_source_event_id
        assert terminal.epoch.evidence_hash == opened.epoch.evidence_hash

        rejected = await _repository(postgres).process_evidence(later)
        assert (rejected.status, rejected.reason_code) == ("DUPLICATE", "CONTEXT_ALREADY_TERMINAL")
        rows = await postgres.fetch(
            f"SELECT reason, occurred_at FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1 ORDER BY occurred_at",
            lifecycle_id,
        )
        assert [row["reason"] for row in rows] == ["OPENED", "LIFECYCLE_TERMINAL"]
        assert rows[-1]["occurred_at"] == START + timedelta(hours=1)
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_rejects_weakened_constraint_column_and_partial_index(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    constraint = "ck_5scr_context_epoch_shadow_only_v1"
    index = "uq_5scr_context_transition_dedupe_v1"

    await postgres.execute(f"ALTER TABLE {EPOCH_TABLE} DROP CONSTRAINT {constraint}")
    try:
        await postgres.execute(
            f"ALTER TABLE {EPOCH_TABLE} ADD CONSTRAINT {constraint} CHECK (execution_authority IS NOT NULL)"
        )
        status = await repository.schema_status()
        assert f"{constraint}:definition" in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {EPOCH_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {EPOCH_TABLE} ADD CONSTRAINT {constraint} CHECK (execution_authority IS FALSE)"
        )

    await postgres.execute(f"ALTER TABLE {EPOCH_TABLE} ALTER COLUMN execution_authority SET DEFAULT true")
    try:
        status = await repository.schema_status()
        assert f"{EPOCH_TABLE}.execution_authority:default=true" in status.invalid_columns
    finally:
        await postgres.execute(f"ALTER TABLE {EPOCH_TABLE} ALTER COLUMN execution_authority SET DEFAULT false")

    await postgres.execute(f"DROP INDEX {index}")
    try:
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {TRANSITION_TABLE} (dedupe_key) WHERE reason = 'OPENED'"
        )
        status = await repository.schema_status()
        assert f"{index}:predicate" in status.invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX IF EXISTS {index}")
        await postgres.execute(f"CREATE UNIQUE INDEX {index} ON {TRANSITION_TABLE} (dedupe_key)")

    assert (await repository.schema_status()).ready


async def test_readiness_rejects_transition_shape_and_active_predicate_drift(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    constraint = "ck_5scr_context_transition_shape_v1"
    index = "uq_5scr_context_active_lifecycle_v1"
    canonical_shape = (
        "(reason = 'OPENED' AND from_context_epoch_id IS NULL AND to_context_epoch_id IS NOT NULL) "
        "OR (reason = 'MATERIAL_CONTEXT_CHANGED' AND from_context_epoch_id IS NOT NULL "
        "AND to_context_epoch_id IS NOT NULL AND from_context_epoch_id <> to_context_epoch_id) "
        "OR (reason = 'LIFECYCLE_TERMINAL' AND from_context_epoch_id IS NOT NULL "
        "AND to_context_epoch_id IS NULL)"
    )

    await postgres.execute(f"ALTER TABLE {TRANSITION_TABLE} DROP CONSTRAINT {constraint}")
    try:
        await postgres.execute(f"ALTER TABLE {TRANSITION_TABLE} ADD CONSTRAINT {constraint} CHECK (TRUE)")
        status = await repository.schema_status()
        assert f"{constraint}:definition" in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {TRANSITION_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(f"ALTER TABLE {TRANSITION_TABLE} ADD CONSTRAINT {constraint} CHECK ({canonical_shape})")

    await postgres.execute(f"DROP INDEX {index}")
    try:
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {EPOCH_TABLE} (strategy_lifecycle_id) WHERE state = 'TERMINAL'"
        )
        status = await repository.schema_status()
        assert f"{index}:predicate" in status.invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX IF EXISTS {index}")
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {EPOCH_TABLE} (strategy_lifecycle_id) WHERE state = 'ACTIVE'"
        )

    assert (await repository.schema_status()).ready
