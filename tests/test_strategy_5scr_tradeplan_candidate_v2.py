from __future__ import annotations

import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal, cast

import pytest
from pydantic import ValidationError

import analysis.strategy_5scr_tradeplan_candidate_v2 as tradeplan_rules
import storage.strategy_5scr_tradeplan_candidate_v2_repository as tradeplan_storage
from analysis.strategy_5scr_tradeplan_candidate_v2 import (
    derive_structural_stop_authority_v1,
    derive_structural_target_map_v1,
    intersect_price_intervals_v1,
    solve_tradeplan_candidate_v2,
)
from contracts.strategy_5scr_context_epoch_v1 import StrategyContextEpochV1
from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import ExecutionBoxV1, execution_box_identity_v1
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2
from contracts.strategy_5scr_tradeplan_candidate_v2 import (
    BrokerGeometryCostAuthorityV1,
    PriceIntervalV1,
    StructuralCandleAuthorityV1,
    StructuralTargetMapAuthorityV1,
    StructuralTargetMapEvidenceV1,
    TradePlanCandidateBuildEvidenceV2,
    TradePlanCandidateV2,
    structural_target_map_authority_hash_v1,
)

NOW = datetime(2026, 8, 13, 0, tzinfo=UTC)
H = "sha256:" + "1" * 64


def test_schema_fingerprint_binds_exact_catalog_bytes() -> None:
    unquoted = "CREATE   INDEX candidate_idx ON authority_table (state)"
    formatting_only = "create index CANDIDATE_IDX on AUTHORITY_TABLE (STATE)"
    literal = "CHECK (state = 'ACTIVE')"
    identifier = 'SELECT "AuthorityScope" FROM authority_table'
    dollar_quoted = "CREATE FUNCTION guard() RETURNS trigger AS $body$ RETURN NEW; $body$ LANGUAGE plpgsql"

    assert tradeplan_storage._sql_fingerprint(unquoted) != tradeplan_storage._sql_fingerprint(formatting_only)
    assert tradeplan_storage._sql_fingerprint(unquoted) == tradeplan_storage._sql_fingerprint(unquoted)
    assert tradeplan_storage._sql_fingerprint(literal) != tradeplan_storage._sql_fingerprint(
        literal.replace("'ACTIVE'", "'active'")
    )
    assert tradeplan_storage._sql_fingerprint(identifier) != tradeplan_storage._sql_fingerprint(
        identifier.replace('"AuthorityScope"', '"authorityscope"')
    )
    assert tradeplan_storage._sql_fingerprint(dollar_quoted) != tradeplan_storage._sql_fingerprint(
        dollar_quoted.replace("RETURN NEW;", "RETURN OLD;")
    )
    assert tradeplan_storage._sql_fingerprint("-- guard\nRETURN NEW;") != tradeplan_storage._sql_fingerprint(
        "-- guard RETURN NEW;"
    )


def test_schema_status_fails_closed_for_nonpersistent_authority_tables() -> None:
    status = tradeplan_storage.TradePlanCandidateV2SchemaStatus(
        missing_tables=(),
        invalid_tables=(tradeplan_storage.CANDIDATE_TABLE,),
        missing_columns=(),
        invalid_columns=(),
        missing_constraints=(),
        invalid_constraints=(),
        missing_indexes=(),
        invalid_indexes=(),
        missing_triggers=(),
        invalid_triggers=(),
    )
    source = inspect.getsource(tradeplan_storage.Strategy5SCRTradePlanCandidateV2Repository.schema_status)

    assert not status.ready
    assert "relkind::text AS relkind" in source
    assert "relpersistence::text AS relpersistence" in source
    assert "relispartition" in source


def _candle(
    timeframe: Literal["H4", "H1"],
    index: int,
    *,
    open: str,
    high: str,
    low: str,
    close: str,
    start: datetime | None = None,
) -> StructuralCandleAuthorityV1:
    hours = 4 if timeframe == "H4" else 1
    base = (start or NOW - timedelta(hours=24)) + timedelta(hours=hours * index)
    return StructuralCandleAuthorityV1(
        source_content_hash="sha256:" + format(index + 10, "064x"),
        canonical_row_id=index + 1,
        selected_raw_candle_id=index + 101,
        symbol="EURUSD",
        timeframe=timeframe,
        open_time_utc=base,
        close_time_utc=base + timedelta(hours=hours),
        open=Decimal(open),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        provider="test-provider",
        feed="test-feed",
        provider_timestamp_semantics="CANONICAL_WINDOW",
        selection_policy="CANONICAL_TEST_V1",
        selection_rank=index,
    )


def _h4_buy(*, near: str = "1.10120", far: str = "1.10300") -> tuple[StructuralCandleAuthorityV1, ...]:
    # Two strict swing highs: nearest at candle 1, farther at candle 3.
    return (
        _candle("H4", 0, open="1.0990", high="1.1005", low="1.0980", close="1.1000"),
        _candle("H4", 1, open="1.1000", high=near, low="1.0990", close="1.1004"),
        _candle("H4", 2, open="1.1004", high="1.1006", low="1.0994", close="1.1002"),
        _candle("H4", 3, open="1.1002", high=far, low="1.0998", close="1.1010"),
        _candle("H4", 4, open="1.1010", high="1.1015", low="1.0997", close="1.1000"),
        _candle("H4", 5, open="1.1000", high="1.1007", low="1.0996", close="1.1000"),
    )


def _h4_sell(*, near: str = "1.09880", far: str = "1.09700") -> tuple[StructuralCandleAuthorityV1, ...]:
    return (
        _candle("H4", 0, open="1.1010", high="1.1020", low="1.0995", close="1.1000"),
        _candle("H4", 1, open="1.1000", high="1.1010", low=near, close="1.0996"),
        _candle("H4", 2, open="1.0996", high="1.1006", low="1.0992", close="1.0998"),
        _candle("H4", 3, open="1.0998", high="1.1002", low=far, close="1.0990"),
        _candle("H4", 4, open="1.0990", high="1.1003", low="1.0985", close="1.1000"),
        _candle("H4", 5, open="1.1000", high="1.1005", low="1.0993", close="1.1000"),
    )


def _h1_coverage(*, touch: Decimal | None = None) -> tuple[StructuralCandleAuthorityV1, ...]:
    return tuple(
        _candle(
            "H1",
            index,
            open="1.0998",
            high=str(touch if touch is not None and index == 3 else Decimal("1.1001")),
            low="1.0997",
            close="1.1000",
            start=NOW - timedelta(hours=12),
        )
        for index in range(12)
    )


def _h1_consumes_all(direction: Literal["BUY", "SELL"]) -> tuple[StructuralCandleAuthorityV1, ...]:
    rows = list(_h1_coverage())
    # Use a close after both strict-swing right candles have closed so one
    # authoritative H1 wick consumes every directional target in the map.
    rows[10] = _candle(
        "H1",
        10,
        open="1.1000",
        high="1.1040" if direction == "BUY" else "1.1002",
        low="1.0998" if direction == "BUY" else "1.0960",
        close="1.1000",
        start=NOW - timedelta(hours=12),
    )
    return tuple(rows)


def _lifecycle() -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id="5scr-lifecycle:" + "a" * 32,
        symbol="EURUSD",
        state="ANALYSIS_OPEN",
        opened_at_utc=NOW - timedelta(days=1),
        last_event_at_utc=NOW - timedelta(hours=1),
        last_continuity_event_at_utc=NOW - timedelta(hours=1),
        last_material_event_at_utc=NOW - timedelta(hours=2),
        material_state_hash="a" * 64,
    )


def _context(direction: Literal["BUY", "SELL"]) -> StrategyContextEpochV1:
    return StrategyContextEpochV1(
        context_epoch_id="5scr-context:" + "b" * 32,
        strategy_lifecycle_id=_lifecycle().strategy_lifecycle_id,
        epoch_sequence=1,
        symbol="EURUSD",
        state="ACTIVE",
        material_context_hash="sha256:" + "b" * 64,
        opened_at_utc=NOW - timedelta(hours=24),
        last_confirmed_at_utc=NOW - timedelta(hours=2),
        daily_source_candle_ids=("d1",),
        h4_source_candle_ids=("h4",),
        daily_bias="BULLISH" if direction == "BUY" else "BEARISH",
        h4_structure="IMPULSE",
        price_location="DISCOUNT" if direction == "BUY" else "PREMIUM",
        liquidity_state="ACCEPTED",
        direction_domain="BUY_ONLY" if direction == "BUY" else "SELL_ONLY",
        allowed_routes=(f"{direction}_BREAK_RETEST",),
        blocked_routes=(),
        target_map_version="targets-v1",
        structural_invalidation_version="stop-v1",
        transition_reason="OPENED",
        evidence_hash=H,
        last_observed_at_utc=NOW - timedelta(hours=1),
        last_source_event_id="event-1",
    )


def _thesis(direction: Literal["BUY", "SELL"]) -> DirectionalThesisV1:
    return DirectionalThesisV1(
        strategy_thesis_id="5scr-thesis:" + "c" * 32,
        strategy_lifecycle_id=_lifecycle().strategy_lifecycle_id,
        context_epoch_id=_context(direction).context_epoch_id,
        thesis_sequence=1,
        symbol="EURUSD",
        strategy_direction=direction,
        direction_domain_at_creation="BUY_ONLY" if direction == "BUY" else "SELL_ONLY",
        selected_route=f"{direction}_BREAK_RETEST",
        pressure_authority_mode="RADAR_ONLY",
        pressure_contract_status="RADAR_ONLY",
        pressure_reference_direction=direction,
        pressure_authority_hash="sha256:" + "c" * 64,
        h1_proof_id="5scr-h1-proof:" + "d" * 32,
        m15_proof_id="5scr-m15-proof:" + "e" * 32,
        structural_proof_hash="sha256:" + "d" * 64,
        semantic_identity_hash="sha256:" + "e" * 64,
        created_at_utc=NOW - timedelta(hours=10),
        liveness_checked_through_utc=NOW - timedelta(hours=1),
    )


def _box(direction: Literal["BUY", "SELL"], *, low: float = 1.0990, high: float = 1.1000) -> ExecutionBoxV1:
    material = "sha256:" + "f" * 64
    box_id = execution_box_identity_v1(_thesis(direction).strategy_thesis_id, 1, 1, material)
    return ExecutionBoxV1(
        execution_box_id=box_id,
        strategy_lifecycle_id=_lifecycle().strategy_lifecycle_id,
        context_epoch_id=_context(direction).context_epoch_id,
        strategy_thesis_id=_thesis(direction).strategy_thesis_id,
        box_sequence=1,
        box_version=1,
        symbol="EURUSD",
        strategy_direction=direction,
        route_type=f"{direction}_BREAK_RETEST",
        state="FROZEN",
        box_low=low,
        box_high=high,
        opened_at_utc=NOW - timedelta(hours=4),
        frozen_at_utc=NOW - timedelta(hours=2),
        freeze_authority_hash="sha256:" + "a" * 64,
        material_box_hash=material,
        evidence_hash="sha256:" + "9" * 64,
        thesis_semantic_identity_hash=_thesis(direction).semantic_identity_hash,
        source_m1_ids=("sha256:" + "1" * 64,),
        source_m1_evidence_ids=("sha256:" + "2" * 64,),
        last_observed_at_utc=NOW - timedelta(hours=1),
    )


def _broker() -> BrokerGeometryCostAuthorityV1:
    return BrokerGeometryCostAuthorityV1(
        authority_id="cost-eurusd-v1",
        symbol="EURUSD",
        captured_at_utc=NOW - timedelta(minutes=5),
        valid_until_utc=NOW + timedelta(minutes=5),
        digits=5,
        point=Decimal("0.00001"),
        tick_size=Decimal("0.00001"),
        pip_size=Decimal("0.0001"),
        spread_price=Decimal("0.00002"),
    )


def _evidence(
    direction: Literal["BUY", "SELL"], *, h4=None, h1=None, request="req-1"
) -> TradePlanCandidateBuildEvidenceV2:
    box = _box(direction)
    h4_rows = h4 or (_h4_buy() if direction == "BUY" else _h4_sell())
    h1_rows = h1 or _h1_coverage()
    target = StructuralTargetMapEvidenceV1(
        strategy_lifecycle_id=_lifecycle().strategy_lifecycle_id,
        context_epoch_id=_context(direction).context_epoch_id,
        strategy_thesis_id=_thesis(direction).strategy_thesis_id,
        execution_box_id=box.execution_box_id,
        material_context_hash=_context(direction).material_context_hash,
        thesis_semantic_identity_hash=_thesis(direction).semantic_identity_hash,
        execution_box_material_hash=box.material_box_hash,
        symbol="EURUSD",
        direction=direction,
        target_map_version="targets-v1",
        decision_at_utc=NOW,
        coverage_start_utc=_context(direction).opened_at_utc,
        coverage_end_utc=NOW,
        h4_cohort_count=len(h4_rows),
        h1_coverage_start_utc=h4_rows[2].close_time_utc,
        h1_coverage_end_utc=NOW,
        h1_cohort_count=len(h1_rows),
        selection_anchor=h1_rows[-1],
        h4_candles=h4_rows,
        h1_consumption_candles=h1_rows,
    )
    return TradePlanCandidateBuildEvidenceV2(
        source_request_id=request,
        decision_at_utc=NOW,
        target_map_evidence=target,
        broker_geometry=_broker(),
    )


def _solve(direction: Literal["BUY", "SELL"], *, evidence=None, box=None, current=None, candidate_sequence=1):
    return solve_tradeplan_candidate_v2(
        lifecycle=_lifecycle(),
        context=_context(direction),
        thesis=_thesis(direction),
        execution_box=box or _box(direction),
        evidence=evidence or _evidence(direction),
        evaluation_sequence=1,
        candidate_sequence=candidate_sequence,
        current_candidate=current,
    )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_valid_buy_and_sell_build_shadow_candidate(direction: str) -> None:
    result = _solve(cast(Literal["BUY", "SELL"], direction))
    assert result.decision == "CANDIDATE"
    assert result.candidate is not None
    assert result.candidate.execution_authority is False
    assert result.candidate.valid_for_execution is False
    assert result.candidate.next_required_stage == "RISK_RESERVATION"
    assert result.candidate.gross_rr >= Decimal("1.5")


def test_nearest_eight_pip_target_blocks_without_selecting_far_twenty_pip_target() -> None:
    result = _solve(
        "BUY",
        box=_box("BUY", low=1.0999, high=1.1000),
        evidence=_evidence("BUY", h4=_h4_buy(near="1.10080", far="1.10200")),
    )
    assert (result.decision, result.reason_code) == ("NO_TRADE", "NO_TRADE_TARGET_BELOW_10_PIPS")


def test_target_eight_pips_from_anchor_is_valid_if_route_has_ten_pip_room() -> None:
    result = _solve("BUY", evidence=_evidence("BUY", h4=_h4_buy(near="1.10080", far="1.10200")))
    assert result.decision == "CANDIDATE"
    assert result.candidate is not None and result.candidate.target_authority.target_price == Decimal("1.10080")


def test_exact_ten_pips_is_eligible() -> None:
    result = _solve("BUY", evidence=_evidence("BUY", h4=_h4_buy(near="1.10100")))
    assert result.decision == "CANDIDATE"


def test_rr_exactly_one_point_five_passes_after_canonical_quantization() -> None:
    result = _solve("BUY", evidence=_evidence("BUY", h4=_h4_buy(near="1.10119")))
    assert result.decision == "CANDIDATE"
    assert result.candidate is not None
    assert result.candidate.target_distance_pips == Decimal("13.2")
    assert result.candidate.risk_distance_pips == Decimal("8.8")
    assert result.candidate.gross_rr == Decimal("1.500000000000")


def test_raw_rr_below_one_point_five_is_rejected_before_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the otherwise conservative upper-bound grid projection one tick
    # above the exact 1.5 boundary. The final raw Decimal check must reject it,
    # even if durable 12-place quantization could make a near-boundary value
    # appear equal to the threshold.
    monkeypatch.setattr(
        tradeplan_rules,
        "_floor_grid",
        lambda value, tick: (value / tick).to_integral_value(rounding="ROUND_CEILING") * tick,
    )
    result = _solve("BUY", evidence=_evidence("BUY", h4=_h4_buy(near="1.10118")))
    assert (result.decision, result.reason_code) == ("NO_TRADE", "NO_TRADE_RR_BELOW_MINIMUM")


def test_cost_room_failure_is_distinct_from_generic_empty_intersection() -> None:
    broker_payload = _broker().model_dump(mode="python")
    broker_payload.update(
        authority_hash="sha256:" + "0" * 64,
        spread_price=Decimal("0.00050"),
    )
    broker = BrokerGeometryCostAuthorityV1.model_validate(broker_payload)
    evidence = _evidence("BUY").model_copy(update={"broker_geometry": broker})
    result = _solve("BUY", evidence=evidence)
    assert (result.decision, result.reason_code) == ("NO_TRADE", "NO_TRADE_EXECUTION_COST")

    disjoint = intersect_price_intervals_v1(
        (
            PriceIntervalV1(low=Decimal("1.0990"), high=Decimal("1.0994"), source="LEFT"),
            PriceIntervalV1(low=Decimal("1.0996"), high=Decimal("1.1000"), source="RIGHT"),
        ),
        tick_size=Decimal("0.00001"),
    )
    assert disjoint is None


def test_h1_after_formation_consumes_nearest_and_selects_next_target() -> None:
    h4 = _h4_buy(near="1.10120", far="1.10300")
    h1 = _h1_coverage(touch=Decimal("1.1013"))
    target_map = derive_structural_target_map_v1(_evidence("BUY", h4=h4, h1=h1).target_map_evidence)
    selected = next(item for item in target_map.targets if item.target_id == target_map.selected_target_id)
    assert selected.target_price == Decimal("1.10300")
    assert target_map.targets[0].consumed_at_utc == h1[3].close_time_utc


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_later_consumption_invalidates_current_without_a_successor(direction: str) -> None:
    typed_direction = cast(Literal["BUY", "SELL"], direction)
    first = _solve(typed_direction)
    assert first.candidate is not None
    h4 = _h4_buy() if typed_direction == "BUY" else _h4_sell()
    evidence = _evidence(
        typed_direction,
        h4=h4,
        h1=_h1_consumes_all(typed_direction),
        request=f"consume-all-{typed_direction.lower()}",
    )
    result = _solve(typed_direction, evidence=evidence, current=first.candidate)
    assert (result.decision, result.reason_code) == (
        "NO_TRADE",
        "NO_TRADE_TARGET_ALREADY_CONSUMED",
    )
    assert result.evaluation is not None and result.evaluation.decision == "NO_TRADE"
    assert result.candidate is None
    assert result.previous_candidate == first.candidate
    assert result.transition is not None
    assert result.transition.to_state == "INVALIDATED"
    assert result.transition.reason_code == "TRADEPLAN_TARGET_AUTHORITY_LOST"
    assert result.transition.successor_tradeplan_id is None


def test_consumption_invalidation_reduction_is_deterministic_for_request_retry() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    evidence = _evidence(
        "BUY",
        h1=_h1_consumes_all("BUY"),
        request="consume-retry",
    )
    invalidated = _solve("BUY", evidence=evidence, current=first.candidate)
    assert invalidated.transition is not None
    # The pure reducer has no evaluation ledger, so it deterministically emits
    # the same transition authority. Durable storage resolves the identical
    # request before invoking it again and therefore persists this only once.
    replay = _solve("BUY", evidence=evidence, current=first.candidate)
    assert replay.decision == "NO_TRADE"
    assert replay.transition == invalidated.transition
    assert replay.evaluation == invalidated.evaluation


def test_h1_before_or_at_formation_does_not_consume_target() -> None:
    h4 = _h4_buy()
    h1 = _h1_coverage()
    target_map = derive_structural_target_map_v1(_evidence("BUY", h4=h4, h1=h1).target_map_evidence)
    assert target_map.targets[0].consumed_at_utc is None


def test_stop_is_exact_route_extreme_plus_one_tick() -> None:
    buy = derive_structural_stop_authority_v1(box=_box("BUY"), broker=_broker())
    sell = derive_structural_stop_authority_v1(box=_box("SELL"), broker=_broker())
    assert buy.structural_stop_price == Decimal("1.09899")
    assert sell.structural_stop_price == Decimal("1.10001")


def test_forged_candle_material_hash_is_rejected() -> None:
    payload = _h4_buy()[0].model_dump(mode="python")
    payload["high"] = Decimal("9")
    with pytest.raises(ValidationError, match="material candle hash"):
        StructuralCandleAuthorityV1.model_validate(payload)


def test_target_map_version_must_match_context() -> None:
    target = _evidence("BUY").target_map_evidence.model_copy(update={"target_map_version": "targets-v2"})
    evidence = _evidence("BUY").model_copy(update={"target_map_evidence": target})
    assert _solve("BUY", evidence=evidence).reason_code == "NO_TRADE_TARGET_NOT_AUTHORITATIVE"


def test_building_box_waits_and_terminal_box_does_not_form_candidate() -> None:
    box = _box("BUY")
    building = box.model_copy(update={"state": "BUILDING", "frozen_at_utc": None, "freeze_authority_hash": None})
    building_evidence = _evidence("BUY")
    target = building_evidence.target_map_evidence.model_copy(update={"execution_box_id": building.execution_box_id})
    building_evidence = building_evidence.model_copy(update={"target_map_evidence": target})
    assert _solve("BUY", box=building, evidence=building_evidence).reason_code == "WAIT_EXECUTION_BOX_NOT_FROZEN"


def test_broker_cost_expiry_fails_closed() -> None:
    broker = _broker().model_copy(update={"valid_until_utc": NOW - timedelta(seconds=1)})
    evidence = _evidence("BUY").model_copy(update={"broker_geometry": broker})
    assert _solve("BUY", evidence=evidence).reason_code == "NO_TRADE_BROKER_CONSTRAINT"


def test_exact_retry_is_duplicate_and_nonmaterial_lineage_churn_is_ignored() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    churn = _evidence("BUY", request="req-2").model_copy(
        update={"source_deployment_id": "new-deployment", "source_replica_id": "replica-2"}
    )
    replay = _solve("BUY", evidence=churn, current=first.candidate)
    assert replay.decision == "DUPLICATE"
    assert replay.candidate == first.candidate
    assert replay.evaluation is not None
    assert replay.evaluation.decision == "CANDIDATE"
    assert replay.evaluation.result_tradeplan_id == first.candidate.tradeplan_id
    assert replay.evaluation.reason_codes == ("TRADEPLAN_CANDIDATE_REUSED",)


def test_exact_evidence_retry_precedes_advanced_parent_liveness_gate() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    lifecycle = _lifecycle().model_copy(update={"last_event_at_utc": NOW + timedelta(minutes=1)})
    result = solve_tradeplan_candidate_v2(
        lifecycle=lifecycle,
        context=_context("BUY"),
        thesis=_thesis("BUY"),
        execution_box=_box("BUY"),
        evidence=_evidence("BUY"),
        evaluation_sequence=2,
        candidate_sequence=2,
        current_candidate=first.candidate,
    )
    assert (result.decision, result.reason_code) == (
        "DUPLICATE",
        "TRADEPLAN_EXACT_REQUEST_ALREADY_EVALUATED",
    )
    assert result.evaluation is None


def test_neutral_h1_coverage_churn_reuses_material_candidate_with_new_evaluation() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    old = _evidence("BUY")
    extra = _candle(
        "H1",
        12,
        open="1.1000",
        high="1.1002",
        low="1.0998",
        close="1.1000",
        start=NOW - timedelta(hours=12),
    )
    target = old.target_map_evidence.model_copy(
        update={
            "decision_at_utc": NOW + timedelta(hours=1),
            "coverage_end_utc": NOW + timedelta(hours=1),
            "h1_coverage_end_utc": NOW + timedelta(hours=1),
            "h1_cohort_count": old.target_map_evidence.h1_cohort_count + 1,
            "selection_anchor": extra,
            "h1_consumption_candles": (*old.target_map_evidence.h1_consumption_candles, extra),
        }
    )
    evidence = old.model_copy(
        update={
            "source_request_id": "req-neutral-h1",
            "decision_at_utc": NOW + timedelta(hours=1),
            "target_map_evidence": target,
            "broker_geometry": BrokerGeometryCostAuthorityV1.model_validate(
                {
                    **_broker().model_dump(mode="python"),
                    "authority_hash": "sha256:" + "0" * 64,
                    "valid_until_utc": NOW + timedelta(hours=2),
                }
            ),
        }
    )
    replay = _solve("BUY", evidence=evidence, current=first.candidate)
    assert replay.decision == "DUPLICATE"
    assert replay.candidate == first.candidate
    assert replay.evaluation is not None
    assert replay.evaluation.evidence_hash != first.candidate.evidence_hash


def test_broker_capture_clock_churn_is_lineage_only_when_geometry_is_identical() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    payload = _broker().model_dump(mode="python")
    payload.update(
        authority_hash="sha256:" + "0" * 64,
        captured_at_utc=NOW - timedelta(minutes=4),
        valid_until_utc=NOW + timedelta(minutes=6),
    )
    broker = BrokerGeometryCostAuthorityV1.model_validate(payload)
    evidence = _evidence("BUY", request="req-broker-refresh").model_copy(update={"broker_geometry": broker})
    replay = _solve("BUY", evidence=evidence, current=first.candidate)
    assert replay.decision == "DUPLICATE"
    assert replay.candidate == first.candidate
    assert replay.evaluation is not None


def test_target_map_authority_cannot_be_replayed_with_forged_lineage() -> None:
    target_map = derive_structural_target_map_v1(_evidence("BUY").target_map_evidence)
    payload = target_map.model_dump(mode="python")
    payload["source_evidence_hash"] = "sha256:" + "7" * 64
    with pytest.raises(ValidationError, match="target-map authority integrity"):
        StructuralTargetMapAuthorityV1.model_validate(payload)


def test_provider_lineage_churn_does_not_create_material_target_or_candidate() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    old = _evidence("BUY")
    changed_h4 = tuple(
        StructuralCandleAuthorityV1.model_validate(
            {
                **candle.model_dump(mode="python", exclude={"candle_evidence_id", "material_candle_hash"}),
                "canonical_row_id": candle.canonical_row_id + 100,
                "selected_raw_candle_id": candle.selected_raw_candle_id + 100,
                "source_content_hash": "sha256:" + format(index + 300, "064x"),
                "provider": "replacement-provider",
                "feed": "replacement-feed",
                "selection_policy": "RESELECTION_V2",
            }
        )
        for index, candle in enumerate(old.target_map_evidence.h4_candles)
    )
    target = old.target_map_evidence.model_copy(update={"h4_candles": changed_h4})
    evidence = old.model_copy(update={"source_request_id": "req-lineage-churn", "target_map_evidence": target})
    old_map = derive_structural_target_map_v1(old.target_map_evidence)
    new_map = derive_structural_target_map_v1(target)
    old_target = next(item for item in old_map.targets if item.target_id == old_map.selected_target_id)
    new_target = next(item for item in new_map.targets if item.target_id == new_map.selected_target_id)
    assert old_target.target_id == new_target.target_id
    assert old_target.material_target_hash == new_target.material_target_hash
    assert old_target.authority_hash != new_target.authority_hash
    assert old_map.authority_hash != new_map.authority_hash

    replay = _solve("BUY", evidence=evidence, current=first.candidate)
    assert replay.decision == "DUPLICATE"
    assert replay.candidate == first.candidate
    assert replay.evaluation is not None


def test_self_hashed_map_cannot_select_a_farther_unconsumed_target() -> None:
    target_map = derive_structural_target_map_v1(_evidence("BUY").target_map_evidence)
    farther = target_map.targets[1]
    forged = target_map.model_copy(update={"selected_target_id": farther.target_id})
    forged_hash = structural_target_map_authority_hash_v1(forged)
    payload = forged.model_dump(mode="python")
    payload["authority_hash"] = forged_hash
    payload["target_map_id"] = "5scr-target-map:" + hashlib.sha256(forged_hash.encode()).hexdigest()[:32]
    with pytest.raises(ValidationError, match="nearest unconsumed"):
        StructuralTargetMapAuthorityV1.model_validate(payload)


def test_off_grid_route_or_target_fails_closed_as_broker_constraint() -> None:
    off_grid_box = _box("BUY", low=1.099001, high=1.1000)
    result = _solve("BUY", box=off_grid_box)
    assert (result.decision, result.reason_code) == ("NO_TRADE", "NO_TRADE_BROKER_CONSTRAINT")

    result = _solve("BUY", evidence=_evidence("BUY", h4=_h4_buy(near="1.101205")))
    assert (result.decision, result.reason_code) == ("NO_TRADE", "NO_TRADE_BROKER_CONSTRAINT")


def test_a_b_a_creates_three_distinct_occurrences() -> None:
    a1 = _solve("BUY")
    assert a1.candidate is not None
    b_evidence = _evidence("BUY", h4=_h4_buy(near="1.10130", far="1.10310"), request="req-b")
    b = _solve("BUY", evidence=b_evidence, current=a1.candidate)
    assert b.candidate is not None and b.transition is not None
    # Persisted storage exposes the successor as current ACTIVE; emulate that immutable projection.
    a2_evidence = _evidence("BUY", request="req-a2")
    a2 = _solve("BUY", evidence=a2_evidence, current=b.candidate)
    assert a2.candidate is not None and a2.transition is not None
    assert len({a1.candidate.tradeplan_id, b.candidate.tradeplan_id, a2.candidate.tradeplan_id}) == 3
    assert a1.candidate.material_candidate_hash == a2.candidate.material_candidate_hash
    assert a2.candidate.candidate_sequence == 3


def test_current_candidate_material_drift_quarantines_in_solver() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    drifted = first.candidate.model_copy(update={"candidate_price": Decimal("1.0995")})
    result = _solve("BUY", current=drifted)
    assert (result.decision, result.reason_code) == (
        "QUARANTINED",
        "TRADEPLAN_CURRENT_CANDIDATE_INTEGRITY_DRIFT",
    )
    assert result.evaluation is None


def test_contract_rejects_rebuilt_candidate_with_material_drift() -> None:
    first = _solve("BUY")
    assert first.candidate is not None
    payload = first.candidate.model_dump(mode="python")
    payload["candidate_price"] = Decimal("1.0995")
    with pytest.raises(ValidationError, match="material candidate hash|distance/RR"):
        TradePlanCandidateV2.model_validate(payload)


def test_target_cohort_requires_unique_clocks_and_context_start_binding() -> None:
    evidence = _evidence("BUY")
    h4 = list(evidence.target_map_evidence.h4_candles)
    h4[1] = _candle(
        "H4",
        101,
        open=str(h4[1].open),
        high=str(h4[1].high),
        low=str(h4[1].low),
        close=str(h4[1].close),
        start=h4[0].open_time_utc - timedelta(hours=404),
    )
    payload = evidence.target_map_evidence.model_dump(mode="python")
    payload["h4_candles"] = tuple(h4)
    with pytest.raises(ValidationError, match="ordered and unique"):
        StructuralTargetMapEvidenceV1.model_validate(payload)

    wrong_start = evidence.target_map_evidence.model_copy(
        update={"coverage_start_utc": _context("BUY").opened_at_utc + timedelta(hours=1)}
    )
    result = _solve(
        "BUY",
        evidence=evidence.model_copy(update={"target_map_evidence": wrong_start}),
    )
    assert result.reason_code == "NO_TRADE_TARGET_NOT_AUTHORITATIVE"
