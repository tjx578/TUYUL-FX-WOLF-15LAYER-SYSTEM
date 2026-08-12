"""Disposable-PostgreSQL gates for immutable DirectionalThesis P4."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from analysis.strategy_5scr_directional_thesis_v1 import (
    build_directional_thesis_proofs,
    candle_evidence_hash,
)
from analysis.strategy_5scr_structural_proof_provider_v1 import candle_authority_from_row
from contracts.strategy_5scr_context_epoch_v1 import (
    ContextCandleAuthorityV1,
    MaterialContextEvidenceV1,
    StrategyContextEpochV1,
)
from contracts.strategy_5scr_directional_thesis_v1 import (
    ClosedCandleAuthorityRefV1,
    DirectionalThesisEvidenceV1,
    PressureDirectionAuthorityV1,
    RouteDirectionAuthorizationV1,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from storage.strategy_5scr_context_epoch_v1_repository import (
    EPOCH_TABLE,
    TRANSITION_TABLE,
    StrategyContextEpochV1Repository,
)
from storage.strategy_5scr_directional_thesis_v1_repository import (
    H1_PROOF_TABLE,
    M15_PROOF_TABLE,
    THESIS_TABLE,
    DirectionalThesisV1IntegrityError,
    Strategy5SCRDirectionalThesisV1Repository,
)
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

START = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
SYMBOL = "EURUSD"
ROUTE = "BUY_BREAK_RETEST"
SELL_ROUTE = "SELL_BREAK_RETEST"


def _sha256(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _lineage_refresh(
    candle: ClosedCandleAuthorityRefV1,
    *,
    suffix: str,
) -> ClosedCandleAuthorityRefV1:
    payload = candle.model_dump(mode="python")
    payload.update(
        canonical_row_id=(candle.canonical_row_id or 0) + 1_000_000,
        selected_raw_candle_id=(candle.selected_raw_candle_id or 0) + 1_000_000,
        provider="XM_RESELECTED",
        feed=f"lineage-refresh-{suffix}",
        source_content_hash=_sha256(f"lineage-refresh-{suffix}"),
        volume=candle.volume + 100,
        tick_count=candle.tick_count + 10,
        candle_evidence_id="sha256:" + ("0" * 64),
    )
    provisional = ClosedCandleAuthorityRefV1.model_validate(payload)
    return provisional.model_copy(update={"candle_evidence_id": candle_evidence_hash(provisional)})


def _next_pressure_authority(evidence: DirectionalThesisEvidenceV1) -> PressureDirectionAuthorityV1:
    return PressureDirectionAuthorityV1(
        mode="RADAR_ONLY",
        contract_status="RADAR_ONLY",
        raw_pressure_direction=evidence.strategy_direction,
        source_event_ids=(f"pressure-authority-refresh-{uuid4().hex}",),
        rule_version="pressure-authority.v2",
        observed_at_utc=evidence.decision_at_utc - timedelta(minutes=10),
        valid_until_utc=evidence.decision_at_utc + timedelta(hours=1),
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid4().hex}"


def _appended_candle(
    evidence: DirectionalThesisEvidenceV1,
    *,
    row_id: int,
    close: float,
    low: float,
    high: float,
) -> Any:
    previous = evidence.m15_candles[-1]
    return _closed_candle(
        row_id=row_id,
        timeframe="M15",
        open_at=previous.close_time_utc,
        open_price=previous.close,
        high=high,
        low=low,
        close=close,
    )


def _repository(postgres: PoolBackedPostgres) -> Strategy5SCRDirectionalThesisV1Repository:
    return Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres))


def _lifecycle_repository(postgres: PoolBackedPostgres) -> StrategyLifecycleV2Repository:
    return StrategyLifecycleV2Repository(pg=cast(Any, postgres))


def _context_repository(postgres: PoolBackedPostgres) -> StrategyContextEpochV1Repository:
    return StrategyContextEpochV1Repository(pg=cast(Any, postgres))


def _context_candle(timeframe: str) -> ContextCandleAuthorityV1:
    duration = timedelta(days=1) if timeframe == "D1" else timedelta(hours=4)
    close_at = START - timedelta(hours=4)
    return ContextCandleAuthorityV1(
        candle_id=f"{SYMBOL}:{timeframe}:{uuid4().hex}",
        symbol=SYMBOL,
        timeframe=cast(Any, timeframe),
        open_time_utc=close_at - duration,
        close_time_utc=close_at,
        complete=True,
        provider="XM",
        provider_timestamp_semantics="PERIOD_OPEN",
        provider_session_lineage_valid=True,
        structural_authority=True,
    )


def _context_evidence(
    event_id: str,
    *,
    observed_at: datetime = START,
    bidirectional: bool = False,
) -> MaterialContextEvidenceV1:
    return MaterialContextEvidenceV1(
        source_pressure_event_id=event_id,
        source_event_ids=(event_id,),
        symbol=SYMBOL,
        observed_at_utc=observed_at,
        d1_candles=(_context_candle("D1"),),
        h4_candles=(_context_candle("H4"),),
        daily_bias="BULLISH",
        h4_structure="BULLISH_EXPANSION",
        price_location="DISCOUNT",
        liquidity_state="SELLSIDE_SWEPT",
        direction_domain="BOTH_CONDITIONAL" if bidirectional else "BUY_ONLY",
        allowed_routes=tuple(sorted((ROUTE, SELL_ROUTE))) if bidirectional else (ROUTE,),
        blocked_routes=() if bidirectional else ("SELL_BREAKOUT_CHASE",),
        target_map_version="targets-v1",
        structural_invalidation_version="invalidation-v1",
    )


def _lifecycle(lifecycle_id: str) -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id=lifecycle_id,
        symbol=SYMBOL,
        state="ANALYSIS_OPEN",
        direction_state="BUY",
        opened_at_utc=START - timedelta(hours=1),
        last_event_at_utc=START,
        last_continuity_event_at_utc=START,
        last_material_event_at_utc=START,
        material_state_hash="c" * 64,
        event_count=3,
        clean_block_count=1,
    )


def _closed_candle(
    *,
    row_id: int,
    timeframe: str,
    open_at: datetime,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> Any:
    duration = timedelta(hours=1) if timeframe == "H1" else timedelta(minutes=15)
    source = f"{SYMBOL}|{timeframe}|{open_at.isoformat()}|{open_price}|{high}|{low}|{close}"
    return candle_authority_from_row(
        {
            "id": row_id,
            "selected_raw_candle_id": 10_000 + row_id,
            "symbol": SYMBOL,
            "timeframe": timeframe,
            "open_time": open_at,
            "close_time": open_at + duration,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
            "tick_count": 25,
            "selected_provider": "XM",
            "selected_feed": "demo-account",
            "provider_timestamp_semantics": "PERIOD_OPEN",
            "selection_policy": "5scr.provider-priority.v1",
            "selection_rank": 1300,
            "content_hash": hashlib.sha256(source.encode()).hexdigest(),
        }
    )


def _thesis_evidence(lifecycle_id: str, context: StrategyContextEpochV1) -> DirectionalThesisEvidenceV1:
    h1 = (
        _closed_candle(
            row_id=1,
            timeframe="H1",
            open_at=START,
            open_price=1.0990,
            high=1.1010,
            low=1.0980,
            close=1.1000,
        ),
        _closed_candle(
            row_id=2,
            timeframe="H1",
            open_at=START + timedelta(hours=1),
            open_price=1.1000,
            high=1.1030,
            low=1.0990,
            close=1.1020,
        ),
    )
    m15 = (
        _closed_candle(
            row_id=3,
            timeframe="M15",
            open_at=START + timedelta(hours=2),
            open_price=1.1010,
            high=1.1020,
            low=1.1000,
            close=1.1015,
        ),
        _closed_candle(
            row_id=4,
            timeframe="M15",
            open_at=START + timedelta(hours=2, minutes=15),
            open_price=1.1015,
            high=1.1040,
            low=1.1010,
            close=1.1030,
        ),
        _closed_candle(
            row_id=5,
            timeframe="M15",
            open_at=START + timedelta(hours=2, minutes=30),
            open_price=1.1030,
            high=1.1040,
            low=1.1015,
            close=1.1032,
        ),
    )
    pressure_event_id = f"pressure-authority-{uuid4().hex}"
    return DirectionalThesisEvidenceV1(
        strategy_lifecycle_id=lifecycle_id,
        context_epoch_id=context.context_epoch_id,
        symbol=SYMBOL,
        decision_at_utc=START + timedelta(hours=3),
        strategy_direction="BUY",
        selected_route=ROUTE,
        pressure_authority=PressureDirectionAuthorityV1(
            mode="RADAR_ONLY",
            contract_status="RADAR_ONLY",
            raw_pressure_direction="BUY",
            source_event_ids=(pressure_event_id,),
            rule_version="pressure-authority.v1",
            observed_at_utc=START + timedelta(hours=2, minutes=45),
            valid_until_utc=START + timedelta(hours=4),
        ),
        h1_candles=h1,
        m15_candles=m15,
        source_request_id=f"request-{uuid4().hex}",
    )


def _route_authorization(
    context: StrategyContextEpochV1,
    *,
    direction: str,
    selected_route: str,
) -> RouteDirectionAuthorizationV1:
    return RouteDirectionAuthorizationV1(
        context_epoch_id=context.context_epoch_id,
        material_context_hash=context.material_context_hash,
        selected_route=selected_route,
        strategy_direction=cast(Any, direction),
        source_event_ids=(f"typed-route-{direction.lower()}-{uuid4().hex}",),
        rule_version="5scr.route-direction.v1",
    )


def _with_typed_route(
    evidence: DirectionalThesisEvidenceV1,
    context: StrategyContextEpochV1,
) -> DirectionalThesisEvidenceV1:
    return DirectionalThesisEvidenceV1.model_validate(
        {
            **evidence.model_dump(exclude={"route_authorization"}),
            "route_authorization": _route_authorization(
                context,
                direction=evidence.strategy_direction,
                selected_route=evidence.selected_route,
            ),
        }
    )


def _sell_successor_evidence(
    evidence: DirectionalThesisEvidenceV1,
    context: StrategyContextEpochV1,
) -> DirectionalThesisEvidenceV1:
    later_h1 = (
        _closed_candle(
            row_id=201,
            timeframe="H1",
            open_at=START + timedelta(hours=2),
            open_price=1.1020,
            high=1.1040,
            low=1.1010,
            close=1.1025,
        ),
        _closed_candle(
            row_id=202,
            timeframe="H1",
            open_at=START + timedelta(hours=3),
            open_price=1.1025,
            high=1.1030,
            low=1.0980,
            close=1.0990,
        ),
    )
    later_m15 = (
        _closed_candle(
            row_id=203,
            timeframe="M15",
            open_at=START + timedelta(hours=4),
            open_price=1.0990,
            high=1.1000,
            low=1.0980,
            close=1.0987,
        ),
        _closed_candle(
            row_id=204,
            timeframe="M15",
            open_at=START + timedelta(hours=4, minutes=15),
            open_price=1.0987,
            high=1.0990,
            low=1.0965,
            close=1.0970,
        ),
        _closed_candle(
            row_id=205,
            timeframe="M15",
            open_at=START + timedelta(hours=4, minutes=30),
            open_price=1.0970,
            high=1.0982,
            low=1.0965,
            close=1.0972,
        ),
    )
    pressure_event_id = f"pressure-authority-sell-{uuid4().hex}"
    return DirectionalThesisEvidenceV1.model_validate(
        {
            **evidence.model_dump(
                exclude={
                    "decision_at_utc",
                    "strategy_direction",
                    "selected_route",
                    "pressure_authority",
                    "route_authorization",
                    "h1_candles",
                    "m15_candles",
                    "source_request_id",
                }
            ),
            "decision_at_utc": START + timedelta(hours=5),
            "strategy_direction": "SELL",
            "selected_route": SELL_ROUTE,
            "pressure_authority": PressureDirectionAuthorityV1(
                mode="RADAR_ONLY",
                contract_status="RADAR_ONLY",
                raw_pressure_direction="SELL",
                source_event_ids=(pressure_event_id,),
                rule_version="pressure-authority.v1",
                observed_at_utc=START + timedelta(hours=4, minutes=45),
                valid_until_utc=START + timedelta(hours=6),
            ),
            "route_authorization": _route_authorization(
                context,
                direction="SELL",
                selected_route=SELL_ROUTE,
            ),
            "h1_candles": (*evidence.h1_candles, *later_h1),
            "m15_candles": (*evidence.m15_candles, *later_m15),
            "source_request_id": f"sell-successor-{uuid4().hex}",
        }
    )


async def _seed_parent_chain(
    postgres: PoolBackedPostgres,
) -> tuple[str, MaterialContextEvidenceV1, StrategyContextEpochV1, DirectionalThesisEvidenceV1]:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    context_event = _context_evidence(f"context-event-{uuid4().hex}")
    await _lifecycle_repository(postgres).upsert_lifecycle(_lifecycle(lifecycle_id))
    linked = await _lifecycle_repository(postgres).link_event(
        StrategyLifecycleEventLink(
            strategy_lifecycle_id=lifecycle_id,
            pressure_event_id=context_event.source_pressure_event_id,
            transport_lifecycle_id=f"transport:{uuid4().hex}",
            source_clean_block_id=f"raw-block-{uuid4().hex}",
            linked_at_utc=context_event.observed_at_utc,
            link_reason="EPISODE_OPENED",
        )
    )
    assert linked
    context_result = await _context_repository(postgres).process_evidence(context_event)
    assert context_result.status == "PERSISTED" and context_result.epoch is not None
    evidence = _thesis_evidence(lifecycle_id, context_result.epoch)
    built = build_directional_thesis_proofs(context=context_result.epoch, evidence=evidence)
    assert built.status == "READY", built
    return lifecycle_id, context_event, context_result.epoch, evidence


async def _seed_bidirectional_parent_chain(
    postgres: PoolBackedPostgres,
) -> tuple[str, MaterialContextEvidenceV1, StrategyContextEpochV1, DirectionalThesisEvidenceV1]:
    lifecycle_id = f"5scr-lifecycle:{uuid4().hex}"
    context_event = _context_evidence(f"context-event-{uuid4().hex}", bidirectional=True)
    await _lifecycle_repository(postgres).upsert_lifecycle(_lifecycle(lifecycle_id))
    linked = await _lifecycle_repository(postgres).link_event(
        StrategyLifecycleEventLink(
            strategy_lifecycle_id=lifecycle_id,
            pressure_event_id=context_event.source_pressure_event_id,
            transport_lifecycle_id=f"transport:{uuid4().hex}",
            source_clean_block_id=f"raw-block-{uuid4().hex}",
            linked_at_utc=context_event.observed_at_utc,
            link_reason="EPISODE_OPENED",
        )
    )
    assert linked
    context_result = await _context_repository(postgres).process_evidence(context_event)
    assert context_result.status == "PERSISTED" and context_result.epoch is not None
    evidence = _with_typed_route(_thesis_evidence(lifecycle_id, context_result.epoch), context_result.epoch)
    built = build_directional_thesis_proofs(context=context_result.epoch, evidence=evidence)
    assert built.status == "READY", built
    return lifecycle_id, context_event, context_result.epoch, evidence


async def _p4_counts(postgres: PoolBackedPostgres, lifecycle_id: str) -> dict[str, int]:
    row = await postgres.fetchrow(
        f"SELECT (SELECT count(*) FROM {H1_PROOF_TABLE} WHERE strategy_lifecycle_id = $1) AS h1, "
        f"(SELECT count(*) FROM {M15_PROOF_TABLE} WHERE strategy_lifecycle_id = $1) AS m15, "
        f"(SELECT count(*) FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1) AS theses",
        lifecycle_id,
    )
    assert row is not None
    return {key: int(value) for key, value in dict(row).items()}


async def _cleanup(postgres: PoolBackedPostgres, lifecycle_id: str) -> None:
    # P4 immutability triggers correctly reject ordinary DELETE.  This test-only
    # cleanup temporarily disables the exact named triggers and deletes only the
    # disposable lifecycle cohort before restoring every trigger.
    tables_and_triggers = (
        (THESIS_TABLE, "trg_strategy_5scr_directional_theses_v1_guard"),
        (M15_PROOF_TABLE, "trg_strategy_5scr_m15_structural_proofs_v1_immutable"),
        (H1_PROOF_TABLE, "trg_strategy_5scr_h1_structure_proofs_v1_immutable"),
    )
    try:
        for table, trigger in tables_and_triggers:
            await postgres.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        await postgres.execute(f"DELETE FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1", lifecycle_id)
        await postgres.execute(f"DELETE FROM {M15_PROOF_TABLE} WHERE strategy_lifecycle_id = $1", lifecycle_id)
        await postgres.execute(f"DELETE FROM {H1_PROOF_TABLE} WHERE strategy_lifecycle_id = $1", lifecycle_id)
    finally:
        for table, trigger in reversed(tables_and_triggers):
            await postgres.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    await postgres.execute(
        f"DELETE FROM {TRANSITION_TABLE} WHERE strategy_lifecycle_id = $1",
        lifecycle_id,
    )
    await postgres.execute(f"DELETE FROM {EPOCH_TABLE} WHERE strategy_lifecycle_id = $1", lifecycle_id)
    await postgres.execute(
        "DELETE FROM strategy_5scr_lifecycle_event_links_v2 WHERE strategy_lifecycle_id = $1",
        lifecycle_id,
    )
    await postgres.execute(
        "DELETE FROM strategy_5scr_analysis_lifecycles_v2 WHERE strategy_lifecycle_id = $1",
        lifecycle_id,
    )


async def test_schema_ready_shadow_only_and_direct_mutation_rejected(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        status = await repository.schema_status()
        assert status.ready, status
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED" and persisted.thesis is not None

        flags = await postgres.fetchrow(
            f"SELECT "
            f"(SELECT execution_authority FROM {H1_PROOF_TABLE} WHERE strategy_lifecycle_id = $1) AS h1, "
            f"(SELECT execution_authority FROM {M15_PROOF_TABLE} WHERE strategy_lifecycle_id = $1) AS m15, "
            f"(SELECT execution_authority FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1) AS thesis, "
            f"(SELECT valid_for_execution FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1) AS executable",
            lifecycle_id,
        )
        assert flags is not None and dict(flags) == {
            "h1": False,
            "m15": False,
            "thesis": False,
            "executable": False,
        }

        with pytest.raises(postgres.check_violation_error) as proof_mutation:
            await postgres.execute(
                f"UPDATE {H1_PROOF_TABLE} SET execution_authority = true WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(proof_mutation.value, "constraint_name", None) == "ck_5scr_proof_immutable_v1"

        with pytest.raises(postgres.check_violation_error) as thesis_mutation:
            await postgres.execute(
                f"UPDATE {THESIS_TABLE} SET strategy_direction = 'SELL' WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
            )
        assert getattr(thesis_mutation.value, "constraint_name", None) == "ck_5scr_thesis_immutable_v1"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_database_independently_rejects_shadow_authority_insertions(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, evidence = await _seed_parent_chain(postgres)
    repository = _repository(postgres)
    try:
        persisted = await repository.process_evidence(evidence)
        assert persisted.status == "PERSISTED"

        h1_columns = await postgres.fetchrow(
            f"SELECT * FROM {H1_PROOF_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        m15_columns = await postgres.fetchrow(
            f"SELECT * FROM {M15_PROOF_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        thesis_columns = await postgres.fetchrow(
            f"SELECT * FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert h1_columns is not None and m15_columns is not None and thesis_columns is not None

        h1 = dict(h1_columns)
        h1.update(
            h1_proof_id=_new_id("5scr-h1-proof"),
            semantic_dedupe_key=f"shadow-negative-h1-{uuid4().hex}",
            execution_authority=True,
        )
        with pytest.raises(postgres.check_violation_error) as h1_rejection:
            await postgres.execute(
                f"""
                INSERT INTO {H1_PROOF_TABLE} (
                    h1_proof_id, strategy_lifecycle_id, context_epoch_id, symbol,
                    strategy_direction, structure_event, anchor_candle_id,
                    confirmation_candle_id, reference_level, confirmation_close,
                    confirmed_at, decision_at, coverage_start_at, coverage_end_at,
                    source_candle_ids, source_content_hashes, coverage_complete,
                    structural_authority, material_proof_hash, evidence_hash,
                    semantic_dedupe_key, rule_version, evidence_payload,
                    execution_authority
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                    $15,$16,$17,$18,$19,$20,$21,$22,$23,$24
                )
                """,
                h1["h1_proof_id"],
                h1["strategy_lifecycle_id"],
                h1["context_epoch_id"],
                h1["symbol"],
                h1["strategy_direction"],
                h1["structure_event"],
                h1["anchor_candle_id"],
                h1["confirmation_candle_id"],
                h1["reference_level"],
                h1["confirmation_close"],
                h1["confirmed_at"],
                h1["decision_at"],
                h1["coverage_start_at"],
                h1["coverage_end_at"],
                h1["source_candle_ids"],
                h1["source_content_hashes"],
                h1["coverage_complete"],
                h1["structural_authority"],
                h1["material_proof_hash"],
                h1["evidence_hash"],
                h1["semantic_dedupe_key"],
                h1["rule_version"],
                h1["evidence_payload"],
                h1["execution_authority"],
            )
        assert getattr(h1_rejection.value, "constraint_name", None) == "ck_5scr_h1_proof_shadow_only_v1"

        m15 = dict(m15_columns)
        m15.update(
            m15_proof_id=_new_id("5scr-m15-proof"),
            semantic_dedupe_key=f"shadow-negative-m15-{uuid4().hex}",
            execution_authority=True,
        )
        with pytest.raises(postgres.check_violation_error) as m15_rejection:
            await postgres.execute(
                f"""
                INSERT INTO {M15_PROOF_TABLE} (
                    m15_proof_id, h1_proof_id, strategy_lifecycle_id,
                    context_epoch_id, symbol, strategy_direction,
                    reference_candle_id, break_candle_id, completion_candle_id,
                    break_level, h1_confirmed_at, break_close_at, completed_at,
                    completion_kind, decision_at, coverage_start_at,
                    coverage_end_at, source_candle_ids, source_content_hashes,
                    coverage_complete, structural_authority, ordering_valid,
                    material_proof_hash, evidence_hash, semantic_dedupe_key,
                    rule_version, evidence_payload, execution_authority
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                    $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28
                )
                """,
                m15["m15_proof_id"],
                m15["h1_proof_id"],
                m15["strategy_lifecycle_id"],
                m15["context_epoch_id"],
                m15["symbol"],
                m15["strategy_direction"],
                m15["reference_candle_id"],
                m15["break_candle_id"],
                m15["completion_candle_id"],
                m15["break_level"],
                m15["h1_confirmed_at"],
                m15["break_close_at"],
                m15["completed_at"],
                m15["completion_kind"],
                m15["decision_at"],
                m15["coverage_start_at"],
                m15["coverage_end_at"],
                m15["source_candle_ids"],
                m15["source_content_hashes"],
                m15["coverage_complete"],
                m15["structural_authority"],
                m15["ordering_valid"],
                m15["material_proof_hash"],
                m15["evidence_hash"],
                m15["semantic_dedupe_key"],
                m15["rule_version"],
                m15["evidence_payload"],
                m15["execution_authority"],
            )
        assert getattr(m15_rejection.value, "constraint_name", None) == "ck_5scr_m15_proof_shadow_only_v1"

        thesis = dict(thesis_columns)
        for mutation in ({"execution_authority": True}, {"valid_for_execution": True}):
            candidate = {
                **thesis,
                **mutation,
                "strategy_thesis_id": _new_id("5scr-thesis"),
                "thesis_sequence": int(thesis["thesis_sequence"]) + 100 + len(mutation),
                "semantic_identity_hash": _sha256(f"shadow-negative-thesis-{uuid4().hex}"),
            }
            with pytest.raises(postgres.check_violation_error) as thesis_rejection:
                await postgres.execute(
                    f"""
                    INSERT INTO {THESIS_TABLE} (
                        strategy_thesis_id, strategy_lifecycle_id,
                        context_epoch_id, thesis_sequence, symbol,
                        strategy_direction, direction_immutable, state,
                        direction_domain_at_creation, selected_route,
                        route_authorization_hash, pressure_authority_mode,
                        pressure_contract_status, pressure_reference_direction,
                        pressure_formal_transition_event_id,
                        pressure_authority_hash, counter_pressure_proof_hash,
                        h1_proof_id, m15_proof_id, structural_proof_hash,
                        semantic_identity_hash, rule_version, created_at,
                        closed_at, closure_reason, state_version,
                        valid_for_execution, execution_authority, payload
                    ) VALUES (
                        $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                        $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,
                        $27,$28,$29
                    )
                    """,
                    candidate["strategy_thesis_id"],
                    candidate["strategy_lifecycle_id"],
                    candidate["context_epoch_id"],
                    candidate["thesis_sequence"],
                    candidate["symbol"],
                    candidate["strategy_direction"],
                    candidate["direction_immutable"],
                    candidate["state"],
                    candidate["direction_domain_at_creation"],
                    candidate["selected_route"],
                    candidate["route_authorization_hash"],
                    candidate["pressure_authority_mode"],
                    candidate["pressure_contract_status"],
                    candidate["pressure_reference_direction"],
                    candidate["pressure_formal_transition_event_id"],
                    candidate["pressure_authority_hash"],
                    candidate["counter_pressure_proof_hash"],
                    candidate["h1_proof_id"],
                    candidate["m15_proof_id"],
                    candidate["structural_proof_hash"],
                    candidate["semantic_identity_hash"],
                    candidate["rule_version"],
                    candidate["created_at"],
                    candidate["closed_at"],
                    candidate["closure_reason"],
                    candidate["state_version"],
                    candidate["valid_for_execution"],
                    candidate["execution_authority"],
                    candidate["payload"],
                )
            assert getattr(thesis_rejection.value, "constraint_name", None) == "ck_5scr_thesis_shadow_only_v1"

        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
        assert context.execution_authority is False
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_database_rejects_locked_pressure_with_counter_proof(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        persisted = await _repository(postgres).process_evidence(evidence)
        assert persisted.status == "PERSISTED"
        row = await postgres.fetchrow(
            f"SELECT * FROM {THESIS_TABLE} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert row is not None
        candidate = dict(row)
        candidate.update(
            strategy_thesis_id=_new_id("5scr-thesis"),
            thesis_sequence=int(candidate["thesis_sequence"]) + 1,
            semantic_identity_hash=_sha256(f"locked-counter-negative-{uuid4().hex}"),
            pressure_authority_mode="CONSOLIDATED_DIRECTION_CONTRACT",
            pressure_contract_status="LOCKED",
            pressure_reference_direction=candidate["strategy_direction"],
            pressure_formal_transition_event_id=f"pressure-transition-{uuid4().hex}",
            counter_pressure_proof_hash=_sha256(f"counter-proof-{uuid4().hex}"),
        )

        with pytest.raises(postgres.check_violation_error) as rejection:
            await postgres.execute(
                f"""
                INSERT INTO {THESIS_TABLE} (
                    strategy_thesis_id, strategy_lifecycle_id,
                    context_epoch_id, thesis_sequence, symbol,
                    strategy_direction, direction_immutable, state,
                    direction_domain_at_creation, selected_route,
                    route_authorization_hash, pressure_authority_mode,
                    pressure_contract_status, pressure_reference_direction,
                    pressure_formal_transition_event_id,
                    pressure_authority_hash, counter_pressure_proof_hash,
                    h1_proof_id, m15_proof_id, structural_proof_hash,
                    semantic_identity_hash, rule_version, created_at,
                    closed_at, closure_reason, state_version,
                    valid_for_execution, execution_authority, payload
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                    $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,
                    $27,$28,$29
                )
                """,
                candidate["strategy_thesis_id"],
                candidate["strategy_lifecycle_id"],
                candidate["context_epoch_id"],
                candidate["thesis_sequence"],
                candidate["symbol"],
                candidate["strategy_direction"],
                candidate["direction_immutable"],
                candidate["state"],
                candidate["direction_domain_at_creation"],
                candidate["selected_route"],
                candidate["route_authorization_hash"],
                candidate["pressure_authority_mode"],
                candidate["pressure_contract_status"],
                candidate["pressure_reference_direction"],
                candidate["pressure_formal_transition_event_id"],
                candidate["pressure_authority_hash"],
                candidate["counter_pressure_proof_hash"],
                candidate["h1_proof_id"],
                candidate["m15_proof_id"],
                candidate["structural_proof_hash"],
                candidate["semantic_identity_hash"],
                candidate["rule_version"],
                candidate["created_at"],
                candidate["closed_at"],
                candidate["closure_reason"],
                candidate["state_version"],
                candidate["valid_for_execution"],
                candidate["execution_authority"],
                candidate["payload"],
            )
        assert getattr(rejection.value, "constraint_name", None) == "ck_5scr_thesis_pressure_authority_v1"

        # The valid sibling shape must remain legal: LOCKED consolidated
        # authority with no counter-pressure proof.  Roll this direct insert
        # back so the disposable cohort stays at one canonical thesis row.
        positive = {
            **candidate,
            "strategy_thesis_id": _new_id("5scr-thesis"),
            "semantic_identity_hash": _sha256(f"locked-counter-positive-{uuid4().hex}"),
            "counter_pressure_proof_hash": None,
        }

        class _RollbackPositiveCheckError(RuntimeError):
            pass

        with pytest.raises(_RollbackPositiveCheckError):
            async with postgres.transaction() as connection:
                await connection.execute(
                    f"""
                INSERT INTO {THESIS_TABLE} (
                    strategy_thesis_id, strategy_lifecycle_id,
                    context_epoch_id, thesis_sequence, symbol,
                    strategy_direction, direction_immutable, state,
                    direction_domain_at_creation, selected_route,
                    route_authorization_hash, pressure_authority_mode,
                    pressure_contract_status, pressure_reference_direction,
                    pressure_formal_transition_event_id,
                    pressure_authority_hash, counter_pressure_proof_hash,
                    h1_proof_id, m15_proof_id, structural_proof_hash,
                    semantic_identity_hash, rule_version, created_at,
                    closed_at, closure_reason, state_version,
                    valid_for_execution, execution_authority, payload
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                    $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,
                    $27,$28,$29
                )
                    """,
                    positive["strategy_thesis_id"],
                    positive["strategy_lifecycle_id"],
                    positive["context_epoch_id"],
                    positive["thesis_sequence"],
                    positive["symbol"],
                    positive["strategy_direction"],
                    positive["direction_immutable"],
                    "INVALIDATED",
                    positive["direction_domain_at_creation"],
                    positive["selected_route"],
                    positive["route_authorization_hash"],
                    positive["pressure_authority_mode"],
                    positive["pressure_contract_status"],
                    positive["pressure_reference_direction"],
                    positive["pressure_formal_transition_event_id"],
                    positive["pressure_authority_hash"],
                    positive["counter_pressure_proof_hash"],
                    positive["h1_proof_id"],
                    positive["m15_proof_id"],
                    positive["structural_proof_hash"],
                    positive["semantic_identity_hash"],
                    positive["rule_version"],
                    positive["created_at"],
                    positive["created_at"],
                    "TEST_LOCKED_NULL_COUNTER_ALLOWED",
                    positive["state_version"],
                    positive["valid_for_execution"],
                    positive["execution_authority"],
                    positive["payload"],
                )
                assert (
                    await connection.fetchval(
                        f"SELECT count(*) FROM {THESIS_TABLE} WHERE strategy_thesis_id = $1",
                        positive["strategy_thesis_id"],
                    )
                    == 1
                )
                raise _RollbackPositiveCheckError
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_retry_restart_and_concurrency_create_one_logical_thesis(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        concurrent = await asyncio.gather(
            _repository(postgres).process_evidence(evidence),
            _repository(postgres).process_evidence(evidence),
        )
        assert sorted(item.status for item in concurrent) == ["DUPLICATE", "PERSISTED"]
        first = next(item for item in concurrent if item.status == "PERSISTED")
        assert first.thesis is not None

        # A fresh repository is the restart boundary: all identity is recovered
        # from PostgreSQL, never from in-process reducer memory.
        replay = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert replay.status == "DUPLICATE" and replay.thesis is not None
        assert replay.thesis.strategy_thesis_id == first.thesis.strategy_thesis_id

        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1 and history[0].strategy_thesis_id == first.thesis.strategy_thesis_id
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_lineage_only_refresh_reuses_durable_proofs_without_drift(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        first = await repository.process_evidence(evidence)
        assert first.status == "PERSISTED" and first.thesis is not None

        refreshed = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(exclude={"h1_candles", "m15_candles", "source_request_id"}),
                "h1_candles": tuple(
                    _lineage_refresh(candle, suffix=f"h1-{index}") for index, candle in enumerate(evidence.h1_candles)
                ),
                "m15_candles": tuple(
                    _lineage_refresh(candle, suffix=f"m15-{index}") for index, candle in enumerate(evidence.m15_candles)
                ),
                "source_request_id": f"lineage-refresh-{uuid4().hex}",
            }
        )
        first_build = build_directional_thesis_proofs(context=context, evidence=evidence)
        refresh_build = build_directional_thesis_proofs(context=context, evidence=refreshed)
        assert first_build.status == refresh_build.status == "READY"
        assert first_build.artifact is not None and refresh_build.artifact is not None
        assert first_build.artifact.h1_proof.evidence_hash != refresh_build.artifact.h1_proof.evidence_hash
        assert first_build.artifact.m15_proof.evidence_hash != refresh_build.artifact.m15_proof.evidence_hash
        assert first_build.artifact.h1_proof.material_proof_hash == refresh_build.artifact.h1_proof.material_proof_hash
        assert (
            first_build.artifact.m15_proof.material_proof_hash == refresh_build.artifact.m15_proof.material_proof_hash
        )
        assert first_build.artifact.semantic_identity_hash == refresh_build.artifact.semantic_identity_hash

        replay = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(refreshed)
        assert replay.status == "DUPLICATE" and replay.thesis is not None
        assert replay.thesis.strategy_thesis_id == first.thesis.strategy_thesis_id
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize(
    "mutation",
    (
        "evidence_payload",
        "evidence_hash",
        "material_hash",
        "candle_lineage",
        "direction",
        "break_level",
        "coverage",
        "timestamp",
        "m15_evidence_hash",
        "h1_confirmation_close",
        "m15_h1_confirmed_at",
    ),
)
async def test_active_exact_replay_reconstructs_every_durable_proof_dimension(
    postgres: PoolBackedPostgres,
    mutation: str,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    h1_trigger = "trg_strategy_5scr_h1_structure_proofs_v1_immutable"
    m15_trigger = "trg_strategy_5scr_m15_structural_proofs_v1_immutable"
    try:
        opened = await _repository(postgres).process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None

        if mutation in {"m15_evidence_hash", "m15_h1_confirmed_at"}:
            await postgres.execute(f"ALTER TABLE {M15_PROOF_TABLE} DISABLE TRIGGER {m15_trigger}")
            try:
                if mutation == "m15_evidence_hash":
                    await postgres.execute(
                        f"UPDATE {M15_PROOF_TABLE} SET evidence_hash = $2 WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        _sha256(f"corrupt-m15-evidence-{uuid4().hex}"),
                    )
                else:
                    corrupt_clock = START + timedelta(hours=1, minutes=30)
                    await postgres.execute(
                        f"UPDATE {M15_PROOF_TABLE} SET h1_confirmed_at = $2, evidence_payload = "
                        "jsonb_set(evidence_payload, '{h1_confirmed_at_utc}', to_jsonb($2::timestamptz), false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        corrupt_clock,
                    )
            finally:
                await postgres.execute(f"ALTER TABLE {M15_PROOF_TABLE} ENABLE TRIGGER {m15_trigger}")
        else:
            await postgres.execute(f"ALTER TABLE {H1_PROOF_TABLE} DISABLE TRIGGER {h1_trigger}")
            try:
                if mutation == "evidence_payload":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET evidence_payload = "
                        "jsonb_set(evidence_payload, '{anchor_candle,feed}', to_jsonb($2::text), false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        f"corrupt-feed-{uuid4().hex}",
                    )
                elif mutation == "evidence_hash":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET evidence_hash = $2 WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        _sha256(f"corrupt-h1-evidence-{uuid4().hex}"),
                    )
                elif mutation == "material_hash":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET material_proof_hash = $2 WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        _sha256(f"corrupt-h1-material-{uuid4().hex}"),
                    )
                elif mutation == "candle_lineage":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET anchor_candle_id = $2 WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        _sha256(f"corrupt-h1-candle-{uuid4().hex}"),
                    )
                elif mutation == "direction":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET evidence_payload = "
                        "jsonb_set(evidence_payload, '{strategy_direction}', '\"SELL\"'::jsonb, false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                    )
                elif mutation == "break_level":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET reference_level = reference_level + 0.001 "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                    )
                elif mutation == "coverage":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET evidence_payload = "
                        "jsonb_set(evidence_payload, '{coverage_end_at_utc}', to_jsonb($2::text), false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        (START + timedelta(hours=4)).isoformat(),
                    )
                elif mutation == "timestamp":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET evidence_payload = "
                        "jsonb_set(evidence_payload, '{confirmed_at_utc}', to_jsonb($2::text), false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                        (START + timedelta(hours=4)).isoformat(),
                    )
                elif mutation == "h1_confirmation_close":
                    await postgres.execute(
                        f"UPDATE {H1_PROOF_TABLE} SET confirmation_close = confirmation_close - 0.0005, "
                        "evidence_payload = jsonb_set(evidence_payload, '{confirmation_close}', "
                        "to_jsonb((confirmation_close - 0.0005)::double precision), false) "
                        "WHERE strategy_lifecycle_id = $1",
                        lifecycle_id,
                    )
                else:  # pragma: no cover - parametrization is closed above
                    raise AssertionError(f"unknown mutation: {mutation}")
            finally:
                await postgres.execute(f"ALTER TABLE {H1_PROOF_TABLE} ENABLE TRIGGER {h1_trigger}")

        before = await _p4_counts(postgres, lifecycle_id)
        with pytest.raises(DirectionalThesisV1IntegrityError, match="H1_PROOF|M15_PROOF"):
            await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert await _p4_counts(postgres, lifecycle_id) == before
        active = await _repository(postgres).load_active(lifecycle_id)
        assert active is not None and active.strategy_thesis_id == opened.thesis.strategy_thesis_id
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize("proof_kind", ("H1", "M15"))
async def test_exact_replay_rejects_self_consistent_forged_structural_claim(
    postgres: PoolBackedPostgres,
    proof_kind: str,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    h1_trigger = "trg_strategy_5scr_h1_structure_proofs_v1_immutable"
    m15_trigger = "trg_strategy_5scr_m15_structural_proofs_v1_immutable"
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        table = H1_PROOF_TABLE if proof_kind == "H1" else M15_PROOF_TABLE
        trigger = h1_trigger if proof_kind == "H1" else m15_trigger
        row = await postgres.fetchrow(
            f"SELECT evidence_payload FROM {table} WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
        )
        assert row is not None
        raw_payload = dict(row)["evidence_payload"]
        if isinstance(raw_payload, str):
            raw_payload = json.loads(raw_payload)
        payload = json.loads(json.dumps(raw_payload, default=str))

        level_field = "reference_level" if proof_kind == "H1" else "break_level"
        forged_level = 1.1050 if proof_kind == "H1" else 1.1060
        payload[level_field] = forged_level
        assignments = f"{level_field}=$2, evidence_payload=$3::jsonb"
        args = (
            forged_level,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

        await postgres.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        try:
            await postgres.execute(
                f"UPDATE {table} SET {assignments} WHERE strategy_lifecycle_id=$1",
                lifecycle_id,
                *args,
            )
        finally:
            await postgres.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")

        before = await _p4_counts(postgres, lifecycle_id)
        with pytest.raises(DirectionalThesisV1IntegrityError, match=f"{proof_kind}_PROOF_PAYLOAD_INVALID"):
            await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert await _p4_counts(postgres, lifecycle_id) == before
        active = await repository.load_active(lifecycle_id)
        assert active is not None and active.strategy_thesis_id == opened.thesis.strategy_thesis_id
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_closed_exact_replay_validates_durable_proof_chain_before_duplicate(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    m15_trigger = "trg_strategy_5scr_m15_structural_proofs_v1_immutable"
    try:
        opened = await _repository(postgres).process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        closed = await _repository(postgres).invalidate_active(
            lifecycle_id,
            evidence.decision_at_utc + timedelta(minutes=1),
            "TEST_CLOSED_DUPLICATE_PROOF_CHAIN",
        )
        assert closed.status == "INVALIDATED"

        await postgres.execute(f"ALTER TABLE {M15_PROOF_TABLE} DISABLE TRIGGER {m15_trigger}")
        try:
            await postgres.execute(
                f"UPDATE {M15_PROOF_TABLE} SET evidence_hash = $2 WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
                _sha256(f"corrupt-closed-m15-{uuid4().hex}"),
            )
        finally:
            await postgres.execute(f"ALTER TABLE {M15_PROOF_TABLE} ENABLE TRIGGER {m15_trigger}")

        before = await _p4_counts(postgres, lifecycle_id)
        with pytest.raises(DirectionalThesisV1IntegrityError, match="M15_PROOF"):
            await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert await _p4_counts(postgres, lifecycle_id) == before
        assert await _repository(postgres).load_active(lifecycle_id) is None
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1 and history[0].state == "INVALIDATED"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_corrupt_durable_proof_reuse_fails_closed_and_rolls_back(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, evidence = await _seed_parent_chain(postgres)
    h1_trigger = "trg_strategy_5scr_h1_structure_proofs_v1_immutable"
    try:
        first = await _repository(postgres).process_evidence(evidence)
        assert first.status == "PERSISTED" and first.thesis is not None
        await _repository(postgres).invalidate_active(
            lifecycle_id,
            evidence.decision_at_utc + timedelta(minutes=1),
            "TEST_FORCE_REUSE",
        )

        await postgres.execute(f"ALTER TABLE {H1_PROOF_TABLE} DISABLE TRIGGER {h1_trigger}")
        try:
            await postgres.execute(
                f"UPDATE {H1_PROOF_TABLE} SET evidence_hash = $2 WHERE strategy_lifecycle_id = $1",
                lifecycle_id,
                _sha256(f"corrupt-proof-{uuid4().hex}"),
            )
        finally:
            await postgres.execute(f"ALTER TABLE {H1_PROOF_TABLE} ENABLE TRIGGER {h1_trigger}")

        lineage_refresh = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(exclude={"pressure_authority", "h1_candles", "m15_candles", "source_request_id"}),
                "pressure_authority": _next_pressure_authority(evidence),
                "h1_candles": tuple(
                    _lineage_refresh(candle, suffix=f"corrupt-h1-{index}")
                    for index, candle in enumerate(evidence.h1_candles)
                ),
                "m15_candles": tuple(
                    _lineage_refresh(candle, suffix=f"corrupt-m15-{index}")
                    for index, candle in enumerate(evidence.m15_candles)
                ),
                "source_request_id": f"proof-reuse-{uuid4().hex}",
            }
        )
        before = await _p4_counts(postgres, lifecycle_id)
        with pytest.raises(DirectionalThesisV1IntegrityError, match="H1_PROOF"):
            await _repository(postgres).process_evidence(lineage_refresh)
        assert await _p4_counts(postgres, lifecycle_id) == before
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1 and history[0].state == "INVALIDATED"
        assert context.context_epoch_id == history[0].context_epoch_id
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_later_opposite_h1_break_invalidates_active_thesis_and_old_replay_cannot_resurrect(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None

        opposite_h1 = (
            _closed_candle(
                row_id=101,
                timeframe="H1",
                open_at=START + timedelta(hours=2),
                open_price=1.1020,
                high=1.1040,
                low=1.1010,
                close=1.1025,
            ),
            _closed_candle(
                row_id=102,
                timeframe="H1",
                open_at=START + timedelta(hours=3),
                open_price=1.1025,
                high=1.1030,
                low=1.0980,
                close=1.0990,
            ),
        )
        invalidating_evidence = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(exclude={"decision_at_utc", "h1_candles", "source_request_id"}),
                "decision_at_utc": START + timedelta(hours=4),
                "h1_candles": (*evidence.h1_candles, *opposite_h1),
                "source_request_id": f"h1-opposite-{uuid4().hex}",
            }
        )

        invalidated = await repository.process_evidence(invalidating_evidence)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "H1_STRUCTURE_SUPERSEDED_BY_OPPOSITE_BREAK",
        )
        assert invalidated.thesis is not None
        assert invalidated.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert invalidated.thesis.state == "INVALIDATED"
        assert invalidated.thesis.closure_reason == "H1_STRUCTURE_SUPERSEDED_BY_OPPOSITE_BREAK"
        assert await repository.load_active(lifecycle_id) is None

        replay = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert (replay.status, replay.reason_code) == (
            "DUPLICATE",
            "DIRECTIONAL_THESIS_ALREADY_PERSISTED",
        )
        assert replay.thesis is not None
        assert replay.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert replay.thesis.state == "INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None
        replay_again = await asyncio.gather(
            _repository(postgres).process_evidence(evidence),
            _repository(postgres).process_evidence(evidence),
        )
        assert {item.status for item in replay_again} == {"DUPLICATE"}
        assert {item.thesis.strategy_thesis_id for item in replay_again if item.thesis is not None} == {
            opened.thesis.strategy_thesis_id
        }
        history = await repository.load_history(lifecycle_id)
        assert len(history) == 1
        assert history[0].strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert history[0].state == "INVALIDATED"
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_opposite_h1_invalidates_active_even_when_successor_pressure_is_expired(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        opposite_h1 = (
            _closed_candle(
                row_id=131,
                timeframe="H1",
                open_at=START + timedelta(hours=2),
                open_price=1.1020,
                high=1.1040,
                low=1.1010,
                close=1.1025,
            ),
            _closed_candle(
                row_id=132,
                timeframe="H1",
                open_at=START + timedelta(hours=3),
                open_price=1.1025,
                high=1.1030,
                low=1.0980,
                close=1.0990,
            ),
        )
        expired = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(
                    exclude={"decision_at_utc", "pressure_authority", "h1_candles", "source_request_id"}
                ),
                "decision_at_utc": START + timedelta(hours=4, minutes=1),
                "pressure_authority": evidence.pressure_authority.model_copy(
                    update={"valid_until_utc": START + timedelta(hours=4)}
                ),
                "h1_candles": (*evidence.h1_candles, *opposite_h1),
                "source_request_id": f"expired-pressure-opposite-h1-{uuid4().hex}",
            }
        )

        invalidated = await repository.process_evidence(expired)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "H1_STRUCTURE_SUPERSEDED_BY_OPPOSITE_BREAK",
        )
        assert invalidated.thesis is not None
        assert invalidated.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert invalidated.thesis.state == "INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None
        assert len(await repository.load_history(lifecycle_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_opposite_request_closes_old_thesis_then_second_call_persists_fresh_direction(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, buy_evidence = await _seed_bidirectional_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(buy_evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        sell_evidence = _sell_successor_evidence(buy_evidence, context)

        invalidated = await repository.process_evidence(sell_evidence)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "H1_STRUCTURE_SUPERSEDED_BY_OPPOSITE_BREAK",
        )
        assert invalidated.thesis is not None
        assert invalidated.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert invalidated.thesis.strategy_direction == "BUY"
        assert invalidated.thesis.state == "INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None

        successor = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(sell_evidence)
        assert successor.status == "PERSISTED" and successor.thesis is not None
        assert successor.thesis.strategy_direction == "SELL"
        assert successor.thesis.strategy_thesis_id != opened.thesis.strategy_thesis_id
        assert successor.thesis.thesis_sequence == opened.thesis.thesis_sequence + 1
        assert successor.thesis.state == "ACTIVE"
        history = await repository.load_history(lifecycle_id)
        assert [(item.thesis_sequence, item.strategy_direction, item.state) for item in history] == [
            (1, "BUY", "INVALIDATED"),
            (2, "SELL", "ACTIVE"),
        ]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_buy_sell_buy_single_snapshot_invalidates_old_once_then_persists_fresh_buy_after_restart(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        a_to_b_to_a_h1 = (
            _closed_candle(
                row_id=301,
                timeframe="H1",
                open_at=START + timedelta(hours=2),
                open_price=1.1020,
                high=1.1040,
                low=1.1010,
                close=1.1025,
            ),
            _closed_candle(
                row_id=302,
                timeframe="H1",
                open_at=START + timedelta(hours=3),
                open_price=1.1025,
                high=1.1030,
                low=1.0980,
                close=1.0990,
            ),
            _closed_candle(
                row_id=303,
                timeframe="H1",
                open_at=START + timedelta(hours=4),
                open_price=1.0990,
                high=1.1010,
                low=1.0980,
                close=1.1000,
            ),
            _closed_candle(
                row_id=304,
                timeframe="H1",
                open_at=START + timedelta(hours=5),
                open_price=1.1000,
                high=1.1070,
                low=1.0995,
                close=1.1060,
            ),
        )
        fresh_buy_m15 = (
            _closed_candle(
                row_id=305,
                timeframe="M15",
                open_at=START + timedelta(hours=6),
                open_price=1.1060,
                high=1.1070,
                low=1.1055,
                close=1.1065,
            ),
            _closed_candle(
                row_id=306,
                timeframe="M15",
                open_at=START + timedelta(hours=6, minutes=15),
                open_price=1.1065,
                high=1.1085,
                low=1.1060,
                close=1.1080,
            ),
            _closed_candle(
                row_id=307,
                timeframe="M15",
                open_at=START + timedelta(hours=6, minutes=30),
                open_price=1.1080,
                high=1.1087,
                low=1.1072,
                close=1.1082,
            ),
        )
        decision_at = START + timedelta(hours=6, minutes=45)
        snapshot = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(
                    exclude={
                        "decision_at_utc",
                        "pressure_authority",
                        "h1_candles",
                        "m15_candles",
                        "source_request_id",
                    }
                ),
                "decision_at_utc": decision_at,
                "pressure_authority": evidence.pressure_authority.model_copy(
                    update={"valid_until_utc": decision_at + timedelta(hours=1)}
                ),
                "h1_candles": (*evidence.h1_candles, *a_to_b_to_a_h1),
                "m15_candles": (*evidence.m15_candles, *fresh_buy_m15),
                "source_request_id": f"buy-sell-buy-snapshot-{uuid4().hex}",
            }
        )
        fresh_build = build_directional_thesis_proofs(context=_context, evidence=snapshot)
        assert fresh_build.status == "READY" and fresh_build.artifact is not None
        assert fresh_build.artifact.semantic_identity_hash != opened.thesis.semantic_identity_hash

        invalidated = await repository.process_evidence(snapshot)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "H1_STRUCTURE_SUPERSEDED_BY_OPPOSITE_BREAK",
        )
        assert invalidated.thesis is not None
        assert invalidated.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert invalidated.thesis.state == "INVALIDATED"

        restarted = Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres))
        fresh = await restarted.process_evidence(snapshot)
        assert fresh.status == "PERSISTED" and fresh.thesis is not None
        assert fresh.thesis.strategy_direction == "BUY"
        assert fresh.thesis.strategy_thesis_id != opened.thesis.strategy_thesis_id
        assert fresh.thesis.thesis_sequence == 2

        duplicate = await _repository(postgres).process_evidence(snapshot)
        assert duplicate.status == "DUPLICATE" and duplicate.thesis is not None
        assert duplicate.thesis.strategy_thesis_id == fresh.thesis.strategy_thesis_id
        stale_replay = await _repository(postgres).process_evidence(evidence)
        assert stale_replay.status == "REJECTED"
        active = await repository.load_active(lifecycle_id)
        assert active is not None and active.strategy_thesis_id == fresh.thesis.strategy_thesis_id
        history = await repository.load_history(lifecycle_id)
        assert [(item.thesis_sequence, item.state) for item in history] == [
            (1, "INVALIDATED"),
            (2, "ACTIVE"),
        ]
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize(
    "invalidator_close",
    (1.1020, 1.1010),
    ids=("equal-break-level", "through-break-level"),
)
async def test_later_m15_close_through_level_invalidates_active_thesis_and_old_replay_cannot_resurrect(
    postgres: PoolBackedPostgres,
    invalidator_close: float,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None

        invalidator = _appended_candle(
            evidence,
            row_id=111,
            high=1.1035,
            low=1.1005,
            close=invalidator_close,
        )
        invalidating_evidence = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(exclude={"m15_candles", "source_request_id"}),
                "m15_candles": (*evidence.m15_candles, invalidator),
                "source_request_id": f"m15-invalidator-{uuid4().hex}",
            }
        )

        invalidated = await repository.process_evidence(invalidating_evidence)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "M15_STRUCTURAL_PROOF_INVALIDATED",
        )
        assert invalidated.thesis is not None
        assert invalidated.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert invalidated.thesis.state == "INVALIDATED"
        assert invalidated.thesis.closure_reason == "M15_STRUCTURAL_PROOF_INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None

        replay = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(evidence)
        assert (replay.status, replay.reason_code) == (
            "DUPLICATE",
            "DIRECTIONAL_THESIS_ALREADY_PERSISTED",
        )
        assert replay.thesis is not None
        assert replay.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert replay.thesis.state == "INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None
        replay_again = await asyncio.gather(
            _repository(postgres).process_evidence(evidence),
            _repository(postgres).process_evidence(evidence),
        )
        assert {item.status for item in replay_again} == {"DUPLICATE"}
        assert {item.thesis.strategy_thesis_id for item in replay_again if item.thesis is not None} == {
            opened.thesis.strategy_thesis_id
        }
        history = await repository.load_history(lifecycle_id)
        assert len(history) == 1
        assert history[0].strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert history[0].state == "INVALIDATED"
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
async def test_newer_reinforcement_level_does_not_replace_stored_active_m15_liveness_level(
    postgres: PoolBackedPostgres,
    direction: str,
) -> None:
    lifecycle_id, _context_event, context, buy_evidence = await _seed_bidirectional_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        original = buy_evidence if direction == "BUY" else _sell_successor_evidence(buy_evidence, context)
        opened = await repository.process_evidence(original)
        assert opened.status == "PERSISTED" and opened.thesis is not None

        if direction == "BUY":
            # New candidate level 1.1000 is below stored active level 1.1020.
            # Its 1.1010 break close sits between them: the successor remains
            # structurally valid, but the immutable active proof is invalid.
            later = (
                _closed_candle(
                    row_id=221,
                    timeframe="M15",
                    open_at=START + timedelta(hours=2, minutes=30),
                    open_price=1.0990,
                    high=1.1000,
                    low=1.0985,
                    close=1.0995,
                ),
                _closed_candle(
                    row_id=222,
                    timeframe="M15",
                    open_at=START + timedelta(hours=2, minutes=45),
                    open_price=1.0995,
                    high=1.1015,
                    low=1.0990,
                    close=1.1010,
                ),
                _closed_candle(
                    row_id=223,
                    timeframe="M15",
                    open_at=START + timedelta(hours=3),
                    open_price=1.1010,
                    high=1.1018,
                    low=1.1005,
                    close=1.1012,
                ),
            )
            decision_at = START + timedelta(hours=3, minutes=15)
        else:
            # SELL mirror: new level 1.1000 is above stored active 1.0980;
            # its 1.0990 break close is valid for the successor but crosses
            # the immutable active level.
            later = (
                _closed_candle(
                    row_id=225,
                    timeframe="M15",
                    open_at=START + timedelta(hours=4, minutes=30),
                    open_price=1.1005,
                    high=1.1010,
                    low=1.1000,
                    close=1.1005,
                ),
                _closed_candle(
                    row_id=226,
                    timeframe="M15",
                    open_at=START + timedelta(hours=4, minutes=45),
                    open_price=1.1005,
                    high=1.1010,
                    low=1.0985,
                    close=1.0990,
                ),
                _closed_candle(
                    row_id=227,
                    timeframe="M15",
                    open_at=START + timedelta(hours=5),
                    open_price=1.0990,
                    high=1.0997,
                    low=1.0985,
                    close=1.0995,
                ),
            )
            decision_at = START + timedelta(hours=5, minutes=15)

        candidate_invalidated = DirectionalThesisEvidenceV1.model_validate(
            {
                **original.model_dump(
                    exclude={"decision_at_utc", "pressure_authority", "m15_candles", "source_request_id"}
                ),
                "decision_at_utc": decision_at,
                "pressure_authority": original.pressure_authority.model_copy(
                    update={"valid_until_utc": decision_at + timedelta(hours=1)}
                ),
                "m15_candles": (*original.m15_candles, *later),
                "source_request_id": f"between-m15-levels-{direction.lower()}-{uuid4().hex}",
            }
        )

        result = await repository.process_evidence(candidate_invalidated)
        assert (result.status, result.reason_code) == (
            "INVALIDATED",
            "M15_STRUCTURAL_PROOF_INVALIDATED",
        )
        assert result.thesis is not None
        assert result.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert result.thesis.strategy_direction == direction
        assert result.thesis.state == "INVALIDATED"
        assert await repository.load_active(lifecycle_id) is None
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_same_direction_structural_reinforcement_retains_active_thesis_across_restart(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        repository = _repository(postgres)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None

        h1_reinforcement = (
            _closed_candle(
                row_id=119,
                timeframe="H1",
                open_at=START + timedelta(hours=2),
                open_price=1.1020,
                high=1.1040,
                low=1.1010,
                close=1.1025,
            ),
            _closed_candle(
                row_id=120,
                timeframe="H1",
                open_at=START + timedelta(hours=3),
                open_price=1.1025,
                high=1.1060,
                low=1.1020,
                close=1.1050,
            ),
        )
        m15_reinforcement = (
            _closed_candle(
                row_id=121,
                timeframe="M15",
                open_at=START + timedelta(hours=4),
                open_price=1.1050,
                high=1.1060,
                low=1.1045,
                close=1.1055,
            ),
            _closed_candle(
                row_id=122,
                timeframe="M15",
                open_at=START + timedelta(hours=4, minutes=15),
                open_price=1.1055,
                high=1.1070,
                low=1.1050,
                close=1.1065,
            ),
            _closed_candle(
                row_id=123,
                timeframe="M15",
                open_at=START + timedelta(hours=4, minutes=30),
                open_price=1.1065,
                high=1.1070,
                low=1.1055,
                close=1.1066,
            ),
        )
        refreshed_pressure = evidence.pressure_authority.model_copy(
            update={"valid_until_utc": START + timedelta(hours=6)}
        )
        reinforced_evidence = DirectionalThesisEvidenceV1.model_validate(
            {
                **evidence.model_dump(
                    exclude={
                        "decision_at_utc",
                        "pressure_authority",
                        "h1_candles",
                        "m15_candles",
                        "source_request_id",
                    }
                ),
                "decision_at_utc": START + timedelta(hours=4, minutes=45),
                "pressure_authority": refreshed_pressure,
                "h1_candles": (*evidence.h1_candles, *h1_reinforcement),
                "m15_candles": (*evidence.m15_candles, *m15_reinforcement),
                "source_request_id": f"same-direction-reinforcement-{uuid4().hex}",
            }
        )

        reinforced = await repository.process_evidence(reinforced_evidence)
        assert (reinforced.status, reinforced.reason_code) == (
            "NO_CHANGE",
            "ACTIVE_DIRECTIONAL_THESIS_RETAINED_ON_REINFORCEMENT",
        )
        assert reinforced.thesis is not None
        assert reinforced.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert reinforced.thesis.state == "ACTIVE"
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}

        restarted = await Strategy5SCRDirectionalThesisV1Repository(cast(Any, postgres)).process_evidence(
            reinforced_evidence
        )
        assert (restarted.status, restarted.reason_code) == (
            "NO_CHANGE",
            "ACTIVE_DIRECTIONAL_THESIS_RETAINED_ON_REINFORCEMENT",
        )
        assert restarted.thesis is not None
        assert restarted.thesis.strategy_thesis_id == opened.thesis.strategy_thesis_id
        active = await repository.load_active(lifecycle_id)
        assert active is not None and active.strategy_thesis_id == opened.thesis.strategy_thesis_id
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_forced_thesis_insert_failure_rolls_back_both_proofs(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    function_name = f"test_p4_thesis_failure_{uuid4().hex}"
    trigger_name = function_name
    await postgres.execute(
        f"""
        CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'forced P4 thesis failure';
        END
        $$
        """
    )
    await postgres.execute(
        f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON {THESIS_TABLE} FOR EACH ROW EXECUTE FUNCTION {function_name}()"
    )
    try:
        with pytest.raises(Exception, match="forced P4 thesis failure"):
            await _repository(postgres).process_evidence(evidence)
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 0, "m15": 0, "theses": 0}
    finally:
        await postgres.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {THESIS_TABLE}")
        await postgres.execute(f"DROP FUNCTION IF EXISTS {function_name}()")
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_parent_closes_thesis_and_replay_cannot_resurrect(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, _context_event, _context, evidence = await _seed_parent_chain(postgres)
    try:
        opened = await _repository(postgres).process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.thesis is not None
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 "
            "SET state = 'INVALIDATED', last_event_at = $2 WHERE strategy_lifecycle_id = $1",
            lifecycle_id,
            START + timedelta(hours=4),
        )

        # Terminal parent authority wins before any incoming symbol/context
        # validation.  Even a malformed late replay must close, never preserve,
        # the durable active thesis.
        malformed_replay = evidence.model_copy(
            update={
                "symbol": "GBPUSD",
                "context_epoch_id": f"5scr-context:{'f' * 32}",
            }
        )
        closed = await _repository(postgres).process_evidence(malformed_replay)
        assert closed.status == "TERMINATED" and closed.thesis is not None
        assert closed.thesis.state == "TERMINAL"
        assert await _repository(postgres).load_active(lifecycle_id) is None

        replay = await _repository(postgres).process_evidence(evidence)
        assert (replay.status, replay.reason_code) == ("NO_CHANGE", "NO_ACTIVE_THESIS")
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1 and history[0].state == "TERMINAL"
        assert history[0].strategy_direction == "BUY"
        assert await _p4_counts(postgres, lifecycle_id) == {"h1": 1, "m15": 1, "theses": 1}
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_superseded_parent_is_reconciled_before_missing_replay_context(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _context_event, context, evidence = await _seed_parent_chain(postgres)
    try:
        opened = await _repository(postgres).process_evidence(evidence)
        assert opened.status == "PERSISTED"
        await postgres.execute(
            f"UPDATE {EPOCH_TABLE} SET state = 'SUPERSEDED', closed_at = $2, "
            "state_version = state_version + 1 WHERE context_epoch_id = $1",
            context.context_epoch_id,
            START + timedelta(hours=4),
        )
        missing_context_replay = evidence.model_copy(update={"context_epoch_id": f"5scr-context:{'e' * 32}"})

        result = await _repository(postgres).process_evidence(missing_context_replay)

        assert (result.status, result.reason_code) == ("REJECTED", "CONTEXT_EPOCH_MISSING")
        assert await _repository(postgres).load_active(lifecycle_id) is None
        history = await _repository(postgres).load_history(lifecycle_id)
        assert len(history) == 1
        assert history[0].state == "INVALIDATED"
        assert history[0].strategy_direction == "BUY"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_old_context_replay_cannot_close_current_context_thesis(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, _old_event, old_context, old_evidence = await _seed_parent_chain(postgres)
    try:
        old_opened = await _repository(postgres).process_evidence(old_evidence)
        assert old_opened.status == "PERSISTED"

        next_event = _context_evidence(
            f"context-event-{uuid4().hex}",
            observed_at=START + timedelta(minutes=1),
        )
        linked = await _lifecycle_repository(postgres).link_event(
            StrategyLifecycleEventLink(
                strategy_lifecycle_id=lifecycle_id,
                pressure_event_id=next_event.source_pressure_event_id,
                transport_lifecycle_id=f"transport:{uuid4().hex}",
                source_clean_block_id=f"raw-block-{uuid4().hex}",
                linked_at_utc=next_event.observed_at_utc,
                link_reason="EPISODE_CONTINUED",
            )
        )
        assert linked
        next_result = await _context_repository(postgres).process_evidence(next_event)
        assert next_result.status == "PERSISTED" and next_result.epoch is not None, next_result
        assert next_result.epoch.context_epoch_id != old_context.context_epoch_id

        next_evidence = _thesis_evidence(lifecycle_id, next_result.epoch)
        current_opened = await _repository(postgres).process_evidence(next_evidence)
        assert current_opened.status == "PERSISTED" and current_opened.thesis is not None

        old_replay = await _repository(postgres).process_evidence(old_evidence)

        assert (old_replay.status, old_replay.reason_code) == (
            "REJECTED",
            "CONTEXT_EPOCH_NOT_ACTIVE",
        )
        active = await _repository(postgres).load_active(lifecycle_id)
        assert active is not None
        assert active.strategy_thesis_id == current_opened.thesis.strategy_thesis_id
        assert active.context_epoch_id == next_result.epoch.context_epoch_id
        history = await _repository(postgres).load_history(lifecycle_id)
        assert [item.state for item in history] == ["INVALIDATED", "ACTIVE"]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_rejects_weakened_shadow_constraint_and_active_index(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    constraint = "ck_5scr_thesis_shadow_only_v1"
    index = "uq_5scr_thesis_active_lifecycle_v1"
    trigger = "trg_strategy_5scr_directional_theses_v1_guard"

    await postgres.execute(f"ALTER TABLE {THESIS_TABLE} DROP CONSTRAINT {constraint}")
    try:
        await postgres.execute(f"ALTER TABLE {THESIS_TABLE} ADD CONSTRAINT {constraint} CHECK (TRUE)")
        status = await repository.schema_status()
        assert f"{constraint}:definition" in status.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {THESIS_TABLE} DROP CONSTRAINT IF EXISTS {constraint}")
        await postgres.execute(
            f"ALTER TABLE {THESIS_TABLE} ADD CONSTRAINT {constraint} "
            "CHECK (direction_immutable IS TRUE AND valid_for_execution IS FALSE "
            "AND execution_authority IS FALSE)"
        )

    await postgres.execute(f"DROP INDEX {index}")
    try:
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {THESIS_TABLE} (strategy_lifecycle_id) WHERE state = 'TERMINAL'"
        )
        status = await repository.schema_status()
        assert f"{index}:definition" in status.invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX IF EXISTS {index}")
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {THESIS_TABLE} (strategy_lifecycle_id) WHERE state = 'ACTIVE'"
        )

    await postgres.execute(f"DROP TRIGGER {trigger} ON {THESIS_TABLE}")
    try:
        assert not (await repository.schema_status()).ready
    finally:
        await postgres.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {THESIS_TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION strategy_5scr_guard_thesis_update_v1()"
        )

    function_row = await postgres.fetchrow(
        "SELECT pg_get_functiondef(oid) AS definition "
        "FROM pg_catalog.pg_proc WHERE proname = 'strategy_5scr_guard_thesis_update_v1'"
    )
    assert function_row is not None
    original_function = str(function_row["definition"])
    try:
        await postgres.execute(
            """
            CREATE OR REPLACE FUNCTION strategy_5scr_guard_thesis_update_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RETURN NEW;
            END
            $$
            """
        )
        status = await repository.schema_status()
        assert f"{trigger}:function_definition" in status.invalid_triggers
    finally:
        await postgres.execute(original_function)

    assert (await repository.schema_status()).ready
