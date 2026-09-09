"""Contract gates for the source-aware Wolf15 observer export envelope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from contracts.observer_telemetry_export_v1 import (
    FinalSignalStateMirrorV1,
    ObserverSourceEventRangeV1,
    ObserverTelemetryEnvelopeV1,
    PairAdmissionEvaluationV3_1,
    StrategyAnalysisAdmissionV1,
    build_observer_envelope,
    observer_draft,
    observer_event_hash,
    observer_sha256,
    observer_source_from_env,
)

NOW = datetime(2026, 8, 22, 1, 2, 3, tzinfo=UTC)


def _source():
    return observer_source_from_env(
        service="strategy-5scr-pair-admission",
        policy_version="5scr.pair-admission.raw-ledger.v2",
        environ={
            "GIT_COMMIT_SHA": "a" * 40,
            "DEPLOYMENT_ID": "deployment-test-1",
        },
    )


def _pair_body() -> PairAdmissionEvaluationV3_1:
    return PairAdmissionEvaluationV3_1(
        symbol="EURUSD",
        raw_block_id="5scr-raw-block:" + "b" * 32,
        evaluation_id="5scr-admission-evaluation:" + "c" * 32,
        coverage_status="EVALUATED",
        decision="NOT_GRANTED",
        reason_code="RAW_DURATION_BELOW_MINIMUM",
        rule_version="5scr.pair-admission.raw-ledger.v2",
        evaluated_at_utc=NOW,
        source_event_range=ObserverSourceEventRangeV1(
            first_event_id="raw-1",
            last_event_id="raw-2",
            first_occurred_at_utc=NOW - timedelta(seconds=30),
            last_occurred_at_utc=NOW,
            event_count=2,
        ),
        source_event_ids=("raw-1", "raw-2"),
    )


def _pair_envelope(*, sequence: int = 1, previous_hash: str | None = None):
    draft = observer_draft(
        logical_event_key="pair-evaluation|deployment-test-1|block-b",
        stream_id="pair-admission:deployment-test-1:block-b",
        occurred_at_utc=NOW,
        source=_source(),
        body=_pair_body(),
    )
    return build_observer_envelope(
        draft,
        stream_sequence=sequence,
        previous_event_hash=previous_hash,
        published_at_utc=NOW + timedelta(seconds=1),
    )


def test_envelope_serialization_and_hash_are_deterministic() -> None:
    first = _pair_envelope()
    second = ObserverTelemetryEnvelopeV1.model_validate(first.model_dump(mode="json"))

    assert first == second
    assert observer_event_hash(first) == observer_event_hash(second)
    assert first.payload.payload_hash == observer_sha256(first.payload.body)
    assert observer_sha256({"b": 2, "a": 1}) == observer_sha256({"a": 1, "b": 2})
    assert first.authority.authority_class == "CANONICAL_PAIR_ADMISSION"
    assert first.authority.observer_authority == "OBSERVATIONAL_ONLY"
    assert first.safety.observer_can_mutate_source is False


def test_event_identity_is_stable_for_one_logical_source_event() -> None:
    first = observer_draft(
        logical_event_key="canonical-evaluation-1",
        stream_id="pair-admission:one",
        occurred_at_utc=NOW,
        source=_source(),
        body=_pair_body(),
    )
    changed = observer_draft(
        logical_event_key="canonical-evaluation-1",
        stream_id="pair-admission:one",
        occurred_at_utc=NOW,
        source=_source(),
        body=_pair_body().model_copy(update={"reason_code": "DIFFERENT_CANONICAL_CONTENT"}),
    )

    assert first.event_id == changed.event_id
    assert first.payload.payload_hash != changed.payload.payload_hash


def test_stream_chain_requires_the_immediate_predecessor() -> None:
    first = _pair_envelope()
    second = _pair_envelope(sequence=2, previous_hash=observer_event_hash(first))

    assert second.stream.previous_stream_sequence == 1
    assert second.stream.previous_event_hash == observer_event_hash(first)

    with pytest.raises(ValidationError, match="immediate predecessor"):
        _pair_envelope(sequence=3, previous_hash=None)


def test_payload_type_version_and_authority_cannot_drift() -> None:
    raw = _pair_envelope().model_dump(mode="json")
    raw["authority"]["authority_class"] = "RISK_STATE"
    with pytest.raises(ValidationError, match="authority_class"):
        ObserverTelemetryEnvelopeV1.model_validate(raw)

    raw = _pair_envelope().model_dump(mode="json")
    raw["payload"]["payload_version"] = "99.0"
    with pytest.raises(ValidationError, match="payload_version"):
        ObserverTelemetryEnvelopeV1.model_validate(raw)


def test_payload_hash_and_unknown_fields_fail_closed() -> None:
    raw = _pair_envelope().model_dump(mode="json")
    raw["payload"]["body"]["decision"] = "GRANTED"
    with pytest.raises(ValidationError, match="payload_hash"):
        ObserverTelemetryEnvelopeV1.model_validate(raw)

    raw = _pair_envelope().model_dump(mode="json")
    raw["observer_command"] = {"action": "BUY"}
    with pytest.raises(ValidationError, match="Extra inputs"):
        ObserverTelemetryEnvelopeV1.model_validate(raw)


def test_source_aware_mirror_can_report_executable_canonical_fact() -> None:
    body = FinalSignalStateMirrorV1(
        final_signal_id="final-signal-1",
        state="READY",
        direction="BUY",
        valid_for_execution=True,
        observed_at_utc=NOW,
    )
    envelope = build_observer_envelope(
        observer_draft(
            logical_event_key="final-signal-1|READY",
            stream_id="final-signal:final-signal-1",
            occurred_at_utc=NOW,
            source=_source(),
            body=body,
        ),
        stream_sequence=1,
        previous_event_hash=None,
        published_at_utc=NOW,
    )

    assert envelope.payload.body["valid_for_execution"] is True
    assert envelope.source.system == "WOLF15"
    assert envelope.authority.observer_authority == "OBSERVATIONAL_ONLY"
    assert envelope.safety.observer_can_mutate_source is False


def test_source_system_cannot_be_relabelled_as_observer() -> None:
    raw = _pair_envelope().model_dump(mode="json")
    raw["source"]["system"] = "OBSERVER"
    with pytest.raises(ValidationError, match="WOLF15"):
        ObserverTelemetryEnvelopeV1.model_validate(raw)


def test_coverage_not_applicable_is_distinct_from_unknown() -> None:
    not_applicable = _pair_body().model_copy(
        update={
            "coverage_status": "NOT_APPLICABLE",
            "decision": "NOT_APPLICABLE",
            "reason_code": "SYMBOL_OUTSIDE_RAW_AUTHORITY_SCOPE",
            "evaluated_at_utc": None,
        }
    )
    indeterminate = _pair_body().model_copy(
        update={
            "coverage_status": "INDETERMINATE_RAW_AUTHORITY_COVERAGE",
            "decision": "UNKNOWN",
            "reason_code": "RAW_RANGE_INCOMPLETE",
            "evaluated_at_utc": None,
        }
    )

    assert PairAdmissionEvaluationV3_1.model_validate(not_applicable.model_dump()).decision == "NOT_APPLICABLE"
    assert PairAdmissionEvaluationV3_1.model_validate(indeterminate.model_dump()).decision == "UNKNOWN"

    invalid = indeterminate.model_dump()
    invalid["decision"] = "NOT_APPLICABLE"
    with pytest.raises(ValidationError, match="remain UNKNOWN"):
        PairAdmissionEvaluationV3_1.model_validate(invalid)


@pytest.mark.parametrize("admission_class", ["CANONICAL_RAW", "MATURE_ADVISORY"])
def test_analysis_admission_preserves_authority_class(admission_class: str) -> None:
    body = StrategyAnalysisAdmissionV1(
        analysis_admission_id=f"analysis-admission:{admission_class.lower()}",
        strategy_lifecycle_id="5scr-lifecycle:" + "d" * 32,
        authority_scope_id="5scr-admission:" + "e" * 32,
        symbol="EURUSD",
        admission_class=admission_class,
        decision="ADMITTED",
        rule_version="5scr.analysis-admission.v1",
        admitted_at_utc=NOW,
        next_required_stage="CLOSED_CANDLE_EVIDENCE",
        source_event_ids=("source-1",),
    )
    draft = observer_draft(
        logical_event_key=body.analysis_admission_id,
        stream_id=f"analysis-lifecycle:{body.strategy_lifecycle_id}",
        occurred_at_utc=NOW,
        source=_source(),
        body=body,
    )

    assert draft.payload.body["admission_class"] == admission_class
    assert draft.authority_class == "STRATEGY_ANALYSIS_ADMISSION"


def test_naive_times_and_ambiguous_commit_identity_are_rejected() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        _pair_body().model_copy(update={"evaluated_at_utc": datetime(2026, 8, 22)}).model_validate(
            _pair_body().model_copy(update={"evaluated_at_utc": datetime(2026, 8, 22)}).model_dump()
        )

    with pytest.raises(ValidationError, match="string_pattern_mismatch"):
        observer_source_from_env(service="test", environ={"GIT_COMMIT_SHA": "latest"})


def test_missing_runtime_identity_is_explicit_not_fabricated() -> None:
    source = observer_source_from_env(service="test", environ={})

    assert source.commit_sha == "UNAVAILABLE"
    assert source.deployment_id is None
