"""Disposable-PostgreSQL gates for shadow-only TradePlanCandidate V2."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_tradeplan_candidate_v2 import derive_structural_target_map_v1
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    BrokerGeometryCostAuthorityV1,
    StructuralCandleAuthorityV1,
    StructuralTargetMapEvidenceV1,
    TradePlanCandidateBuildEvidenceV2,
    canonical_hash_v1,
)
from storage.strategy_5scr_directional_thesis_v1_repository import _context_from_row
from storage.strategy_5scr_execution_box_v1_repository import (
    BOX_TABLE as P5_BOX_TABLE,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    OBSERVATION_TABLE as P5_OBSERVATION_TABLE,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    Strategy5SCRExecutionBoxV1Repository,
)
from storage.strategy_5scr_tradeplan_candidate_v2_repository import (
    CANDIDATE_TABLE,
    EVALUATION_TABLE,
    Strategy5SCRTradePlanCandidateV2Repository,
    TradePlanCandidateV2IntegrityError,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _cleanup as _cleanup_p5,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _evidence as _p5_evidence,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _insert_canonical_m1_evidence,
    _p4_repository,
    _seed_bidirectional_parent_chain,
    _sell_m1_cohort,
    _sell_successor_evidence,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _seed as _seed_p5,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_CANONICAL_BASE = 500_000_000_000_000_000
_RAW_BASE = 600_000_000_000_000_000
_DECISION = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
_CANDIDATE_TRIGGER = "trg_strategy_5scr_tradeplan_candidates_v2_guard"
_EVALUATION_TRIGGER = "trg_strategy_5scr_tradeplan_candidate_evaluations_v2_immutable"


class _BarrierConnection:
    """Real PG connection wrapper that pauses one canonical cohort read."""

    def __init__(self, connection: Any, *, timeframe: Literal["H4", "H1"], reached: asyncio.Event) -> None:
        self._connection = connection
        self._timeframe = timeframe
        self._reached = reached
        self.release = asyncio.Event()
        self._paused = False

    async def fetch(self, query: str, *args: Any) -> Any:
        rows = await self._connection.fetch(query, *args)
        if not self._paused and "FROM canonical_candles" in query and f"timeframe='{self._timeframe}'" in query:
            self._paused = True
            self._reached.set()
            await asyncio.wait_for(self.release.wait(), timeout=10)
        return rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _BarrierPostgres:
    """Retain production transactions while exposing a deterministic race fence."""

    def __init__(self, postgres: PoolBackedPostgres, *, timeframe: Literal["H4", "H1"]) -> None:
        self._postgres = postgres
        self._timeframe = timeframe
        self.reached = asyncio.Event()
        self.connection: _BarrierConnection | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            wrapped = _BarrierConnection(
                connection,
                timeframe=cast(Literal["H4", "H1"], self._timeframe),
                reached=self.reached,
            )
            self.connection = wrapped
            yield wrapped


def _candle(
    timeframe: Literal["H4", "H1"],
    index: int,
    *,
    opened_at: datetime,
    open_price: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
) -> StructuralCandleAuthorityV1:
    duration = timedelta(hours=4 if timeframe == "H4" else 1)
    # PostgreSQL NUMERIC reconstructs canonical values without insignificant
    # trailing zeros.  Normalize at the fixture boundary so evidence hashes
    # are byte-identical to the repository's DB reconstruction.
    open_price, high, low, close = (
        open_price.normalize(),
        high.normalize(),
        low.normalize(),
        close.normalize(),
    )
    return StructuralCandleAuthorityV1(
        source_content_hash="sha256:" + format(_RAW_BASE + index, "064x"),
        canonical_row_id=_CANONICAL_BASE + index,
        selected_raw_candle_id=_RAW_BASE + index,
        symbol="EURUSD",
        timeframe=timeframe,
        open_time_utc=opened_at,
        close_time_utc=opened_at + duration,
        open=open_price,
        high=high,
        low=low,
        close=close,
        provider="XM",
        feed="demo-account",
        provider_timestamp_semantics="PERIOD_OPEN",
        selection_policy="5scr.provider-priority.v1",
        selection_rank=1300,
    )


def _buy_h4(*, near: Decimal, far: Decimal) -> tuple[StructuralCandleAuthorityV1, ...]:
    anchor = Decimal("1.1020")
    highs = (anchor + Decimal("0.0001"), near, anchor + Decimal("0.0001"), far, anchor + Decimal("0.0002"))
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    return tuple(
        _candle(
            "H4",
            index,
            opened_at=start + timedelta(hours=4 * index),
            open_price=anchor,
            high=high,
            low=anchor - Decimal("0.0010"),
            close=anchor,
        )
        for index, high in enumerate(highs)
    )


def _sell_h4(*, near: Decimal, far: Decimal) -> tuple[StructuralCandleAuthorityV1, ...]:
    anchor = Decimal("1.1010")
    lows = (anchor - Decimal("0.0001"), near, anchor - Decimal("0.0001"), far, anchor - Decimal("0.0002"))
    start = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    return tuple(
        _candle(
            "H4",
            100 + index,
            opened_at=start + timedelta(hours=4 * index),
            open_price=anchor,
            high=anchor + Decimal("0.0010"),
            low=low,
            close=anchor,
        )
        for index, low in enumerate(lows)
    )


def _h1(
    anchor: Decimal, *, touch: Decimal | None = None, id_offset: int = 20
) -> tuple[StructuralCandleAuthorityV1, ...]:
    start = datetime(2026, 8, 12, 20, 0, tzinfo=UTC)
    rows: list[StructuralCandleAuthorityV1] = []
    for index in range(12):
        high = anchor + Decimal("0.0001")
        low = anchor - Decimal("0.0001")
        if touch is not None and index == 0:
            high = max(high, touch)
            low = min(low, touch)
        rows.append(
            _candle(
                "H1",
                id_offset + index,
                opened_at=start + timedelta(hours=index),
                open_price=anchor,
                high=high,
                low=low,
                close=anchor,
            )
        )
    return tuple(rows)


def _broker(symbol: str = "EURUSD") -> BrokerGeometryCostAuthorityV1:
    return BrokerGeometryCostAuthorityV1(
        authority_id=f"p6-cost-{symbol.lower()}-v1",
        symbol=symbol,
        captured_at_utc=_DECISION - timedelta(minutes=5),
        valid_until_utc=_DECISION + timedelta(minutes=5),
        digits=5,
        point=Decimal("0.00001"),
        tick_size=Decimal("0.00001"),
        pip_size=Decimal("0.0001"),
        spread_price=Decimal("0.00002"),
    )


async def _insert_candle(postgres: PoolBackedPostgres, candle: StructuralCandleAuthorityV1) -> None:
    await postgres.execute(
        """
        INSERT INTO raw_provider_candles (
            id,provider,feed,symbol,timeframe,provider_timestamp,
            provider_timestamp_semantics,open_time,close_time,open,high,low,close,
            volume,tick_count,complete,payload_hash,metadata
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,100,25,true,$14,'{}'::jsonb)
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
        candle.source_content_hash.removeprefix("sha256:"),
    )
    await postgres.execute(
        """
        INSERT INTO canonical_candles (
            id,symbol,timeframe,open_time,close_time,open,high,low,close,volume,tick_count,
            complete,selected_provider,selected_feed,provider_timestamp_semantics,
            selected_raw_candle_id,selection_policy,selection_rank,content_hash
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,100,25,true,$10,$11,$12,$13,$14,$15,$16)
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
        candle.provider,
        candle.feed,
        candle.provider_timestamp_semantics,
        candle.selected_raw_candle_id,
        candle.selection_policy,
        candle.selection_rank,
        candle.source_content_hash.removeprefix("sha256:"),
    )


async def _insert_target_cohort(postgres: PoolBackedPostgres, evidence: TradePlanCandidateBuildEvidenceV2) -> None:
    for candle in (*evidence.target_map_evidence.h4_candles, *evidence.target_map_evidence.h1_consumption_candles):
        await _insert_candle(postgres, candle)


async def _seed_parent(
    postgres: PoolBackedPostgres,
    *,
    freeze: bool = True,
) -> tuple[str, Any, Any, Any]:
    lifecycle_id, thesis, opened_evidence = await _seed_p5(postgres)
    p5 = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    opened = await p5.process_evidence(opened_evidence)
    assert opened.status == "PERSISTED" and opened.box is not None
    box = opened.box
    if freeze:
        frozen = await p5.process_evidence(_p5_evidence(thesis, index=2, freeze=True))
        assert frozen.status == "FROZEN" and frozen.box is not None
        box = frozen.box
    row = await postgres.fetchrow(
        "SELECT * FROM strategy_5scr_context_epochs_v1 WHERE context_epoch_id=$1",
        thesis.context_epoch_id,
    )
    assert row is not None
    return lifecycle_id, thesis, box, _context_from_row(row)


async def _seed_sell_parent(postgres: PoolBackedPostgres) -> tuple[str, Any, Any, Any]:
    lifecycle_id, _context_event, context, buy_evidence = await _seed_bidirectional_parent_chain(postgres)
    sell = await _p4_repository(postgres).process_evidence(_sell_successor_evidence(buy_evidence, context))
    assert sell.status == "PERSISTED" and sell.thesis is not None
    candles = _sell_m1_cohort()
    opened_evidence = _p5_evidence(
        sell.thesis,
        index=20,
        candles=candles,
        observed_at_utc=datetime(2026, 8, 12, 13, 6, tzinfo=UTC),
    )
    await _insert_canonical_m1_evidence(postgres, opened_evidence)
    p5 = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    opened = await p5.process_evidence(opened_evidence)
    assert opened.status == "PERSISTED"
    frozen = await p5.process_evidence(
        _p5_evidence(
            sell.thesis,
            index=21,
            candles=candles,
            freeze=True,
            observed_at_utc=datetime(2026, 8, 12, 13, 7, tzinfo=UTC),
        )
    )
    assert frozen.status == "FROZEN" and frozen.box is not None
    row = await postgres.fetchrow(
        "SELECT * FROM strategy_5scr_context_epochs_v1 WHERE context_epoch_id=$1",
        sell.thesis.context_epoch_id,
    )
    assert row is not None
    return lifecycle_id, sell.thesis, frozen.box, _context_from_row(row)


def _build_evidence(
    thesis: Any,
    box: Any,
    context: Any,
    *,
    request: str = "p6-request-1",
    near: Decimal = Decimal("1.1030"),
    far: Decimal = Decimal("1.1040"),
    consumed: bool = False,
) -> TradePlanCandidateBuildEvidenceV2:
    direction = cast(Literal["BUY", "SELL"], thesis.strategy_direction)
    if direction == "BUY":
        h4 = _buy_h4(near=near, far=far)
        anchor = Decimal("1.1020")
        h1 = _h1(anchor, touch=near if consumed else None)
    else:
        h4 = _sell_h4(near=near, far=far)
        anchor = Decimal("1.1010")
        h1 = _h1(anchor, touch=near if consumed else None, id_offset=220)
    target = StructuralTargetMapEvidenceV1(
        strategy_lifecycle_id=thesis.strategy_lifecycle_id,
        context_epoch_id=thesis.context_epoch_id,
        strategy_thesis_id=thesis.strategy_thesis_id,
        execution_box_id=box.execution_box_id,
        material_context_hash=context.material_context_hash,
        thesis_semantic_identity_hash=thesis.semantic_identity_hash,
        execution_box_material_hash=box.material_box_hash,
        symbol=thesis.symbol,
        direction=direction,
        target_map_version=context.target_map_version,
        decision_at_utc=_DECISION,
        coverage_start_utc=context.opened_at_utc,
        coverage_end_utc=_DECISION,
        h4_cohort_count=len(h4),
        h1_coverage_start_utc=h4[2].close_time_utc,
        h1_coverage_end_utc=_DECISION,
        h1_cohort_count=len(h1),
        selection_anchor=h1[-1],
        h4_candles=h4,
        h1_consumption_candles=h1,
    )
    return TradePlanCandidateBuildEvidenceV2(
        source_request_id=request,
        decision_at_utc=_DECISION,
        target_map_evidence=target,
        broker_geometry=_broker(thesis.symbol),
    )


def _later_evidence_with_h1(
    evidence: TradePlanCandidateBuildEvidenceV2,
    later_h1: StructuralCandleAuthorityV1,
    *,
    request: str,
    h4_candles: tuple[StructuralCandleAuthorityV1, ...] | None = None,
) -> TradePlanCandidateBuildEvidenceV2:
    """Advance one exact canonical observation without reusing a decision clock."""

    later_decision = later_h1.close_time_utc
    h1_rows = (*evidence.target_map_evidence.h1_consumption_candles, later_h1)
    target = StructuralTargetMapEvidenceV1.model_validate(
        {
            **evidence.target_map_evidence.model_dump(mode="python"),
            "decision_at_utc": later_decision,
            "coverage_end_utc": later_decision,
            "h1_coverage_end_utc": later_decision,
            "h1_cohort_count": len(h1_rows),
            "selection_anchor": later_h1,
            "h4_candles": h4_candles or evidence.target_map_evidence.h4_candles,
            "h1_consumption_candles": h1_rows,
        }
    )
    broker = BrokerGeometryCostAuthorityV1.model_validate(
        {
            **evidence.broker_geometry.model_dump(mode="python"),
            "authority_hash": "sha256:" + "0" * 64,
            "captured_at_utc": later_decision - timedelta(minutes=5),
            "valid_until_utc": later_decision + timedelta(minutes=5),
        }
    )
    return TradePlanCandidateBuildEvidenceV2.model_validate(
        {
            **evidence.model_dump(mode="python"),
            "source_request_id": request,
            "decision_at_utc": later_decision,
            "target_map_evidence": target,
            "broker_geometry": broker,
        }
    )


async def _cleanup(postgres: PoolBackedPostgres, lifecycle_id: str) -> None:
    candidate_row = await postgres.fetchrow("SELECT to_regclass($1) IS NOT NULL AS yes", CANDIDATE_TABLE)
    evaluation_row = await postgres.fetchrow("SELECT to_regclass($1) IS NOT NULL AS yes", EVALUATION_TABLE)
    candidate_table_exists = candidate_row is not None and bool(candidate_row["yes"])
    evaluation_table_exists = evaluation_row is not None and bool(evaluation_row["yes"])
    try:
        if evaluation_table_exists:
            await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DISABLE TRIGGER {_EVALUATION_TRIGGER}")
            await postgres.execute(f"DELETE FROM {EVALUATION_TABLE} WHERE strategy_lifecycle_id=$1", lifecycle_id)
        if candidate_table_exists:
            await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
            await postgres.execute(f"DELETE FROM {CANDIDATE_TABLE} WHERE strategy_lifecycle_id=$1", lifecycle_id)
    finally:
        if candidate_table_exists:
            await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
        if evaluation_table_exists:
            await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} ENABLE TRIGGER {_EVALUATION_TRIGGER}")
    await postgres.execute("DELETE FROM canonical_candles WHERE id >= $1 AND id < $2", _CANONICAL_BASE, _RAW_BASE)
    await postgres.execute(
        "DELETE FROM raw_provider_candles WHERE id >= $1 AND id < $2", _RAW_BASE, _RAW_BASE + 100_000
    )
    # P5's shared cleanup performs ALTER/DELETE through separate pool calls.
    # Pre-delete the child rows atomically on one connection so its follow-up
    # parent cleanup cannot race the immutable triggers under a pooled backend.
    async with postgres.transaction() as connection:
        try:
            await connection.execute(
                f"ALTER TABLE {P5_OBSERVATION_TABLE} DISABLE TRIGGER "
                "trg_strategy_5scr_execution_box_observations_v1_immutable"
            )
            await connection.execute(
                f"ALTER TABLE {P5_BOX_TABLE} DISABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard"
            )
            await connection.execute(
                f"DELETE FROM {P5_OBSERVATION_TABLE} WHERE strategy_lifecycle_id=$1",
                lifecycle_id,
            )
            await connection.execute(f"DELETE FROM {P5_BOX_TABLE} WHERE strategy_lifecycle_id=$1", lifecycle_id)
        finally:
            await connection.execute(
                f"ALTER TABLE {P5_BOX_TABLE} ENABLE TRIGGER trg_strategy_5scr_execution_boxes_v1_guard"
            )
            await connection.execute(
                f"ALTER TABLE {P5_OBSERVATION_TABLE} ENABLE TRIGGER "
                "trg_strategy_5scr_execution_box_observations_v1_immutable"
            )
    await _cleanup_p5(postgres, lifecycle_id)


async def _side_effect_counts(postgres: PoolBackedPostgres) -> dict[str, int]:
    tables = (
        "strategy_5scr_tradeplan_candidates",
        "strategy_5scr_risk_reservations",
        "strategy_5scr_final_signal_outbox",
        "execution_commands",
    )
    counts: dict[str, int] = {}
    for table in tables:
        row = await postgres.fetchrow(f"SELECT count(*) AS n FROM {table}")
        assert row is not None
        counts[table] = int(row["n"])
    return counts


async def test_buy_ready_retry_restart_concurrency_and_no_downstream_side_effect(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    before = await _side_effect_counts(postgres)
    try:
        await _insert_target_cohort(postgres, evidence)
        first, retry = await asyncio.gather(
            repository.process_evidence(evidence), repository.process_evidence(evidence)
        )
        assert sorted((first.status, retry.status)) == ["DUPLICATE", "PERSISTED"]
        persisted = first if first.status == "PERSISTED" else retry
        assert persisted.candidate is not None
        assert persisted.candidate.execution_authority is False
        assert persisted.candidate.valid_for_execution is False
        restarted = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
        assert (await restarted.process_evidence(evidence)).status == "DUPLICATE"
        assert await restarted.load_active(box.execution_box_id) == persisted.candidate
        assert len(await restarted.load_history(lifecycle_id)) == 1
        assert len(await restarted.load_evaluations(box.execution_box_id)) == 1
        assert await _side_effect_counts(postgres) == before
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_sell_ready_persists_and_restarts_shadow_only(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_sell_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(
        thesis,
        box,
        context,
        near=Decimal("1.1000"),
        far=Decimal("1.0990"),
    )
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.status == "PERSISTED" and result.candidate is not None
        assert result.candidate.direction == "SELL"
        assert result.candidate.target_authority.target_price < result.candidate.candidate_price
        assert result.candidate.candidate_price < result.candidate.stop_authority.structural_stop_price
        recovered = await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).load_active(
            box.execution_box_id
        )
        assert recovered == result.candidate
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_nearest_eight_pips_blocks_even_when_farther_twenty_exists(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    # P5 route low is 1.1015: 1.1023 leaves only eight pips of
    # admissible target room.  The farther target must not be cherry-picked.
    evidence = _build_evidence(thesis, box, context, near=Decimal("1.1023"), far=Decimal("1.1035"))
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert (result.status, result.reason_code) == ("NO_TRADE", "NO_TRADE_TARGET_BELOW_10_PIPS")
        assert await repository.load_active(box.execution_box_id) is None
        evaluations = await repository.load_evaluations(box.execution_box_id)
        assert len(evaluations) == 1 and evaluations[0].decision == "NO_TRADE"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_consumed_nearest_target_uses_next_authoritative_target(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context, near=Decimal("1.1030"), far=Decimal("1.1040"), consumed=True)
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.status == "PERSISTED" and result.candidate is not None
        assert result.candidate.target_authority.target_price == Decimal("1.1040")
        assert result.candidate.target_authority.consumed_at_utc is None
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_canonical_lineage_refresh_reuses_same_material_candidate(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        first = await repository.process_evidence(evidence)
        assert first.status == "PERSISTED" and first.candidate is not None

        refreshed_rows: list[StructuralCandleAuthorityV1] = []
        for index, candle in enumerate(evidence.target_map_evidence.h4_candles):
            new_raw_id = _RAW_BASE + 1_000 + index
            new_hash = "sha256:" + format(new_raw_id, "064x")
            await postgres.execute(
                "INSERT INTO raw_provider_candles (id,provider,feed,symbol,timeframe,provider_timestamp,"
                "provider_timestamp_semantics,open_time,close_time,open,high,low,close,volume,tick_count,"
                "complete,payload_hash,metadata) VALUES ($1,'XM_REFRESH','refreshed-feed',$2,$3,$4,"
                "'PERIOD_OPEN',$4,$5,$6,$7,$8,$9,100,25,true,$10,'{}'::jsonb)",
                new_raw_id,
                candle.symbol,
                candle.timeframe,
                candle.open_time_utc,
                candle.close_time_utc,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                new_hash.removeprefix("sha256:"),
            )
            await postgres.execute(
                "UPDATE canonical_candles SET selected_provider='XM_REFRESH',selected_feed='refreshed-feed',"
                "selected_raw_candle_id=$2,content_hash=$3 WHERE id=$1",
                candle.canonical_row_id,
                new_raw_id,
                new_hash.removeprefix("sha256:"),
            )
            refreshed_rows.append(
                StructuralCandleAuthorityV1.model_validate(
                    {
                        **candle.model_dump(mode="python"),
                        "candle_evidence_id": "sha256:" + "0" * 64,
                        "source_content_hash": new_hash,
                        "selected_raw_candle_id": new_raw_id,
                        "provider": "XM_REFRESH",
                        "feed": "refreshed-feed",
                    }
                )
            )
        later_h1 = _candle(
            "H1",
            32,
            opened_at=_DECISION,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1021"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
        await _insert_candle(postgres, later_h1)
        refreshed = _later_evidence_with_h1(
            evidence,
            later_h1,
            request="p6-lineage-refresh",
            h4_candles=tuple(refreshed_rows),
        )
        second = await repository.process_evidence(refreshed)
        assert (second.status, second.reason_code) == (
            "DUPLICATE",
            "TRADEPLAN_CANDIDATE_ALREADY_PERSISTED",
        ), (second.status, second.reason_code)
        assert second.candidate == first.candidate
        assert len(await repository.load_history(lifecycle_id)) == 1
        assert len(await repository.load_evaluations(box.execution_box_id)) == 2
    finally:
        # _cleanup removes canonical rows before all P6 raw lineage rows.
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize("direction", ("BUY", "SELL"))
async def test_later_canonical_target_consumption_invalidates_active_without_resurrection(
    postgres: PoolBackedPostgres,
    direction: Literal["BUY", "SELL"],
) -> None:
    if direction == "BUY":
        lifecycle_id, thesis, box, context = await _seed_parent(postgres)
        evidence = _build_evidence(thesis, box, context)
        later_h1 = _candle(
            "H1",
            32,
            opened_at=_DECISION,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1041"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
    else:
        lifecycle_id, thesis, box, context = await _seed_sell_parent(postgres)
        evidence = _build_evidence(
            thesis,
            box,
            context,
            near=Decimal("1.1000"),
            far=Decimal("1.0990"),
        )
        later_h1 = _candle(
            "H1",
            232,
            opened_at=_DECISION,
            open_price=Decimal("1.1010"),
            high=Decimal("1.1011"),
            low=Decimal("1.0989"),
            close=Decimal("1.1010"),
        )
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    try:
        await _insert_target_cohort(postgres, evidence)
        first = await repository.process_evidence(evidence)
        assert first.status == "PERSISTED" and first.candidate is not None

        await _insert_candle(postgres, later_h1)
        consumed = _later_evidence_with_h1(
            evidence,
            later_h1,
            request=f"p6-{direction.lower()}-targets-consumed",
        )
        invalidated = await repository.process_evidence(consumed)
        assert (invalidated.status, invalidated.reason_code) == (
            "NO_TRADE",
            "NO_TRADE_TARGET_ALREADY_CONSUMED",
        )
        assert invalidated.candidate is not None
        assert invalidated.candidate.tradeplan_id == first.candidate.tradeplan_id
        assert invalidated.candidate.lifecycle_state == "INVALIDATED"
        assert invalidated.previous_candidate == first.candidate
        assert invalidated.evaluation is not None
        assert invalidated.evaluation.decision == "NO_TRADE"
        assert invalidated.evaluation.reason_codes == ("NO_TRADE_TARGET_ALREADY_CONSUMED",)

        restarted = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
        replay = await restarted.process_evidence(consumed)
        assert replay.status == "DUPLICATE"
        assert await restarted.load_active(box.execution_box_id) is None
        history = await restarted.load_history(lifecycle_id)
        assert len(history) == 1
        assert history[0].tradeplan_id == first.candidate.tradeplan_id
        assert history[0].lifecycle_state == "INVALIDATED"
        evaluations = await restarted.load_evaluations(box.execution_box_id)
        assert [item.decision for item in evaluations] == ["CANDIDATE", "NO_TRADE"]
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize(
    ("near", "expected"),
    ((Decimal("1.102499"), "NO_TRADE"), (Decimal("1.1025"), "PERSISTED")),
)
async def test_target_floor_decimal_boundary_9_99_vs_10_00(
    postgres: PoolBackedPostgres,
    near: Decimal,
    expected: str,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context, near=near, far=Decimal("1.1040"))
    if near == Decimal("1.102499"):
        broker = BrokerGeometryCostAuthorityV1.model_validate(
            {
                **evidence.broker_geometry.model_dump(mode="python"),
                "authority_hash": "sha256:" + "0" * 64,
                "digits": 6,
                "point": Decimal("0.000001"),
                "tick_size": Decimal("0.000001"),
            }
        )
        evidence = evidence.model_copy(update={"broker_geometry": broker})
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.status == expected
        if expected == "PERSISTED":
            assert result.candidate is not None
            assert result.candidate.target_distance_pips >= Decimal("10")
        else:
            assert result.reason_code == "NO_TRADE_TARGET_BELOW_10_PIPS"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_building_box_waits_without_candidate(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres, freeze=False)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert (result.status, result.reason_code) == ("WAIT", "WAIT_EXECUTION_BOX_NOT_FROZEN")
        assert await repository.load_active(box.execution_box_id) is None
        assert len(await repository.load_evaluations(box.execution_box_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_same_clock_conflicting_request_is_quarantined_without_second_evaluation(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        first = await repository.process_evidence(evidence)
        assert first.evaluation is not None
        conflicting = evidence.model_copy(
            update={
                "source_request_id": "p6-same-clock-conflict",
                "source_deployment_id": "conflicting-deployment",
            }
        )
        result = await repository.process_evidence(conflicting)
        assert (result.status, result.reason_code) == ("QUARANTINED", "TRADEPLAN_REQUEST_EVIDENCE_DRIFT")
        assert len(await repository.load_evaluations(box.execution_box_id)) == 1
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_missing_forged_and_incomplete_canonical_target_cohort_fail_closed(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        missing = await repository.process_evidence(evidence)
        assert (missing.status, missing.reason_code) == ("QUARANTINED", "CANONICAL_TARGET_COHORT_INCOMPLETE")
        await _insert_target_cohort(postgres, evidence)
        pivot = evidence.target_map_evidence.h4_candles[1]
        await postgres.execute("UPDATE canonical_candles SET high=high+0.0001 WHERE id=$1", pivot.canonical_row_id)
        forged = await repository.process_evidence(evidence.model_copy(update={"source_request_id": "p6-forged"}))
        assert forged.status == "QUARANTINED"
        assert forged.reason_code in {"CANONICAL_TARGET_CANDLE_DRIFT", "CANONICAL_TARGET_COHORT_INCOMPLETE"}
        await postgres.execute("UPDATE canonical_candles SET complete=false WHERE id=$1", pivot.canonical_row_id)
        incomplete = await repository.process_evidence(
            evidence.model_copy(update={"source_request_id": "p6-incomplete"})
        )
        assert incomplete.status == "QUARANTINED"
        assert await repository.load_active(box.execution_box_id) is None
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_omitting_nearer_canonical_target_is_rejected_as_anti_cherry_pick(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    full = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, full)
        shortened_h4 = full.target_map_evidence.h4_candles[2:]
        target = full.target_map_evidence.model_copy(
            update={
                "h4_candles": shortened_h4,
                "h4_cohort_count": len(shortened_h4),
                "h1_coverage_start_utc": shortened_h4[2].close_time_utc,
            }
        )
        cherry_pick = full.model_copy(update={"source_request_id": "p6-cherry-pick", "target_map_evidence": target})
        result = await repository.process_evidence(cherry_pick)
        assert (result.status, result.reason_code) == ("QUARANTINED", "CANONICAL_TARGET_COHORT_INCOMPLETE")
    finally:
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize("timeframe", ("H4", "H1"))
async def test_concurrent_canonical_insert_between_cohort_reads_never_forms_stale_candidate(
    postgres: PoolBackedPostgres,
    timeframe: Literal["H4", "H1"],
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    evidence = _build_evidence(thesis, box, context)
    barrier = _BarrierPostgres(postgres, timeframe=timeframe)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, barrier))
    durable = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    try:
        await _insert_target_cohort(postgres, evidence)
        pending = asyncio.create_task(repository.process_evidence(evidence))
        await asyncio.wait_for(barrier.reached.wait(), timeout=10)
        try:
            if timeframe == "H4":
                # A complete left/pivot/right trio creates a nearer structural
                # target after the caller's H4 cohort was read.
                start = datetime(2026, 8, 13, 0, 30, tzinfo=UTC)
                for index, high in enumerate(
                    (Decimal("1.1021"), Decimal("1.1028"), Decimal("1.1021")),
                    start=400,
                ):
                    await _insert_candle(
                        postgres,
                        _candle(
                            "H4",
                            index,
                            opened_at=start + timedelta(hours=index - 400),
                            open_price=Decimal("1.1020"),
                            high=high,
                            low=Decimal("1.1010"),
                            close=Decimal("1.1020"),
                        ),
                    )
            else:
                # This H1 row consumes every previously selected BUY target.
                await _insert_candle(
                    postgres,
                    _candle(
                        "H1",
                        450,
                        opened_at=datetime(2026, 8, 13, 6, 30, tzinfo=UTC),
                        open_price=Decimal("1.1020"),
                        high=Decimal("1.1041"),
                        low=Decimal("1.1019"),
                        close=Decimal("1.1020"),
                    ),
                )
        finally:
            assert barrier.connection is not None
            barrier.connection.release.set()
        result = await pending
        assert (result.status, result.reason_code) == (
            "QUARANTINED",
            "CANONICAL_TARGET_COHORT_CHANGED_DURING_READ",
        )
        assert await durable.load_active(box.execution_box_id) is None
        assert await durable.load_history(lifecycle_id) == ()
        assert await durable.load_evaluations(box.execution_box_id) == ()
    finally:
        if barrier.connection is not None:
            barrier.connection.release.set()
        await _cleanup(postgres, lifecycle_id)


async def test_terminal_parent_closes_active_before_bogus_incoming_scope(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        opened = await repository.process_evidence(evidence)
        assert opened.status == "PERSISTED" and opened.candidate is not None
        await postgres.execute(
            "UPDATE strategy_5scr_analysis_lifecycles_v2 SET state='INVALIDATED', last_event_at=$2 "
            "WHERE strategy_lifecycle_id=$1",
            lifecycle_id,
            _DECISION + timedelta(minutes=1),
        )
        bogus = evidence.target_map_evidence.model_copy(
            update={
                "context_epoch_id": "5scr-context:" + "f" * 32,
                "strategy_thesis_id": "5scr-thesis:" + "f" * 32,
                "execution_box_id": "5scr-execution-box:" + "f" * 32,
            }
        )
        result = await repository.process_evidence(
            evidence.model_copy(update={"source_request_id": "p6-terminal-bogus", "target_map_evidence": bogus})
        )
        assert (result.status, result.reason_code) == ("INVALIDATED", "TRADEPLAN_PARENT_NOT_ACTIVE")
        assert len(await repository.load_history(lifecycle_id)) == 1
        assert (await repository.load_history(lifecycle_id))[0].lifecycle_state == "INVALIDATED"
        assert (await repository.process_evidence(evidence)).status == "REJECTED"
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_database_rejects_authority_on_candidate_and_evaluation(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        persisted = await repository.process_evidence(evidence)
        assert persisted.candidate is not None and persisted.evaluation is not None
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {CANDIDATE_TABLE} SET execution_authority=true WHERE tradeplan_id=$1",
                persisted.candidate.tradeplan_id,
            )
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {EVALUATION_TABLE} SET valid_for_execution=true WHERE evaluation_id=$1",
                persisted.evaluation.evaluation_id,
            )
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_failed_evaluation_insert_rolls_back_candidate_and_predecessor_transition(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    first_evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, first_evidence)
        first = await repository.process_evidence(first_evidence)
        assert first.candidate is not None
        await postgres.execute(
            f"ALTER TABLE {EVALUATION_TABLE} ADD CONSTRAINT ck_p6_forced_rollback "
            "CHECK (decision <> 'CANDIDATE') NOT VALID"
        )
        later_h1 = _candle(
            "H1",
            32,
            opened_at=_DECISION,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1021"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
        await _insert_candle(postgres, later_h1)
        successor = _later_evidence_with_h1(first_evidence, later_h1, request="p6-successor")
        successor_broker = BrokerGeometryCostAuthorityV1.model_validate(
            {
                **successor.broker_geometry.model_dump(mode="python"),
                "authority_hash": "sha256:" + "0" * 64,
                "spread_price": Decimal("0.00003"),
            }
        )
        successor = successor.model_copy(update={"broker_geometry": successor_broker})
        with pytest.raises(postgres.check_violation_error):
            await repository.process_evidence(successor)
        history = await repository.load_history(lifecycle_id)
        assert len(history) == 1 and history[0].lifecycle_state == "ACTIVE"
        assert len(await repository.load_evaluations(box.execution_box_id)) == 1
    finally:
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DROP CONSTRAINT IF EXISTS ck_p6_forced_rollback")
        await _cleanup(postgres, lifecycle_id)


async def test_a_b_a_persists_distinct_occurrences_and_restart_does_not_resurrect_predecessor(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    a1_evidence = _build_evidence(thesis, box, context, request="p6-a1")
    try:
        await _insert_target_cohort(postgres, a1_evidence)
        a1 = await repository.process_evidence(a1_evidence)
        assert a1.status == "PERSISTED" and a1.candidate is not None

        # Same canonical target map, later observation, materially distinct
        # broker geometry B.
        h1_b = _candle(
            "H1",
            32,
            opened_at=_DECISION,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1021"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
        await _insert_candle(postgres, h1_b)
        b_evidence = _later_evidence_with_h1(a1_evidence, h1_b, request="p6-b")
        broker_b = BrokerGeometryCostAuthorityV1.model_validate(
            {
                **b_evidence.broker_geometry.model_dump(mode="python"),
                "authority_hash": "sha256:" + "0" * 64,
                "spread_price": Decimal("0.00003"),
            }
        )
        b_evidence = b_evidence.model_copy(update={"broker_geometry": broker_b})
        b = await repository.process_evidence(b_evidence)
        assert b.status == "PERSISTED" and b.candidate is not None

        h1_a2 = _candle(
            "H1",
            33,
            opened_at=h1_b.close_time_utc,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1021"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
        await _insert_candle(postgres, h1_a2)
        a2_evidence = _later_evidence_with_h1(b_evidence, h1_a2, request="p6-a2")
        broker_a2 = BrokerGeometryCostAuthorityV1.model_validate(
            {
                **a2_evidence.broker_geometry.model_dump(mode="python"),
                "authority_hash": "sha256:" + "0" * 64,
                "spread_price": Decimal("0.00002"),
            }
        )
        a2_evidence = a2_evidence.model_copy(update={"broker_geometry": broker_a2})
        a2 = await repository.process_evidence(a2_evidence)
        assert a2.status == "PERSISTED" and a2.candidate is not None
        assert [a1.candidate.candidate_sequence, b.candidate.candidate_sequence, a2.candidate.candidate_sequence] == [
            1,
            2,
            3,
        ]
        assert a1.candidate.material_candidate_hash == a2.candidate.material_candidate_hash
        assert len({a1.candidate.tradeplan_id, b.candidate.tradeplan_id, a2.candidate.tradeplan_id}) == 3
        history = await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).load_history(lifecycle_id)
        assert [item.lifecycle_state for item in history] == ["SUPERSEDED", "SUPERSEDED", "ACTIVE"]
    finally:
        await _cleanup(postgres, lifecycle_id)


async def test_durable_candidate_corruption_fails_closed_on_restart_and_replay(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.candidate is not None
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await postgres.execute(
            f"UPDATE {CANDIDATE_TABLE} SET payload=jsonb_set(payload,'{{route_type}}','\"SELL_BREAK_RETEST\"') "
            "WHERE tradeplan_id=$1",
            result.candidate.tradeplan_id,
        )
        restarted = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.load_active(box.execution_box_id)
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.process_evidence(evidence.model_copy(update={"source_request_id": "p6-corrupt-replay"}))
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await _cleanup(postgres, lifecycle_id)


async def test_self_consistent_forged_candidate_formation_payload_and_hash_fail_closed(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.candidate is not None
        row = await postgres.fetchrow(
            f"SELECT payload FROM {CANDIDATE_TABLE} WHERE tradeplan_id=$1",
            result.candidate.tradeplan_id,
        )
        assert row is not None
        raw_payload = row["payload"]
        candidate_payload = json.loads(raw_payload) if isinstance(raw_payload, str) else dict(raw_payload)
        forged_evidence = evidence.model_copy(update={"source_request_id": "p6-forged-formation-request"})
        forged_hash = canonical_hash_v1(
            forged_evidence.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
        )
        candidate_payload["evidence_hash"] = forged_hash
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await postgres.execute(
            f"UPDATE {CANDIDATE_TABLE} SET payload=$2::jsonb,formation_evidence_hash=$3,"
            "evidence_payload=$4::jsonb WHERE tradeplan_id=$1",
            result.candidate.tradeplan_id,
            json.dumps(candidate_payload, sort_keys=True, separators=(",", ":")),
            forged_hash,
            json.dumps(forged_evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        restarted = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.load_active(box.execution_box_id)
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.process_evidence(evidence.model_copy(update={"source_request_id": "p6-after-forgery"}))
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await _cleanup(postgres, lifecycle_id)


async def test_self_consistent_forged_evaluation_build_and_aux_payloads_fail_closed(
    postgres: PoolBackedPostgres,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.evaluation is not None
        row = await postgres.fetchrow(
            f"SELECT evidence_payload,stop_authority_payload FROM {EVALUATION_TABLE} WHERE evaluation_id=$1",
            result.evaluation.evaluation_id,
        )
        assert row is not None
        raw_wrapper = row["evidence_payload"]
        wrapper = json.loads(raw_wrapper) if isinstance(raw_wrapper, str) else dict(raw_wrapper)
        # Rewrite the canonical-candle lineage without changing any OHLC fact.
        # This produces a different, internally valid build evidence and target
        # map while preserving the candidate's material target/stop geometry.
        original_h4 = evidence.target_map_evidence.h4_candles
        forged_first = StructuralCandleAuthorityV1.model_validate(
            {
                **original_h4[0].model_dump(
                    mode="python",
                    exclude={"candle_evidence_id", "material_candle_hash"},
                ),
                "canonical_row_id": original_h4[0].canonical_row_id + 50_000,
                "selected_raw_candle_id": original_h4[0].selected_raw_candle_id + 50_000,
                "source_content_hash": "sha256:" + "e" * 64,
                "provider": "FORGED-XM-LINEAGE",
            }
        )
        forged_target_evidence = evidence.target_map_evidence.model_copy(
            update={"h4_candles": (forged_first, *original_h4[1:])}
        )
        forged_build = evidence.model_copy(
            update={
                "source_request_id": "p6-forged-evaluation-request",
                "target_map_evidence": forged_target_evidence,
            }
        )
        forged_target_map = derive_structural_target_map_v1(forged_target_evidence)
        forged_hash = canonical_hash_v1(
            forged_build.model_dump(mode="json", exclude={"source_deployment_id", "source_replica_id"})
        )
        evaluation_payload = dict(wrapper["evaluation"])
        evaluation_payload["source_request_id"] = forged_build.source_request_id
        evaluation_payload["evidence_hash"] = forged_hash
        evaluation_id_material = (
            f"{result.evaluation.strategy_lifecycle_id}|{result.evaluation.evaluation_sequence}|"
            f"{forged_hash}|{result.evaluation.decision}|{'|'.join(result.evaluation.reason_codes)}"
        )
        forged_evaluation_id = "5scr-tradeplan-eval:" + hashlib.sha256(evaluation_id_material.encode()).hexdigest()[:32]
        evaluation_payload["evaluation_id"] = forged_evaluation_id
        wrapper["evaluation"] = evaluation_payload
        wrapper["build_evidence"] = forged_build.model_dump(mode="json")
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DISABLE TRIGGER {_EVALUATION_TRIGGER}")
        await postgres.execute(
            f"UPDATE {EVALUATION_TABLE} SET evaluation_id=$2,source_request_id=$3,evidence_hash=$4,"
            "evidence_payload=$5::jsonb,target_authority_payload=$6::jsonb "
            "WHERE evaluation_id=$1",
            result.evaluation.evaluation_id,
            forged_evaluation_id,
            forged_build.source_request_id,
            forged_hash,
            json.dumps(wrapper, sort_keys=True, separators=(",", ":")),
            json.dumps(forged_target_map.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).load_evaluations(box.execution_box_id)
    finally:
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} ENABLE TRIGGER {_EVALUATION_TRIGGER}")
        await _cleanup(postgres, lifecycle_id)


@pytest.mark.parametrize(
    ("column", "value"),
    (("pip_size", Decimal("0.001")), ("target_mode", "FORGED_TARGET_MODE")),
)
async def test_candidate_pip_size_and_target_mode_column_drift_fail_closed(
    postgres: PoolBackedPostgres,
    column: str,
    value: Decimal | str,
) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    evidence = _build_evidence(thesis, box, context)
    numbers_constraint = "ck_5scr_tradeplan_candidate_v2_numbers"
    numbers_constraint_dropped = False
    try:
        await _insert_target_cohort(postgres, evidence)
        result = await repository.process_evidence(evidence)
        assert result.candidate is not None
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
        if column == "pip_size":
            await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DROP CONSTRAINT {numbers_constraint}")
            numbers_constraint_dropped = True
        await postgres.execute(
            f"UPDATE {CANDIDATE_TABLE} SET {column}=$2 WHERE tradeplan_id=$1",
            result.candidate.tradeplan_id,
            value,
        )
        restarted = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.load_active(box.execution_box_id)
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await restarted.process_evidence(evidence.model_copy(update={"source_request_id": f"p6-{column}-drift"}))
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await _cleanup(postgres, lifecycle_id)
        if numbers_constraint_dropped:
            await postgres.execute(
                f"ALTER TABLE {CANDIDATE_TABLE} ADD CONSTRAINT {numbers_constraint} CHECK ("
                "candidate_sequence >= 1 AND candidate_revision >= 1 AND box_sequence >= 1 "
                "AND box_version >= 1 AND state_version >= 1 AND candidate_price > 0 AND stop_loss > 0 "
                "AND target_price > 0 AND risk_distance_price > 0 AND target_distance_price > 0 "
                "AND rr > 0 AND pip_size > 0 AND broker_digits BETWEEN 0 AND 12 AND broker_point > 0 "
                "AND broker_tick_size > 0 AND broker_pip_size > 0 AND broker_spread_price >= 0 "
                "AND broker_point <= broker_tick_size AND pip_size = broker_pip_size)"
            )


async def test_predecessor_lineage_corruption_fails_closed_on_history_load(postgres: PoolBackedPostgres) -> None:
    lifecycle_id, thesis, box, context = await _seed_parent(postgres)
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    first_evidence = _build_evidence(thesis, box, context, request="p6-predecessor-a")
    try:
        await _insert_target_cohort(postgres, first_evidence)
        first = await repository.process_evidence(first_evidence)
        assert first.candidate is not None
        h1_b = _candle(
            "H1",
            32,
            opened_at=_DECISION,
            open_price=Decimal("1.1020"),
            high=Decimal("1.1021"),
            low=Decimal("1.1019"),
            close=Decimal("1.1020"),
        )
        await _insert_candle(postgres, h1_b)
        second_evidence = _later_evidence_with_h1(first_evidence, h1_b, request="p6-predecessor-b")
        broker_b = BrokerGeometryCostAuthorityV1.model_validate(
            {
                **second_evidence.broker_geometry.model_dump(mode="python"),
                "authority_hash": "sha256:" + "0" * 64,
                "spread_price": Decimal("0.00003"),
            }
        )
        second = await repository.process_evidence(second_evidence.model_copy(update={"broker_geometry": broker_b}))
        assert second.status == "PERSISTED" and second.candidate is not None
        assert second.candidate.candidate_sequence == 2
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await postgres.execute(
            f"UPDATE {CANDIDATE_TABLE} SET payload=jsonb_set(payload,'{{previous_tradeplan_id}}',$2::jsonb) "
            "WHERE tradeplan_id=$1",
            second.candidate.tradeplan_id,
            '"5scr-tradeplan-v2:' + "f" * 32 + '"',
        )
        with pytest.raises(TradePlanCandidateV2IntegrityError):
            await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).load_history(lifecycle_id)
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
        await _cleanup(postgres, lifecycle_id)


async def test_readiness_fails_closed_for_weakened_constraint_index_and_trigger(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres))
    assert (await repository.schema_status()).ready
    evaluation_box_fk = "fk_5scr_tradeplan_candidate_evaluation_v2_box_scope"
    evaluation_parent_unique = "uq_5scr_execution_box_tradeplan_evaluation_scope_v1"
    try:
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DROP CONSTRAINT {evaluation_box_fk}")
        await postgres.execute(f"ALTER TABLE {P5_BOX_TABLE} DROP CONSTRAINT {evaluation_parent_unique}")
        await postgres.execute(
            f"ALTER TABLE {P5_BOX_TABLE} ADD CONSTRAINT {evaluation_parent_unique} UNIQUE (execution_box_id)"
        )
        await postgres.execute(
            f"ALTER TABLE {EVALUATION_TABLE} ADD CONSTRAINT {evaluation_box_fk} "
            f"FOREIGN KEY (execution_box_id) REFERENCES {P5_BOX_TABLE}(execution_box_id) ON DELETE RESTRICT"
        )
        weakened = await repository.schema_status()
        assert evaluation_parent_unique in weakened.invalid_constraints
        assert evaluation_box_fk in weakened.invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DROP CONSTRAINT IF EXISTS {evaluation_box_fk}")
        await postgres.execute(f"ALTER TABLE {P5_BOX_TABLE} DROP CONSTRAINT IF EXISTS {evaluation_parent_unique}")
        await postgres.execute(
            f"ALTER TABLE {P5_BOX_TABLE} ADD CONSTRAINT {evaluation_parent_unique} UNIQUE "
            "(execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,symbol,"
            "strategy_direction,material_box_hash)"
        )
        await postgres.execute(
            f"ALTER TABLE {EVALUATION_TABLE} ADD CONSTRAINT {evaluation_box_fk} FOREIGN KEY "
            "(execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,symbol,"
            "strategy_direction,material_box_hash) REFERENCES "
            f"{P5_BOX_TABLE}(execution_box_id,strategy_lifecycle_id,context_epoch_id,strategy_thesis_id,"
            "symbol,strategy_direction,material_box_hash) ON DELETE RESTRICT"
        )
    constraint = "ck_5scr_tradeplan_candidate_v2_shadow_only"
    try:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE {CANDIDATE_TABLE} ADD CONSTRAINT {constraint} CHECK (execution_authority IS NOT NULL)"
        )
        assert constraint in (await repository.schema_status()).invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(
            f"ALTER TABLE {CANDIDATE_TABLE} ADD CONSTRAINT {constraint} "
            "CHECK (valid_for_execution IS FALSE AND execution_authority IS FALSE "
            "AND next_required_stage = 'RISK_RESERVATION')"
        )
    try:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} DISABLE TRIGGER {_CANDIDATE_TRIGGER}")
        assert _CANDIDATE_TRIGGER in (await repository.schema_status()).invalid_triggers
    finally:
        await postgres.execute(f"ALTER TABLE {CANDIDATE_TABLE} ENABLE TRIGGER {_CANDIDATE_TRIGGER}")
    index = "uq_5scr_tradeplan_candidate_v2_active_box"
    try:
        await postgres.execute(f"DROP INDEX {index}")
        await postgres.execute(f"CREATE UNIQUE INDEX {index} ON {CANDIDATE_TABLE}(execution_box_id)")
        assert index in (await repository.schema_status()).invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX {index}")
        await postgres.execute(
            f"CREATE UNIQUE INDEX {index} ON {CANDIDATE_TABLE}(execution_box_id) WHERE lifecycle_state = 'ACTIVE'"
        )
    assert (await repository.schema_status()).ready


async def test_future_and_wrong_scope_target_evidence_rejected_before_database() -> None:
    # The contract itself prevents future leakage and mixed canonical scope;
    # repository tests above prove DB canonicalization for valid-shaped claims.
    h4 = _buy_h4(near=Decimal("1.1030"), far=Decimal("1.1040"))
    h1 = _h1(Decimal("1.1020"))
    payload = dict(
        strategy_lifecycle_id="5scr-lifecycle:" + "a" * 32,
        context_epoch_id="5scr-context:" + "b" * 32,
        strategy_thesis_id="5scr-thesis:" + "c" * 32,
        execution_box_id="5scr-execution-box:" + "d" * 32,
        material_context_hash="sha256:" + "1" * 64,
        thesis_semantic_identity_hash="sha256:" + "2" * 64,
        execution_box_material_hash="sha256:" + "3" * 64,
        symbol="EURUSD",
        direction="BUY",
        target_map_version="targets-v1",
        decision_at_utc=_DECISION,
        coverage_start_utc=datetime(2026, 8, 12, 7, tzinfo=UTC),
        coverage_end_utc=_DECISION,
        h4_cohort_count=len(h4),
        h1_coverage_start_utc=h4[2].close_time_utc,
        h1_coverage_end_utc=_DECISION,
        h1_cohort_count=len(h1),
        selection_anchor=h1[-1],
        h4_candles=h4,
        h1_consumption_candles=h1,
    )
    future = list(h1)
    future[-1] = StructuralCandleAuthorityV1.model_validate(
        {
            **future[-1].model_dump(
                mode="python",
                exclude={"candle_evidence_id", "material_candle_hash"},
            ),
            "open_time_utc": _DECISION,
            "close_time_utc": _DECISION + timedelta(hours=1),
        }
    )
    with pytest.raises(ValidationError, match="future candle leakage"):
        StructuralTargetMapEvidenceV1.model_validate(
            {**payload, "selection_anchor": future[-1], "h1_consumption_candles": future}
        )
    wrong = list(h4)
    wrong[0] = StructuralCandleAuthorityV1.model_validate(
        {
            **wrong[0].model_dump(
                mode="python",
                exclude={"candle_evidence_id", "material_candle_hash"},
            ),
            "symbol": "USDJPY",
        }
    )
    with pytest.raises(ValidationError, match="scope mismatch"):
        StructuralTargetMapEvidenceV1.model_validate({**payload, "h4_candles": wrong})
