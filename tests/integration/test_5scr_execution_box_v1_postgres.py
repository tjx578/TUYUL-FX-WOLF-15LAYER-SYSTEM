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
    derive_execution_box_route_geometry_authority,
    execution_box_freeze_authority_hash,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    BOX_TABLE,
    OBSERVATION_TABLE,
    Strategy5SCRExecutionBoxV1Repository,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _cleanup as _cleanup_p4,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _repository as _p4_repository,
)
from tests.integration.test_5scr_directional_thesis_v1_postgres import (
    _seed_bidirectional_parent_chain,
    _seed_parent_chain,
    _sell_successor_evidence,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_P5_CANONICAL_ID_BASE = 100_000_000_000_000_000
_P5_RAW_ID_BASE = 200_000_000_000_000_000


def _sha(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    )


def _m1(index: int, *, low: float = 1.1000, high: float = 1.1020) -> M1CandleAuthorityV1:
    opened = datetime(2026, 8, 12, 11, index, tzinfo=UTC)
    role = index % 4
    if role == 0:  # reference
        open_price, close_price = low + 0.0004, high - 0.0004
    elif role == 1:  # break: bullish close above the reference high (1.1020)
        low, high, open_price, close_price = 1.1010, 1.1032, 1.1015, 1.1030
    elif role == 2:  # retest: probe below and hold the reference high
        low, high, open_price, close_price = 1.1015, 1.1028, 1.1024, 1.1022
    else:  # acceptance: bullish close beyond the reference high
        low, high, open_price, close_price = 1.1019, 1.1034, 1.1021, 1.1031
    material = {
        "symbol": "EURUSD",
        "timeframe": "M1",
        "open_time_utc": opened,
        "close_time_utc": opened + timedelta(minutes=1),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
    }
    payload: dict[str, Any] = {
        **material,
        "material_candle_hash": _sha(material),
        "source_content_hash": _sha({"source": index, "low": low, "high": high}),
        "canonical_row_id": _P5_CANONICAL_ID_BASE + index,
        "selected_raw_candle_id": _P5_RAW_ID_BASE + index,
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


def _m1_cohort(offset: int, *, reference_low: float = 1.1000) -> tuple[M1CandleAuthorityV1, ...]:
    """Four contiguous route roles with a distinct canonical identity cohort."""

    return (
        _m1(offset, low=reference_low),
        _m1(offset + 1),
        _m1(offset + 2),
        _m1(offset + 3),
    )


def _sell_m1_cohort(offset: int = 20) -> tuple[M1CandleAuthorityV1, ...]:
    """Four canonical SELL roles occurring after the SELL thesis decision clock."""

    start = datetime(2026, 8, 12, 13, 1, tzinfo=UTC)
    prices = (
        (1.1026, 1.1030, 1.1010, 1.1014),  # reference
        (1.1012, 1.1015, 1.0990, 1.0995),  # bearish break below reference low
        (1.1000, 1.1015, 1.0995, 1.1008),  # retest and rejection of break level
        (1.1007, 1.1009, 1.0988, 1.0992),  # bearish acceptance below break level
    )
    candles: list[M1CandleAuthorityV1] = []
    for role, (open_price, high, low, close_price) in enumerate(prices):
        index = offset + role
        opened = start + timedelta(minutes=role)
        material = {
            "symbol": "EURUSD",
            "timeframe": "M1",
            "open_time_utc": opened,
            "close_time_utc": opened + timedelta(minutes=1),
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
        }
        payload: dict[str, Any] = {
            **material,
            "material_candle_hash": _sha(material),
            "source_content_hash": _sha({"source": index, "direction": "SELL"}),
            "canonical_row_id": _P5_CANONICAL_ID_BASE + index,
            "selected_raw_candle_id": _P5_RAW_ID_BASE + index,
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
        candles.append(M1CandleAuthorityV1(candle_evidence_id=evidence_hash, **payload))
    return tuple(candles)


def _evidence(
    thesis: Any,
    *,
    index: int = 1,
    candles: tuple[M1CandleAuthorityV1, ...] | None = None,
    freeze: bool = False,
    observed_at_utc: datetime | None = None,
) -> ExecutionBoxEvidenceV1:
    resolved_candles = candles or _m1_cohort(0)
    geometry = derive_execution_box_route_geometry_authority(
        context_epoch_id=thesis.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        symbol=thesis.symbol,
        strategy_direction=thesis.strategy_direction,
        route_type=thesis.selected_route,
        material_m1_candles=resolved_candles,
        reference_candle_material_hash=resolved_candles[0].material_candle_hash,
        break_candle_material_hash=resolved_candles[1].material_candle_hash,
        retest_candle_material_hash=resolved_candles[2].material_candle_hash,
        acceptance_candle_material_hash=resolved_candles[3].material_candle_hash,
    )
    payload: dict[str, Any] = dict(
        strategy_lifecycle_id=thesis.strategy_lifecycle_id,
        context_epoch_id=thesis.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        thesis_semantic_identity_hash=thesis.semantic_identity_hash,
        symbol=thesis.symbol,
        strategy_direction=thesis.strategy_direction,
        route_type=thesis.selected_route,
        observed_at_utc=observed_at_utc or datetime(2026, 8, 12, 12, index, tzinfo=UTC),
        material_m1_candles=resolved_candles,
        route_geometry_authority=geometry,
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


async def _seed(
    postgres: PoolBackedPostgres,
    *,
    seed_m1: bool = True,
) -> tuple[str, Any, ExecutionBoxEvidenceV1]:
    lifecycle_id, _context_event, _context, thesis_evidence = await _seed_parent_chain(postgres)
    thesis_result = await _p4_repository(postgres).process_evidence(thesis_evidence)
    assert thesis_result.status == "PERSISTED" and thesis_result.thesis is not None
    evidence = _evidence(thesis_result.thesis)
    if seed_m1:
        await _insert_canonical_m1_evidence(postgres, evidence)
    return lifecycle_id, thesis_result.thesis, evidence


async def _cleanup(postgres: PoolBackedPostgres, lifecycle_id: str) -> None:
    try:
        await postgres.execute(
            f"ALTER TABLE {OBSERVATION_TABLE} DISABLE TRIGGER trg_strategy_5scr_execution_box_observations_v1_immutable"
        )
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DISABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard")
        await postgres.execute(
            f"DELETE FROM {OBSERVATION_TABLE} WHERE strategy_lifecycle_id=$1",
            lifecycle_id,
        )
        await postgres.execute(f"DELETE FROM {BOX_TABLE} WHERE strategy_lifecycle_id=$1", lifecycle_id)
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} ENABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard")
        await postgres.execute(
            f"ALTER TABLE {OBSERVATION_TABLE} ENABLE TRIGGER trg_strategy_5scr_execution_box_observations_v1_immutable"
        )
    await _cleanup_p4(postgres, lifecycle_id)
    await postgres.execute(
        "DELETE FROM canonical_candles WHERE id >= $1 AND id < $2",
        _P5_CANONICAL_ID_BASE,
        _P5_RAW_ID_BASE,
    )
    await postgres.execute(
        "DELETE FROM raw_provider_candles WHERE id >= $1 AND id < $2",
        _P5_RAW_ID_BASE,
        _P5_RAW_ID_BASE + _P5_CANONICAL_ID_BASE,
    )


async def _insert_canonical_m1(postgres: PoolBackedPostgres, candle: M1CandleAuthorityV1) -> None:
    """Insert the exact raw/canonical pair claimed by one M1 authority ref."""

    await postgres.execute(
        """
        INSERT INTO raw_provider_candles (
            id,provider,feed,symbol,timeframe,provider_timestamp,
            provider_timestamp_semantics,open_time,close_time,open,high,low,close,
            volume,tick_count,complete,payload_hash,metadata
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,true,$16,'{}'::jsonb
        )
        ON CONFLICT (id) DO UPDATE SET
            provider=EXCLUDED.provider,feed=EXCLUDED.feed,symbol=EXCLUDED.symbol,
            timeframe=EXCLUDED.timeframe,provider_timestamp=EXCLUDED.provider_timestamp,
            provider_timestamp_semantics=EXCLUDED.provider_timestamp_semantics,
            open_time=EXCLUDED.open_time,close_time=EXCLUDED.close_time,
            open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,close=EXCLUDED.close,
            volume=EXCLUDED.volume,tick_count=EXCLUDED.tick_count,complete=EXCLUDED.complete,
            payload_hash=EXCLUDED.payload_hash
        """,
        candle.selected_raw_candle_id,
        candle.provider,
        candle.feed,
        candle.symbol,
        candle.timeframe,
        candle.open_time_utc,
        candle.provider_timestamp_semantics,
        candle.open_time_utc,
        candle.close_time_utc,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        candle.tick_count,
        candle.source_content_hash.removeprefix("sha256:"),
    )
    await postgres.execute(
        """
        INSERT INTO canonical_candles (
            id,symbol,timeframe,open_time,close_time,open,high,low,close,volume,
            tick_count,complete,selected_provider,selected_feed,
            provider_timestamp_semantics,selected_raw_candle_id,selection_policy,
            selection_rank,content_hash
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,true,$12,$13,$14,$15,$16,$17,$18
        )
        ON CONFLICT (symbol,timeframe,open_time) DO UPDATE SET
            close_time=EXCLUDED.close_time,open=EXCLUDED.open,high=EXCLUDED.high,
            low=EXCLUDED.low,close=EXCLUDED.close,volume=EXCLUDED.volume,
            tick_count=EXCLUDED.tick_count,complete=EXCLUDED.complete,
            selected_provider=EXCLUDED.selected_provider,selected_feed=EXCLUDED.selected_feed,
            provider_timestamp_semantics=EXCLUDED.provider_timestamp_semantics,
            selected_raw_candle_id=EXCLUDED.selected_raw_candle_id,
            selection_policy=EXCLUDED.selection_policy,selection_rank=EXCLUDED.selection_rank,
            content_hash=EXCLUDED.content_hash
        """,
        candle.canonical_row_id,
        candle.symbol,
        candle.timeframe,
        candle.open_time_utc,
        candle.close_time_utc,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        candle.tick_count,
        candle.provider,
        candle.feed,
        candle.provider_timestamp_semantics,
        candle.selected_raw_candle_id,
        candle.selection_policy,
        candle.selection_rank,
        candle.source_content_hash.removeprefix("sha256:"),
    )


async def _insert_canonical_m1_evidence(postgres: PoolBackedPostgres, evidence: ExecutionBoxEvidenceV1) -> None:
    for candle in evidence.material_m1_candles:
        await _insert_canonical_m1(postgres, candle)


async def _cleanup_canonical_m1(postgres: PoolBackedPostgres, evidence: ExecutionBoxEvidenceV1) -> None:
    canonical_ids = [item.canonical_row_id for item in evidence.material_m1_candles]
    raw_ids = [item.selected_raw_candle_id for item in evidence.material_m1_candles]
    await postgres.execute("DELETE FROM canonical_candles WHERE id=ANY($1::bigint[])", canonical_ids)
    await postgres.execute("DELETE FROM raw_provider_candles WHERE id=ANY($1::bigint[])", raw_ids)


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


async def test_database_rejects_direct_authority_on_each_p5_table(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.box is not None
        observation_id = await postgres.fetchrow(
            f"SELECT observation_id FROM {OBSERVATION_TABLE} WHERE execution_box_id=$1",
            persisted.box.execution_box_id,
        )
        assert observation_id is not None
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {BOX_TABLE} SET valid_for_execution=true WHERE execution_box_id=$1",
                persisted.box.execution_box_id,
            )
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {OBSERVATION_TABLE} SET execution_authority=true WHERE observation_id=$1",
                observation_id["observation_id"],
            )
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


async def test_sell_route_persists_freezes_and_restarts_shadow_only(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, buy_evidence = await _seed_bidirectional_parent_chain(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    sell_candles = _sell_m1_cohort()
    try:
        sell_parent = await _p4_repository(postgres).process_evidence(_sell_successor_evidence(buy_evidence, context))
        assert sell_parent.status == "PERSISTED" and sell_parent.thesis is not None
        assert sell_parent.thesis.strategy_direction == "SELL"

        opened_evidence = _evidence(
            sell_parent.thesis,
            index=20,
            candles=sell_candles,
            observed_at_utc=datetime(2026, 8, 12, 13, 6, tzinfo=UTC),
        )
        await _insert_canonical_m1_evidence(postgres, opened_evidence)
        opened = await repository.process_evidence(opened_evidence)
        assert opened.status == "PERSISTED" and opened.box is not None
        assert opened.box.strategy_direction == "SELL"
        assert opened.box.route_type == "SELL_BREAK_RETEST"
        assert opened.box.execution_authority is False
        assert opened.box.valid_for_execution is False

        freeze_evidence = _evidence(
            sell_parent.thesis,
            index=21,
            candles=sell_candles,
            freeze=True,
            observed_at_utc=datetime(2026, 8, 12, 13, 7, tzinfo=UTC),
        )
        frozen = await repository.process_evidence(freeze_evidence)
        assert frozen.status == "FROZEN" and frozen.box is not None
        restarted = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
        recovered = await restarted.load_active(sell_parent.thesis.strategy_thesis_id)
        assert recovered == frozen.box
        replay = await restarted.process_evidence(freeze_evidence)
        assert replay.status == "DUPLICATE" and replay.box == frozen.box
        assert len(await restarted.load_history(sell_parent.thesis.strategy_thesis_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_admitted_m1_snapshot_survives_later_canonical_table_correction(
    postgres: PoolBackedPostgres,
) -> None:
    """P5 freezes admission-time M1 authority; canonical corrections govern only future admissions."""

    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.box is not None
        formation = opened.box
        corrected = evidence.material_m1_candles[0]
        await postgres.execute(
            "UPDATE canonical_candles SET selected_provider='XM_CORRECTED' WHERE id=$1",
            corrected.canonical_row_id,
        )

        restarted = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
        assert await restarted.load_active(thesis.strategy_thesis_id) == formation
        assert await restarted.load_history(thesis.strategy_thesis_id) == (formation,)
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
            candles=_m1_cohort(4, reference_low=1.0990),
        )
        await _insert_canonical_m1_evidence(postgres, revision)
        revised = await repository.process_evidence(revision)
        assert revised.status == "SUPERSEDED" and revised.box is not None, revised
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
        expansion = _evidence(thesis, index=4, candles=_m1_cohort(8, reference_low=1.0900))
        await _insert_canonical_m1_evidence(postgres, expansion)
        rejected = await repository.process_evidence(expansion)
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
            revision = _evidence(thesis, index=2, candles=_m1_cohort(4, reference_low=1.0990))
            await _insert_canonical_m1_evidence(postgres, revision)
            await repository.process_evidence(revision)
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
        evidence_b = _evidence(thesis, index=2, candles=_m1_cohort(4, reference_low=1.0990))
        await _insert_canonical_m1_evidence(postgres, evidence_b)
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


async def test_nonexistent_or_forged_m1_authority_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres, seed_m1=False)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        rejected = await repository.process_evidence(evidence)
        assert rejected.status == "REJECTED"
        assert rejected.reason_code == "CANONICAL_M1_CANDLE_MISSING"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()

        await _insert_canonical_m1_evidence(postgres, evidence)
        forged = _evidence(thesis, index=2, candles=(_m1(0, low=1.0990), _m1(1), _m1(2), _m1(3)))
        rejected = await repository.process_evidence(forged)
        assert rejected.status == "QUARANTINED"
        assert rejected.reason_code == "CANONICAL_M1_CANDLE_DRIFT"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup_canonical_m1(postgres, evidence)
        await _cleanup(postgres, lifecycle_id)


async def test_canonical_m1_mixed_symbol_or_noncontiguous_coverage_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    candle = evidence.material_m1_candles[1]
    try:
        await postgres.execute(
            "UPDATE canonical_candles SET symbol='GBPUSD' WHERE id=$1",
            candle.canonical_row_id,
        )
        result = await repository.process_evidence(evidence)
        assert result.status == "QUARANTINED"
        assert result.reason_code == "CANONICAL_M1_CANDLE_DRIFT"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()

        await postgres.execute(
            "UPDATE canonical_candles SET symbol=$2 WHERE id=$1",
            candle.canonical_row_id,
            candle.symbol,
        )
        await postgres.execute(
            "UPDATE canonical_candles SET open_time=open_time+interval '30 seconds',"
            "close_time=close_time+interval '30 seconds' WHERE id=$1",
            candle.canonical_row_id,
        )
        result = await repository.process_evidence(evidence)
        assert result.status == "QUARANTINED"
        assert result.reason_code == "CANONICAL_M1_CANDLE_DRIFT"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize(
    ("column", "replacement", "_expected_reason"),
    (
        ("selected_provider", "OTHER_PROVIDER", "M1_CANONICAL_PROVIDER_DRIFT"),
        ("timeframe", "M5", "M1_CANONICAL_TIMEFRAME_DRIFT"),
        ("close_time", datetime(2026, 8, 12, 11, 5, tzinfo=UTC), "M1_CANONICAL_WINDOW_DRIFT"),
    ),
)
async def test_canonical_m1_provider_timeframe_and_window_drift_fail_closed(
    postgres: PoolBackedPostgres,
    column: str,
    replacement: object,
    _expected_reason: str,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        candle = evidence.material_m1_candles[0]
        await postgres.execute(
            f"UPDATE canonical_candles SET {column}=$2 WHERE id=$1",
            candle.canonical_row_id,
            replacement,
        )
        rejected = await repository.process_evidence(evidence)
        assert rejected.status == "QUARANTINED"
        assert rejected.reason_code == "CANONICAL_M1_CANDLE_DRIFT"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup_canonical_m1(postgres, evidence)
        await _cleanup(postgres, lifecycle_id)


async def test_nonmaterial_refresh_advances_watermark_and_rejects_late_material_event(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, first = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(first)
        assert opened.status == "PERSISTED" and opened.box is not None
        newest = _evidence(thesis, index=3)
        refreshed = await repository.process_evidence(newest)
        assert refreshed.status == "NO_CHANGE" and refreshed.box is not None
        assert refreshed.box.last_observed_at_utc == newest.observed_at_utc
        assert refreshed.box.box_version == opened.box.box_version

        late_candles = _m1_cohort(4, reference_low=1.0990)
        for item in late_candles:
            await _insert_canonical_m1(postgres, item)
        late = _evidence(thesis, index=2, candles=late_candles)
        rejected = await repository.process_evidence(late)
        assert (rejected.status, rejected.reason_code) == (
            "REJECTED",
            "STALE_EXECUTION_BOX_EVIDENCE",
        )
        active = await Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres)).load_active(thesis.strategy_thesis_id)
        assert active is not None and active.execution_box_id == opened.box.execution_box_id
        assert active.last_observed_at_utc == newest.observed_at_utc
    finally:
        await _cleanup_canonical_m1(postgres, first)
        await _cleanup(postgres, lifecycle_id)


async def test_equal_time_conflicting_material_is_quarantined(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, first = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(first)
        assert opened.status == "PERSISTED" and opened.box is not None
        conflict_candles = _m1_cohort(4, reference_low=1.0990)
        for item in conflict_candles:
            await _insert_canonical_m1(postgres, item)
        conflict_payload = _evidence(thesis, index=1, candles=conflict_candles).model_dump(mode="python")
        conflict_payload["source_request_id"] = "same-clock-distinct-request"
        conflict = ExecutionBoxEvidenceV1.model_validate(conflict_payload)
        rejected = await repository.process_evidence(conflict)
        assert rejected.status == "QUARANTINED"
        assert rejected.reason_code == "AMBIGUOUS_EXECUTION_BOX_EVIDENCE_CLOCK"
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert len(history) == 1 and history[0].execution_box_id == opened.box.execution_box_id
    finally:
        await _cleanup_canonical_m1(postgres, first)
        await _cleanup(postgres, lifecycle_id)


async def test_pre_thesis_m1_and_observation_are_rejected_without_writes(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, _evidence_after = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    old_candles = (_m1(0), _m1(1), _m1(2), _m1(3))
    old = _evidence(thesis, index=1, candles=old_candles).model_copy(
        update={"observed_at_utc": thesis.created_at_utc - timedelta(minutes=1)}
    )
    await _insert_canonical_m1_evidence(postgres, old)
    try:
        rejected = await repository.process_evidence(old)
        assert rejected.status == "REJECTED"
        assert rejected.reason_code == "EXECUTION_BOX_PARENT_CLOCK_PRECEDES_THESIS"
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup_canonical_m1(postgres, old)
        await _cleanup(postgres, lifecycle_id)


async def test_route_geometry_authority_cannot_claim_unrelated_m1_roles(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        geometry = evidence.route_geometry_authority.model_copy(
            update={"break_candle_material_hash": "sha256:" + "f" * 64}
        )
        malformed = evidence.model_copy(update={"route_geometry_authority": geometry})
        with pytest.raises(ValueError, match="route geometry"):
            ExecutionBoxEvidenceV1.model_validate(malformed.model_dump(mode="python"))
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_route_geometry_rejects_doji_that_never_breaks_reference_level(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        candles = list(evidence.material_m1_candles)
        break_candle = candles[1]
        material = {
            "symbol": break_candle.symbol,
            "timeframe": break_candle.timeframe,
            "open_time_utc": break_candle.open_time_utc,
            "close_time_utc": break_candle.close_time_utc,
            "open": 1.1015,
            "high": 1.1020,
            "low": 1.1010,
            "close": 1.1015,
        }
        payload = break_candle.model_dump(mode="python", exclude={"candle_evidence_id", "material_candle_hash"})
        payload.update(material_candle_hash=_sha(material), **material)
        provisional = M1CandleAuthorityV1.model_construct(
            candle_evidence_id="sha256:" + "0" * 64,
            **payload,
        )
        payload["candle_evidence_id"] = _sha(provisional.model_dump(mode="json", exclude={"candle_evidence_id"}))
        candles[1] = M1CandleAuthorityV1.model_validate(payload)
        with pytest.raises(ValueError, match="break candle"):
            _evidence(thesis, index=9, candles=tuple(candles))
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_full_parent_payload_drift_fails_closed_before_box_write(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        await postgres.execute(
            "ALTER TABLE strategy_5scr_directional_theses_v1 "
            "DISABLE TRIGGER trg_strategy_5scr_directional_theses_v1_guard"
        )
        await postgres.execute(
            "UPDATE strategy_5scr_directional_theses_v1 "
            "SET payload=jsonb_set(payload,'{selected_route}','\"SELL_BREAK_RETEST\"'::jsonb) "
            "WHERE strategy_thesis_id=$1",
            thesis.strategy_thesis_id,
        )
        with pytest.raises(Exception, match="DIRECTIONAL_THESIS_.*DRIFT|DIRECTIONAL_THESIS_PAYLOAD"):
            await repository.process_evidence(evidence)
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
    finally:
        await postgres.execute(
            "ALTER TABLE strategy_5scr_directional_theses_v1 "
            "ENABLE TRIGGER trg_strategy_5scr_directional_theses_v1_guard"
        )
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_parent_closes_existing_box_before_incoming_m1_validation(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.box is not None
        invalidated = await _p4_repository(postgres).invalidate_active(
            lifecycle_id,
            evidence.observed_at_utc + timedelta(minutes=5),
            "P5_TERMINAL_PRECEDENCE",
        )
        assert invalidated.status == "INVALIDATED"
        await _cleanup_canonical_m1(postgres, evidence)

        malformed = _evidence(thesis, index=7)
        result = await repository.process_evidence(malformed)
        assert result.status == "INVALIDATED"
        assert result.reason_code == "EXECUTION_BOX_PARENT_NOT_ACTIVE"
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert len(history) == 1 and history[0].state == "INVALIDATED"
        replay = await Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres)).process_evidence(malformed)
        assert replay.status == "REJECTED"
        assert len(await repository.load_history(thesis.strategy_thesis_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_exact_freeze_replay_and_restart_are_idempotent(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, first = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(first)
        assert opened.status == "PERSISTED" and opened.box is not None
        freeze = _evidence(thesis, index=2, freeze=True)
        frozen = await repository.process_evidence(freeze)
        assert frozen.status == "FROZEN" and frozen.box is not None
        replay = await Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres)).process_evidence(freeze)
        assert replay.status == "DUPLICATE" and replay.box == frozen.box
        history = await repository.load_history(thesis.strategy_thesis_id)
        assert len(history) == 1 and history[0].state == "FROZEN"
        assert history[0].state_version == frozen.box.state_version
    finally:
        await _cleanup_canonical_m1(postgres, first)
        await _cleanup(postgres, lifecycle_id)


async def test_exact_replay_remains_duplicate_after_parent_liveness_advances(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.box is not None
        await postgres.execute(
            "ALTER TABLE strategy_5scr_directional_theses_v1 "
            "DISABLE TRIGGER trg_strategy_5scr_directional_theses_v1_guard"
        )
        advanced = evidence.observed_at_utc + timedelta(minutes=30)
        await postgres.execute(
            "UPDATE strategy_5scr_directional_theses_v1 SET "
            "liveness_checked_through=$2::timestamptz,"
            "payload=jsonb_set("
            "jsonb_set(payload,'{liveness_checked_through_utc}',to_jsonb($3::text)),"
            "'{state_version}',to_jsonb(state_version+1)),"
            "state_version=state_version+1 WHERE strategy_thesis_id=$1",
            thesis.strategy_thesis_id,
            advanced,
            advanced.isoformat(),
        )
        await postgres.execute(
            "ALTER TABLE strategy_5scr_directional_theses_v1 "
            "ENABLE TRIGGER trg_strategy_5scr_directional_theses_v1_guard"
        )
        replay = await Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert replay.status == "DUPLICATE"
        assert len(await repository.load_history(thesis.strategy_thesis_id)) == 1
    finally:
        await postgres.execute(
            "ALTER TABLE strategy_5scr_directional_theses_v1 "
            "ENABLE TRIGGER trg_strategy_5scr_directional_theses_v1_guard"
        )
        await _cleanup(postgres, lifecycle_id)


async def test_frozen_exact_request_with_lineage_drift_is_quarantined(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED"
        freeze = _evidence(thesis, index=2, freeze=True)
        frozen = await repository.process_evidence(freeze)
        assert frozen.status == "FROZEN" and frozen.box is not None
        drift = freeze.model_copy(update={"source_deployment_id": "drifted-deployment"})
        rejected = await repository.process_evidence(drift)
        assert (rejected.status, rejected.reason_code) == (
            "QUARANTINED",
            "EXECUTION_BOX_REQUEST_EVIDENCE_DRIFT",
        )
        active = await repository.load_active(thesis.strategy_thesis_id)
        assert active is not None and active.execution_box_id == frozen.box.execution_box_id
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_successor_sequence_and_identity_remain_distinct_across_a_b_a(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence_a = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    evidence_b = _evidence(thesis, index=2, candles=_m1_cohort(4, reference_low=1.0990))
    try:
        first = await repository.process_evidence(evidence_a)
        assert first.box is not None
        await _insert_canonical_m1_evidence(postgres, evidence_b)
        second = await repository.process_evidence(evidence_b)
        assert second.box is not None
        third = await repository.process_evidence(_evidence(thesis, index=3))
        assert third.box is not None
        assert [first.box.box_sequence, second.box.box_sequence, third.box.box_sequence] == [1, 2, 3]
        assert [first.box.box_version, second.box.box_version, third.box.box_version] == [1, 2, 3]
        assert len({first.box.execution_box_id, second.box.execution_box_id, third.box.execution_box_id}) == 3
        assert first.box.material_box_hash == third.box.material_box_hash
        assert second.box.previous_execution_box_id == first.box.execution_box_id
        assert third.box.previous_execution_box_id == second.box.execution_box_id
    finally:
        await _cleanup_canonical_m1(postgres, evidence_a)
        await _cleanup_canonical_m1(postgres, evidence_b)
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_rejects_same_name_weakened_state_constraint(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    constraint = "ck_5scr_execution_box_state_v1"
    try:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} "
            "CHECK (strategy_direction IN ('BUY','SELL') AND "
            "state IN ('BUILDING','FROZEN','SUPERSEDED','INVALIDATED','CONSUMED','EXPIRED','ROGUE'))"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert constraint in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} "
            "CHECK (strategy_direction IN ('BUY','SELL') AND "
            "state IN ('BUILDING','FROZEN','SUPERSEDED','INVALIDATED','CONSUMED','EXPIRED'))"
        )
    assert (await repository.schema_status()).ready


async def test_database_rejects_cross_thesis_or_skipped_predecessor_lineage(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.box is not None
        row = await postgres.fetchrow(
            f"SELECT * FROM {BOX_TABLE} WHERE execution_box_id=$1",
            opened.box.execution_box_id,
        )
        assert row is not None
        payload = dict(row)
        payload.update(
            execution_box_id="5scr-execution-box:" + "f" * 32,
            box_sequence=opened.box.box_sequence + 2,
            box_version=opened.box.box_version + 2,
            previous_execution_box_id=opened.box.execution_box_id,
            previous_box_sequence=opened.box.box_sequence,
            previous_box_version=opened.box.box_version,
        )
        with pytest.raises(postgres.check_violation_error) as exc_info:
            await postgres.execute(
                f"""
                INSERT INTO {BOX_TABLE} (
                    execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,
                    box_sequence,box_version,previous_execution_box_id,previous_box_sequence,
                    previous_box_version,symbol,strategy_direction,route_type,state,box_low,box_high,
                    opened_at,material_box_hash,formation_evidence_hash,evidence_hash,thesis_semantic_identity_hash,
                    source_m1_ids,source_m1_evidence_ids,last_observed_at,state_version,rule_version,
                    valid_for_execution,execution_authority,payload,evidence_payload,latest_evidence_payload
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'BUILDING',$13,$14,$15,$16,$17,$18,$19,
                    $20,$21,$22,1,$23,false,false,$24,$25,$26
                )
                """,
                payload["execution_box_id"],
                payload["strategy_lifecycle_id"],
                payload["context_epoch_id"],
                payload["strategy_thesis_id"],
                payload["box_sequence"],
                payload["box_version"],
                payload["previous_execution_box_id"],
                payload["previous_box_sequence"],
                payload["previous_box_version"],
                payload["symbol"],
                payload["strategy_direction"],
                payload["route_type"],
                payload["box_low"],
                payload["box_high"],
                payload["opened_at"],
                payload["material_box_hash"],
                payload["formation_evidence_hash"],
                payload["evidence_hash"],
                payload["thesis_semantic_identity_hash"],
                payload["source_m1_ids"],
                payload["source_m1_evidence_ids"],
                payload["last_observed_at"],
                payload["rule_version"],
                payload["payload"],
                payload["evidence_payload"],
                payload.get("latest_evidence_payload", payload["evidence_payload"]),
            )
        assert getattr(exc_info.value, "constraint_name", None) == "ck_5scr_execution_box_lineage_v1"
        assert len(await repository.load_history(thesis.strategy_thesis_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_observation_ledger_is_append_only_and_shadow_only(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.box is not None
        observation = await postgres.fetchrow(
            f"SELECT * FROM {OBSERVATION_TABLE} WHERE execution_box_id=$1",
            persisted.box.execution_box_id,
        )
        assert observation is not None
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {OBSERVATION_TABLE} SET execution_authority=true WHERE observation_id=$1",
                observation["observation_id"],
            )
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"DELETE FROM {OBSERVATION_TABLE} WHERE observation_id=$1",
                observation["observation_id"],
            )
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_observation_ledger_rejects_scope_forged_for_a_real_box(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.box is not None
        with pytest.raises(postgres.foreign_key_violation_error) as exc:
            await postgres.execute(
                f"""
                INSERT INTO {OBSERVATION_TABLE} (
                    observation_id,execution_box_id,strategy_lifecycle_id,context_epoch_id,
                    strategy_thesis_id,symbol,observed_at,source_request_id,evidence_hash,
                    material_box_hash,outcome,evidence_payload,execution_authority
                ) VALUES ($1,$2,$3,$4,$5,'GBPUSD',$6,$7,$8,$9,'DUPLICATE',$10::jsonb,false)
                """,
                "5scr-execution-box-observation:" + "f" * 32,
                persisted.box.execution_box_id,
                persisted.box.strategy_lifecycle_id,
                persisted.box.context_epoch_id,
                persisted.box.strategy_thesis_id,
                evidence.observed_at_utc + timedelta(minutes=1),
                "forged-scope-request",
                persisted.box.evidence_hash,
                persisted.box.material_box_hash,
                json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            )
        assert getattr(exc.value, "constraint_name", None) == "fk_5scr_execution_box_observation_box_v1"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_durable_lifecycle_symbol_drift_rejects_box_authority(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, evidence = await _seed(postgres)
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    try:
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 SET symbol='GBPUSD' WHERE strategy_lifecycle_id=$1",
            lifecycle_id,
        )
        rejected = await repository.process_evidence(evidence)
        assert (rejected.status, rejected.reason_code) == (
            "REJECTED",
            "CANONICAL_LIFECYCLE_SCOPE_MISMATCH",
        )
        assert await repository.load_history(thesis.strategy_thesis_id) == ()
        count = await postgres.fetchrow(
            f"SELECT COUNT(*) AS count FROM {OBSERVATION_TABLE} WHERE strategy_lifecycle_id=$1",
            lifecycle_id,
        )
        assert count is not None and int(count["count"]) == 0
    finally:
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 SET symbol='EURUSD' WHERE strategy_lifecycle_id=$1",
            lifecycle_id,
        )
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_rejects_same_name_weakened_active_index(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    index = "uq_5scr_execution_box_active_lifecycle_v1"
    try:
        await postgres.execute(f"DROP INDEX {index}")
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {BOX_TABLE}(strategy_lifecycle_id) "
            "WHERE state IN ('BUILDING','FROZEN') AND execution_authority IS TRUE"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert index in status.invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX IF EXISTS {index}")
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {BOX_TABLE}(strategy_lifecycle_id) WHERE state IN ('BUILDING','FROZEN')"
        )
    assert (await repository.schema_status()).ready


async def test_readiness_rejects_same_name_noop_guard_trigger(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    trigger = "trg_strategy_5scr_execution_boxes_v1_guard"
    function = "strategy_5scr_guard_execution_box_v1"
    production_definitions = await postgres.fetchrow(
        """
        SELECT pg_get_functiondef(t.tgfoid) AS function_definition,
               pg_get_triggerdef(t.oid) AS trigger_definition
        FROM pg_trigger t
        WHERE t.tgname=$1 AND t.tgrelid=$2::regclass AND NOT t.tgisinternal
        """,
        trigger,
        BOX_TABLE,
    )
    assert production_definitions is not None
    try:
        await postgres.execute(f"DROP TRIGGER {trigger} ON {BOX_TABLE}")
        await postgres.execute(f"DROP FUNCTION {function}()")
        await postgres.execute(
            f"""
            CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                -- Retain legacy marker strings while deliberately allowing every mutation:
                -- EXECUTION_BOX_GEOMETRY_IMMUTABLE EXECUTION_BOX_TRANSITION_INVALID
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END $$
            """
        )
        await postgres.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {BOX_TABLE} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert trigger in status.invalid_triggers
    finally:
        await postgres.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {BOX_TABLE}")
        await postgres.execute(f"DROP FUNCTION IF EXISTS {function}()")
        # Restore byte-for-byte semantics captured from the migrated disposable DB,
        # so this readiness negative cannot silently lag behind a migration repair.
        await postgres.execute(production_definitions["function_definition"])
        await postgres.execute(production_definitions["trigger_definition"])
    assert (await repository.schema_status()).ready


async def test_readiness_rejects_previous_box_fk_without_same_thesis_scope(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    constraint = "fk_5scr_execution_box_previous_v1"
    try:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY(previous_execution_box_id) REFERENCES {BOX_TABLE}(execution_box_id)"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert constraint in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {BOX_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {BOX_TABLE} ADD CONSTRAINT {constraint} "
            "FOREIGN KEY(previous_execution_box_id,strategy_lifecycle_id,context_epoch_id,"
            "strategy_thesis_id,symbol,strategy_direction,previous_box_sequence,previous_box_version) "
            f"REFERENCES {BOX_TABLE}(execution_box_id,strategy_lifecycle_id,context_epoch_id,"
            "strategy_thesis_id,symbol,strategy_direction,box_sequence,box_version) ON DELETE RESTRICT"
        )
    assert (await repository.schema_status()).ready


async def test_readiness_inherits_exact_parent_schema_status(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    constraint = "ck_5scr_thesis_shadow_only_v1"
    try:
        await postgres.execute(f"ALTER TABLE strategy_5scr_directional_theses_v1 DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE strategy_5scr_directional_theses_v1 ADD CONSTRAINT {constraint} "
            "CHECK (valid_for_execution IS NOT NULL AND execution_authority IS NOT NULL)"
        )
        status = await repository.schema_status()
        assert status.ready is False
        assert any(item.startswith(f"p4:{constraint}") for item in status.invalid_constraints)
    finally:
        await postgres.execute(
            f"ALTER TABLE strategy_5scr_directional_theses_v1 DROP CONSTRAINT IF EXISTS {constraint}"
        )
        await postgres.execute(
            f"ALTER TABLE strategy_5scr_directional_theses_v1 ADD CONSTRAINT {constraint} "
            "CHECK (direction_immutable IS TRUE AND valid_for_execution IS FALSE "
            "AND execution_authority IS FALSE)"
        )
    assert (await repository.schema_status()).ready
