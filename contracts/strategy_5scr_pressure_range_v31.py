"""PressureRangeV31: the material observed price range of one pressure episode (SSOT §16.2 + A1-09…A1-12).

Effective authority for this object is **SSOT v3.1 (6daea387…a83902) + the approved amendment entries
A1-09 … A1-12 only**. A1-01 … A1-08 are PENDING and grant nothing here.

§16.1 calls it "material **observed** price range selama pressure episode", so it is bound to observed-price
authority (§2.4 `reference price ≠ observed price ≠ execution price`) and scoped to the lifecycle/episode —
never to a thesis, never to a route, never to a direction.

What the amendment fixed, and this module implements verbatim:

- A1-09 window: the **MarketEpisode close is the sole closure authority**. Lifecycle supersession does not
  close it; raw-block termination alone does not close it; a closed range never reopens; late evidence is
  appended while open and becomes a permanent gap after closure.
- A1-10 derivation: the qualifying-observation universe is decided **first**, then `low`/`high` are the min/max
  of the qualifying **wicks**. An empty qualifying set gives `null` bounds and `MISSING` — never `0`, never a
  fabricated point range. `source_price_ids` is period-aligned: one entry per expected canonical period.
- A1-11 coverage: threshold-free set completeness. No ratio, no magic number. The four §16.2 values only.
- A1-12 change classification: three classes over an explicit field partition.

The object holds no authority of any kind: no direction, no route, no target, no entry/SL/TP, no RR, no lot, no
broker field, no admission class. Containment travels beside it (the #497/#499 pattern), never inside it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_identity_v31 import (
    IDENTITY_ENCODING_VERSION,
    SELECTED_SSOT_HASH,
    canonical_sha256_v31,
    identity_uuid_v31,
)
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31

PRESSURE_RANGE_V31_RULE_VERSION = "5scr.pressure-range.v31.v1"
# G1 GAP_FILL (Route 2): the derivation of pressure_range_id is an implementation decision, so it is versioned.
PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION = "v31.pressure-range-identity.v1"
V31_PRESSURE_RANGE_NAMESPACE = UUID("3f2b6d41-6f2a-4c0e-9a3e-7b1c5d8e2f04")

_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"

# A1-09: the canonical window anchor is a DERIVATION LABEL, never an admission class and never an authority.
CoverageAnchorRule = Literal["RAW_BLOCK_START", "FIRST_RETAINED_ADVISORY_EVENT"]
# §16.2, verbatim and closed. DEGRADED and UNAVAILABLE do not exist; STALE lives on other axes (§11.3).
PriceCoverageStatus = Literal["COMPLETE", "PARTIAL", "MISSING", "QUARANTINED"]
# §11.5 candle-quality ladder. Only AUTHORITATIVE qualifies (A1-10 clauses 2 and 3).
PeriodEvidenceQuality = Literal["AUTHORITATIVE", "UNKNOWN", "FORMING", "INCOMPLETE", "QUARANTINED"]

# A1-12 field partition. These three sets ARE the change classification; there is no material hash (G8).
GEOMETRY_MATERIAL_FIELDS = ("started_at", "ended_at", "coverage_anchor_rule", "low", "high")
COVERAGE_FIELDS = ("price_coverage_status", "coverage_gaps")
EVIDENCE_FIELDS = ("source_price_ids", "observed_through_utc")
PressureRangeChange = Literal["MATERIAL_RANGE_CHANGE", "COVERAGE_CHANGE", "EVIDENCE_REFRESH", "NO_MATERIAL_CHANGE"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


class CanonicalPeriodPriceEvidenceV31(_Strict):
    """One authoritative closed canonical period, referenced implementation-neutrally.

    A1-10 clause 7 makes this the ONLY legal top-level member of ``source_price_ids``: a raw tick id can never
    stand here. Ticks may appear as provenance *underneath* a period, which is what ``raw_tick_provenance`` is
    for — it is audit material and takes no part in coverage, in the bounds or in any identity.
    """

    canonical_symbol: str = Field(pattern=_SYMBOL)
    timeframe: Literal["M1"] = "M1"  # A1-10 clause 1: M1 only until a tick store is declared authoritative
    period_open_utc: datetime
    period_close_utc: datetime
    low: float = Field(gt=0)
    high: float = Field(gt=0)
    quality: PeriodEvidenceQuality
    is_closed: bool
    evidence_id: str = Field(pattern=_DIGEST)
    material_evidence_hash: str = Field(pattern=_DIGEST)
    raw_tick_provenance: tuple[str, ...] = ()  # provenance only, never a source_price_ids member

    @model_validator(mode="after")
    def _coherent(self) -> CanonicalPeriodPriceEvidenceV31:
        _aware(self.period_open_utc, self.period_close_utc)
        if self.period_close_utc - self.period_open_utc != timedelta(minutes=1):
            raise ValueError("M1 period must span exactly one minute")
        if self.high < self.low:
            raise ValueError("period high must not be below period low")
        return self


class PressureRangePolicyV31(_Strict):
    """Hashed, versioned policy. A1-10: every policy input is versioned; no default may be compiled in.

    This module introduces **no** outlier algorithm of its own: §11.5 owns that, and the version it ran under is
    recorded here so a replay can prove which ladder produced a `QUARANTINED` period.
    """

    policy_version: str = Field(min_length=3, max_length=120)
    timeframe: Literal["M1"]
    calendar_policy_version: str = Field(min_length=3, max_length=120)  # produced the expected-period set
    outlier_policy_version: str = Field(min_length=3, max_length=120)  # §11.5, not re-implemented here
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _hashed(self) -> PressureRangePolicyV31:
        body = {k: v for k, v in self.model_dump(mode="json").items() if k != "policy_hash"}
        if self.policy_hash != canonical_sha256_v31(body):
            raise ValueError("PRESSURE_RANGE_POLICY_HASH_MISMATCH")
        return self


def pressure_range_id_v31(
    *,
    strategy_lifecycle_id: UUID,
    coverage_anchor_rule: str,
    started_at: datetime,
    range_policy_hash: str,
) -> UUID:
    """G1 GAP_FILL (Route 2). Anchored at the window START so the id survives a growing window.

    Deliberately absent: deployment, replica, worker, request or publisher identifiers, broker state, telemetry,
    the admission class, and the bounds themselves. A canonical and an advisory lineage of one episode anchor
    differently (§8.5), so they are different objects with different ids — that is authority, not drift.
    """

    _aware(started_at)
    return identity_uuid_v31(
        V31_PRESSURE_RANGE_NAMESPACE,
        [
            PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION,
            str(strategy_lifecycle_id),
            coverage_anchor_rule,
            started_at.isoformat(),
            range_policy_hash,
        ],
    )


class PressureRangeV31(_Strict):
    """Immutable observation of the material price range. Evidence only; it authorises nothing."""

    rule_version: Literal["5scr.pressure-range.v31.v1"] = PRESSURE_RANGE_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    selected_ssot_hash: Literal["sha256:6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902"] = (
        SELECTED_SSOT_HASH
    )
    identity_derivation_version: Literal["v31.pressure-range-identity.v1"] = PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION
    pressure_range_id: UUID
    strategy_lifecycle_id: UUID
    market_episode_id: UUID  # §8.1 provenance; audit only, never part of the identity tuple
    canonical_symbol: str = Field(pattern=_SYMBOL)
    coverage_anchor_rule: CoverageAnchorRule
    started_at: datetime
    ended_at: datetime | None  # A1-09: set only by the MarketEpisode close
    low: float | None
    high: float | None
    price_coverage_status: PriceCoverageStatus
    coverage_gaps: tuple[datetime, ...]  # expected period opens with no qualifying evidence
    # A1-10 clause 7: canonical-period evidence ids only. The digest pattern is what makes a raw `tick:<id>`
    # illegal AS SUCH, rather than merely inconsistent with the evidence hash.
    source_price_ids: tuple[Annotated[str, Field(pattern=_DIGEST)], ...]
    observed_through_utc: datetime
    range_policy_version: str
    range_policy_hash: str = Field(pattern=_DIGEST)
    evidence_hash: str = Field(pattern=_DIGEST)  # the only hash §16.2 declares
    authority: Literal["MATERIAL_PRICE_EVIDENCE_ONLY"] = "MATERIAL_PRICE_EVIDENCE_ONLY"
    direction_authority: Literal[False] = False
    structural_authority: bool  # §8.5: derived, true only when coverage is COMPLETE
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> PressureRangeV31:
        _aware(self.started_at, self.ended_at, self.observed_through_utc, *self.coverage_gaps)
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("PRESSURE_RANGE_LIFECYCLE_NOT_EPISODE_ROOTED")
        expected = pressure_range_id_v31(
            strategy_lifecycle_id=self.strategy_lifecycle_id,
            coverage_anchor_rule=self.coverage_anchor_rule,
            started_at=self.started_at,
            range_policy_hash=self.range_policy_hash,
        )
        if self.pressure_range_id != expected:
            raise ValueError("PRESSURE_RANGE_ID_NOT_DERIVED")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("PRESSURE_RANGE_WINDOW_ORDER_INVALID")
        if self.observed_through_utc < self.started_at:
            raise ValueError("PRESSURE_RANGE_OBSERVED_THROUGH_BEFORE_START")
        # A1-10: bounds are present together or absent together, and absence means MISSING — never zero.
        if (self.low is None) != (self.high is None):
            raise ValueError("PRESSURE_RANGE_BOUNDS_MUST_BE_PAIRED")
        if self.low is None:
            if self.price_coverage_status != "MISSING":
                raise ValueError("ABSENT_BOUNDS_REQUIRE_MISSING_COVERAGE")
        else:
            assert self.high is not None
            if self.low <= 0 or self.high <= 0:
                raise ValueError("PRESSURE_RANGE_BOUNDS_MUST_BE_POSITIVE")
            if self.high < self.low:
                raise ValueError("PRESSURE_RANGE_HIGH_BELOW_LOW")
            if self.price_coverage_status == "MISSING":
                raise ValueError("MISSING_COVERAGE_REQUIRES_ABSENT_BOUNDS")
        if len(set(self.source_price_ids)) != len(self.source_price_ids):
            raise ValueError("PRESSURE_RANGE_SOURCE_IDS_NOT_UNIQUE")
        if self.source_price_ids != tuple(sorted(self.source_price_ids)):
            raise ValueError("PRESSURE_RANGE_SOURCE_IDS_NOT_SORTED")
        if self.price_coverage_status == "MISSING" and self.source_price_ids:
            raise ValueError("MISSING_COVERAGE_REQUIRES_NO_SOURCE_EVIDENCE")
        if self.coverage_gaps != tuple(sorted(self.coverage_gaps)):
            raise ValueError("PRESSURE_RANGE_GAPS_NOT_SORTED")
        if self.price_coverage_status == "COMPLETE" and self.coverage_gaps:
            raise ValueError("COMPLETE_COVERAGE_REQUIRES_NO_GAPS")
        # §8.5: only COMPLETE coverage may carry structural authority. The range never holds any other authority.
        if self.structural_authority != (self.price_coverage_status == "COMPLETE"):
            raise ValueError("STRUCTURAL_AUTHORITY_NOT_DERIVED_FROM_COVERAGE")
        if self.evidence_hash != pressure_range_evidence_hash_v31(self):
            raise ValueError("PRESSURE_RANGE_EVIDENCE_HASH_MISMATCH")
        return self


def pressure_range_evidence_hash_v31(record: PressureRangeV31) -> str:
    """§16.2's single declared hash, over everything the record asserts except the hash itself."""

    body = {k: v for k, v in record.model_dump(mode="json").items() if k != "evidence_hash"}
    return canonical_sha256_v31(body)


def classify_pressure_range_change_v31(
    previous: PressureRangeV31 | None, current: PressureRangeV31
) -> PressureRangeChange:
    """A1-12, by explicit field comparison — deliberately NOT by a material hash (G8).

    Precedence is geometry, then coverage, then evidence. A `PARTIAL → COMPLETE` transition with identical
    bounds is a `COVERAGE_CHANGE`, not a refresh: that is the case a two-class model silently loses.
    """

    if previous is None:
        return "MATERIAL_RANGE_CHANGE"
    if previous.pressure_range_id != current.pressure_range_id:
        raise ValueError("PRESSURE_RANGE_CHANGE_ACROSS_DIFFERENT_RANGES")

    def differs(fields: tuple[str, ...]) -> bool:
        return any(getattr(previous, name) != getattr(current, name) for name in fields)

    if differs(GEOMETRY_MATERIAL_FIELDS):
        return "MATERIAL_RANGE_CHANGE"
    if differs(COVERAGE_FIELDS):
        return "COVERAGE_CHANGE"
    if differs(EVIDENCE_FIELDS):
        return "EVIDENCE_REFRESH"
    return "NO_MATERIAL_CHANGE"


# A1-12 downstream matrix. The ExecutionBox column is absent on purpose: that is G7 and belongs to 12C.
DOWNSTREAM_REEVALUATION_V31: dict[str, tuple[str, ...]] = {
    "MATERIAL_RANGE_CHANGE": ("LIFECYCLE", "STRUCTURAL_TARGET"),
    "COVERAGE_CHANGE": ("LIFECYCLE",),
    "EVIDENCE_REFRESH": (),
    "NO_MATERIAL_CHANGE": (),
}


def downstream_reevaluation_v31(change: str) -> tuple[str, ...]:
    """What a change REQUIRES to be re-evaluated. It revises nothing itself, and never names the ExecutionBox."""

    if change not in DOWNSTREAM_REEVALUATION_V31:
        raise ValueError("UNKNOWN_PRESSURE_RANGE_CHANGE")
    return DOWNSTREAM_REEVALUATION_V31[change]


__all__ = [
    "COVERAGE_FIELDS",
    "DOWNSTREAM_REEVALUATION_V31",
    "EVIDENCE_FIELDS",
    "GEOMETRY_MATERIAL_FIELDS",
    "PRESSURE_RANGE_IDENTITY_DERIVATION_VERSION",
    "PRESSURE_RANGE_V31_RULE_VERSION",
    "V31_PRESSURE_RANGE_NAMESPACE",
    "CanonicalPeriodPriceEvidenceV31",
    "CoverageAnchorRule",
    "PressureRangeChange",
    "PressureRangePolicyV31",
    "PressureRangeV31",
    "PriceCoverageStatus",
    "classify_pressure_range_change_v31",
    "downstream_reevaluation_v31",
    "pressure_range_evidence_hash_v31",
    "pressure_range_id_v31",
]
