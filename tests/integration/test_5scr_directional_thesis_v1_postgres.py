"""Disposable-PostgreSQL gates for immutable DirectionalThesis P4."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from analysis.strategy_5scr_directional_thesis_v1 import (
    build_directional_thesis_proofs,
)
from analysis.strategy_5scr_structural_proof_provider_v1 import candle_authority_from_row
from contracts.strategy_5scr_context_epoch_v1 import (
    ContextCandleAuthorityV1,
    MaterialContextEvidenceV1,
    StrategyContextEpochV1,
)
from contracts.strategy_5scr_directional_thesis_v1 import (
    DirectionalThesisEvidenceV1,
    PressureDirectionAuthorityV1,
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
        direction_domain="BUY_ONLY",
        allowed_routes=(ROUTE,),
        blocked_routes=("SELL_BREAKOUT_CHASE",),
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
