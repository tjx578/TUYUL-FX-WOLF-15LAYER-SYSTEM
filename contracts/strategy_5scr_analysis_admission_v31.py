"""StrategyAnalysisAdmissionV31: implements the SSOT v3.1 §7A.4 object ``StrategyAnalysisAdmissionV1`` (S1B-1).

``V31`` is the implementation/version namespace (owner decision S2), not a semantic change: the field set is §7A.4
verbatim plus audit bindings. The main-branch ``StrategyAnalysisAdmissionV1`` is LEGACY_NONCONFORMANT and is never
imported or adapted here.

- CANONICAL_RAW (§7A.2): source is a GRANTED PairAdmission, proven by an EVALUATED PairAdmissionCoverageV1 bound to
  the same evaluation (§25.3: coverage before admission).
- MATURE_ADVISORY (§7A.2–7A.3): source is typed ``AdvisoryPressureEvidenceV31`` classified by a hashed
  ``AdvisoryPressureMaturityPolicyV31``. No PairAdmission is required or faked; absence of PairAdmission is never a
  rejection reason (§7A.7). Hard containment: FULL_SHADOW_ANALYSIS, SHADOW_ONLY, no risk, no execution.
- Identity (§4.2): admissions are distinct authority records inside ONE market episode:
  canonical id over [episode, CANONICAL_RAW, pair_admission_evaluation_id];
  advisory id over [episode, MATURE_ADVISORY, maturity_policy_hash] (0/1 decision per maturity-policy revision).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31, identity_uuid_v31

STRATEGY_ANALYSIS_ADMISSION_V31_CONTRACT_VERSION = "strategy-analysis-admission.v31.v1"
V31_STRATEGY_ANALYSIS_ADMISSION_NAMESPACE = UUID("1f8e3117-7d3b-4957-96a1-68b4832f8699")

AdmissionClass = Literal["CANONICAL_RAW", "MATURE_ADVISORY"]
AdmissionStatus = Literal["PENDING", "GRANTED", "REJECTED", "SUSPENDED", "EXPIRED"]  # §7A.4
AnalysisAuthority = Literal["FULL_CANONICAL_ANALYSIS", "FULL_SHADOW_ANALYSIS"]
SourceAuthority = Literal["RAW_SIGNALTHROTTLE_LEDGER", "DERIVED_PRESSURE_ADVISORY"]  # §7A.4 spelling
PressureDirection = Literal["BUY", "SELL", "CONFLICT", "INCOMPLETE"]
LineageAlignment = Literal["ALIGNED", "CONFLICT", "UNAVAILABLE"]
AdvisoryMaturity = Literal["IMMATURE", "MATURE", "EXTREME", "EXPIRED", "UNKNOWN"]
PromotionEligibility = Literal["CANONICAL_RISK_PATH", "SHADOW_ONLY"]
AdvisorySourceFamily = Literal["CANARY", "DERIVED_PRESSURE", "MICROBOOST_DERIVED"]  # §7A.2 sources
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


def _body_hash(model: BaseModel, hash_field: str) -> str:
    return canonical_sha256_v31({k: v for k, v in model.model_dump(mode="json").items() if k != hash_field})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class AdvisoryPressureEvidenceV31(_Strict):
    """Typed, audit-ready advisory pressure input (IMPLEMENTATION_DETAIL). Never an admission authority by itself."""

    canonical_symbol: str = Field(pattern=_SYMBOL)
    market_episode_id: UUID
    source_event_ids: tuple[str, ...] = Field(min_length=1)
    source_family: AdvisorySourceFamily
    source_authority_class: Literal["DERIVED_PRESSURE_ADVISORY"]  # §6.2; raw ledger events never arrive here
    pressure_direction: PressureDirection
    direction_lineage_alignment: LineageAlignment
    duration_seconds: float = Field(ge=0)
    effective_events: int = Field(ge=0)  # deduplicated (§7A.3)
    pulse_count: int = Field(ge=0)
    direction_persistence: float = Field(ge=0, le=1)
    continuity_quality: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    density_bucket: str | None = Field(max_length=60)  # recorded; not a policy input in this increment
    evidence_coverage_sufficient: bool
    eligible_for_context_resolution: bool
    observed_from: datetime
    observed_until: datetime
    pressure_valid_until: datetime
    evidence_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _bound(self) -> AdvisoryPressureEvidenceV31:
        _aware(self.observed_from, self.observed_until, self.pressure_valid_until)
        if not self.observed_from <= self.observed_until:
            raise ValueError("evidence window must be ordered")
        if list(self.source_event_ids) != sorted(set(self.source_event_ids)):
            raise ValueError("source_event_ids must be sorted and unique (deduplicated)")
        if self.evidence_hash != _body_hash(self, "evidence_hash"):
            raise ValueError("ADVISORY_EVIDENCE_HASH_MISMATCH")
        return self


class AdvisoryMaturityTierV31(_Strict):
    status: Literal["MATURE", "EXTREME"]
    min_duration_seconds: float = Field(ge=0)
    min_effective_events: int = Field(ge=0)
    min_pulse_count: int = Field(ge=0)
    min_direction_persistence: float = Field(ge=0, le=1)
    min_continuity_quality: float = Field(ge=0, le=1)
    min_source_quality: float = Field(ge=0, le=1)


class AdvisoryPressureMaturityPolicyV31(_Strict):
    """AdvisoryPressureMaturityPolicyRegistry (§7A.3, §26). Every threshold is policy data; nothing is defaulted."""

    policy_version: str = Field(min_length=3, max_length=120)
    admissible_source_families: tuple[AdvisorySourceFamily, ...] = Field(min_length=1)
    tiers: tuple[AdvisoryMaturityTierV31, ...] = Field(min_length=1, max_length=2)
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> AdvisoryPressureMaturityPolicyV31:
        if len({t.status for t in self.tiers}) != len(self.tiers):
            raise ValueError("one tier per maturity status")
        if self.policy_hash != _body_hash(self, "policy_hash"):
            raise ValueError("ADVISORY_MATURITY_POLICY_HASH_MISMATCH")
        return self


class StrategyAnalysisAdmissionPolicyV31(_Strict):
    """StrategyAnalysisAdmissionPolicyRegistry (§26): the two §18 admission clocks. No defaults."""

    policy_version: str = Field(min_length=3, max_length=120)
    canonical_admission_ttl_seconds: int = Field(gt=0)  # STRATEGY_ANALYSIS_ADMISSION_VALID_UNTIL
    advisory_analysis_ttl_seconds: int = Field(gt=0)  # ADVISORY_ANALYSIS_VALID_UNTIL
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> StrategyAnalysisAdmissionPolicyV31:
        if self.policy_hash != _body_hash(self, "policy_hash"):
            raise ValueError("STRATEGY_ANALYSIS_ADMISSION_POLICY_HASH_MISMATCH")
        return self


def strategy_analysis_admission_id_v31(*, market_episode_id: UUID, admission_class: str, source_anchor: str) -> UUID:
    return identity_uuid_v31(
        V31_STRATEGY_ANALYSIS_ADMISSION_NAMESPACE, [str(market_episode_id), admission_class, source_anchor]
    )


class StrategyAnalysisAdmissionV31(_Strict):
    """§7A.4 fields verbatim, then audit bindings. One authority record; never a lifecycle, never an order."""

    implements_ssot_object: Literal["StrategyAnalysisAdmissionV1"] = "StrategyAnalysisAdmissionV1"
    contract_version: Literal["strategy-analysis-admission.v31.v1"] = STRATEGY_ANALYSIS_ADMISSION_V31_CONTRACT_VERSION
    # --- §7A.4 ---
    strategy_analysis_admission_id: UUID
    symbol: str = Field(pattern=_SYMBOL)
    market_episode_id: UUID
    admission_class: AdmissionClass
    admission_status: AdmissionStatus
    analysis_authority: AnalysisAuthority
    source_authority: SourceAuthority
    pair_admission_evaluation_id: UUID | None
    pair_admission_coverage_id: UUID | None
    pressure_direction: PressureDirection
    direction_lineage_alignment: LineageAlignment
    advisory_maturity: AdvisoryMaturity
    advisory_maturity_policy_version: str | None
    context_resolution_allowed: bool
    structural_evidence_prefetch_required: bool
    tradeplan_candidate_allowed: bool
    promotion_eligibility: PromotionEligibility
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    reason_code: str = Field(min_length=3, max_length=200)
    evidence_hash: str = Field(pattern=_DIGEST)
    granted_at_utc: datetime | None
    expires_at_utc: datetime | None
    # --- audit bindings ---
    advisory_maturity_policy_hash: str | None = Field(pattern=_DIGEST)
    admission_policy_version: str
    admission_policy_hash: str = Field(pattern=_DIGEST)
    decided_at_utc: datetime
    final_signal_allowed: Literal[False] = False
    execution_command_allowed: Literal[False] = False
    broker_side_effect_allowed: Literal[False] = False

    @model_validator(mode="after")
    def _coherent(self) -> StrategyAnalysisAdmissionV31:
        _aware(self.granted_at_utc, self.expires_at_utc, self.decided_at_utc)
        canonical = self.admission_class == "CANONICAL_RAW"
        anchor = str(self.pair_admission_evaluation_id) if canonical else str(self.advisory_maturity_policy_hash)
        expected = strategy_analysis_admission_id_v31(
            market_episode_id=self.market_episode_id, admission_class=self.admission_class, source_anchor=anchor
        )
        if self.strategy_analysis_admission_id != expected:
            raise ValueError("STRATEGY_ANALYSIS_ADMISSION_ID_NOT_DERIVED")
        if self.pair_admission_coverage_id is None:
            raise ValueError("both admission classes pass PairAdmissionCoverage first (§25.3)")
        if canonical:
            if (self.analysis_authority, self.source_authority, self.promotion_eligibility) != (
                "FULL_CANONICAL_ANALYSIS",
                "RAW_SIGNALTHROTTLE_LEDGER",
                "CANONICAL_RISK_PATH",
            ):
                raise ValueError("CANONICAL_RAW scope mismatch")
            if self.pair_admission_evaluation_id is None:
                raise ValueError("CANONICAL_RAW requires its PairAdmission evaluation")
            if self.advisory_maturity_policy_version is not None or self.advisory_maturity_policy_hash is not None:
                raise ValueError("CANONICAL_RAW carries no advisory maturity policy")
        else:
            # Hard containment (§7A.2): shadow only, no PairAdmission fabricated.
            if (self.analysis_authority, self.source_authority, self.promotion_eligibility) != (
                "FULL_SHADOW_ANALYSIS",
                "DERIVED_PRESSURE_ADVISORY",
                "SHADOW_ONLY",
            ):
                raise ValueError("MATURE_ADVISORY must stay FULL_SHADOW_ANALYSIS / SHADOW_ONLY")
            if self.pair_admission_evaluation_id is not None:
                raise ValueError("MATURE_ADVISORY never carries a PairAdmission evaluation")
            if self.advisory_maturity_policy_version is None or self.advisory_maturity_policy_hash is None:
                raise ValueError("MATURE_ADVISORY requires its versioned, hashed maturity policy")
        granted = self.admission_status == "GRANTED"
        flags = (
            self.context_resolution_allowed,
            self.structural_evidence_prefetch_required,
            self.tradeplan_candidate_allowed,
        )
        if flags != (granted, granted, granted):
            raise ValueError("analysis flags are set exactly for GRANTED")
        if granted != (self.granted_at_utc is not None) or granted != (self.expires_at_utc is not None):
            raise ValueError("granted_at/expires_at are set exactly for GRANTED")
        if granted:
            if self.pressure_direction not in {"BUY", "SELL"} or self.direction_lineage_alignment != "ALIGNED":
                raise ValueError("GRANTED requires a definite, aligned pressure direction")
            if not canonical and self.advisory_maturity not in {"MATURE", "EXTREME"}:
                raise ValueError("MATURE_ADVISORY GRANTED requires MATURE or EXTREME")
            assert self.granted_at_utc is not None and self.expires_at_utc is not None
            if not self.granted_at_utc <= self.decided_at_utc < self.expires_at_utc:
                raise ValueError("ADMISSION_CLOCK_ORDER_INVALID")
        return self


def strategy_analysis_admission_hash_v31(admission: StrategyAnalysisAdmissionV31) -> str:
    """Record (revision) hash. The logical identity is ``strategy_analysis_admission_id``."""

    return canonical_sha256_v31(admission.model_dump(mode="json"))


__all__ = [
    "STRATEGY_ANALYSIS_ADMISSION_V31_CONTRACT_VERSION",
    "V31_STRATEGY_ANALYSIS_ADMISSION_NAMESPACE",
    "AdvisoryMaturityTierV31",
    "AdvisoryPressureEvidenceV31",
    "AdvisoryPressureMaturityPolicyV31",
    "StrategyAnalysisAdmissionPolicyV31",
    "StrategyAnalysisAdmissionV31",
    "strategy_analysis_admission_hash_v31",
    "strategy_analysis_admission_id_v31",
]
