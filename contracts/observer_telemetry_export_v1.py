"""Typed, source-aware telemetry exported from Wolf15 to read-only observers.

The observer is not an execution plane.  The envelope may faithfully mirror a
canonical Wolf15 fact whose ``valid_for_execution`` value is true, but the
envelope itself always has observational authority and can never mutate the
source.  This distinction is intentional: rejecting executable source facts
would make reconciliation incomplete, while granting the observer authority
would violate the system boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OBSERVER_TELEMETRY_ENVELOPE_VERSION = "observer-telemetry-envelope.v1"
OBSERVER_TELEMETRY_EVENT_NAMESPACE = UUID("50d55255-ec44-5827-af02-f88b0b0ba35e")

ObserverAuthorityClass = Literal[
    "RAW_PRESSURE",
    "CANONICAL_PAIR_ADMISSION",
    "STRATEGY_ANALYSIS_ADMISSION",
    "ANALYSIS_LIFECYCLE",
    "CONTEXT_EPOCH",
    "CANONICAL_DECISION",
    "RISK_STATE",
    "FINAL_SIGNAL_STATE",
    "EXECUTION_COMMAND_STATE",
]
PairAdmissionCoverageStatus = Literal[
    "EVALUATED",
    "NOT_APPLICABLE",
    "MISSING_EVALUATION_INCIDENT",
    "INDETERMINATE_RAW_AUTHORITY_COVERAGE",
]


class FrozenObserverContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def canonical_observer_json_bytes(value: Any) -> bytes:
    """Return the single canonical JSON representation used by all hashes."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def observer_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_observer_json_bytes(value)).hexdigest()


class ObserverSourceEventRangeV1(FrozenObserverContract):
    first_event_id: str | None = Field(default=None, min_length=1, max_length=500)
    last_event_id: str | None = Field(default=None, min_length=1, max_length=500)
    first_occurred_at_utc: datetime | None = None
    last_occurred_at_utc: datetime | None = None
    event_count: int = Field(..., ge=0)

    @field_validator("first_occurred_at_utc", "last_occurred_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime | None, info: Any) -> datetime | None:
        return None if value is None else _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _range_is_coherent(self) -> ObserverSourceEventRangeV1:
        identifiers = self.first_event_id is not None and self.last_event_id is not None
        times = self.first_occurred_at_utc is not None and self.last_occurred_at_utc is not None
        if self.event_count == 0:
            if any(
                value is not None
                for value in (
                    self.first_event_id,
                    self.last_event_id,
                    self.first_occurred_at_utc,
                    self.last_occurred_at_utc,
                )
            ):
                raise ValueError("an empty source range cannot contain endpoints")
            return self
        if not identifiers or not times:
            raise ValueError("a non-empty source range requires ID and time endpoints")
        assert self.first_occurred_at_utc is not None
        assert self.last_occurred_at_utc is not None
        if self.last_occurred_at_utc < self.first_occurred_at_utc:
            raise ValueError("source event range cannot run backwards")
        return self


class PairAdmissionEvaluationV3_1(FrozenObserverContract):  # noqa: N801 - external contract name
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    raw_block_id: str = Field(..., min_length=1, max_length=500)
    evaluation_id: str = Field(..., min_length=1, max_length=500)
    coverage_status: PairAdmissionCoverageStatus
    decision: Literal["GRANTED", "NOT_GRANTED", "NOT_APPLICABLE", "UNKNOWN"]
    reason_code: str | None = Field(default=None, max_length=160)
    rule_version: str = Field(..., min_length=1, max_length=100)
    evaluated_at_utc: datetime | None = None
    source_event_range: ObserverSourceEventRangeV1
    source_event_ids: tuple[str, ...] = ()
    execution_authority: Literal[False] = False

    @field_validator("evaluated_at_utc")
    @classmethod
    def _evaluated_at_is_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value, "evaluated_at_utc")

    @model_validator(mode="after")
    def _coverage_semantics_are_explicit(self) -> PairAdmissionEvaluationV3_1:
        if self.source_event_ids != tuple(dict.fromkeys(self.source_event_ids)):
            raise ValueError("source_event_ids must be ordered and unique")
        if len(self.source_event_ids) != self.source_event_range.event_count:
            raise ValueError("source_event_ids must match source_event_range.event_count")
        if self.coverage_status == "EVALUATED":
            if self.evaluated_at_utc is None or self.decision not in {"GRANTED", "NOT_GRANTED"}:
                raise ValueError("EVALUATED coverage requires a timestamp and canonical decision")
        elif self.coverage_status == "NOT_APPLICABLE":
            if self.decision != "NOT_APPLICABLE" or self.evaluated_at_utc is not None:
                raise ValueError("NOT_APPLICABLE coverage is not an evaluation")
        elif self.decision != "UNKNOWN" or self.evaluated_at_utc is not None:
            raise ValueError("missing or indeterminate coverage must remain UNKNOWN")
        if self.decision == "GRANTED" and self.reason_code is not None:
            raise ValueError("GRANTED pair admission cannot carry a blocker reason")
        if self.decision != "GRANTED" and not self.reason_code:
            raise ValueError("non-granted pair admission requires an explicit reason")
        return self


class StrategyAnalysisAdmissionV1(FrozenObserverContract):
    analysis_admission_id: str = Field(..., min_length=1, max_length=500)
    # Analysis admission precedes lifecycle formation in the canonical raw
    # path, so a lifecycle ID is only present when the source already owns it.
    strategy_lifecycle_id: str | None = Field(default=None, pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    authority_scope_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    admission_class: Literal["CANONICAL_RAW", "MATURE_ADVISORY"]
    decision: Literal["ADMITTED", "NOT_ADMITTED"]
    reason_code: str | None = Field(default=None, max_length=160)
    rule_version: str = Field(..., min_length=1, max_length=100)
    admitted_at_utc: datetime
    next_required_stage: str | None = Field(default=None, max_length=100)
    source_event_ids: tuple[str, ...]
    execution_authority: Literal[False] = False

    @field_validator("admitted_at_utc")
    @classmethod
    def _admitted_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "admitted_at_utc")

    @model_validator(mode="after")
    def _admission_is_coherent(self) -> StrategyAnalysisAdmissionV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("analysis admission source_event_ids must be non-empty, sorted, and unique")
        if self.decision == "ADMITTED" and self.reason_code is not None:
            raise ValueError("ADMITTED analysis cannot carry a blocker reason")
        if self.decision == "NOT_ADMITTED" and not self.reason_code:
            raise ValueError("NOT_ADMITTED analysis requires a reason")
        return self


class AnalysisLifecycleTransitionV1(FrozenObserverContract):
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    previous_state: str | None = Field(default=None, max_length=100)
    new_state: str = Field(..., min_length=1, max_length=100)
    reason_code: str = Field(..., min_length=1, max_length=160)
    transition_time_utc: datetime
    source_event_ids: tuple[str, ...]
    execution_authority: Literal[False] = False

    @field_validator("transition_time_utc")
    @classmethod
    def _transition_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "transition_time_utc")

    @model_validator(mode="after")
    def _sources_are_stable(self) -> AnalysisLifecycleTransitionV1:
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("lifecycle transition source_event_ids must be non-empty, sorted, and unique")
        if self.previous_state == self.new_state:
            raise ValueError("lifecycle transition must change state")
        return self


class ContextEpochTransitionObserverV1(FrozenObserverContract):
    context_epoch_id: str | None = Field(default=None, pattern=r"^5scr-context:[0-9a-f]{32}$")
    strategy_lifecycle_id: str = Field(..., pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    previous_epoch_id: str | None = Field(default=None, pattern=r"^5scr-context:[0-9a-f]{32}$")
    material_context_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    direction_domain: str = Field(..., min_length=1, max_length=100)
    route: tuple[str, ...]
    target_map_version: str | None = Field(default=None, max_length=100)
    transition_reason: str = Field(..., min_length=1, max_length=100)
    transition_time_utc: datetime
    source_event_ids: tuple[str, ...]
    execution_authority: Literal[False] = False

    @field_validator("transition_time_utc")
    @classmethod
    def _transition_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "transition_time_utc")

    @model_validator(mode="after")
    def _sets_are_stable(self) -> ContextEpochTransitionObserverV1:
        if self.route != tuple(sorted(set(self.route))):
            raise ValueError("context route must be sorted and unique")
        if not self.source_event_ids or self.source_event_ids != tuple(sorted(set(self.source_event_ids))):
            raise ValueError("context transition source_event_ids must be non-empty, sorted, and unique")
        return self


class CanonicalDecisionReasonV1(FrozenObserverContract):
    decision_id: str = Field(..., min_length=1, max_length=500)
    strategy_lifecycle_id: str | None = Field(default=None, pattern=r"^5scr-lifecycle:[0-9a-f]{32}$")
    authority_scope_id: str = Field(..., min_length=1, max_length=500)
    stage: str = Field(..., min_length=1, max_length=100)
    decision: str = Field(..., min_length=1, max_length=100)
    reason_code: str = Field(..., min_length=1, max_length=160)
    reason_codes: tuple[str, ...] = ()
    next_required_stage: str | None = Field(default=None, max_length=100)
    evidence_refs: tuple[str, ...]
    decided_at_utc: datetime
    execution_authority: Literal[False] = False

    @field_validator("decided_at_utc")
    @classmethod
    def _decided_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decided_at_utc")

    @model_validator(mode="after")
    def _evidence_is_stable(self) -> CanonicalDecisionReasonV1:
        if not self.evidence_refs or self.evidence_refs != tuple(sorted(set(self.evidence_refs))):
            raise ValueError("canonical decision evidence_refs must be non-empty, sorted, and unique")
        if self.reason_codes:
            if self.reason_codes != tuple(dict.fromkeys(self.reason_codes)):
                raise ValueError("canonical decision reason_codes must be ordered and unique")
            if self.reason_codes[0] != self.reason_code:
                raise ValueError("reason_code must be the first canonical reason_codes item")
        return self


class RiskStateMirrorV1(FrozenObserverContract):
    risk_state_id: str = Field(..., min_length=1, max_length=500)
    state: str = Field(..., min_length=1, max_length=100)
    valid_for_execution: bool
    risk_authority: bool
    observed_at_utc: datetime

    @field_validator("observed_at_utc")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "observed_at_utc")


class FinalSignalStateMirrorV1(FrozenObserverContract):
    final_signal_id: str = Field(..., min_length=1, max_length=500)
    state: str = Field(..., min_length=1, max_length=100)
    direction: Literal["BUY", "SELL", "WAIT"]
    valid_for_execution: bool
    observed_at_utc: datetime

    @field_validator("observed_at_utc")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "observed_at_utc")


class ExecutionCommandStateMirrorV1(FrozenObserverContract):
    command_id: str = Field(..., min_length=1, max_length=500)
    state: str = Field(..., min_length=1, max_length=100)
    direction: Literal["BUY", "SELL"]
    valid_for_execution: bool
    broker_execution_authority: bool
    observed_at_utc: datetime

    @field_validator("observed_at_utc")
    @classmethod
    def _observed_at_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "observed_at_utc")


ObserverPayloadBodyV1: TypeAlias = (
    PairAdmissionEvaluationV3_1
    | StrategyAnalysisAdmissionV1
    | AnalysisLifecycleTransitionV1
    | ContextEpochTransitionObserverV1
    | CanonicalDecisionReasonV1
    | RiskStateMirrorV1
    | FinalSignalStateMirrorV1
    | ExecutionCommandStateMirrorV1
)

_PAYLOAD_REGISTRY: dict[str, tuple[type[FrozenObserverContract], str, ObserverAuthorityClass]] = {
    "PairAdmissionEvaluationV3_1": (PairAdmissionEvaluationV3_1, "3.1", "CANONICAL_PAIR_ADMISSION"),
    "StrategyAnalysisAdmissionV1": (StrategyAnalysisAdmissionV1, "1.0", "STRATEGY_ANALYSIS_ADMISSION"),
    "AnalysisLifecycleTransitionV1": (AnalysisLifecycleTransitionV1, "1.0", "ANALYSIS_LIFECYCLE"),
    "ContextEpochTransitionV1": (ContextEpochTransitionObserverV1, "1.0", "CONTEXT_EPOCH"),
    "CanonicalDecisionReasonV1": (CanonicalDecisionReasonV1, "1.0", "CANONICAL_DECISION"),
    "RiskStateMirrorV1": (RiskStateMirrorV1, "1.0", "RISK_STATE"),
    "FinalSignalStateMirrorV1": (FinalSignalStateMirrorV1, "1.0", "FINAL_SIGNAL_STATE"),
    "ExecutionCommandStateMirrorV1": (ExecutionCommandStateMirrorV1, "1.0", "EXECUTION_COMMAND_STATE"),
}
_PAYLOAD_CLASS_TO_NAME = {contract: name for name, (contract, _, _) in _PAYLOAD_REGISTRY.items()}


class ObserverStreamPositionV1(FrozenObserverContract):
    stream_id: str = Field(..., min_length=1, max_length=500)
    stream_sequence: int = Field(..., ge=1)
    previous_stream_sequence: int | None = Field(default=None, ge=1)
    previous_event_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _chain_is_contiguous(self) -> ObserverStreamPositionV1:
        if self.stream_sequence == 1:
            if self.previous_stream_sequence is not None or self.previous_event_hash is not None:
                raise ValueError("the first stream event cannot have a predecessor")
        elif self.previous_stream_sequence != self.stream_sequence - 1 or self.previous_event_hash is None:
            raise ValueError("a non-first stream event requires its immediate predecessor")
        return self


class ObserverTimingV1(FrozenObserverContract):
    occurred_at_utc: datetime
    published_at_utc: datetime

    @field_validator("occurred_at_utc", "published_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _publication_follows_occurrence(self) -> ObserverTimingV1:
        if self.published_at_utc < self.occurred_at_utc:
            raise ValueError("published_at_utc cannot precede occurred_at_utc")
        return self


class ObserverSourceV1(FrozenObserverContract):
    system: Literal["WOLF15"] = "WOLF15"
    service: str = Field(..., min_length=1, max_length=160)
    commit_sha: str = Field(..., pattern=r"^(?:[0-9a-f]{7,64}|UNAVAILABLE)$")
    deployment_id: str | None = Field(default=None, max_length=200)
    schema_version: Literal["observer-telemetry-envelope.v1"] = OBSERVER_TELEMETRY_ENVELOPE_VERSION
    policy_version: str | None = Field(default=None, max_length=160)


class ObserverAuthorityV1(FrozenObserverContract):
    authority_class: ObserverAuthorityClass
    observer_authority: Literal["OBSERVATIONAL_ONLY"] = "OBSERVATIONAL_ONLY"


class ObserverPayloadV1(FrozenObserverContract):
    payload_type: str = Field(..., min_length=1, max_length=160)
    payload_version: str = Field(..., min_length=1, max_length=100)
    payload_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    body: dict[str, Any]

    @model_validator(mode="after")
    def _hash_matches_body(self) -> ObserverPayloadV1:
        if self.payload_hash != observer_sha256(self.body):
            raise ValueError("payload_hash does not match the canonical body")
        return self


class ObserverSafetyV1(FrozenObserverContract):
    observer_can_mutate_source: Literal[False] = False


class ObserverTelemetryEnvelopeV1(FrozenObserverContract):
    event_id: UUID
    stream: ObserverStreamPositionV1
    timing: ObserverTimingV1
    source: ObserverSourceV1
    authority: ObserverAuthorityV1
    payload: ObserverPayloadV1
    safety: ObserverSafetyV1 = Field(default_factory=ObserverSafetyV1)

    @model_validator(mode="after")
    def _typed_payload_matches_authority(self) -> ObserverTelemetryEnvelopeV1:
        registered = _PAYLOAD_REGISTRY.get(self.payload.payload_type)
        if registered is None:
            raise ValueError("payload_type is not registered for observer export v1")
        contract, version, authority_class = registered
        if self.payload.payload_version != version:
            raise ValueError("payload_version does not match payload_type")
        if self.authority.authority_class != authority_class:
            raise ValueError("authority_class does not match payload_type")
        contract.model_validate(self.payload.body)
        return self


@dataclass(frozen=True)
class ObserverTelemetryDraftV1:
    """A logical export event before its transaction allocates stream order."""

    logical_event_key: str
    stream_id: str
    occurred_at_utc: datetime
    source: ObserverSourceV1
    authority_class: ObserverAuthorityClass
    payload: ObserverPayloadV1

    @property
    def event_id(self) -> UUID:
        return uuid5(
            OBSERVER_TELEMETRY_EVENT_NAMESPACE,
            f"{self.payload.payload_type}|{self.logical_event_key}",
        )


def observer_source_from_env(
    *,
    service: str,
    policy_version: str | None = None,
    environ: dict[str, str] | None = None,
) -> ObserverSourceV1:
    values = os.environ if environ is None else environ
    commit_sha = next(
        (
            values[name].strip().lower()
            for name in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "SOURCE_COMMIT_SHA")
            if values.get(name, "").strip()
        ),
        "UNAVAILABLE",
    )
    deployment_id = next(
        (values[name].strip() for name in ("RAILWAY_DEPLOYMENT_ID", "DEPLOYMENT_ID") if values.get(name, "").strip()),
        None,
    )
    return ObserverSourceV1(
        service=service,
        commit_sha=commit_sha,
        deployment_id=deployment_id,
        policy_version=policy_version,
    )


def observer_payload(body: ObserverPayloadBodyV1) -> tuple[ObserverAuthorityClass, ObserverPayloadV1]:
    payload_name = _PAYLOAD_CLASS_TO_NAME.get(type(body))
    if payload_name is None:
        raise TypeError(f"unregistered observer payload contract: {type(body).__name__}")
    _, version, authority_class = _PAYLOAD_REGISTRY[payload_name]
    serialized = body.model_dump(mode="json")
    return authority_class, ObserverPayloadV1(
        payload_type=payload_name,
        payload_version=version,
        payload_hash=observer_sha256(serialized),
        body=serialized,
    )


def observer_draft(
    *,
    logical_event_key: str,
    stream_id: str,
    occurred_at_utc: datetime,
    source: ObserverSourceV1,
    body: ObserverPayloadBodyV1,
) -> ObserverTelemetryDraftV1:
    authority_class, payload = observer_payload(body)
    return ObserverTelemetryDraftV1(
        logical_event_key=logical_event_key,
        stream_id=stream_id,
        occurred_at_utc=_utc(occurred_at_utc, "occurred_at_utc"),
        source=source,
        authority_class=authority_class,
        payload=payload,
    )


def build_observer_envelope(
    draft: ObserverTelemetryDraftV1,
    *,
    stream_sequence: int,
    previous_event_hash: str | None,
    published_at_utc: datetime | None = None,
) -> ObserverTelemetryEnvelopeV1:
    published_at = datetime.now(UTC) if published_at_utc is None else _utc(published_at_utc, "published_at_utc")
    return ObserverTelemetryEnvelopeV1(
        event_id=draft.event_id,
        stream=ObserverStreamPositionV1(
            stream_id=draft.stream_id,
            stream_sequence=stream_sequence,
            previous_stream_sequence=None if stream_sequence == 1 else stream_sequence - 1,
            previous_event_hash=previous_event_hash,
        ),
        timing=ObserverTimingV1(
            occurred_at_utc=draft.occurred_at_utc,
            published_at_utc=published_at,
        ),
        source=draft.source,
        authority=ObserverAuthorityV1(authority_class=draft.authority_class),
        payload=draft.payload,
    )


def observer_event_hash(envelope: ObserverTelemetryEnvelopeV1) -> str:
    return observer_sha256(envelope.model_dump(mode="json"))


def validate_observer_payload_body(payload: ObserverPayloadV1) -> ObserverPayloadBodyV1:
    contract = _PAYLOAD_REGISTRY[payload.payload_type][0]
    return cast(ObserverPayloadBodyV1, contract.model_validate(payload.body))


__all__ = [
    "AnalysisLifecycleTransitionV1",
    "CanonicalDecisionReasonV1",
    "ContextEpochTransitionObserverV1",
    "ExecutionCommandStateMirrorV1",
    "FinalSignalStateMirrorV1",
    "OBSERVER_TELEMETRY_ENVELOPE_VERSION",
    "ObserverAuthorityClass",
    "ObserverPayloadV1",
    "ObserverSafetyV1",
    "ObserverSourceEventRangeV1",
    "ObserverSourceV1",
    "ObserverStreamPositionV1",
    "ObserverTelemetryDraftV1",
    "ObserverTelemetryEnvelopeV1",
    "PairAdmissionCoverageStatus",
    "PairAdmissionEvaluationV3_1",
    "RiskStateMirrorV1",
    "StrategyAnalysisAdmissionV1",
    "build_observer_envelope",
    "canonical_observer_json_bytes",
    "observer_draft",
    "observer_event_hash",
    "observer_payload",
    "observer_sha256",
    "observer_source_from_env",
    "validate_observer_payload_body",
]
