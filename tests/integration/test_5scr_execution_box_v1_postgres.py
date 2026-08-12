"""Disposable-PostgreSQL gates for versioned shadow-only ExecutionBox V1."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest

from contracts.strategy_5scr_execution_box_v1 import (
    ExecutionBoxEvidenceV1,
    M1CandleAuthorityV1,
    execution_box_freeze_authority_hash,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    BOX_TABLE,
    Strategy5SCRExecutionBoxV1Repository,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _cleanup as _cleanup_p4,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _repository as _p4_repository,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _seed_parent_chain,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)


def _sha(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    )


def _m1(index: int, *, low: float = 1.1000, high: float = 1.1020) -> M1CandleAuthorityV1:
    opened = datetime(2026, 8, 12, 11, index, tzinfo=UTC)
    material = {
        "symbol": "EURUSD",
        "timeframe": "M1",
        "open_time_utc": opened,
        "close_time_utc": opened + timedelta(minutes=1),
        "open": low + 0.0005,
        "high": high,
        "low": low,
        "close": high - 0.0005,
    }
    payload: dict[str, Any] = {
        **material,
        "material_candle_hash": _sha(material),
        "source_content_hash": _sha({"source": index, "low": low, "high": high}),
        "canonical_row_id": 20_000 + index,
        "selected_raw_candle_id": 30_000 + index,
        "volume": 100.0,
        "tick_count": 20,
        "provider": "XM",
        "feed": "demo-account",
        "provider_timestamp_semantics": "PERIOD_OPEN",
        "selection_policy": "provider-priority.v1",
        "selection_rank": 1300,
        "is_closed": True,
        "price_authority": True,
    }
    provisional = M1CandleAuthorityV1.model_construct(
        candle_evidence_id="sha256:" + "0" * 64,
        **payload,
    )
    evidence_hash = _sha(provisional.model_dump(mode="json", exclude={"candle_evidence_id"}))
    return M1CandleAuthorityV1(candle_evidence_id=evidence_hash, **payload)


def _evidence(
    thesis: Any,
    *,
    index: int = 1,
    candles: tuple[M1CandleAuthorityV1, ...] | None = None,
    freeze: bool = False,
) -> ExecutionBoxEvidenceV1:
    payload: dict[str, Any] = dict(
        strategy_lifecycle_id=thesis.strategy_lifecycle_id,
        context_epoch_id=thesis.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        thesis_semantic_identity_hash=thesis.semantic_identity_hash,
        symbol=thesis.symbol,
        strategy_direction=thesis.strategy_direction,
        route_type=thesis.selected_route,
        observed_at_utc=datetime(2026, 8, 12, 12, index, tzinfo=UTC),
        material_m1_candles=candles or (_m1(0), _m1(1)),
        freeze_requested=freeze,
        freeze_reason="M1_ROUTE_GEOMETRY_CONFIRMED" if freeze else None,
        freeze_authority_hash=None,
        source_request_id=f"p5-request-{index}",
        source_deployment_id=f"deployment-{index}",
        source_replica_id=f"replica-{index}",
        source_cluster_id=f"cluster-{index}",
        telemetry_count=index,
        reference_price=1.101 + index / 100_000,
    )
    if freeze:
        provisional = ExecutionBoxEvidenceV1.model_construct(**payload)
        payload["freeze_authority_hash"] = execution_box_freeze_authority_hash(provisional)
    return ExecutionBoxEvidenceV1.model_validate(payload)


async def _seed(postgres: PoolBackedPostgres) -> tuple[str, Any, ExecutionBoxEvidenceV1]:
    lifecycle_id, _context_event, _context, thesis_evidence = await _seed_parent_chain(postgres)
    thesis_result = await _p4_repository(postgres).process_evidence(thesis_evidence)
    assert thesis_result.status == "PERSISTED" and thesis_result.thesis is not None
    return lifecycle_id, thesis_result.thesis, _evidence(thesis_result.thesis)


async def _cleanup(postgres: PoolBackedPostgres, lifecycle_id: str) -> None:
    try:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DISABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard")
        await postgres.execute(f"DELETE FROM {BOX_TABLE} WHERE strategy_lifecycle_id=$1", lifecycle_id)
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} ENABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard")
    await _cleanup_p4(postgres, lifecycle_id)


async def test_schema_ready_and_database_rejects_execution_authority(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    status = await repository.schema_status()
    assert status.ready, status
    lifecycle_id, _thesis, evidence = await _seed(postgres)
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.box is not None
        assert persisted.box.execution_authority is False
        with pytest.raises(postgres.check_violation_error) as exc:
            await postgres.execute(
                f"UPDATE {BOX_TABLE} SET execution_authority=true WHERE execution_box_id=$1",
                persisted.box.execution_box_id,
            )
        assert getattr(exc.value, "constraint_name", None) in {
            "ck_5scr_execution_box_immutable_v1",
            "ck_5scr_execution_box_shadow_only_v1",
        }
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_retry_restart_and_concurrency_create_one_logical_box(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        first, second = await asyncio.gather(
            repository.process_evidence(evidence),
            repository.process_evidence(evidence),
        )
        assert sorted((first.status, second.status)) == ["DUPLICATE", "PERSISTED"]
        restarted = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
        replay = await restarted.process_evidence(evidence)
        assert replay.status == "DUPLICATE"
        history = await restarted.load_history(thesis.strategy_thesis_id)
        assert len(history) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_material_revision_is_atomic_and_freeze_prevents_expansion(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        first = await repository.process_evidence(evidence)
        assert first.status == "PERSISTED" and first.box is not None
        revision = _evidence(
            thesis,
            index=2,
            candles=(_m1(0, low=1.0990), _m1(1)),
        )
        revised = await repository.process_evidence(revision)
        assert revised.status == "SUPERSEDED" and revised.box is not None
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert [(item.box_version, item.state) for item in history] == [
            (1, "SUPERSEDED"),
            (2, "BUILDING"),
        ]
        frozen = await repository.process_evidence(
            _evidence(thesis, index=3, candles=revision.material_m1_candles, freeze=True)
        )
        assert frozen.status == "FROZEN" and frozen.box is not None
        assert frozen.box.freeze_authority_hash is not None
        row = await postgres.fetchrow(
            f"SELECT freeze_authority_hash FROM {BOX_TABLE} WHERE execution_box_id=$1",
            frozen.box.execution_box_id,
        )
        assert row is not None and row["freeze_authority_hash"] == frozen.box.freeze_authority_hash
        rejected = await repository.process_evidence(_evidence(thesis, index=4, candles=(_m1(0, low=1.0900), _m1(1))))
        assert (rejected.status, rejected.reason_code) == (
            "REJECTED",
            "FROZEN_EXECUTION_BOX_IMMUTABLE",
        )
        active = await repository.load_active(thesis.strategy_thesis_id)
        assert active is not None and active.execution_box_id == frozen.box.execution_box_id
        assert (active.box_low, active.box_high) == (frozen.box.box_low, frozen.box.box_high)
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_failed_successor_insert_rolls_back_predecessor_supersession(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    trigger = "trg_5scr_p5_test_reject_successor"
    function = "strategy_5scr_p5_test_reject_successor"
    try:
        first = await repository.process_evidence(evidence)
        assert first.status == "PERSISTED" and first.box is not None
        await postgres.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.box_version > 1 THEN RAISE EXCEPTION 'FORCED_P5_SUCCESSOR_FAILURE'; END IF;
                RETURN NEW;
            END $$
            """
        )
        await postgres.execute(
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON {BOX_TABLE} FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        with pytest.raises(Exception, match="FORCED_P5_SUCCESSOR_FAILURE"):
            await repository.process_evidence(_evidence(thesis, index=2, candles=(_m1(0, low=1.0990), _m1(1))))
        active = await repository.load_active(thesis.strategy_thesis_id)
        assert active is not None and active.execution_box_id == first.box.execution_box_id
        assert active.state == "BUILDING"
        assert len(await repository.load_history(thesis.strategy_thesis_id)) == 1
    finally:
        await postgres.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {BOX_TABLE}")
        await postgres.execute(f"DROP FUNCTION IF EXISTS {function}()")
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_thesis_closes_box_and_replay_cannot_resurrect(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED"
        invalidated = await _p4_repository(postgres).invalidate_active(
            lifecycle_id,
            evidence.observed_at_utc + timedelta(minutes=10),
            "P5_PARENT_TEST",
        )
        assert invalidated.status == "INVALIDATED"
        reconciled = await repository.process_evidence(_evidence(thesis, index=2))
        assert reconciled.status == "INVALIDATED"
        replay = await Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres)).process_evidence(
            _evidence(thesis, index=3)
        )
        assert replay.status == "REJECTED"
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert len(history) == 1 and history[0].state == "INVALIDATED"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_fails_closed_when_shadow_constraint_is_weakened(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    constraint = "ck_5scr_execution_box_shadow_only_v1"
    try:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} CHECK (execution_authority IS NOT NULL)"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert constraint in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} "
            "CHECK (valid_for_execution IS FALSE AND execution_authority IS FALSE)"
        )
    assert (await repository.schema_status()).ready


async def test_readiness_fails_closed_when_guard_trigger_is_disabled(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    trigger = "trg_strategy_5scr_execution_boxes_v1_guard"
    try:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DISABLE TRIGGER {trigger}")
        status = await repository.schema_status()
        assert status.ready is False
        assert trigger in status.invalid_triggers
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} ENABLE TRIGGER {trigger}")
    assert (await repository.schema_status()).ready


async def test_a_to_b_to_a_persists_three_distinct_versions(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence_a = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        first = await repository.process_evidence(evidence_a)
        evidence_b = _evidence(thesis, index=2, candles=(_m1(0, low=1.0990), _m1(1)))
        second = await repository.process_evidence(evidence_b)
        third = await repository.process_evidence(_evidence(thesis, index=3))
        assert first.box is not None and second.box is not None and third.box is not None
        assert [first.box.box_version, second.box.box_version, third.box.box_version] == [1, 2, 3]
        assert first.box.material_box_hash == third.box.material_box_hash
        assert first.box.execution_box_id != third.box.execution_box_id
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert [(item.box_version, item.state) for item in history] == [
            (1, "SUPERSEDED"),
            (2, "SUPERSEDED"),
            (3, "BUILDING"),
        ]
    finally:
        await _cleanup(postgres, lifecycle_id)
