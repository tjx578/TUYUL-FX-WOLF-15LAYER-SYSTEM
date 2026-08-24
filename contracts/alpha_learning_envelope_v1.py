"""Pure WLA-01 wire contract for observational WOLF15 learning exports.

This module deliberately contains no storage, transport, registration, runtime,
broker, EA, deployment, or execution integration.  It defines two source-owned
event families, a closed typed payload registry, canonical serialization, and a
strict reference parser.  Mirrored source facts retain provenance but the
envelope itself can never mutate WOLF15, issue a verdict, execute, or promote.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID, uuid5

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALPHA_LEARNING_ENVELOPE_VERSION = "alpha-learning-envelope.v1"
ALPHA_LEARNING_CANONICALIZATION_VERSION = "wolf15.wla.canonical-json.v1"
ALPHA_LEARNING_AUTHENTICATION_VERSION = "wolf15.alpha-learning-authentication.v1"
ALPHA_LEARNING_SIGNATURE_DOMAIN = "WOLF15_ALPHA_LEARNING_ENVELOPE_V1"
ALPHA_LEARNING_EVENT_NAMESPACE = UUID("e94f4671-1c16-5a5a-8a18-c69a7349d5c9")

MAX_CANONICAL_ENVELOPE_BYTES = 65_536
MAX_DIRECT_SOURCE_REFS = 32
MAX_REASON_CODES = 16
MAX_MISSING_FIELDS = 16
MAX_HORIZON_SECONDS = 31_536_000

ALPHA_FACT_EVENT = "wolf15.alpha-fact.exported.v1"
OUTCOME_EVIDENCE_EVENT = "wolf15.outcome-evidence.exported.v1"
ALPHA_FACT_SCHEMA_ID = "urn:wolf15:wla:schema:alpha-fact-exported:v1"
OUTCOME_EVIDENCE_SCHEMA_ID = "urn:wolf15:wla:schema:outcome-evidence-exported:v1"

EventName: TypeAlias = Literal[
    "wolf15.alpha-fact.exported.v1",
    "wolf15.outcome-evidence.exported.v1",
]
SourceAuthorityClass: TypeAlias = Literal[
    "WOLF15_CANONICAL_ALPHA",
    "WOLF15_SOURCE_OUTCOME_EVIDENCE",
]
QualityReasonCode: TypeAlias = Literal[
    "SOURCE_REVISION_UNAVAILABLE",
    "SOURCE_CLOCK_DEGRADED",
    "SOURCE_CLOCK_UNKNOWN",
    "SOURCE_EVIDENCE_INCOMPLETE",
    "SOURCE_FIELD_MISSING",
    "SOURCE_CONTRACT_QUARANTINE",
]
UncertaintyFlag: TypeAlias = Literal[
    "SOURCE_REVISION_UNAVAILABLE",
    "SOURCE_CLOCK_DEGRADED",
    "SOURCE_CLOCK_UNKNOWN",
    "SOURCE_EVIDENCE_INCOMPLETE",
]
PositiveDecimal = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=8)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=8)]


class FrozenLearningContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return value.astimezone(UTC)


def _ordered_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{field_name} must be sorted and unique")
    return values


def canonical_alpha_learning_json_bytes(value: Any) -> bytes:
    """Return the only canonical JSON representation accepted by WLA-01."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def alpha_learning_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_alpha_learning_json_bytes(value)).hexdigest()


class ContractIdentityV1(FrozenLearningContract):
    envelope_version: Literal["alpha-learning-envelope.v1"]
    event_name: EventName
    event_version: Literal[1]
    schema_id: str = Field(..., min_length=1, max_length=200)


class EventIdentityV1(FrozenLearningContract):
    event_id: UUID
    logical_event_key: str = Field(..., min_length=1, max_length=500, pattern=r"^[A-Za-z0-9][A-Za-z0-9:._|/-]*$")


class EvidenceRefV1(FrozenLearningContract):
    ref_type: Literal[
        "WOLF15_SOURCE_RECORD",
        "WOLF15_ALPHA",
        "WOLF15_EXECUTION",
        "WOLF15_MARKET_OBSERVATION",
    ]
    ref_id: str = Field(..., min_length=1, max_length=500)
    ref_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


def _refs_are_sorted_unique(values: tuple[EvidenceRefV1, ...], field_name: str) -> tuple[EvidenceRefV1, ...]:
    keys = tuple((item.ref_type, item.ref_id) for item in values)
    if keys != tuple(sorted(set(keys))):
        raise ValueError(f"{field_name} must be sorted and unique by ref_type/ref_id")
    return values


class AncestryManifestRefV1(FrozenLearningContract):
    manifest_id: str = Field(..., min_length=1, max_length=500)
    covered_sequence_start: int = Field(..., ge=1)
    covered_sequence_end: int = Field(..., ge=1)
    event_count: int = Field(..., gt=MAX_DIRECT_SOURCE_REFS, le=1_000_000)
    integrity_root: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _range_matches_count(self) -> AncestryManifestRefV1:
        if self.covered_sequence_end < self.covered_sequence_start:
            raise ValueError("ancestry manifest range cannot run backwards")
        if self.event_count != self.covered_sequence_end - self.covered_sequence_start + 1:
            raise ValueError("ancestry manifest event_count must match its covered range")
        return self


class CausalityV1(FrozenLearningContract):
    correlation_id: UUID
    causation_id: UUID | None
    direct_source_refs: tuple[EvidenceRefV1, ...] = Field(..., max_length=MAX_DIRECT_SOURCE_REFS)
    ancestry_manifest: AncestryManifestRefV1 | None

    @field_validator("direct_source_refs")
    @classmethod
    def _direct_refs_are_bounded(cls, value: tuple[EvidenceRefV1, ...]) -> tuple[EvidenceRefV1, ...]:
        return _refs_are_sorted_unique(value, "direct_source_refs")

    @model_validator(mode="after")
    def _some_source_lineage_exists(self) -> CausalityV1:
        if not self.direct_source_refs and self.ancestry_manifest is None:
            raise ValueError("source events require direct refs or a sealed ancestry manifest")
        return self


class StreamPositionV1(FrozenLearningContract):
    stream_id: str = Field(..., min_length=1, max_length=500)
    stream_sequence: int = Field(..., ge=1)
    previous_stream_sequence: int | None = Field(default=None, ge=1)
    previous_event_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    ordering_scope: Literal["SOURCE_STREAM"]

    @model_validator(mode="after")
    def _chain_is_contiguous(self) -> StreamPositionV1:
        if self.stream_sequence == 1:
            if self.previous_stream_sequence is not None or self.previous_event_hash is not None:
                raise ValueError("the first stream event cannot have a predecessor")
        elif self.previous_stream_sequence != self.stream_sequence - 1 or self.previous_event_hash is None:
            raise ValueError("a non-first stream event requires its immediate predecessor")
        return self


class SourceIdentityV1(FrozenLearningContract):
    source_system: Literal["WOLF15"]
    source_service: str = Field(..., min_length=1, max_length=160)
    code_revision: str = Field(..., pattern=r"^(?:[0-9a-f]{40}|UNAVAILABLE)$")
    deployment_id: str = Field(..., min_length=1, max_length=200)
    policy_version: str = Field(..., min_length=1, max_length=160)
    config_version: str = Field(..., min_length=1, max_length=160)


class SourceTimingV1(FrozenLearningContract):
    occurred_at_utc: datetime
    observed_at_utc: datetime
    source_published_at_utc: datetime
    source_precision: Literal["MICROSECOND", "MILLISECOND", "SECOND", "COARSE"]
    clock_status: Literal["SYNCHRONIZED", "DEGRADED", "UNKNOWN"]
    maximum_clock_skew_ms: int = Field(..., ge=0, le=300_000)

    @field_validator("occurred_at_utc", "observed_at_utc", "source_published_at_utc")
    @classmethod
    def _times_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _utc(value, str(info.field_name))

    @model_validator(mode="after")
    def _source_clock_order_is_explicit(self) -> SourceTimingV1:
        if self.observed_at_utc < self.occurred_at_utc:
            raise ValueError("observed_at_utc cannot precede occurred_at_utc")
        if self.source_published_at_utc < self.observed_at_utc:
            raise ValueError("source_published_at_utc cannot precede observed_at_utc")
        return self


class AuthorityV1(FrozenLearningContract):
    source_authority_class: SourceAuthorityClass
    source_interaction_authority: Literal["OBSERVATIONAL_ONLY"]
    wla_decision_authority: Literal["NONE"]
    wla_gate_authority: Literal["NONE"]


class SafetyV1(FrozenLearningContract):
    can_mutate_source: Literal[False]
    can_issue_verdict: Literal[False]
    can_execute: Literal[False]
    can_self_promote: Literal[False]


class IntegrityV1(FrozenLearningContract):
    canonicalization_version: Literal["wolf15.wla.canonical-json.v1"]
    payload_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")
    envelope_hash: str = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")


class ProducerAuthenticationV1(FrozenLearningContract):
    authentication_version: Literal["wolf15.alpha-learning-authentication.v1"]
    algorithm: Literal["ED25519"]
    signature_domain: Literal["WOLF15_ALPHA_LEARNING_ENVELOPE_V1"]
    key_id: str = Field(..., min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    producer_role: SourceAuthorityClass
    signature: str = Field(..., pattern=r"^base64url:[A-Za-z0-9_-]{86}$")


class ProducerKeyBindingV1(FrozenLearningContract):
    """One caller-supplied allowlist entry; this contract performs no key I/O."""

    key_id: str = Field(..., min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    algorithm: Literal["ED25519"]
    signature_domain: str = Field(..., min_length=1, max_length=160)
    source_system: Literal["WOLF15"]
    source_service: str = Field(..., min_length=1, max_length=160)
    producer_role: SourceAuthorityClass
    status: Literal["ACTIVE", "REVOKED"]
    public_key: str = Field(..., pattern=r"^base64url:[A-Za-z0-9_-]{43}$")


class ProducerAuthenticationError(ValueError):
    """Fail-closed producer-authentication or identity-conflict rejection."""


class QualityV1(FrozenLearningContract):
    evidence_status: Literal["VALID", "QUARANTINED"]
    reason_codes: tuple[QualityReasonCode, ...] = Field(..., max_length=MAX_REASON_CODES)
    missing_fields: tuple[str, ...] = Field(..., max_length=MAX_MISSING_FIELDS)
    uncertainty_flags: tuple[UncertaintyFlag, ...] = Field(..., max_length=MAX_REASON_CODES)
    correction_of_event_id: UUID | None
    supersedes_event_id: UUID | None
    invalidates_event_id: UUID | None

    @field_validator("reason_codes", "missing_fields", "uncertainty_flags")
    @classmethod
    def _quality_sequences_are_canonical(cls, value: tuple[str, ...], info: Any) -> tuple[str, ...]:
        return _ordered_unique(value, str(info.field_name))

    @model_validator(mode="after")
    def _quality_status_is_fail_closed(self) -> QualityV1:
        refs = tuple(
            item
            for item in (self.correction_of_event_id, self.supersedes_event_id, self.invalidates_event_id)
            if item is not None
        )
        if len(refs) != len(set(refs)):
            raise ValueError("correction, supersession, and invalidation refs must be distinct")
        if self.evidence_status == "VALID":
            if self.reason_codes or self.missing_fields or self.uncertainty_flags:
                raise ValueError("VALID evidence cannot hide reasons, missingness, or uncertainty")
        elif not self.reason_codes:
            raise ValueError("QUARANTINED evidence requires an explicit reason")
        return self


class TraceV1(FrozenLearningContract):
    producer_run_id: UUID
    replay_manifest_ref: str | None = Field(default=None, min_length=1, max_length=500)
    dataset_manifest_ref: str | None = Field(default=None, min_length=1, max_length=500)
    model_manifest_ref: str | None = Field(default=None, min_length=1, max_length=500)


class CanonicalAlphaDecisionFactV1(FrozenLearningContract):
    payload_type: Literal["canonical-alpha-decision.v1"]
    alpha_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    decision: Literal["BUY", "SELL", "WAIT"]
    decision_reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=MAX_REASON_CODES)
    evidence_refs: tuple[EvidenceRefV1, ...] = Field(..., min_length=1, max_length=MAX_DIRECT_SOURCE_REFS)
    decision_policy_version: str = Field(..., min_length=1, max_length=160)
    decided_at_utc: datetime
    source_valid_for_execution: bool

    @field_validator("decision_reason_codes")
    @classmethod
    def _reasons_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, "decision_reason_codes")

    @field_validator("evidence_refs")
    @classmethod
    def _evidence_refs_are_canonical(cls, value: tuple[EvidenceRefV1, ...]) -> tuple[EvidenceRefV1, ...]:
        return _refs_are_sorted_unique(value, "evidence_refs")

    @field_validator("decided_at_utc")
    @classmethod
    def _decision_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decided_at_utc")

    @model_validator(mode="after")
    def _wait_is_not_execution_valid(self) -> CanonicalAlphaDecisionFactV1:
        if self.decision == "WAIT" and self.source_valid_for_execution:
            raise ValueError("WAIT cannot be source-valid for execution")
        return self


class CanonicalAlphaAbstentionFactV1(FrozenLearningContract):
    payload_type: Literal["canonical-alpha-abstention.v1"]
    alpha_evaluation_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    abstention_kind: Literal["INSUFFICIENT_EVIDENCE", "RISK_BLOCKED", "POLICY_BLOCKED", "SOURCE_UNKNOWN"]
    reason_codes: tuple[str, ...] = Field(..., min_length=1, max_length=MAX_REASON_CODES)
    evidence_refs: tuple[EvidenceRefV1, ...] = Field(..., min_length=1, max_length=MAX_DIRECT_SOURCE_REFS)
    decision_policy_version: str = Field(..., min_length=1, max_length=160)
    decided_at_utc: datetime
    source_valid_for_execution: Literal[False]

    @field_validator("reason_codes")
    @classmethod
    def _reasons_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_unique(value, "reason_codes")

    @field_validator("evidence_refs")
    @classmethod
    def _evidence_refs_are_canonical(cls, value: tuple[EvidenceRefV1, ...]) -> tuple[EvidenceRefV1, ...]:
        return _refs_are_sorted_unique(value, "evidence_refs")

    @field_validator("decided_at_utc")
    @classmethod
    def _decision_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "decided_at_utc")


class FillOutcomeEvidenceV1(FrozenLearningContract):
    payload_type: Literal["fill-evidence.v1"]
    execution_id: str = Field(..., min_length=1, max_length=500)
    order_id: str = Field(..., min_length=1, max_length=500)
    fill_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    requested_quantity: PositiveDecimal
    filled_quantity: PositiveDecimal
    fill_price: PositiveDecimal
    filled_at_utc: datetime
    finality: Literal["FULL"]

    @field_validator("filled_at_utc")
    @classmethod
    def _fill_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "filled_at_utc")

    @model_validator(mode="after")
    def _full_fill_matches_request(self) -> FillOutcomeEvidenceV1:
        if self.filled_quantity != self.requested_quantity:
            raise ValueError("FULL fill quantity must equal requested quantity")
        return self


class PartialFillOutcomeEvidenceV1(FrozenLearningContract):
    payload_type: Literal["partial-fill-evidence.v1"]
    execution_id: str = Field(..., min_length=1, max_length=500)
    order_id: str = Field(..., min_length=1, max_length=500)
    fill_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    requested_quantity: PositiveDecimal
    cumulative_filled_quantity: PositiveDecimal
    remaining_quantity: PositiveDecimal
    fill_price: PositiveDecimal
    filled_at_utc: datetime
    finality: Literal["PARTIAL"]

    @field_validator("filled_at_utc")
    @classmethod
    def _fill_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "filled_at_utc")

    @model_validator(mode="after")
    def _partial_fill_balances(self) -> PartialFillOutcomeEvidenceV1:
        if self.cumulative_filled_quantity + self.remaining_quantity != self.requested_quantity:
            raise ValueError("partial fill quantities must balance to requested_quantity")
        return self


class RejectOutcomeEvidenceV1(FrozenLearningContract):
    payload_type: Literal["reject-evidence.v1"]
    request_id: str = Field(..., min_length=1, max_length=500)
    order_id: str | None = Field(default=None, min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    reason_code: str = Field(..., min_length=1, max_length=160)
    rejected_at_utc: datetime
    finality: Literal["REJECTED"]

    @field_validator("rejected_at_utc")
    @classmethod
    def _reject_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "rejected_at_utc")


class CancelOutcomeEvidenceV1(FrozenLearningContract):
    payload_type: Literal["cancel-evidence.v1"]
    order_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    side: Literal["BUY", "SELL"]
    reason_code: str = Field(..., min_length=1, max_length=160)
    filled_quantity: NonNegativeDecimal
    cancelled_at_utc: datetime
    finality: Literal["CANCELLED"]

    @field_validator("cancelled_at_utc")
    @classmethod
    def _cancel_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "cancelled_at_utc")


class HorizonObservationEvidenceV1(FrozenLearningContract):
    payload_type: Literal["horizon-observation-evidence.v1"]
    alpha_id: str = Field(..., min_length=1, max_length=500)
    symbol: str = Field(..., min_length=3, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    observation_kind: Literal["MARKET_HORIZON_SNAPSHOT"]
    horizon_policy_version: str = Field(..., min_length=1, max_length=160)
    horizon_seconds: int = Field(..., gt=0, le=MAX_HORIZON_SECONDS)
    reference_price: PositiveDecimal
    observed_price: PositiveDecimal
    observed_at_utc: datetime

    @field_validator("observed_at_utc")
    @classmethod
    def _observation_time_is_utc(cls, value: datetime) -> datetime:
        return _utc(value, "observed_at_utc")


AlphaFactPayloadV1: TypeAlias = CanonicalAlphaDecisionFactV1 | CanonicalAlphaAbstentionFactV1
OutcomeEvidencePayloadV1: TypeAlias = (
    FillOutcomeEvidenceV1
    | PartialFillOutcomeEvidenceV1
    | RejectOutcomeEvidenceV1
    | CancelOutcomeEvidenceV1
    | HorizonObservationEvidenceV1
)
LearningPayloadV1: TypeAlias = Annotated[
    AlphaFactPayloadV1 | OutcomeEvidencePayloadV1,
    Field(discriminator="payload_type"),
]

_EVENT_SCHEMA: dict[str, tuple[str, SourceAuthorityClass, frozenset[str]]] = {
    ALPHA_FACT_EVENT: (
        ALPHA_FACT_SCHEMA_ID,
        "WOLF15_CANONICAL_ALPHA",
        frozenset({"canonical-alpha-decision.v1", "canonical-alpha-abstention.v1"}),
    ),
    OUTCOME_EVIDENCE_EVENT: (
        OUTCOME_EVIDENCE_SCHEMA_ID,
        "WOLF15_SOURCE_OUTCOME_EVIDENCE",
        frozenset(
            {
                "fill-evidence.v1",
                "partial-fill-evidence.v1",
                "reject-evidence.v1",
                "cancel-evidence.v1",
                "horizon-observation-evidence.v1",
            }
        ),
    ),
}


def alpha_learning_event_id(
    *,
    event_name: str,
    event_version: int,
    source_system: str,
    logical_event_key: str,
) -> UUID:
    """Return the stable ID; deployment is provenance, not logical identity."""

    return uuid5(
        ALPHA_LEARNING_EVENT_NAMESPACE,
        f"{event_name}|{event_version}|{source_system}|{logical_event_key}",
    )


class AlphaLearningEnvelopeV1(FrozenLearningContract):
    contract: ContractIdentityV1
    identity: EventIdentityV1
    causality: CausalityV1
    stream: StreamPositionV1
    source: SourceIdentityV1
    timing: SourceTimingV1
    authority: AuthorityV1
    safety: SafetyV1
    producer_authentication: ProducerAuthenticationV1
    integrity: IntegrityV1
    quality: QualityV1
    trace: TraceV1
    payload: LearningPayloadV1

    @model_validator(mode="after")
    def _closed_registry_and_hashes_match(self) -> AlphaLearningEnvelopeV1:
        schema_id, authority_class, allowed_payloads = _EVENT_SCHEMA[self.contract.event_name]
        if self.contract.schema_id != schema_id:
            raise ValueError("schema_id does not match event_name")
        if self.payload.payload_type not in allowed_payloads:
            raise ValueError("payload_type is not registered for event_name")
        if self.authority.source_authority_class != authority_class:
            raise ValueError("source_authority_class does not match event_name")
        if self.producer_authentication.producer_role != authority_class:
            raise ValueError("producer authentication role does not match event authority")

        expected_id = alpha_learning_event_id(
            event_name=self.contract.event_name,
            event_version=self.contract.event_version,
            source_system=self.source.source_system,
            logical_event_key=self.identity.logical_event_key,
        )
        if self.identity.event_id != expected_id:
            raise ValueError("event_id does not match the canonical identity tuple")

        if self.integrity.payload_hash != alpha_learning_sha256(self.payload.model_dump(mode="json")):
            raise ValueError("payload_hash does not match the canonical typed payload")
        if self.integrity.envelope_hash != alpha_learning_envelope_hash(self):
            raise ValueError("envelope_hash does not match the non-self-referential projection")

        required_reasons: set[str] = set()
        required_uncertainty: set[str] = set()
        if self.source.code_revision == "UNAVAILABLE":
            required_reasons.add("SOURCE_REVISION_UNAVAILABLE")
            required_uncertainty.add("SOURCE_REVISION_UNAVAILABLE")
        if self.timing.clock_status == "DEGRADED":
            required_reasons.add("SOURCE_CLOCK_DEGRADED")
            required_uncertainty.add("SOURCE_CLOCK_DEGRADED")
        elif self.timing.clock_status == "UNKNOWN":
            required_reasons.add("SOURCE_CLOCK_UNKNOWN")
            required_uncertainty.add("SOURCE_CLOCK_UNKNOWN")
        if not required_reasons.issubset(self.quality.reason_codes):
            raise ValueError("quality reasons do not expose source identity/clock uncertainty")
        if not required_uncertainty.issubset(self.quality.uncertainty_flags):
            raise ValueError("uncertainty flags do not expose source identity/clock uncertainty")
        if required_reasons and self.quality.evidence_status != "QUARANTINED":
            raise ValueError("unavailable source identity or clock health must be quarantined")

        if any(
            value is not None
            for value in (
                self.trace.replay_manifest_ref,
                self.trace.dataset_manifest_ref,
                self.trace.model_manifest_ref,
            )
        ):
            raise ValueError("source export events cannot claim derived WLA manifests")

        payload_time = _payload_occurred_at(self.payload)
        if payload_time != self.timing.occurred_at_utc:
            raise ValueError("payload occurrence time must match timing.occurred_at_utc")
        return self


def _payload_occurred_at(payload: LearningPayloadV1) -> datetime:
    if isinstance(payload, (CanonicalAlphaDecisionFactV1, CanonicalAlphaAbstentionFactV1)):
        return payload.decided_at_utc
    if isinstance(payload, (FillOutcomeEvidenceV1, PartialFillOutcomeEvidenceV1)):
        return payload.filled_at_utc
    if isinstance(payload, RejectOutcomeEvidenceV1):
        return payload.rejected_at_utc
    if isinstance(payload, CancelOutcomeEvidenceV1):
        return payload.cancelled_at_utc
    return payload.observed_at_utc


def _unsigned_envelope_projection(value: AlphaLearningEnvelopeV1 | dict[str, Any]) -> dict[str, Any]:
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else json.loads(json.dumps(value))
    authentication = raw.get("producer_authentication")
    if not isinstance(authentication, dict):
        raise ValueError("unsigned envelope projection requires producer_authentication")
    authentication.pop("signature", None)
    return raw


def _envelope_hash_projection(value: AlphaLearningEnvelopeV1 | dict[str, Any]) -> dict[str, Any]:
    raw = _unsigned_envelope_projection(value)
    integrity = raw.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("envelope hash projection requires integrity")
    integrity.pop("envelope_hash", None)
    return raw


def alpha_learning_envelope_hash(value: AlphaLearningEnvelopeV1 | dict[str, Any]) -> str:
    """Hash the canonical envelope excluding its hash and producer signature."""

    return alpha_learning_sha256(_envelope_hash_projection(value))


def alpha_learning_signature_preimage(value: AlphaLearningEnvelopeV1 | dict[str, Any]) -> bytes:
    """Return the domain-separated bytes covered by the Ed25519 signature."""

    unsigned = _unsigned_envelope_projection(value)
    authentication = unsigned["producer_authentication"]
    if authentication.get("signature_domain") != ALPHA_LEARNING_SIGNATURE_DOMAIN:
        raise ValueError("producer signature domain is not WLA-01")
    return (
        ALPHA_LEARNING_SIGNATURE_DOMAIN.encode("ascii")
        + b"\x00"
        + canonical_alpha_learning_json_bytes(unsigned)
    )


def build_alpha_learning_envelope_v1(
    *,
    event_name: EventName,
    logical_event_key: str,
    correlation_id: UUID,
    causation_id: UUID | None,
    direct_source_refs: tuple[EvidenceRefV1, ...],
    ancestry_manifest: AncestryManifestRefV1 | None,
    stream: StreamPositionV1,
    source: SourceIdentityV1,
    timing: SourceTimingV1,
    quality: QualityV1,
    producer_run_id: UUID,
    producer_key_id: str,
    producer_signature: str,
    payload: LearningPayloadV1,
) -> AlphaLearningEnvelopeV1:
    schema_id, authority_class, _ = _EVENT_SCHEMA[event_name]
    raw: dict[str, Any] = {
        "contract": {
            "envelope_version": ALPHA_LEARNING_ENVELOPE_VERSION,
            "event_name": event_name,
            "event_version": 1,
            "schema_id": schema_id,
        },
        "identity": {
            "event_id": str(
                alpha_learning_event_id(
                    event_name=event_name,
                    event_version=1,
                    source_system=source.source_system,
                    logical_event_key=logical_event_key,
                )
            ),
            "logical_event_key": logical_event_key,
        },
        "causality": {
            "correlation_id": str(correlation_id),
            "causation_id": None if causation_id is None else str(causation_id),
            "direct_source_refs": [item.model_dump(mode="json") for item in direct_source_refs],
            "ancestry_manifest": None if ancestry_manifest is None else ancestry_manifest.model_dump(mode="json"),
        },
        "stream": stream.model_dump(mode="json"),
        "source": source.model_dump(mode="json"),
        "timing": timing.model_dump(mode="json"),
        "authority": {
            "source_authority_class": authority_class,
            "source_interaction_authority": "OBSERVATIONAL_ONLY",
            "wla_decision_authority": "NONE",
            "wla_gate_authority": "NONE",
        },
        "safety": {
            "can_mutate_source": False,
            "can_issue_verdict": False,
            "can_execute": False,
            "can_self_promote": False,
        },
        "producer_authentication": {
            "authentication_version": ALPHA_LEARNING_AUTHENTICATION_VERSION,
            "algorithm": "ED25519",
            "signature_domain": ALPHA_LEARNING_SIGNATURE_DOMAIN,
            "key_id": producer_key_id,
            "producer_role": authority_class,
            "signature": producer_signature,
        },
        "quality": quality.model_dump(mode="json"),
        "trace": {
            "producer_run_id": str(producer_run_id),
            "replay_manifest_ref": None,
            "dataset_manifest_ref": None,
            "model_manifest_ref": None,
        },
        "payload": payload.model_dump(mode="json"),
    }
    raw["integrity"] = {
        "canonicalization_version": ALPHA_LEARNING_CANONICALIZATION_VERSION,
        "payload_hash": alpha_learning_sha256(raw["payload"]),
    }
    raw["integrity"]["envelope_hash"] = alpha_learning_envelope_hash(raw)
    canonical = canonical_alpha_learning_json_bytes(raw)
    if len(canonical) > MAX_CANONICAL_ENVELOPE_BYTES:
        raise ValueError("canonical envelope exceeds the WLA-01 byte limit")
    return AlphaLearningEnvelopeV1.model_validate_json(canonical)


class UntrustedAlphaLearningEnvelopeV1(FrozenLearningContract):
    """Structurally valid bytes with no authenticated provenance claim."""

    trust_status: Literal["UNTRUSTED"]
    envelope: AlphaLearningEnvelopeV1


class AcceptedAlphaLearningEnvelopeV1:
    """An opaque verifier result; direct construction is intentionally blocked."""

    __slots__ = ("_authenticated_key_id", "_authenticated_producer_role", "_envelope")

    def __new__(cls, *_args: Any, **_kwargs: Any) -> AcceptedAlphaLearningEnvelopeV1:
        raise TypeError("ACCEPTED envelopes can only be created by authenticated verification")

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("ACCEPTED envelopes are immutable verifier results")

    @property
    def trust_status(self) -> Literal["ACCEPTED"]:
        return "ACCEPTED"

    @property
    def envelope(self) -> AlphaLearningEnvelopeV1:
        return self._envelope

    @property
    def authenticated_key_id(self) -> str:
        return self._authenticated_key_id

    @property
    def authenticated_producer_role(self) -> SourceAuthorityClass:
        return self._authenticated_producer_role


def _decode_base64url_field(value: str, *, expected_bytes: int, field_name: str) -> bytes:
    if not value.startswith("base64url:"):
        raise ProducerAuthenticationError(f"{field_name} must use the base64url tag")
    encoded = value.removeprefix("base64url:")
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProducerAuthenticationError(f"{field_name} is not canonical base64url") from exc
    if len(decoded) != expected_bytes:
        raise ProducerAuthenticationError(f"{field_name} has the wrong byte length")
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != encoded:
        raise ProducerAuthenticationError(f"{field_name} is not canonical base64url")
    return decoded


def authenticate_alpha_learning_envelope_v1(
    untrusted: UntrustedAlphaLearningEnvelopeV1,
    *,
    key_registry: Mapping[str, ProducerKeyBindingV1],
    known_event_hashes: Mapping[str, str],
) -> AcceptedAlphaLearningEnvelopeV1:
    """Authenticate provenance and return ACCEPTED only after every check passes."""

    if not isinstance(untrusted, UntrustedAlphaLearningEnvelopeV1):
        raise TypeError("authenticated verification requires an UNTRUSTED parser result")
    envelope = untrusted.envelope
    authentication = envelope.producer_authentication
    binding = key_registry.get(authentication.key_id)
    if binding is None:
        raise ProducerAuthenticationError("producer key is not allowlisted")
    if not isinstance(binding, ProducerKeyBindingV1) or binding.key_id != authentication.key_id:
        raise ProducerAuthenticationError("producer key binding is malformed")
    if binding.status != "ACTIVE":
        raise ProducerAuthenticationError("producer key is revoked")
    if binding.algorithm != authentication.algorithm:
        raise ProducerAuthenticationError("producer key algorithm does not match the envelope")
    if (
        binding.signature_domain != ALPHA_LEARNING_SIGNATURE_DOMAIN
        or authentication.signature_domain != ALPHA_LEARNING_SIGNATURE_DOMAIN
    ):
        raise ProducerAuthenticationError("producer key domain does not match WLA-01")
    if binding.source_system != envelope.source.source_system:
        raise ProducerAuthenticationError("producer key is not bound to the claimed source system")
    if binding.source_service != envelope.source.source_service:
        raise ProducerAuthenticationError("producer key is not bound to the claimed source service")
    if (
        binding.producer_role != authentication.producer_role
        or authentication.producer_role != envelope.authority.source_authority_class
    ):
        raise ProducerAuthenticationError("producer key role does not match the event authority")

    public_key_bytes = _decode_base64url_field(
        binding.public_key,
        expected_bytes=32,
        field_name="producer public key",
    )
    signature_bytes = _decode_base64url_field(
        authentication.signature,
        expected_bytes=64,
        field_name="producer signature",
    )
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature_bytes,
            alpha_learning_signature_preimage(envelope),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ProducerAuthenticationError("producer signature is invalid") from exc

    event_id = str(envelope.identity.event_id)
    known_hash = known_event_hashes.get(event_id)
    if known_hash is not None and known_hash != envelope.integrity.envelope_hash:
        raise ProducerAuthenticationError("event_id is already bound to different content")
    accepted = object.__new__(AcceptedAlphaLearningEnvelopeV1)
    object.__setattr__(accepted, "_envelope", envelope)
    object.__setattr__(accepted, "_authenticated_key_id", binding.key_id)
    object.__setattr__(accepted, "_authenticated_producer_role", binding.producer_role)
    return accepted


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def parse_alpha_learning_envelope_v1(raw: bytes | str) -> UntrustedAlphaLearningEnvelopeV1:
    """Parse canonical JSON structurally and label the result UNTRUSTED."""

    if isinstance(raw, str):
        try:
            encoded = raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("learning envelope text is not valid UTF-8") from exc
    else:
        encoded = bytes(raw)
    if not encoded or len(encoded) > MAX_CANONICAL_ENVELOPE_BYTES:
        raise ValueError("learning envelope byte length is outside the WLA-01 limit")
    try:
        text = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("learning envelope bytes are not valid UTF-8") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("learning envelope is not strict JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("learning envelope root must be an object")
    if canonical_alpha_learning_json_bytes(parsed) != encoded:
        raise ValueError("learning envelope bytes are not canonical WLA-01 JSON")
    envelope = AlphaLearningEnvelopeV1.model_validate_json(encoded)
    return UntrustedAlphaLearningEnvelopeV1(trust_status="UNTRUSTED", envelope=envelope)


__all__ = [
    "ALPHA_FACT_EVENT",
    "ALPHA_FACT_SCHEMA_ID",
    "ALPHA_LEARNING_AUTHENTICATION_VERSION",
    "ALPHA_LEARNING_CANONICALIZATION_VERSION",
    "ALPHA_LEARNING_ENVELOPE_VERSION",
    "ALPHA_LEARNING_SIGNATURE_DOMAIN",
    "MAX_CANONICAL_ENVELOPE_BYTES",
    "OUTCOME_EVIDENCE_EVENT",
    "OUTCOME_EVIDENCE_SCHEMA_ID",
    "AcceptedAlphaLearningEnvelopeV1",
    "AlphaLearningEnvelopeV1",
    "AncestryManifestRefV1",
    "CancelOutcomeEvidenceV1",
    "CanonicalAlphaAbstentionFactV1",
    "CanonicalAlphaDecisionFactV1",
    "EvidenceRefV1",
    "FillOutcomeEvidenceV1",
    "HorizonObservationEvidenceV1",
    "PartialFillOutcomeEvidenceV1",
    "ProducerAuthenticationError",
    "ProducerAuthenticationV1",
    "ProducerKeyBindingV1",
    "QualityV1",
    "RejectOutcomeEvidenceV1",
    "SourceIdentityV1",
    "SourceTimingV1",
    "StreamPositionV1",
    "UntrustedAlphaLearningEnvelopeV1",
    "alpha_learning_signature_preimage",
    "authenticate_alpha_learning_envelope_v1",
    "alpha_learning_envelope_hash",
    "alpha_learning_event_id",
    "alpha_learning_sha256",
    "build_alpha_learning_envelope_v1",
    "canonical_alpha_learning_json_bytes",
    "parse_alpha_learning_envelope_v1",
]
