"""Pure offline WLA-02 golden-corpus mapping and replay contracts.

This module has no storage, network, runtime-registration, broker, execution,
or deployment integration. It maps a closed typed source registry into the
existing WLA-01 envelope payloads and authenticates canonical fixture bytes
again during deterministic bitemporal replay.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.alpha_learning_envelope_v1 import (
    ALPHA_FACT_EVENT,
    OUTCOME_EVIDENCE_EVENT,
    AlphaFactPayloadV1,
    AlphaLearningEnvelopeV1,
    AncestryManifestRefV1,
    CancelOutcomeEvidenceV1,
    CanonicalAlphaAbstentionFactV1,
    CanonicalAlphaDecisionFactV1,
    EvidenceRefV1,
    FillOutcomeEvidenceV1,
    HorizonObservationEvidenceV1,
    LearningPayloadV1,
    OutcomeEvidencePayloadV1,
    ProducerKeyBindingV1,
    QualityV1,
    RejectOutcomeEvidenceV1,
    SourceIdentityV1,
    SourceTimingV1,
    StreamPositionV1,
    alpha_learning_sha256,
    authenticate_alpha_learning_envelope_v1,
    build_alpha_learning_envelope_v1,
    canonical_alpha_learning_json_bytes,
    parse_alpha_learning_envelope_v1,
)

MAX_CORPUS_ENTRIES = 10_000
MAX_CORPUS_SOURCE_FIELDS = 16

DecisionDisposition: TypeAlias = Literal["BUY", "SELL", "WAIT", "HOLD", "NO_TRADE", "CONFLICT"]
CorpusCaseLabel: TypeAlias = Literal[
    "EXECUTED",
    "WAIT",
    "HOLD",
    "NO_TRADE",
    "REJECTED",
    "EXPIRED",
    "CONFLICT",
]
CorpusEvidenceClass: TypeAlias = Literal["WOLF15_DECISION", "REALIZED_BROKER", "COUNTERFACTUAL_MARKET"]


class FrozenGoldenCorpusModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _sorted_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be sorted and unique")
    return values


class DecisionSourceV1(FrozenGoldenCorpusModel):
    record_type: Literal["DECISION"]
    source_record_id: str = Field(..., min_length=1, max_length=500)
    alpha_or_evaluation_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    disposition: DecisionDisposition
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)
    evidence_refs: tuple[EvidenceRefV1, ...] = Field(..., min_length=1, max_length=32)
    decision_policy_version: str = Field(..., min_length=1, max_length=160)
    decided_at_utc: datetime
    source_valid_for_execution: bool

    @field_validator("reason_codes")
    @classmethod
    def _reasons_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value, "reason_codes")

    @field_validator("evidence_refs")
    @classmethod
    def _refs_are_canonical(cls, value: tuple[EvidenceRefV1, ...]) -> tuple[EvidenceRefV1, ...]:
        keys = tuple((item.ref_type, item.ref_id) for item in value)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("evidence_refs must be sorted and unique by ref_type/ref_id")
        return value

    @field_validator("decided_at_utc")
    @classmethod
    def _decision_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decided_at_utc")

    @model_validator(mode="after")
    def _non_action_is_never_execution_valid(self) -> DecisionSourceV1:
        if self.disposition in {"WAIT", "HOLD", "NO_TRADE", "CONFLICT"} and self.source_valid_for_execution:
            raise ValueError("non-action or ambiguous decisions cannot be source-valid for execution")
        return self


class RealizedBrokerOutcomeSourceV1(FrozenGoldenCorpusModel):
    record_type: Literal["REALIZED_BROKER_OUTCOME"]
    evidence_class: Literal["REALIZED_BROKER"]
    source_record_id: str = Field(..., min_length=1, max_length=500)
    decision_id: str = Field(..., min_length=1, max_length=500)
    outcome_kind: Literal["EXECUTED", "REJECTED", "EXPIRED"]
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    occurred_at_utc: datetime
    execution_id: str | None = Field(default=None, min_length=1, max_length=500)
    order_id: str | None = Field(default=None, min_length=1, max_length=500)
    fill_id: str | None = Field(default=None, min_length=1, max_length=500)
    request_id: str | None = Field(default=None, min_length=1, max_length=500)
    requested_quantity: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    filled_quantity: Decimal | None = Field(default=None, ge=0, max_digits=20, decimal_places=8)
    fill_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=8)
    reason_code: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("occurred_at_utc")
    @classmethod
    def _outcome_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "occurred_at_utc")

    @model_validator(mode="after")
    def _closed_realized_shape(self) -> RealizedBrokerOutcomeSourceV1:
        fill_fields = (self.execution_id, self.fill_id, self.requested_quantity, self.fill_price)
        if self.outcome_kind == "EXECUTED":
            if any(value is None for value in (*fill_fields, self.order_id, self.filled_quantity)):
                raise ValueError("EXECUTED requires execution/order/fill IDs, quantities, and fill price")
            if self.filled_quantity != self.requested_quantity:
                raise ValueError("WLA-02 EXECUTED fixtures require a deterministic full fill")
            if self.request_id is not None or self.reason_code is not None:
                raise ValueError("EXECUTED cannot carry reject/expiry fields")
        elif self.outcome_kind == "REJECTED":
            if self.request_id is None or self.reason_code is None:
                raise ValueError("REJECTED requires request_id and reason_code")
            if any(value is not None for value in (*fill_fields, self.filled_quantity)):
                raise ValueError("REJECTED cannot carry fill evidence")
        else:
            if self.order_id is None or self.reason_code is None or self.filled_quantity is None:
                raise ValueError("EXPIRED requires order_id, reason_code, and explicit filled_quantity")
            if any(value is not None for value in (*fill_fields, self.request_id)):
                raise ValueError("EXPIRED cannot carry execution, fill, or request evidence")
        return self


class CounterfactualMarketOutcomeSourceV1(FrozenGoldenCorpusModel):
    record_type: Literal["COUNTERFACTUAL_MARKET_OUTCOME"]
    evidence_class: Literal["COUNTERFACTUAL_MARKET"]
    source_record_id: str = Field(..., min_length=1, max_length=500)
    alpha_id: str = Field(..., min_length=1, max_length=500)
    outcome_kind: Literal["MARKET_HORIZON"]
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    occurred_at_utc: datetime
    horizon_policy_version: str = Field(..., min_length=1, max_length=160)
    horizon_seconds: int = Field(..., gt=0, le=31_536_000)
    reference_price: Decimal = Field(..., gt=0, max_digits=20, decimal_places=8)
    observed_price: Decimal = Field(..., gt=0, max_digits=20, decimal_places=8)

    @field_validator("occurred_at_utc")
    @classmethod
    def _observation_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "occurred_at_utc")


class UnavailableOutcomeSourceV1(FrozenGoldenCorpusModel):
    record_type: Literal["UNAVAILABLE_OUTCOME"]
    evidence_class: Literal["UNAVAILABLE"]
    source_record_id: str = Field(..., min_length=1, max_length=500)
    decision_id: str = Field(..., min_length=1, max_length=500)
    unavailable_kind: Literal["CENSORED", "MISSING"]
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    assessed_at_utc: datetime
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=16)
    missing_fields: tuple[str, ...] = Field(..., min_length=1, max_length=MAX_CORPUS_SOURCE_FIELDS)

    @field_validator("assessed_at_utc")
    @classmethod
    def _assessment_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "assessed_at_utc")

    @field_validator("reason_codes", "missing_fields")
    @classmethod
    def _sequences_are_canonical(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _sorted_unique(value, str(info.field_name))


OutcomeSourceV1: TypeAlias = Annotated[
    RealizedBrokerOutcomeSourceV1 | CounterfactualMarketOutcomeSourceV1 | UnavailableOutcomeSourceV1,
    Field(discriminator="record_type"),
]
GoldenSourceSnapshotV1: TypeAlias = Annotated[
    DecisionSourceV1
    | RealizedBrokerOutcomeSourceV1
    | CounterfactualMarketOutcomeSourceV1,
    Field(discriminator="record_type"),
]


class OutcomeUnavailableError(ValueError):
    """An explicit censored/missing record cannot be promoted into evidence."""


class FutureLeakageError(ValueError):
    """Corpus knowledge exceeds the caller's explicit replay cutoff."""


class CorrectionLineageError(ValueError):
    """Correction lineage is missing, cross-class, cyclic, or forked."""


class AmbiguousCorpusError(ValueError):
    """Corpus identity is duplicated or conflicts without a correction edge."""


def map_decision_source_v1(source: DecisionSourceV1) -> AlphaFactPayloadV1:
    if source.disposition in {"BUY", "SELL", "WAIT"}:
        decision: Literal["BUY", "SELL", "WAIT"]
        if source.disposition == "BUY":
            decision = "BUY"
        elif source.disposition == "SELL":
            decision = "SELL"
        else:
            decision = "WAIT"
        return CanonicalAlphaDecisionFactV1(
            payload_type="canonical-alpha-decision.v1",
            alpha_id=source.alpha_or_evaluation_id,
            symbol=source.symbol,
            decision=decision,
            decision_reason_codes=source.reason_codes,
            evidence_refs=source.evidence_refs,
            decision_policy_version=source.decision_policy_version,
            decided_at_utc=source.decided_at_utc,
            source_valid_for_execution=source.source_valid_for_execution,
        )
    abstention_kind = {
        "HOLD": "RISK_BLOCKED",
        "NO_TRADE": "POLICY_BLOCKED",
        "CONFLICT": "SOURCE_UNKNOWN",
    }[source.disposition]
    return CanonicalAlphaAbstentionFactV1.model_validate(
        {
            "payload_type": "canonical-alpha-abstention.v1",
            "alpha_evaluation_id": source.alpha_or_evaluation_id,
            "symbol": source.symbol,
            "abstention_kind": abstention_kind,
            "reason_codes": source.reason_codes,
            "evidence_refs": source.evidence_refs,
            "decision_policy_version": source.decision_policy_version,
            "decided_at_utc": source.decided_at_utc,
            "source_valid_for_execution": False,
        }
    )


def map_outcome_source_v1(source: OutcomeSourceV1) -> OutcomeEvidencePayloadV1:
    if isinstance(source, UnavailableOutcomeSourceV1):
        raise OutcomeUnavailableError(
            f"{source.unavailable_kind} outcome cannot be promoted into WLA-01 outcome evidence"
        )
    if isinstance(source, CounterfactualMarketOutcomeSourceV1):
        return HorizonObservationEvidenceV1(
            payload_type="horizon-observation-evidence.v1",
            alpha_id=source.alpha_id,
            symbol=source.symbol,
            observation_kind="MARKET_HORIZON_SNAPSHOT",
            horizon_policy_version=source.horizon_policy_version,
            horizon_seconds=source.horizon_seconds,
            reference_price=source.reference_price,
            observed_price=source.observed_price,
            observed_at_utc=source.occurred_at_utc,
        )
    if source.outcome_kind == "EXECUTED":
        assert source.execution_id is not None
        assert source.order_id is not None
        assert source.fill_id is not None
        assert source.requested_quantity is not None
        assert source.filled_quantity is not None
        assert source.fill_price is not None
        return FillOutcomeEvidenceV1(
            payload_type="fill-evidence.v1",
            execution_id=source.execution_id,
            order_id=source.order_id,
            fill_id=source.fill_id,
            symbol=source.symbol,
            side=source.side,
            requested_quantity=source.requested_quantity,
            filled_quantity=source.filled_quantity,
            fill_price=source.fill_price,
            filled_at_utc=source.occurred_at_utc,
            finality="FULL",
        )
    if source.outcome_kind == "REJECTED":
        assert source.request_id is not None
        assert source.reason_code is not None
        return RejectOutcomeEvidenceV1(
            payload_type="reject-evidence.v1",
            request_id=source.request_id,
            order_id=source.order_id,
            symbol=source.symbol,
            side=source.side,
            reason_code=source.reason_code,
            rejected_at_utc=source.occurred_at_utc,
            finality="REJECTED",
        )
    assert source.order_id is not None
    assert source.reason_code is not None
    assert source.filled_quantity is not None
    return CancelOutcomeEvidenceV1(
        payload_type="cancel-evidence.v1",
        order_id=source.order_id,
        symbol=source.symbol,
        side=source.side,
        reason_code=source.reason_code,
        filled_quantity=source.filled_quantity,
        cancelled_at_utc=source.occurred_at_utc,
        finality="CANCELLED",
    )


def map_golden_source_v1(source: GoldenSourceSnapshotV1) -> LearningPayloadV1:
    if isinstance(source, DecisionSourceV1):
        return map_decision_source_v1(source)
    return map_outcome_source_v1(source)


def build_golden_envelope_v1(
    *,
    source_snapshot: GoldenSourceSnapshotV1,
    logical_event_key: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    direct_source_refs: tuple[EvidenceRefV1, ...],
    ancestry_manifest: AncestryManifestRefV1 | None,
    stream: StreamPositionV1,
    source_identity: SourceIdentityV1,
    timing: SourceTimingV1,
    quality: QualityV1,
    producer_run_id: UUID,
    producer_key_id: str,
    producer_signature: str,
) -> AlphaLearningEnvelopeV1:
    payload = map_golden_source_v1(source_snapshot)
    event_name = ALPHA_FACT_EVENT if isinstance(source_snapshot, DecisionSourceV1) else OUTCOME_EVIDENCE_EVENT
    return build_alpha_learning_envelope_v1(
        event_name=event_name,
        logical_event_key=logical_event_key,
        correlation_id=correlation_id,
        causation_id=causation_id,
        direct_source_refs=direct_source_refs,
        ancestry_manifest=ancestry_manifest,
        stream=stream,
        source=source_identity,
        timing=timing,
        quality=quality,
        producer_run_id=producer_run_id,
        producer_key_id=producer_key_id,
        producer_signature=producer_signature,
        payload=payload,
    )


def _snapshot_occurred_at(source: GoldenSourceSnapshotV1) -> datetime:
    if isinstance(source, DecisionSourceV1):
        return source.decided_at_utc
    return source.occurred_at_utc


class GoldenCorpusEntryV1(FrozenGoldenCorpusModel):
    entry_version: Literal["wolf15.wla02.golden-corpus-entry.v1"]
    fixture_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    case_label: CorpusCaseLabel
    evidence_class: CorpusEvidenceClass
    valid_at_utc: datetime
    known_at_utc: datetime
    correction_of_event_id: UUID | None
    source_snapshot_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    source_snapshot: GoldenSourceSnapshotV1
    envelope_canonical_json: str = Field(..., min_length=2, max_length=65_536)

    @field_validator("valid_at_utc", "known_at_utc")
    @classmethod
    def _corpus_times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _entry_bindings_are_consistent(self) -> GoldenCorpusEntryV1:
        if self.known_at_utc < self.valid_at_utc:
            raise ValueError("known_at_utc cannot precede valid_at_utc")
        if self.source_snapshot_hash != alpha_learning_sha256(self.source_snapshot.model_dump(mode="json")):
            raise ValueError("source_snapshot_hash does not match the typed source snapshot")
        envelope = parse_alpha_learning_envelope_v1(self.envelope_canonical_json).envelope
        if envelope.timing.occurred_at_utc != self.valid_at_utc:
            raise ValueError("entry valid time must match envelope occurrence time")
        if self.known_at_utc < envelope.timing.source_published_at_utc:
            raise ValueError("entry knowledge time cannot precede source publication")
        if _snapshot_occurred_at(self.source_snapshot) != self.valid_at_utc:
            raise ValueError("entry valid time must match source snapshot occurrence time")
        expected_payload = map_golden_source_v1(self.source_snapshot)
        if envelope.payload != expected_payload:
            raise ValueError("envelope payload must equal the deterministic typed source mapping")
        if envelope.quality.correction_of_event_id != self.correction_of_event_id:
            raise ValueError("entry correction edge must match envelope quality lineage")
        if isinstance(self.source_snapshot, DecisionSourceV1):
            if self.evidence_class != "WOLF15_DECISION" or envelope.contract.event_name != ALPHA_FACT_EVENT:
                raise ValueError("decision entry cannot claim an outcome evidence class")
            expected_case = (
                "EXECUTED" if self.source_snapshot.disposition in {"BUY", "SELL"} else self.source_snapshot.disposition
            )
            if self.case_label != expected_case:
                raise ValueError("decision case label does not match its source disposition")
        elif isinstance(self.source_snapshot, RealizedBrokerOutcomeSourceV1):
            if self.evidence_class != "REALIZED_BROKER" or envelope.contract.event_name != OUTCOME_EVIDENCE_EVENT:
                raise ValueError("realized outcome cannot claim counterfactual or decision evidence")
            if self.case_label != self.source_snapshot.outcome_kind:
                raise ValueError("realized case label does not match outcome_kind")
            if isinstance(envelope.payload, HorizonObservationEvidenceV1):
                raise ValueError("realized broker entry cannot contain counterfactual payload")
        else:
            if self.evidence_class != "COUNTERFACTUAL_MARKET":
                raise ValueError("counterfactual entry cannot claim realized or decision evidence")
            if self.case_label not in {"WAIT", "HOLD", "NO_TRADE", "CONFLICT"}:
                raise ValueError("counterfactual entry must attach to a non-executed decision case")
            if not isinstance(envelope.payload, HorizonObservationEvidenceV1):
                raise ValueError("counterfactual entry requires a horizon observation payload")
        return self

    @property
    def envelope(self) -> AlphaLearningEnvelopeV1:
        return parse_alpha_learning_envelope_v1(self.envelope_canonical_json).envelope


class GoldenReplayResultV1(FrozenGoldenCorpusModel):
    replay_version: Literal["wolf15.wla02.replay-result.v1"]
    valid_time_cutoff_utc: datetime
    knowledge_time_cutoff_utc: datetime
    accepted_fixture_ids: tuple[str, ...]
    history_event_ids: tuple[UUID, ...]
    effective_event_ids: tuple[UUID, ...]
    history_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    effective_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")


class _ReplayHistoryItemV1(FrozenGoldenCorpusModel):
    fixture_id: str
    event_id: UUID
    envelope_hash: str
    source_snapshot_hash: str
    valid_at_utc: datetime
    known_at_utc: datetime
    evidence_class: CorpusEvidenceClass
    correction_of_event_id: UUID | None


class _ReplayEffectiveItemV1(FrozenGoldenCorpusModel):
    event_id: UUID
    envelope_hash: str
    evidence_class: CorpusEvidenceClass


def replay_golden_corpus_v1(
    entries: Sequence[GoldenCorpusEntryV1],
    *,
    valid_time_cutoff_utc: datetime,
    knowledge_time_cutoff_utc: datetime,
    key_registry: Mapping[str, ProducerKeyBindingV1],
) -> GoldenReplayResultV1:
    valid_cutoff = _utc(valid_time_cutoff_utc, "valid_time_cutoff_utc")
    knowledge_cutoff = _utc(knowledge_time_cutoff_utc, "knowledge_time_cutoff_utc")
    if len(entries) > MAX_CORPUS_ENTRIES:
        raise ValueError("corpus exceeds the WLA-02 entry limit")

    ordered = sorted(entries, key=lambda item: (item.known_at_utc, item.valid_at_utc, item.fixture_id))
    fixture_ids = [entry.fixture_id for entry in ordered]
    if len(fixture_ids) != len(set(fixture_ids)):
        raise AmbiguousCorpusError("duplicate fixture_id")
    leaking = [entry.fixture_id for entry in ordered if entry.known_at_utc > knowledge_cutoff]
    if leaking:
        raise FutureLeakageError(f"knowledge-time cutoff exceeded by: {','.join(leaking)}")

    known_event_hashes: dict[str, str] = {}
    accepted_entries: list[tuple[GoldenCorpusEntryV1, AlphaLearningEnvelopeV1]] = []
    by_event_id: dict[UUID, tuple[GoldenCorpusEntryV1, AlphaLearningEnvelopeV1]] = {}
    active_event_ids: set[UUID] = set()

    for entry in ordered:
        if entry.valid_at_utc > valid_cutoff:
            continue
        untrusted = parse_alpha_learning_envelope_v1(entry.envelope_canonical_json)
        accepted = authenticate_alpha_learning_envelope_v1(
            untrusted,
            key_registry=key_registry,
            known_event_hashes=known_event_hashes,
        )
        envelope = accepted.envelope
        event_id = envelope.identity.event_id
        if event_id in by_event_id:
            raise AmbiguousCorpusError(f"duplicate event_id: {event_id}")

        correction_target = entry.correction_of_event_id
        if correction_target is not None:
            target = by_event_id.get(correction_target)
            if target is None:
                raise CorrectionLineageError("correction target is not an earlier authenticated corpus event")
            target_entry, target_envelope = target
            if correction_target not in active_event_ids:
                raise CorrectionLineageError("correction target is already superseded or correction lineage forked")
            if target_entry.evidence_class != entry.evidence_class:
                raise CorrectionLineageError("correction cannot cross evidence classes")
            if target_envelope.contract.event_name != envelope.contract.event_name:
                raise CorrectionLineageError("correction cannot cross WLA-01 event families")
            if target_entry.known_at_utc >= entry.known_at_utc:
                raise CorrectionLineageError("correction knowledge time must be later than its target")
            active_event_ids.remove(correction_target)

        event_id_text = str(event_id)
        known_event_hashes[event_id_text] = envelope.integrity.envelope_hash
        by_event_id[event_id] = (entry, envelope)
        active_event_ids.add(event_id)
        accepted_entries.append((entry, envelope))

    history_projection = [
        _ReplayHistoryItemV1(
            fixture_id=entry.fixture_id,
            event_id=envelope.identity.event_id,
            envelope_hash=envelope.integrity.envelope_hash,
            source_snapshot_hash=entry.source_snapshot_hash,
            valid_at_utc=entry.valid_at_utc,
            known_at_utc=entry.known_at_utc,
            evidence_class=entry.evidence_class,
            correction_of_event_id=entry.correction_of_event_id,
        )
        for entry, envelope in accepted_entries
    ]
    effective_projection = [
        _ReplayEffectiveItemV1(
            event_id=event_id,
            envelope_hash=by_event_id[event_id][1].integrity.envelope_hash,
            evidence_class=by_event_id[event_id][0].evidence_class,
        )
        for event_id in sorted(active_event_ids, key=str)
    ]
    return GoldenReplayResultV1(
        replay_version="wolf15.wla02.replay-result.v1",
        valid_time_cutoff_utc=valid_cutoff,
        knowledge_time_cutoff_utc=knowledge_cutoff,
        accepted_fixture_ids=tuple(entry.fixture_id for entry, _ in accepted_entries),
        history_event_ids=tuple(envelope.identity.event_id for _, envelope in accepted_entries),
        effective_event_ids=tuple(sorted(active_event_ids, key=str)),
        history_hash=alpha_learning_sha256([item.model_dump(mode="json") for item in history_projection]),
        effective_hash=alpha_learning_sha256([item.model_dump(mode="json") for item in effective_projection]),
    )


def canonical_golden_corpus_json_bytes(value: Any) -> bytes:
    return canonical_alpha_learning_json_bytes(value)


__all__ = [
    "AmbiguousCorpusError",
    "CorrectionLineageError",
    "CounterfactualMarketOutcomeSourceV1",
    "DecisionSourceV1",
    "FutureLeakageError",
    "GoldenCorpusEntryV1",
    "GoldenReplayResultV1",
    "OutcomeUnavailableError",
    "RealizedBrokerOutcomeSourceV1",
    "UnavailableOutcomeSourceV1",
    "build_golden_envelope_v1",
    "canonical_golden_corpus_json_bytes",
    "map_decision_source_v1",
    "map_golden_source_v1",
    "map_outcome_source_v1",
    "replay_golden_corpus_v1",
]
