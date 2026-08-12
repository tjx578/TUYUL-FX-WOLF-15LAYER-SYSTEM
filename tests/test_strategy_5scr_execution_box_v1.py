"""Material identity and state-machine gates for P5 ExecutionBox V1."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_execution_box_v1 import (
    close_execution_box,
    execution_box_evidence_hash,
    material_box_hash,
    reduce_execution_box,
)
from contracts.strategy_5scr_directional_thesis_v1 import DirectionalThesisV1
from contracts.strategy_5scr_execution_box_v1 import (
    ExecutionBoxEvidenceV1,
    M1CandleAuthorityV1,
    execution_box_freeze_authority_hash,
)

START = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
LIFECYCLE = "5scr-lifecycle:" + "1" * 32
CONTEXT = "5scr-context:" + "2" * 32
THESIS = "5scr-thesis:" + "3" * 32


def _sha(payload: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    )


def _candle(index: int, *, low: float = 1.1000, high: float = 1.1020) -> M1CandleAuthorityV1:
    opened = START + timedelta(minutes=index)
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
    payload: dict[str, Any] = dict(
        strategy_lifecycle_id=LIFECYCLE,
        context_epoch_id=CONTEXT,
        strategy_thesis_id=THESIS,
        thesis_semantic_identity_hash="sha256:" + "8" * 64,
        symbol="EURUSD",
        strategy_direction="BUY",
        route_type="BUY_BREAK_RETEST",
        observed_at_utc=START + timedelta(minutes=10 + index),
        material_m1_candles=candles or (_candle(0), _candle(1)),
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
    changed = _evidence(2, candles=(_candle(0, low=1.0990), _candle(1)))
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
    evidence_b = _evidence(2, candles=(_candle(0, low=1.0990), _candle(1)))
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
        evidence=_evidence(3, candles=(_candle(0, low=1.0900), _candle(1))),
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
        evidence=_evidence(1, candles=(_candle(0, low=1.0990), _candle(1))),
        current=opened.box,
        next_sequence=2,
    )
    assert (stale.status, stale.reason_code) == ("REJECTED", "STALE_EXECUTION_BOX_EVIDENCE")
    drift_payload = _evidence(3, candles=(_candle(0, low=1.0990), _candle(1))).model_dump(mode="python")
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
