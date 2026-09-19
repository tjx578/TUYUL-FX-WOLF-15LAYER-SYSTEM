"""PressureDirectionalHypothesisV31 (SSOT §10), from BOTH admission classes (requalified on #504, 2026-09-20).

Authority decisions 2026-09-19, updated 2026-09-20:
- H1 (updated): the admission source is the S1B ``StrategyAnalysisAdmissionReceiptV31`` (#504), CANONICAL_RAW or
  MATURE_ADVISORY (§10.2). The superseded #493 PairAdmission receipt is no longer accepted. The admission fields on
  the record (§10.3 names) are PROVENANCE of the originating admission at creation: never identity, never
  direction or execution authority, never mutated on a later authority upgrade. The current effective analysis
  authority is read from ``AnalysisLifecycleV31``.
- H2: maturity comes only from an explicit, hashed ``PressureMaturityPolicyV31``; no defaults.
- H3: admission GRANTED and maturity are two independent gates.
- H4: ``valid_until`` is fixed at creation from ``PressureHypothesisClockPolicyV31`` and never reset; EXPIRED
  is terminal; a later valid condition creates a new hypothesis with a new id.
- H5: immutable record + append-only transitions + one active pointer per lifecycle.

A hypothesis is ANALYSIS_PRIORITY_ONLY: it never carries legal direction, risk, signal or execution
authority. Final direction comes only from the structural proof chain (SSOT §12.6, §14).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_identity_v31 import (
    IDENTITY_ENCODING_VERSION,
    SELECTED_SSOT_HASH,
    canonical_sha256_v31,
    identity_uuid_v31,
)

PRESSURE_HYPOTHESIS_RULE_VERSION = "5scr.pressure-hypothesis.v31.v2"
WOLF15_V31_HYPOTHESIS_NAMESPACE = UUID("1b613f3b-a78d-4a88-9c44-cceab188ea48")

Direction = Literal["BUY", "SELL"]
MaturityStatus = Literal["QUALIFIED", "MATURE", "EXTREME"]
MATURITY_ORDER: dict[str, int] = {"QUALIFIED": 1, "MATURE": 2, "EXTREME": 3}
HypothesisState = Literal[
    "OPEN",
    "CONTEXT_ALIGNED",
    "CONTEXT_CONFLICT",
    "WAITING_VALID_LOCATION",
    "WAITING_PRICE_QUALITY",
    "WAITING_STRUCTURE",
    "INVALIDATED",
    "EXPIRED",
]
TERMINAL_STATES = frozenset({"INVALIDATED", "EXPIRED"})
ContextAlignment = Literal["ALIGNED", "CONFLICT", "UNRESOLVED", "EMPTY"]  # SSOT §28.14
LocationAlignment = Literal["FAVORABLE", "NEUTRAL", "UNFAVORABLE", "UNKNOWN"]
_DIGEST = r"^sha256:[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


class MaturityTierV31(_Strict):
    status: MaturityStatus
    min_duration_seconds: float = Field(ge=0)
    min_effective_ticks: int = Field(ge=0)
    min_direction_stability: float = Field(ge=0, le=1)


class PressureMaturityPolicyV31(_Strict):
    """Every threshold is policy data. The producer holds no numbers of its own."""

    policy_version: str = Field(min_length=3, max_length=120)
    tiers: tuple[MaturityTierV31, ...] = Field(min_length=1)
    minimum_hypothesis_maturity: MaturityStatus
    policy_hash: str = Field(pattern=_DIGEST)

    @staticmethod
    def compute_hash(policy_version: str, tiers: tuple[MaturityTierV31, ...], minimum: str) -> str:
        return canonical_sha256_v31(
            {
                "policy_version": policy_version,
                "tiers": [tier.model_dump(mode="json") for tier in tiers],
                "minimum_hypothesis_maturity": minimum,
            }
        )

    @model_validator(mode="after")
    def _valid(self) -> PressureMaturityPolicyV31:
        statuses = [tier.status for tier in self.tiers]
        if len(set(statuses)) != len(statuses):
            raise ValueError("one tier per maturity status")
        if self.policy_hash != self.compute_hash(self.policy_version, self.tiers, self.minimum_hypothesis_maturity):
            raise ValueError("MATURITY_POLICY_HASH_MISMATCH")
        return self


class PressureHypothesisClockPolicyV31(_Strict):
    clock_policy_version: str = Field(min_length=3, max_length=120)
    ttl_seconds: int = Field(gt=0)
    clock_source: Literal["INJECTED_DECISION_CLOCK"]
    policy_hash: str = Field(pattern=_DIGEST)

    @staticmethod
    def compute_hash(clock_policy_version: str, ttl_seconds: int, clock_source: str) -> str:
        return canonical_sha256_v31(
            {"clock_policy_version": clock_policy_version, "ttl_seconds": ttl_seconds, "clock_source": clock_source}
        )

    @model_validator(mode="after")
    def _valid(self) -> PressureHypothesisClockPolicyV31:
        if self.policy_hash != self.compute_hash(self.clock_policy_version, self.ttl_seconds, self.clock_source):
            raise ValueError("CLOCK_POLICY_HASH_MISMATCH")
        return self


class PressureMaturityEvidenceV31(_Strict):
    """Measured pressure evidence for one symbol. Values only; classification happens against a policy."""

    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    direction: Direction
    duration_seconds: float = Field(ge=0)
    effective_ticks: int = Field(ge=0)
    direction_stability: float = Field(ge=0, le=1)
    source_event_ids: tuple[str, ...] = Field(min_length=1)


def hypothesis_id_v31(*, strategy_lifecycle_id: UUID, direction: str, opening_pressure_evidence_hash: str) -> UUID:
    """Unchanged by the requalification: no admission id or class, so an authority upgrade never forks it."""

    return identity_uuid_v31(
        WOLF15_V31_HYPOTHESIS_NAMESPACE, [str(strategy_lifecycle_id), direction, opening_pressure_evidence_hash]
    )


def opening_pressure_evidence_hash_v31(
    *, canonical_symbol: str, direction: str, source_event_ids: tuple[str, ...]
) -> str:
    """Material identity only: refreshed telemetry with the same source events hashes identically."""

    return canonical_sha256_v31([canonical_symbol, direction, sorted(set(source_event_ids))])


class PressureDirectionalHypothesisV31(_Strict):
    """Immutable record. State lives in the append-only transition log."""

    rule_version: Literal["5scr.pressure-hypothesis.v31.v2"] = PRESSURE_HYPOTHESIS_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"] = (
        SELECTED_SSOT_HASH
    )
    pressure_hypothesis_id: UUID
    canonical_symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    strategy_lifecycle_id: UUID
    # §10.3 admission fields = provenance of the ORIGINATING admission at creation (never identity/authority).
    strategy_analysis_admission_id: UUID
    admission_receipt_hash: str = Field(pattern=_DIGEST)  # StrategyAnalysisAdmissionReceiptV31 (#504)
    analysis_admission_class: Literal["CANONICAL_RAW", "MATURE_ADVISORY"]
    analysis_authority: Literal["FULL_CANONICAL_ANALYSIS", "FULL_SHADOW_ANALYSIS"]
    promotion_eligibility: Literal["CANONICAL_RISK_PATH", "SHADOW_ONLY"]
    risk_handoff_allowed: bool  # §10.3 eligibility cap only; never an authorization
    direction: Direction
    pressure_authority_mode: Literal["RADAR_ONLY", "CONSOLIDATED_DIRECTION_CONTRACT"]
    pressure_contract_status_at_creation: Literal["OPEN", "LOCKED", "TRANSITION_PENDING"]
    pressure_authority_snapshot_hash: str = Field(pattern=_DIGEST)
    pressure_maturity_status: MaturityStatus
    pressure_maturity_policy_version: str
    pressure_maturity_policy_hash: str = Field(pattern=_DIGEST)
    opening_pressure_evidence_hash: str = Field(pattern=_DIGEST)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    valid_from: datetime
    valid_until: datetime
    clock_policy_version: str
    clock_policy_hash: str = Field(pattern=_DIGEST)
    authority: Literal["ANALYSIS_PRIORITY_ONLY"] = "ANALYSIS_PRIORITY_ONLY"
    legal_direction_authority: Literal[False] = False
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> PressureDirectionalHypothesisV31:
        _aware(self.valid_from, self.valid_until)
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must follow valid_from")
        expected = hypothesis_id_v31(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            direction=self.direction,
            opening_pressure_evidence_hash=self.opening_pressure_evidence_hash,
        )
        if self.pressure_hypothesis_id != expected:
            raise ValueError("HYPOTHESIS_ID_NOT_DERIVED")
        scope = (self.analysis_authority, self.promotion_eligibility, self.risk_handoff_allowed)
        if self.analysis_admission_class == "MATURE_ADVISORY":
            if scope != ("FULL_SHADOW_ANALYSIS", "SHADOW_ONLY", False):  # §10.3 invariant
                raise ValueError(
                    "MATURE_ADVISORY hypothesis must be FULL_SHADOW_ANALYSIS / SHADOW_ONLY / no risk handoff"
                )
            if self.pressure_maturity_status not in {"MATURE", "EXTREME"}:  # §10.2 advisory path
                raise ValueError("MATURE_ADVISORY hypothesis requires MATURE or EXTREME advisory maturity")
        elif scope[:2] != ("FULL_CANONICAL_ANALYSIS", "CANONICAL_RISK_PATH"):
            raise ValueError("CANONICAL_RAW hypothesis scope mismatch")
        return self


def hypothesis_record_hash_v31(record: PressureDirectionalHypothesisV31) -> str:
    return canonical_sha256_v31(record.model_dump(mode="json"))


class PressureHypothesisTransitionV31(_Strict):
    pressure_hypothesis_id: UUID
    sequence: int = Field(ge=1)
    from_state: HypothesisState
    to_state: HypothesisState
    context_alignment: ContextAlignment
    location_alignment: LocationAlignment
    classification: Literal["COUNTER_PRESSURE_PENDING_PROOF"] | None
    reason_code: str = Field(min_length=3, max_length=200)
    material_event_id: str = Field(min_length=1, max_length=240)
    material_event_hash: str = Field(pattern=_DIGEST)
    occurred_at: datetime
    previous_transition_hash: str | None
    transition_hash: str = Field(pattern=_DIGEST)

    @staticmethod
    def compute_hash(payload: dict[str, object]) -> str:
        return canonical_sha256_v31({key: value for key, value in payload.items() if key != "transition_hash"})

    @model_validator(mode="after")
    def _chained(self) -> PressureHypothesisTransitionV31:
        _aware(self.occurred_at)
        if self.from_state in TERMINAL_STATES:
            raise ValueError("TERMINAL_HYPOTHESIS_CANNOT_TRANSITION")
        if (self.to_state == "CONTEXT_CONFLICT") != (self.classification == "COUNTER_PRESSURE_PENDING_PROOF"):
            raise ValueError("CONTEXT_CONFLICT is exactly COUNTER_PRESSURE_PENDING_PROOF")
        if self.to_state == "CONTEXT_CONFLICT" and self.context_alignment != "CONFLICT":
            raise ValueError("CONTEXT_CONFLICT requires context_alignment=CONFLICT")
        if self.to_state == "CONTEXT_ALIGNED" and self.context_alignment != "ALIGNED":
            raise ValueError("CONTEXT_ALIGNED requires context_alignment=ALIGNED")
        if self.to_state == "WAITING_VALID_LOCATION" and self.location_alignment not in {"UNFAVORABLE", "UNKNOWN"}:
            raise ValueError("WAITING_VALID_LOCATION requires an unusable location")
        if self.to_state == "OPEN":
            raise ValueError("OPEN is only the creation state")
        if self.transition_hash != self.compute_hash(self.model_dump(mode="json")):
            raise ValueError("TRANSITION_HASH_MISMATCH")
        return self


class PressureHypothesisStoreV31(Protocol):
    """Durability contract for a future repository (no migration in this increment).

    - ``insert_record`` is insert-once: an existing id with different bytes is a conflict.
    - ``append_transition`` is append-only with a strict ``sequence``/hash chain.
    - ``swap_active`` is a compare-and-set on ONE active pointer per lifecycle.
    """

    def get_record(self, pressure_hypothesis_id: UUID) -> PressureDirectionalHypothesisV31 | None: ...

    def insert_record(self, record: PressureDirectionalHypothesisV31) -> None: ...

    def transitions(self, pressure_hypothesis_id: UUID) -> tuple[PressureHypothesisTransitionV31, ...]: ...

    def append_transition(self, transition: PressureHypothesisTransitionV31) -> None: ...

    def active(self, strategy_lifecycle_id: UUID) -> UUID | None: ...

    def swap_active(self, strategy_lifecycle_id: UUID, *, expected: UUID | None, new: UUID | None) -> None: ...


__all__ = [
    "PRESSURE_HYPOTHESIS_RULE_VERSION",
    "TERMINAL_STATES",
    "WOLF15_V31_HYPOTHESIS_NAMESPACE",
    "MaturityTierV31",
    "PressureDirectionalHypothesisV31",
    "PressureHypothesisClockPolicyV31",
    "PressureHypothesisStoreV31",
    "PressureHypothesisTransitionV31",
    "PressureMaturityEvidenceV31",
    "PressureMaturityPolicyV31",
    "canonical_sha256_v31",
    "hypothesis_id_v31",
    "hypothesis_record_hash_v31",
    "opening_pressure_evidence_hash_v31",
]
