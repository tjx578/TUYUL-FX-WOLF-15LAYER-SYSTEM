"""Material identity and state-machine gates for P5 ExecutionBox V1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest
from pydantic import ValidationError

import storage.strategy_5scr_execution_box_v1_repository as box_storage
from analysis.strategy_5scr_execution_box_v1 import (
    close_execution_box,
    execution_box_evidence_hash,
    material_box_hash,
    reduce_execution_box,
)
from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import (
    ExecutionBoxEvidenceV1,
    ExecutionBoxRouteGeometryAuthorityV1,
    ExecutionBoxV1,
    M1CandleAuthorityV1,
    derive_execution_box_route_geometry_authority,
    execution_box_freeze_authority_hash,
    execution_box_identity_v1,
)

START = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
LIFECYCLE = "5scr-lifecycle:" + "1" * 32
CONTEXT = "5scr-context:" + "2" * 32
THESIS = "5scr-thesis:" + "3" * 32


def test_p5_schema_fingerprint_binds_exact_catalog_bytes() -> None:
    unquoted = "CREATE   INDEX box_idx ON box_table (state)"
    formatting_only = "create index BOX_IDX on BOX_TABLE (STATE)"
    literal = "CHECK (state = 'FROZEN')"
    identifier = 'SELECT "AuthorityScope" FROM box_table'
    dollar_quoted = "CREATE FUNCTION guard() RETURNS trigger AS $body$ RETURN NEW; $body$ LANGUAGE plpgsql"

    assert box_storage._sql_fingerprint(unquoted) != box_storage._sql_fingerprint(formatting_only)
    assert box_storage._sql_fingerprint(unquoted) == box_storage._sql_fingerprint(unquoted)
    assert box_storage._sql_fingerprint(literal) != box_storage._sql_fingerprint(
        literal.replace("'FROZEN'", "'frozen'")
    )
    assert box_storage._sql_fingerprint(identifier) != box_storage._sql_fingerprint(
        identifier.replace('"AuthorityScope"', '"authorityscope"')
    )
    assert box_storage._sql_fingerprint(dollar_quoted) != box_storage._sql_fingerprint(
        dollar_quoted.replace("RETURN NEW;", "RETURN OLD;")
    )
    assert box_storage._sql_fingerprint("-- guard\nRETURN NEW;") != box_storage._sql_fingerprint("-- guard RETURN NEW;")


def _sha(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    )


def _candle(
    index: int,
    *,
    low: float = 1.1000,
    high: float = 1.1020,
    open_price: float | None = None,
    close_price: float | None = None,
) -> M1CandleAuthorityV1:
    opened = START + timedelta(minutes=index)
    material = {
        "symbol": "EURUSD",
        "timeframe": "M1",
        "open_time_utc": opened,
        "close_time_utc": opened + timedelta(minutes=1),
        "open": low + 0.0005 if open_price is None else open_price,
        "high": high,
        "low": low,
        "close": high - 0.0005 if close_price is None else close_price,
    }
    payload: dict[str, Any] = {
        **material,
        "material_candle_hash": _sha(material),
        "source_content_hash": _sha({"source": index}),
        "canonical_row_id": index + 1,
        "selected_raw_candle_id": index + 101,
        "volume": 100.0,
        "tick_count": 20,
        "provider": "XM",
        "feed": "demo",
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


def _route_candles(*, retest_low: float = 1.1008) -> tuple[M1CandleAuthorityV1, ...]:
    return (
        _candle(0, low=1.1000, high=1.1010, open_price=1.1004, close_price=1.1007),
        _candle(1, low=1.1006, high=1.1015, open_price=1.1008, close_price=1.1012),
        _candle(2, low=retest_low, high=1.1014, open_price=1.10125, close_price=1.1011),
        _candle(3, low=1.1010, high=1.1018, open_price=1.1011, close_price=1.1016),
    )


def _thesis(*, state: Literal["ACTIVE", "INVALIDATED", "TERMINAL"] = "ACTIVE") -> DirectionalThesisV1:
    closed = state != "ACTIVE"
    return DirectionalThesisV1(
        strategy_thesis_id=THESIS,
        strategy_lifecycle_id=LIFECYCLE,
        context_epoch_id=CONTEXT,
        thesis_sequence=1,
        symbol="EURUSD",
        strategy_direction="BUY",
        state=state,
        direction_domain_at_creation="BUY_ONLY",
        selected_route="BUY_BREAK_RETEST",
        pressure_authority_mode="RADAR_ONLY",
        pressure_contract_status="RADAR_ONLY",
        pressure_reference_direction="BUY",
        pressure_authority_hash="sha256:" + "4" * 64,
        h1_proof_id="5scr-h1-proof:" + "5" * 32,
        m15_proof_id="5scr-m15-proof:" + "6" * 32,
        structural_proof_hash="sha256:" + "7" * 64,
        semantic_identity_hash="sha256:" + "8" * 64,
        created_at_utc=START,
        liveness_checked_through_utc=START,
        closed_at_utc=START + timedelta(hours=1) if closed else None,
        closure_reason="TEST_TERMINAL" if closed else None,
    )


def _evidence(
    index: int = 1,
    *,
    candles: tuple[M1CandleAuthorityV1, ...] | None = None,
    freeze: bool = False,
    deployment: str = "deploy-a",
    reference_price: float = 1.101,
) -> ExecutionBoxEvidenceV1:
    resolved_candles = candles or _route_candles()
    route_authority = derive_execution_box_route_geometry_authority(
        context_epoch_id=CONTEXT,
        strategy_thesis_id=THESIS,
        symbol="EURUSD",
        strategy_direction="BUY",
        route_type="BUY_BREAK_RETEST",
        material_m1_candles=resolved_candles,
        reference_candle_material_hash=resolved_candles[0].material_candle_hash,
        break_candle_material_hash=resolved_candles[1].material_candle_hash,
        retest_candle_material_hash=resolved_candles[2].material_candle_hash,
        acceptance_candle_material_hash=resolved_candles[3].material_candle_hash,
    )
    payload: dict[str, Any] = dict(
        strategy_lifecycle_id=LIFECYCLE,
        context_epoch_id=CONTEXT,
        strategy_thesis_id=THESIS,
        thesis_semantic_identity_hash="sha256:" + "8" * 64,
        symbol="EURUSD",
        strategy_direction="BUY",
        route_type="BUY_BREAK_RETEST",
        observed_at_utc=START + timedelta(minutes=10 + index),
        material_m1_candles=resolved_candles,
        route_geometry_authority=route_authority,
        freeze_requested=freeze,
        freeze_reason="M1_ROUTE_GEOMETRY_CONFIRMED" if freeze else None,
        freeze_authority_hash=None,
        source_request_id=f"request-{index}",
        source_deployment_id=deployment,
        source_replica_id=f"replica-{index}",
        source_cluster_id=f"cluster-{deployment}",
        source_stage="M1_BOX_OBSERVER",
        source_family="EXECUTION_GEOMETRY",
        telemetry_count=index,
        reference_price=reference_price,
    )
    if freeze:
        provisional = ExecutionBoxEvidenceV1.model_construct(**payload)
        payload["freeze_authority_hash"] = execution_box_freeze_authority_hash(provisional)
    return ExecutionBoxEvidenceV1.model_validate(payload)


def test_same_material_evidence_replayed_100_times_is_one_box() -> None:
    thesis = _thesis()
    first_evidence = _evidence()
    first = reduce_execution_box(thesis=thesis, evidence=first_evidence, current=None, next_sequence=1)
    assert first.status == "OPENED" and first.box is not None
    current = first.box
    for _ in range(100):
        result = reduce_execution_box(thesis=thesis, evidence=first_evidence, current=current, next_sequence=2)
        assert result.status == "DUPLICATE"
        assert result.box == current


def test_nonmaterial_churn_does_not_version_box() -> None:
    first = _evidence()
    churn = _evidence(2, deployment="deploy-z", reference_price=1.1999)
    assert material_box_hash(first) == material_box_hash(churn)
    assert execution_box_evidence_hash(first) != execution_box_evidence_hash(churn)
    opened = reduce_execution_box(thesis=_thesis(), evidence=first, current=None, next_sequence=1)
    result = reduce_execution_box(thesis=_thesis(), evidence=churn, current=opened.box, next_sequence=2)
    assert result.status == "NO_CHANGE"
    assert result.box is not None and result.box.box_version == 1


def test_material_pre_freeze_change_supersedes_and_versions() -> None:
    opened = reduce_execution_box(thesis=_thesis(), evidence=_evidence(), current=None, next_sequence=1)
    changed = _evidence(2, candles=_route_candles(retest_low=1.1009))
    result = reduce_execution_box(thesis=_thesis(), evidence=changed, current=opened.box, next_sequence=2)
    assert result.status == "SUPERSEDED"
    assert result.previous_box is not None and result.previous_box.state == "SUPERSEDED"
    assert result.box is not None and result.box.box_version == 2
    assert result.box.previous_execution_box_id == opened.box.execution_box_id  # type: ignore[union-attr]


def test_a_to_b_to_a_creates_three_box_versions_without_identity_reuse() -> None:
    thesis = _thesis()
    evidence_a = _evidence()
    first = reduce_execution_box(thesis=thesis, evidence=evidence_a, current=None, next_sequence=1)
    assert first.box is not None
    evidence_b = _evidence(2, candles=_route_candles(retest_low=1.1009))
    second = reduce_execution_box(thesis=thesis, evidence=evidence_b, current=first.box, next_sequence=2)
    assert second.box is not None
    third = reduce_execution_box(thesis=thesis, evidence=_evidence(3), current=second.box, next_sequence=3)
    assert third.box is not None
    assert [first.box.box_version, second.box.box_version, third.box.box_version] == [1, 2, 3]
    assert first.box.material_box_hash == third.box.material_box_hash
    assert first.box.execution_box_id != third.box.execution_box_id


def test_freeze_is_same_version_and_post_freeze_expansion_is_rejected() -> None:
    opened = reduce_execution_box(thesis=_thesis(), evidence=_evidence(), current=None, next_sequence=1)
    frozen = reduce_execution_box(
        thesis=_thesis(), evidence=_evidence(2, freeze=True), current=opened.box, next_sequence=2
    )
    assert frozen.status == "FROZEN"
    assert frozen.box is not None and frozen.box.box_version == 1 and frozen.box.state == "FROZEN"
    expanded = reduce_execution_box(
        thesis=_thesis(),
        evidence=_evidence(3, candles=_route_candles(retest_low=1.1007)),
        current=frozen.box,
        next_sequence=2,
    )
    assert expanded.status == "REJECTED"
    assert expanded.reason_code == "FROZEN_EXECUTION_BOX_IMMUTABLE"
    assert expanded.box == frozen.box


def test_parent_scope_and_terminal_thesis_fail_closed() -> None:
    mismatch = _evidence().model_copy(update={"context_epoch_id": "5scr-context:" + "9" * 32})
    rejected = reduce_execution_box(thesis=_thesis(), evidence=mismatch, current=None, next_sequence=1)
    assert (rejected.status, rejected.reason_code) == (
        "REJECTED",
        "EXECUTION_BOX_PARENT_SCOPE_MISMATCH",
    )
    terminal = reduce_execution_box(
        thesis=_thesis(state="INVALIDATED"), evidence=_evidence(), current=None, next_sequence=1
    )
    assert (terminal.status, terminal.reason_code) == ("REJECTED", "DIRECTIONAL_THESIS_NOT_ACTIVE")


def test_terminal_box_never_resurrects() -> None:
    opened = reduce_execution_box(thesis=_thesis(), evidence=_evidence(), current=None, next_sequence=1)
    assert opened.box is not None
    invalidated = close_execution_box(
        opened.box,
        state="INVALIDATED",
        occurred_at_utc=START + timedelta(minutes=30),
    )
    replay = reduce_execution_box(thesis=_thesis(), evidence=_evidence(4), current=invalidated, next_sequence=2)
    assert replay.status == "REJECTED"
    assert replay.reason_code == "EXECUTION_BOX_TERMINAL_NO_RESURRECTION"


def test_stale_event_cannot_roll_box_backward_and_same_request_drift_is_quarantined() -> None:
    thesis = _thesis()
    opened = reduce_execution_box(thesis=thesis, evidence=_evidence(2), current=None, next_sequence=1)
    assert opened.box is not None
    stale = reduce_execution_box(
        thesis=thesis,
        evidence=_evidence(1, candles=_route_candles(retest_low=1.1009)),
        current=opened.box,
        next_sequence=2,
    )
    assert (stale.status, stale.reason_code) == ("REJECTED", "STALE_EXECUTION_BOX_EVIDENCE")
    drift_payload = _evidence(3, candles=_route_candles(retest_low=1.1009)).model_dump(mode="python")
    drift_payload["source_request_id"] = opened.box.last_source_request_id
    drift = reduce_execution_box(
        thesis=thesis,
        evidence=ExecutionBoxEvidenceV1.model_validate(drift_payload),
        current=opened.box,
        next_sequence=2,
    )
    assert (drift.status, drift.reason_code) == (
        "QUARANTINED",
        "EXECUTION_BOX_REQUEST_EVIDENCE_DRIFT",
    )


def test_contract_rejects_execution_authority_and_invalid_geometry() -> None:
    payload = _evidence().model_dump(mode="python")
    payload["execution_authority"] = True
    with pytest.raises(ValidationError):
        ExecutionBoxEvidenceV1.model_validate(payload)

    candle = _candle(0)
    bad = candle.model_dump(mode="python")
    bad["high"] = bad["low"] - 0.001
    with pytest.raises(ValidationError):
        M1CandleAuthorityV1.model_validate(bad)


def test_route_geometry_is_derived_from_typed_break_retest_roles() -> None:
    evidence = _evidence()
    authority = evidence.route_geometry_authority
    assert (authority.route_low, authority.route_high) == (1.1008, 1.1010)
    assert authority.route_low > min(item.low for item in evidence.material_m1_candles)

    forged = authority.model_dump(mode="python")
    forged["route_low"] = 1.1000
    forged["authority_hash"] = "sha256:" + "0" * 64
    payload = evidence.model_dump(mode="python")
    payload["route_geometry_authority"] = ExecutionBoxRouteGeometryAuthorityV1.model_validate(forged)
    with pytest.raises(ValidationError, match="canonical M1 roles"):
        ExecutionBoxEvidenceV1.model_validate(payload)


def test_route_geometry_rejects_wrong_direction_and_unsupported_route() -> None:
    evidence = _evidence()
    authority = evidence.route_geometry_authority.model_dump(mode="python")
    authority["strategy_direction"] = "SELL"
    authority["authority_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="match strategy direction"):
        ExecutionBoxRouteGeometryAuthorityV1.model_validate(authority)

    payload = evidence.model_dump(mode="python")
    payload["route_type"] = "BUY_ORIGIN_RANGE"
    with pytest.raises(ValidationError):
        ExecutionBoxEvidenceV1.model_validate(payload)


def test_route_geometry_requires_reference_close_through_and_directional_acceptance() -> None:
    no_break = list(_route_candles())
    no_break[1] = _candle(1, low=1.1006, high=1.1011, open_price=1.1008, close_price=1.1009)
    with pytest.raises(ValueError, match="reference high"):
        derive_execution_box_route_geometry_authority(
            context_epoch_id=CONTEXT,
            strategy_thesis_id=THESIS,
            symbol="EURUSD",
            strategy_direction="BUY",
            route_type="BUY_BREAK_RETEST",
            material_m1_candles=tuple(no_break),
            reference_candle_material_hash=no_break[0].material_candle_hash,
            break_candle_material_hash=no_break[1].material_candle_hash,
            retest_candle_material_hash=no_break[2].material_candle_hash,
            acceptance_candle_material_hash=no_break[3].material_candle_hash,
        )


def test_route_geometry_forbids_skipped_role_candles_and_post_acceptance_tail() -> None:
    evidence = _evidence()
    reference, break_candle, retest, acceptance = evidence.material_m1_candles
    skipped = _candle(1, low=1.1006, high=1.1011, open_price=1.1008, close_price=1.1009)
    payload = evidence.model_dump(mode="python")
    payload["material_m1_candles"] = (reference, skipped, break_candle, retest, acceptance)
    with pytest.raises(ValidationError, match="exactly four"):
        ExecutionBoxEvidenceV1.model_validate(payload)

    post_acceptance = _candle(4, low=1.1005, high=1.1017, open_price=1.1015, close_price=1.1007)
    payload["material_m1_candles"] = (*evidence.material_m1_candles, post_acceptance)
    with pytest.raises(ValidationError, match="exactly four"):
        ExecutionBoxEvidenceV1.model_validate(payload)


def test_route_geometry_forbids_role_order_drift() -> None:
    evidence = _evidence()
    payload = evidence.model_dump(mode="python")
    reference, break_candle, retest, acceptance = evidence.material_m1_candles
    payload["material_m1_candles"] = (reference, retest, break_candle, acceptance)
    with pytest.raises(ValidationError):
        ExecutionBoxEvidenceV1.model_validate(payload)

    doji = list(_route_candles())
    doji[3] = _candle(3, low=1.1010, high=1.1015, open_price=1.1012, close_price=1.1012)
    with pytest.raises(ValueError, match="acceptance candle"):
        derive_execution_box_route_geometry_authority(
            context_epoch_id=CONTEXT,
            strategy_thesis_id=THESIS,
            symbol="EURUSD",
            strategy_direction="BUY",
            route_type="BUY_BREAK_RETEST",
            material_m1_candles=tuple(doji),
            reference_candle_material_hash=doji[0].material_candle_hash,
            break_candle_material_hash=doji[1].material_candle_hash,
            retest_candle_material_hash=doji[2].material_candle_hash,
            acceptance_candle_material_hash=doji[3].material_candle_hash,
        )


def test_pre_thesis_evidence_and_any_pre_thesis_m1_open_are_rejected() -> None:
    thesis = _thesis()
    old_observation = _evidence().model_copy(update={"observed_at_utc": START - timedelta(seconds=1)})
    rejected = reduce_execution_box(thesis=thesis, evidence=old_observation, current=None, next_sequence=1)
    assert (rejected.status, rejected.reason_code) == (
        "REJECTED",
        "EXECUTION_BOX_PARENT_CLOCK_PRECEDES_THESIS",
    )

    later_thesis = thesis.model_copy(
        update={
            "created_at_utc": START + timedelta(minutes=1),
            "liveness_checked_through_utc": START + timedelta(minutes=1),
        }
    )
    rejected_candle = reduce_execution_box(
        thesis=later_thesis,
        evidence=_evidence(),
        current=None,
        next_sequence=1,
    )
    assert (rejected_candle.status, rejected_candle.reason_code) == (
        "REJECTED",
        "EXECUTION_BOX_M1_PRECEDES_THESIS",
    )


def test_current_box_requires_full_parent_scope_and_canonical_id() -> None:
    thesis = _thesis()
    opened = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=1)
    assert opened.box is not None
    drifted = opened.box.model_copy(update={"strategy_direction": "SELL", "route_type": "SELL_BREAK_RETEST"})
    result = reduce_execution_box(thesis=thesis, evidence=_evidence(2), current=drifted, next_sequence=2)
    assert (result.status, result.reason_code) == (
        "QUARANTINED",
        "ACTIVE_EXECUTION_BOX_PARENT_DRIFT",
    )

    payload = opened.box.model_dump(mode="python")
    payload["execution_box_id"] = "5scr-execution-box:" + "f" * 32
    with pytest.raises(ValidationError, match="execution box ID"):
        ExecutionBoxV1.model_validate(payload)


def test_nonmaterial_refresh_advances_watermark_and_blocks_late_material_change() -> None:
    thesis = _thesis()
    opened = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=1)
    assert opened.box is not None
    refresh = reduce_execution_box(thesis=thesis, evidence=_evidence(3), current=opened.box, next_sequence=2)
    assert refresh.status == "NO_CHANGE" and refresh.box is not None and refresh.previous_box == opened.box
    assert refresh.box.execution_box_id == opened.box.execution_box_id
    assert refresh.box.box_version == opened.box.box_version
    assert refresh.box.last_observed_at_utc == START + timedelta(minutes=13)
    assert refresh.box.state_version == opened.box.state_version + 1

    late = reduce_execution_box(
        thesis=thesis,
        evidence=_evidence(2, candles=_route_candles(retest_low=1.1009)),
        current=refresh.box,
        next_sequence=2,
    )
    assert (late.status, late.reason_code) == ("REJECTED", "STALE_EXECUTION_BOX_EVIDENCE")


def test_equal_clock_conflicting_evidence_is_quarantined() -> None:
    thesis = _thesis()
    evidence_a = _evidence()
    opened = reduce_execution_box(thesis=thesis, evidence=evidence_a, current=None, next_sequence=1)
    assert opened.box is not None
    payload = _evidence(1, candles=_route_candles(retest_low=1.1009)).model_dump(mode="python")
    payload["source_request_id"] = "same-clock-other-request"
    conflict = ExecutionBoxEvidenceV1.model_validate(payload)
    result = reduce_execution_box(thesis=thesis, evidence=conflict, current=opened.box, next_sequence=2)
    assert (result.status, result.reason_code) == (
        "QUARANTINED",
        "AMBIGUOUS_EXECUTION_BOX_EVIDENCE_CLOCK",
    )


def test_exact_freeze_retry_is_duplicate_after_restart_projection() -> None:
    thesis = _thesis()
    opened = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=1)
    freeze_evidence = _evidence(2, freeze=True)
    frozen = reduce_execution_box(
        thesis=thesis,
        evidence=freeze_evidence,
        current=opened.box,
        next_sequence=2,
    )
    assert frozen.status == "FROZEN" and frozen.box is not None
    assert frozen.box.evidence_hash == execution_box_evidence_hash(freeze_evidence)
    replayed = ExecutionBoxV1.model_validate(frozen.box.model_dump(mode="python"))
    retry = reduce_execution_box(
        thesis=thesis,
        evidence=freeze_evidence,
        current=replayed,
        next_sequence=2,
    )
    assert (retry.status, retry.reason_code) == (
        "DUPLICATE",
        "EXECUTION_BOX_FREEZE_ALREADY_PERSISTED",
    )


def test_exact_replay_survives_parent_liveness_advance_but_new_evidence_does_not() -> None:
    thesis = _thesis()
    evidence = _evidence()
    opened = reduce_execution_box(thesis=thesis, evidence=evidence, current=None, next_sequence=1)
    assert opened.box is not None
    advanced = thesis.model_copy(update={"liveness_checked_through_utc": START + timedelta(minutes=20)})
    retry = reduce_execution_box(thesis=advanced, evidence=evidence, current=opened.box, next_sequence=2)
    assert (retry.status, retry.reason_code) == ("DUPLICATE", "EXECUTION_BOX_ALREADY_PERSISTED")
    new_evidence = reduce_execution_box(
        thesis=advanced,
        evidence=_evidence(2, candles=_route_candles(retest_low=1.1009)),
        current=opened.box,
        next_sequence=2,
    )
    assert (new_evidence.status, new_evidence.reason_code) == (
        "REJECTED",
        "EXECUTION_BOX_PARENT_CLOCK_PRECEDES_THESIS",
    )


def test_freeze_retry_requires_full_evidence_identity() -> None:
    thesis = _thesis()
    opened = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=1)
    freeze_evidence = _evidence(2, freeze=True)
    frozen = reduce_execution_box(thesis=thesis, evidence=freeze_evidence, current=opened.box, next_sequence=2)
    assert frozen.box is not None
    changed = freeze_evidence.model_copy(update={"source_deployment_id": "drifted-deployment"})
    retry = reduce_execution_box(thesis=thesis, evidence=changed, current=frozen.box, next_sequence=2)
    assert (retry.status, retry.reason_code) == (
        "QUARANTINED",
        "EXECUTION_BOX_REQUEST_EVIDENCE_DRIFT",
    )


def test_box_sequence_is_bound_to_identity_and_successor_is_contiguous() -> None:
    thesis = _thesis()
    first_at_one = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=1)
    first_at_two = reduce_execution_box(thesis=thesis, evidence=_evidence(), current=None, next_sequence=2)
    assert first_at_one.box is not None and first_at_two.box is not None
    assert first_at_one.box.execution_box_id != first_at_two.box.execution_box_id
    assert first_at_one.box.execution_box_id == execution_box_identity_v1(
        THESIS,
        1,
        1,
        first_at_one.box.material_box_hash,
    )

    drift = reduce_execution_box(
        thesis=thesis,
        evidence=_evidence(2, candles=_route_candles(retest_low=1.1009)),
        current=first_at_one.box,
        next_sequence=99,
    )
    assert (drift.status, drift.reason_code) == (
        "QUARANTINED",
        "EXECUTION_BOX_SEQUENCE_DRIFT",
    )
