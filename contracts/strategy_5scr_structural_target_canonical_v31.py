"""Canonical StructuralTarget V31 adapter contract.

Authority: SSOT v3.1 §17 + amendment A2-01 … A2-07 (all APPROVED_PER_ENTRY, runtime_activation EXPLICIT_ONLY).
Owner GO 2026-09-21: "existing StructuralTargetV31 + existing target machinery → canonical adapter", no rewrite.

`StructuralTargetV31` is reused unchanged as the data record. This module adds only what the 12B audit found
missing: a derived, deterministic `target_id`, source-policy freshness (`freshness_status`, `tested_count`, policy
provenance), completion/consumption evidence, source invalidation evidence and bar lineage.

The legacy selector (`analysis/strategy_5scr_target_selection_v31.py`) stays a LEGACY / NON-CANONICAL path: it
treats `valid_until` as freshness (forbidden by A2-03) and calls the net-geometry solver (final geometry, T10).

Nothing here holds risk, execution or ExecutionBox authority. PressureRange is read-only context and never an
eligibility predicate.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_identity_v31 import identity_uuid_v31
from contracts.strategy_5scr_net_geometry_v31 import Price
from contracts.strategy_5scr_pressure_range_v31 import PressureRangeV31
from contracts.strategy_5scr_target_selection_v31 import StructuralTargetV31, TargetSource

V31_STRUCTURAL_TARGET_NAMESPACE = UUID("aa830080-a9cf-4699-a9e7-46bbc8e5e0f2")
STRUCTURAL_TARGET_IDENTITY_DERIVATION_VERSION = "5scr.structural-target-identity.v31.v1"

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"
_Digest = Annotated[str, Field(pattern=_DIGEST)]

Direction = Literal["BUY", "SELL"]
Timeframe = Literal["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
FreshnessStatus = Literal["FRESH", "NOT_FRESH"]
StructuralBasis = Literal["STRUCTURAL", "NON_STRUCTURAL"]
TargetAuthority = Literal["AUTHORITATIVE", "NON_AUTHORITATIVE"]

# A2-05: the closed eligibility surface, in the order the amendment lists it. `nearest` is not a member.
TargetPredicate = Literal[
    "STRUCTURAL",
    "AUTHORITATIVE",
    "IN_THESIS_DIRECTION",
    "FRESH",
    "UNCONSUMED",
    "NOT_PASSED_AT_DECISION_TIME",
]
ELIGIBILITY_PREDICATES_V31: tuple[TargetPredicate, ...] = (
    "STRUCTURAL",
    "AUTHORITATIVE",
    "IN_THESIS_DIRECTION",
    "FRESH",
    "UNCONSUMED",
    "NOT_PASSED_AT_DECISION_TIME",
)

# A2-07: closed vocabulary, highest-semantic cause first.
TargetRevisionFact = Literal[
    "TARGET_INVALIDATED",
    "TARGET_NO_LONGER_ELIGIBLE",
    "TARGET_MATERIAL_CHANGE",
    "TARGET_UNCHANGED",
]
REVISION_FACT_PRECEDENCE_V31: tuple[TargetRevisionFact, ...] = (
    "TARGET_INVALIDATED",
    "TARGET_NO_LONGER_ELIGIBLE",
    "TARGET_MATERIAL_CHANGE",
    "TARGET_UNCHANGED",
)

# Implementation design (A2-07 fixes no list): the StructuralTargetV31 fields that downstream geometry reads.
TARGET_MATERIAL_FIELDS_V31: tuple[str, ...] = ("price", "evidence_hash")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _aware(*values: datetime | None) -> None:
    if any(v is not None and (v.tzinfo is None or v.utcoffset() is None) for v in values):
        raise ValueError("STRUCTURAL_TARGET_CLOCK_NOT_TIMEZONE_AWARE")


def structural_target_id_v31(
    *,
    canonical_symbol: str,
    source: TargetSource,
    source_timeframe: Timeframe,
    thesis_direction: Direction,
    structural_anchor_id: str,
) -> UUID:
    """A2-06 identity: stable, deterministic, collision-safe, free of runtime randomness.

    UUIDv5[derivation version, symbol, source, timeframe, thesis direction, structural anchor]. Deliberately
    excluded: price and evidence_hash (material — A2-07 case A revises them under the same id), formed_at
    (A2-06), valid_until, freshness, tested_count, consumption, invalidation, authority, and anything from a
    deployment, worker, request, broker quote or iteration order. It is identity, never proof: the evidence lives
    in `evidence_hash` and `source_bar_ids`.
    """

    return identity_uuid_v31(
        V31_STRUCTURAL_TARGET_NAMESPACE,
        [
            STRUCTURAL_TARGET_IDENTITY_DERIVATION_VERSION,
            canonical_symbol,
            source,
            source_timeframe,
            thesis_direction,
            structural_anchor_id,
        ],
    )


class SourcePolicyRefV31(_Strict):
    """A2-03 / A2-04: every freshness or completion verdict names the explicit, versioned source policy."""

    policy_id: str = Field(min_length=1, max_length=120)
    policy_version: str = Field(min_length=1, max_length=60)
    policy_hash: str = Field(pattern=_DIGEST)


class CanonicalStructuralTargetV31(_Strict):
    """One canonical target candidate: the reused `StructuralTargetV31` plus its canonical provenance."""

    derivation_version: Literal["5scr.structural-target-identity.v31.v1"] = (
        STRUCTURAL_TARGET_IDENTITY_DERIVATION_VERSION
    )
    canonical_symbol: str = Field(pattern=_SYMBOL)
    thesis_direction: Direction
    source_timeframe: Timeframe
    structural_anchor_id: str = Field(pattern=_DIGEST)
    source_bar_ids: tuple[_Digest, ...] = Field(min_length=1, max_length=10000)
    target: StructuralTargetV31
    structural_basis: StructuralBasis
    authority: TargetAuthority
    freshness_status: FreshnessStatus
    tested_count: int = Field(ge=0)
    freshness_policy: SourcePolicyRefV31
    completion_policy: SourcePolicyRefV31 | None  # None: the source has no completion rule, so it cannot consume
    completion_evidence_hash: _Digest | None
    invalidated_at: datetime | None
    invalidation_evidence_hash: _Digest | None
    observed_through_utc: datetime
    # A2-03: kept for legacy/cache use only; never read by the canonical selector.
    valid_until_semantics: Literal["NON_CANONICAL_ADVISORY_ONLY"] = "NON_CANONICAL_ADVISORY_ONLY"

    @model_validator(mode="after")
    def _canonical(self) -> CanonicalStructuralTargetV31:
        target = self.target
        _aware(self.invalidated_at, self.observed_through_utc)
        expected = structural_target_id_v31(
            canonical_symbol=self.canonical_symbol,
            source=target.source,
            source_timeframe=self.source_timeframe,
            thesis_direction=self.thesis_direction,
            structural_anchor_id=self.structural_anchor_id,
        )
        if target.target_id != str(expected):
            raise ValueError("STRUCTURAL_TARGET_ID_NOT_DERIVED")
        if self.source_bar_ids != tuple(sorted(set(self.source_bar_ids))):
            raise ValueError("STRUCTURAL_TARGET_SOURCE_BARS_NOT_SORTED_UNIQUE")
        if (target.consumed_at is None) != (self.completion_evidence_hash is None):
            raise ValueError("CONSUMPTION_REQUIRES_COMPLETION_EVIDENCE")
        if target.consumed_at is not None and self.completion_policy is None:
            raise ValueError("TARGET_WITHOUT_COMPLETION_RULE_CANNOT_BE_CONSUMED")
        if (self.invalidated_at is None) != (self.invalidation_evidence_hash is None):
            raise ValueError("INVALIDATION_REQUIRES_SOURCE_EVIDENCE")
        if self.invalidated_at is not None and self.invalidated_at < target.formed_at:
            raise ValueError("INVALIDATION_BEFORE_FORMATION")
        clocks = (target.formed_at, target.consumed_at, self.invalidated_at)
        if any(t is not None and t > self.observed_through_utc for t in clocks):
            raise ValueError("STRUCTURAL_TARGET_STATE_AFTER_OBSERVATION")
        return self


class DecisionPriceV31(_Strict):
    """A2-02 origin: the latest authoritative, non-future strategy-side closed price at decision_time.

    The origin literal admits nothing else: a live broker bid/ask, a future candle, a fill price, a route-derived
    entry or an RR-chosen reference cannot be expressed here.
    """

    canonical_symbol: str = Field(pattern=_SYMBOL)
    origin: Literal["STRATEGY_CLOSED_PRICE_AUTHORITY"]
    price: Price
    observed_at: datetime
    evidence_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _clock(self) -> DecisionPriceV31:
        _aware(self.observed_at)
        return self


class StructuralTargetSelectionRequestV31(_Strict):
    canonical_symbol: str = Field(pattern=_SYMBOL)
    strategy_thesis_id: UUID
    thesis_direction: Direction
    decision_time: datetime
    decision_price: DecisionPriceV31
    candidates: tuple[CanonicalStructuralTargetV31, ...] = Field(max_length=10000)
    # Upstream read-only context (12B #7). Never an eligibility predicate, never written back.
    pressure_range: PressureRangeV31 | None

    @model_validator(mode="after")
    def _clock(self) -> StructuralTargetSelectionRequestV31:
        _aware(self.decision_time)
        return self


class TargetEligibilityV31(_Strict):
    target_id: str
    failed_predicates: tuple[TargetPredicate, ...]


class StructuralTargetSelectionV31(_Strict):
    canonical_symbol: str
    strategy_thesis_id: UUID
    thesis_direction: Direction
    decision_time: datetime
    decision_price_evidence_hash: str
    pressure_range_id: UUID | None
    candidates_hash: str
    status: Literal["SELECTED", "NO_ELIGIBLE_TARGET", "REJECTED"]
    reason: str
    selected_target: StructuralTargetV31 | None
    selected_directional_distance: Decimal | None
    eligibility: tuple[TargetEligibilityV31, ...]
    geometry_solved: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False


class TargetInteractionV31(_Strict):
    """A2-04: TEST is interaction without completion; COMPLETION is the source policy's completion verdict."""

    target_id: str
    kind: Literal["TEST", "COMPLETION"]
    observed_at: datetime
    evidence_hash: str = Field(pattern=_DIGEST)
    authority: TargetAuthority
    policy: SourcePolicyRefV31
    freshness_status_after: FreshnessStatus  # the source policy's verdict; the adapter never derives it

    @model_validator(mode="after")
    def _clock(self) -> TargetInteractionV31:
        _aware(self.observed_at)
        return self


class TargetRevisionV31(_Strict):
    previous_target_id: str
    current_selected_target_id: str | None
    fact: TargetRevisionFact
    failed_predicates: tuple[TargetPredicate, ...]
    material_fields_changed: tuple[str, ...]


class LegacyTargetLevelV31(_Strict):
    """A bare runtime-wired float (`key_support`, `major_resistance`, …). Kept, never promoted."""

    label: str = Field(min_length=1, max_length=80)
    value: float
    conformance: Literal["NONCONFORMANT_LEGACY"] = "NONCONFORMANT_LEGACY"
    structural_authority: Literal[False] = False


__all__ = [
    "ELIGIBILITY_PREDICATES_V31",
    "REVISION_FACT_PRECEDENCE_V31",
    "STRUCTURAL_TARGET_IDENTITY_DERIVATION_VERSION",
    "TARGET_MATERIAL_FIELDS_V31",
    "V31_STRUCTURAL_TARGET_NAMESPACE",
    "CanonicalStructuralTargetV31",
    "DecisionPriceV31",
    "LegacyTargetLevelV31",
    "SourcePolicyRefV31",
    "StructuralTargetSelectionRequestV31",
    "StructuralTargetSelectionV31",
    "TargetEligibilityV31",
    "TargetInteractionV31",
    "TargetPredicate",
    "TargetRevisionFact",
    "TargetRevisionV31",
    "structural_target_id_v31",
]
