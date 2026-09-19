"""DirectionalThesisV31: the first object that may hold direction authority (gap #11, owner D1–D9, 2026-09-19).

SSOT §2.2/§12.6: direction becomes legal only after an authoritative ContextEpoch, the legal direction domain and a
full H1/M15 proof authorize it. SSOT §28.16 lets the thesis exist before that proof (PENDING_*), so existence and
authority are separate:

- D1: ``direction_authority`` is DERIVED from state; true only in STRUCTURALLY_CONFIRMED | GEOMETRY_PENDING. It is
  never execution authority.
- D2: birth at PENDING_H1; an atomic #497 proof binds directly to STRUCTURALLY_CONFIRMED. PENDING_M15 is reserved;
  DORMANT/PENDING_CONTEXT are unreachable (CONFLICT/NDA); GEOMETRY_PENDING is entered by gap #12 only.
- D3: identity = UUIDv5 over [encoding, lifecycle, epoch, direction, thesis_class, route, hypothesis]. No proof id
  (§19.4: one thesis, many triggers), no timestamps.
- D6/H5 pattern: immutable record + append-only hash-chained transitions + one active pointer per lifecycle.
- D7: own explicit clock; ``valid_until`` is immutable and never later than the context epoch deadline.
- D9: route → thesis_class only through a hashed registry.

The thesis binds evidence by reference and never re-runs H1/M15 predicates. It has no entry, SL, TP, RR, volume,
spread, margin, broker or command field. Projection to ``OrderedProofEvidenceV31`` is deferred (D8).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_admission_identity_v31 import IDENTITY_ENCODING_VERSION, SELECTED_SSOT_HASH
from contracts.strategy_5scr_pressure_hypothesis_v31 import canonical_sha256_v31

DIRECTIONAL_THESIS_V31_RULE_VERSION = "5scr.directional-thesis.v31.v1"
V31_THESIS_NAMESPACE = UUID("24ba330a-a439-44cb-8bd6-da026633720c")

Direction = Literal["BUY", "SELL"]
ThesisClass = Literal["CONTINUATION", "COUNTER_PRESSURE", "RANGE_FADE", "BREAKOUT", "REVERSAL_NEW_EPISODE"]
ThesisState = Literal[  # SSOT §28.16, verbatim
    "DORMANT",
    "PENDING_CONTEXT",
    "PENDING_H1",
    "PENDING_M15",
    "STRUCTURALLY_CONFIRMED",
    "GEOMETRY_PENDING",
    "INVALIDATED",
    "SUPERSEDED",
    "EXPIRED",
]
AUTHORITATIVE_STATES = frozenset({"STRUCTURALLY_CONFIRMED", "GEOMETRY_PENDING"})
TERMINAL_STATES = frozenset({"INVALIDATED", "SUPERSEDED", "EXPIRED"})
CREATION_STATE = "PENDING_H1"
# Transitions this increment may emit. GEOMETRY_PENDING belongs to gap #12; PENDING_M15 is reserved (D2).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING_H1": frozenset({"STRUCTURALLY_CONFIRMED", "INVALIDATED", "SUPERSEDED", "EXPIRED"}),
    "STRUCTURALLY_CONFIRMED": frozenset({"INVALIDATED", "SUPERSEDED", "EXPIRED"}),
}
TransitionReason = Literal[
    "STRUCTURAL_PROOF_BOUND",
    "THESIS_INVALIDATED",  # SSOT §21.5
    "THESIS_SUPERSEDED",  # SSOT §21.5
    "THESIS_CLOCK_EXPIRED",
    "CONTEXT_EPOCH_EXPIRED",
]
_REASONS_BY_TARGET: dict[str, frozenset[str]] = {
    "STRUCTURALLY_CONFIRMED": frozenset({"STRUCTURAL_PROOF_BOUND"}),
    "INVALIDATED": frozenset({"THESIS_INVALIDATED"}),
    "SUPERSEDED": frozenset({"THESIS_SUPERSEDED"}),
    "EXPIRED": frozenset({"THESIS_CLOCK_EXPIRED", "CONTEXT_EPOCH_EXPIRED"}),
}
_DIGEST = r"^sha256:[0-9a-f]{64}$"


def direction_authority_v31(state: str) -> bool:
    """D1: the ONLY source of direction authority. Derived, never stored as a free flag."""

    return state in AUTHORITATIVE_STATES


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


def _payload_hash(model: BaseModel, hash_field: str) -> str:
    return canonical_sha256_v31({k: v for k, v in model.model_dump(mode="json").items() if k != hash_field})


class RouteThesisClassV31(_Strict):
    route: str = Field(min_length=1, max_length=160)
    thesis_class: ThesisClass


class ThesisClassRegistryV31(_Strict):
    """D9: route → thesis_class is policy data. A missing route is THESIS_CLASS_MAPPING_MISSING, never inferred."""

    registry_version: str = Field(min_length=3, max_length=120)
    mappings: tuple[RouteThesisClassV31, ...] = Field(min_length=1)
    registry_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> ThesisClassRegistryV31:
        if len({m.route for m in self.mappings}) != len(self.mappings):
            raise ValueError("one thesis_class per route")
        if self.registry_hash != _payload_hash(self, "registry_hash"):
            raise ValueError("THESIS_CLASS_REGISTRY_HASH_MISMATCH")
        return self

    def thesis_class(self, route: str) -> str | None:
        return next((m.thesis_class for m in self.mappings if m.route == route), None)


class ThesisClockPolicyV31(_Strict):
    """D7: explicit, versioned, hashed; no default TTL anywhere."""

    clock_policy_version: str = Field(min_length=3, max_length=120)
    ttl_seconds: int = Field(gt=0)
    clock_source: Literal["INJECTED_DECISION_CLOCK"]
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> ThesisClockPolicyV31:
        if self.policy_hash != _payload_hash(self, "policy_hash"):
            raise ValueError("THESIS_CLOCK_POLICY_HASH_MISMATCH")
        return self


class StructuralProofActionabilityPolicyV31(_Strict):
    """D5: is an immutable proof ACTIONABLE for thesis binding? Named predicates only; the proof is never edited.

    - coverage: the closed H1/M15 candles after the proof must be contiguous through the decision time, so that
      "no later invalidating evidence" is proven, not assumed from a gap;
    - h1: a later adjacent H1 pair whose confirmation closes beyond the anchor extreme AGAINST the proof direction;
    - m15: a later M15 close back through the proof's M15 break level.
    """

    policy_version: str = Field(min_length=3, max_length=120)
    coverage_rule: Literal["CONTIGUOUS_CLOSED_CANDLES_THROUGH_DECISION"]
    h1_invalidation_rule: Literal["ADJACENT_COUNTER_BREAK_CLOSE_BEYOND_ANCHOR_EXTREME"]
    m15_invalidation_rule: Literal["CLOSE_BACK_THROUGH_BREAK_LEVEL"]
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> StructuralProofActionabilityPolicyV31:
        if self.policy_hash != _payload_hash(self, "policy_hash"):
            raise ValueError("PROOF_ACTIONABILITY_POLICY_HASH_MISMATCH")
        return self


def thesis_id_v31(
    *,
    strategy_lifecycle_id: UUID,
    context_epoch_id: UUID,
    direction: str,
    thesis_class: str,
    selected_route: str,
    pressure_hypothesis_id: UUID,
) -> UUID:
    """D3: no proof id, no evaluation/validity time, no row id."""

    name = json.dumps(
        [
            IDENTITY_ENCODING_VERSION,
            str(strategy_lifecycle_id),
            str(context_epoch_id),
            direction,
            thesis_class,
            selected_route,
            str(pressure_hypothesis_id),
        ],
        separators=(",", ":"),
    )
    return uuid5(V31_THESIS_NAMESPACE, name)


class DirectionalThesisV31(_Strict):
    """Immutable record (SSOT §14.2, §25 "0 mutable DirectionalThesis"). State lives in the transition log."""

    rule_version: Literal["5scr.directional-thesis.v31.v1"] = DIRECTIONAL_THESIS_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"] = (
        SELECTED_SSOT_HASH
    )
    strategy_thesis_id: UUID
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    strategy_lifecycle_id: UUID
    strategy_analysis_admission_id: UUID
    admission_receipt_hash: str = Field(pattern=_DIGEST)
    # §14.1 inheritance. MATURE_ADVISORY is NOT_IMPLEMENTED_BY_DESIGN (follows hypothesis decision H1).
    analysis_admission_class: Literal["CANONICAL_RAW"]
    promotion_eligibility: Literal["CANONICAL_RISK_PATH"]
    risk_handoff_allowed: bool  # §14.2 eligibility cap inherited from the hypothesis; never an authorization
    pressure_hypothesis_id: UUID
    hypothesis_record_hash: str = Field(pattern=_DIGEST)
    pressure_authority_mode: Literal["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"]
    pressure_contract_status_at_creation: Literal["OPEN", "LOCKED", "TRANSITION_PENDING"]
    context_epoch_id: UUID
    material_context_hash: str = Field(pattern=_DIGEST)
    context_epoch_valid_until: datetime
    context_route_evaluation_id: UUID
    context_route_evaluation_hash: str = Field(pattern=_DIGEST)
    context_route_receipt_hash: str = Field(pattern=_DIGEST)
    direction: Direction
    direction_immutable: Literal[True] = True
    thesis_class: Literal["CONTINUATION"]  # other §14.2 classes: NOT_IMPLEMENTED_BY_DESIGN in this increment
    thesis_class_registry_version: str
    thesis_class_registry_hash: str = Field(pattern=_DIGEST)
    selected_route: str = Field(min_length=1, max_length=160)
    created_at_decision_time: datetime
    valid_from: datetime
    valid_until: datetime
    valid_until_bound: Literal["THESIS_CLOCK_TTL", "CONTEXT_EPOCH_DEADLINE"]
    clock_ttl_seconds: int = Field(gt=0)
    clock_policy_version: str
    clock_policy_hash: str = Field(pattern=_DIGEST)
    authority: Literal["DIRECTIONAL_THESIS_ONLY"] = "DIRECTIONAL_THESIS_ONLY"
    execution_authority: Literal[False] = False
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> DirectionalThesisV31:
        _aware(self.context_epoch_valid_until, self.created_at_decision_time, self.valid_from, self.valid_until)
        expected = thesis_id_v31(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            context_epoch_id=self.context_epoch_id,
            direction=self.direction,
            thesis_class=self.thesis_class,
            selected_route=self.selected_route,
            pressure_hypothesis_id=self.pressure_hypothesis_id,
        )
        if self.strategy_thesis_id != expected:
            raise ValueError("THESIS_ID_NOT_DERIVED")
        if self.valid_from != self.created_at_decision_time:
            raise ValueError("THESIS_CLOCK_STARTS_AT_CREATION")
        ttl_deadline = self.valid_from + timedelta(seconds=self.clock_ttl_seconds)
        bounded = min(ttl_deadline, self.context_epoch_valid_until)
        label = "THESIS_CLOCK_TTL" if ttl_deadline <= self.context_epoch_valid_until else "CONTEXT_EPOCH_DEADLINE"
        if (self.valid_until, self.valid_until_bound) != (bounded, label):
            raise ValueError("THESIS_VALID_UNTIL_NOT_DERIVED")
        if not self.valid_from < self.valid_until <= self.context_epoch_valid_until:
            raise ValueError("THESIS_CLOCK_OUTSIDE_CONTEXT_EPOCH")
        return self


def thesis_record_hash_v31(record: DirectionalThesisV31) -> str:
    return canonical_sha256_v31(record.model_dump(mode="json"))


class DirectionalThesisTransitionV31(_Strict):
    strategy_thesis_id: UUID
    sequence: int = Field(ge=1)
    from_state: ThesisState
    to_state: ThesisState
    reason_code: TransitionReason
    bound_structural_proof_id: UUID | None
    bound_structural_proof_hash: str | None = Field(pattern=_DIGEST)
    actionability_policy_version: str | None
    actionability_policy_hash: str | None = Field(pattern=_DIGEST)
    resolution_evidence_hash: str | None = Field(pattern=_DIGEST)  # §14.2, set on the binding step only
    material_event_id: str = Field(min_length=1, max_length=240)
    material_event_hash: str = Field(pattern=_DIGEST)
    occurred_at: datetime
    previous_transition_hash: str | None
    transition_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _chained(self) -> DirectionalThesisTransitionV31:
        _aware(self.occurred_at)
        if self.from_state in TERMINAL_STATES:
            raise ValueError("TERMINAL_THESIS_CANNOT_TRANSITION")
        if self.to_state not in ALLOWED_TRANSITIONS.get(self.from_state, frozenset()):
            raise ValueError("THESIS_TRANSITION_NOT_PERMITTED")
        if self.reason_code not in _REASONS_BY_TARGET[self.to_state]:
            raise ValueError("THESIS_TRANSITION_REASON_MISMATCH")
        binding = (
            self.bound_structural_proof_id,
            self.bound_structural_proof_hash,
            self.actionability_policy_version,
            self.actionability_policy_hash,
            self.resolution_evidence_hash,
        )
        if self.to_state == "STRUCTURALLY_CONFIRMED":
            if any(value is None for value in binding):
                raise ValueError("CONFIRMATION_REQUIRES_COMPLETE_PROOF_BINDING")
        elif any(value is not None for value in binding):
            raise ValueError("PROOF_BINDING_ONLY_ON_CONFIRMATION")
        if self.transition_hash != _payload_hash(self, "transition_hash"):
            raise ValueError("THESIS_TRANSITION_HASH_MISMATCH")
        return self


class DirectionalThesisStatusV31(_Strict):
    """Read view in the owner's shape: state + DERIVED direction authority + the proof bound on confirmation."""

    strategy_thesis_id: UUID
    state: ThesisState
    direction: Direction
    direction_authority: bool
    bound_structural_proof_id: UUID | None
    bound_structural_proof_hash: str | None = Field(pattern=_DIGEST)
    execution_authority: Literal[False] = False
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _derived(self) -> DirectionalThesisStatusV31:
        if self.direction_authority != direction_authority_v31(self.state):
            raise ValueError("DIRECTION_AUTHORITY_IS_DERIVED_FROM_STATE")
        if self.direction_authority and self.bound_structural_proof_id is None:
            raise ValueError("AUTHORITATIVE_THESIS_REQUIRES_BOUND_PROOF")
        if (self.bound_structural_proof_id is None) != (self.bound_structural_proof_hash is None):
            raise ValueError("bound proof id and hash come together")
        return self


class DirectionalThesisStoreV31(Protocol):
    """Durability contract for a future repository (no migration in this increment).

    Insert-once records, append-only hash-chained transitions, ONE active pointer per lifecycle (compare-and-set).
    """

    def get_record(self, strategy_thesis_id: UUID) -> DirectionalThesisV31 | None: ...

    def insert_record(self, record: DirectionalThesisV31) -> None: ...

    def transitions(self, strategy_thesis_id: UUID) -> tuple[DirectionalThesisTransitionV31, ...]: ...

    def append_transition(self, transition: DirectionalThesisTransitionV31) -> None: ...

    def active(self, strategy_lifecycle_id: UUID) -> UUID | None: ...

    def swap_active(self, strategy_lifecycle_id: UUID, *, expected: UUID | None, new: UUID | None) -> None: ...


__all__ = [
    "ALLOWED_TRANSITIONS",
    "AUTHORITATIVE_STATES",
    "CREATION_STATE",
    "DIRECTIONAL_THESIS_V31_RULE_VERSION",
    "TERMINAL_STATES",
    "V31_THESIS_NAMESPACE",
    "DirectionalThesisStatusV31",
    "DirectionalThesisStoreV31",
    "DirectionalThesisTransitionV31",
    "DirectionalThesisV31",
    "RouteThesisClassV31",
    "StructuralProofActionabilityPolicyV31",
    "ThesisClassRegistryV31",
    "ThesisClockPolicyV31",
    "direction_authority_v31",
    "thesis_id_v31",
    "thesis_record_hash_v31",
]
