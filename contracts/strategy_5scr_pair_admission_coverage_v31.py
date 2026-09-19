"""PairAdmissionCoverageV1 (SSOT v3.1 §7.6, §7.12, §21.1, §23.8–23.10, §28.3–28.5), S1B-0, owner decision S4.

Coverage is classified separately from the admission decision and before StrategyAnalysisAdmission (§25.3 step 1).
The boundary is typed canonical references, never a concrete PairAdmission implementation: the v3.1 global block
path and the A1 per-symbol path (#492, CONFLICT_OVERRIDE candidate) can both project into
``RawAuthorityCoverageObservationV31`` + ``PairAdmissionEvaluationRefV31``.

Invariant (§7.12): advisory pressure maturity never implies raw-authority eligibility. It is recorded, never read.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_market_episode_v31 import IDENTITY_ENCODING_VERSION, canonical_sha256_v31

PAIR_ADMISSION_COVERAGE_RULE_VERSION = "pair-admission-coverage.v1"  # SSOT §7.12, verbatim
V31_PAIR_ADMISSION_COVERAGE_NAMESPACE = UUID("23ddba85-d0ea-41cd-b935-b6a9ff4ee5f4")

RawAuthorityCoverageStatus = Literal["COMPLETE", "INCOMPLETE", "UNKNOWN"]  # §28.3
AdmissionCoverageStatus = Literal[  # §28.4
    "EVALUATED",
    "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK",
    "MISSING_EVALUATION_INCIDENT",
    "INDETERMINATE_RAW_AUTHORITY_COVERAGE",
]
AdmissionDecision = Literal["GRANTED", "REJECTED", "SUSPENDED"]  # §28.5
AdvisoryPressureMaturity = Literal["IMMATURE", "MATURE", "EXTREME", "EXPIRED", "UNKNOWN"]
REASON_BY_STATUS: dict[str, str] = {  # §21.1
    "EVALUATED": "PAIR_ADMISSION_EVALUATED",
    "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK": "PAIR_ADMISSION_NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK",
    "MISSING_EVALUATION_INCIDENT": "PAIR_ADMISSION_MISSING_EVALUATION_INCIDENT",
    "INDETERMINATE_RAW_AUTHORITY_COVERAGE": "RAW_AUTHORITY_COVERAGE_INDETERMINATE",
}
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_SYMBOL = r"^[A-Z0-9._-]{3,32}$"


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class PairAdmissionCoveragePolicyV31(_Strict):
    """PairAdmissionCoveragePolicyRegistry (§26). The evaluator SLA of §7.5 is policy data, never a default."""

    policy_version: str = Field(min_length=3, max_length=120)
    evaluation_sla_seconds: int = Field(gt=0)
    policy_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _valid(self) -> PairAdmissionCoveragePolicyV31:
        body = {k: v for k, v in self.model_dump(mode="json").items() if k != "policy_hash"}
        if self.policy_hash != canonical_sha256_v31(body):
            raise ValueError("PAIR_ADMISSION_COVERAGE_POLICY_HASH_MISMATCH")
        return self


class RawAuthorityBlockRefV31(_Strict):
    """One raw-authority block as proven by the canonical raw ledger (§7.1)."""

    raw_authority_block_id: str = Field(min_length=1, max_length=240)
    canonical_symbol: str = Field(pattern=_SYMBOL)
    block_started_at: datetime
    eligible: bool
    eligible_at: datetime | None
    raw_lineage_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _bound(self) -> RawAuthorityBlockRefV31:
        _aware(self.block_started_at, self.eligible_at)
        if self.eligible != (self.eligible_at is not None):
            raise ValueError("eligible_at is set exactly for an eligible block")
        if self.eligible_at is not None and self.eligible_at < self.block_started_at:
            raise ValueError("eligibility cannot precede the block start")
        return self


class RawAuthorityCoverageObservationV31(_Strict):
    """What the raw ledger proves about one symbol over one window (RawAuthorityCoveragePolicyRegistry, §26)."""

    canonical_symbol: str = Field(pattern=_SYMBOL)
    observed_window_start_utc: datetime
    observed_window_end_utc: datetime
    raw_authority_coverage_status: RawAuthorityCoverageStatus
    coverage_evidence_hash: str = Field(pattern=_DIGEST)
    block: RawAuthorityBlockRefV31 | None

    @model_validator(mode="after")
    def _bound(self) -> RawAuthorityCoverageObservationV31:
        _aware(self.observed_window_start_utc, self.observed_window_end_utc)
        if self.observed_window_end_utc <= self.observed_window_start_utc:
            raise ValueError("coverage window must have positive length")
        if self.block is not None:
            if self.block.canonical_symbol != self.canonical_symbol:
                raise ValueError("COVERAGE_BLOCK_SYMBOL_MISMATCH")
            if not self.block.block_started_at < self.observed_window_end_utc:
                raise ValueError("COVERAGE_BLOCK_OUTSIDE_WINDOW")
        return self


class PairAdmissionEvaluationRefV31(_Strict):
    """Implementation-neutral reference to one durable PairAdmission evaluation (§7.11 identity fields)."""

    admission_evaluation_id: UUID
    raw_authority_block_id: str = Field(min_length=1, max_length=240)
    canonical_symbol: str = Field(pattern=_SYMBOL)
    decision: AdmissionDecision
    reason_code: str = Field(min_length=3, max_length=200)
    evaluated_at: datetime
    admission_rule_version: str = Field(min_length=3, max_length=160)
    evaluation_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _bound(self) -> PairAdmissionEvaluationRefV31:
        _aware(self.evaluated_at)
        return self


def pair_admission_coverage_id_v31(
    *, canonical_symbol: str, window_start: datetime, window_end: datetime, coverage_policy_hash: str
) -> UUID:
    """§4.2: exactly one coverage classification per symbol / window / rule version."""

    name = json.dumps(
        [
            IDENTITY_ENCODING_VERSION,
            PAIR_ADMISSION_COVERAGE_RULE_VERSION,
            canonical_symbol,
            window_start.isoformat(),
            window_end.isoformat(),
            coverage_policy_hash,
        ],
        separators=(",", ":"),
    )
    return uuid5(V31_PAIR_ADMISSION_COVERAGE_NAMESPACE, name)


class PairAdmissionCoverageV1(_Strict):
    """SSOT §7.12 fields verbatim, plus the audit bindings needed for deterministic replay."""

    pair_admission_coverage_id: UUID
    symbol: str = Field(pattern=_SYMBOL)
    observed_window_start_utc: datetime
    observed_window_end_utc: datetime
    raw_authority_coverage_status: RawAuthorityCoverageStatus
    raw_authority_block_present: bool
    raw_authority_block_eligible: bool | None
    raw_authority_block_id: str | None
    admission_coverage_status: AdmissionCoverageStatus
    admission_evaluation_id: UUID | None
    admission_decision: AdmissionDecision | None
    advisory_pressure_maturity: AdvisoryPressureMaturity
    replay_required: bool
    incident_required: bool
    reason_code: str
    rule_version: Literal["pair-admission-coverage.v1"] = PAIR_ADMISSION_COVERAGE_RULE_VERSION
    # Audit bindings (not SSOT semantics).
    coverage_policy_version: str
    coverage_policy_hash: str = Field(pattern=_DIGEST)
    coverage_evidence_hash: str = Field(pattern=_DIGEST)
    classified_as_of: datetime
    admission_authority: Literal[False] = False
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _coherent(self) -> PairAdmissionCoverageV1:
        _aware(self.observed_window_start_utc, self.observed_window_end_utc, self.classified_as_of)
        expected = pair_admission_coverage_id_v31(
            canonical_symbol=self.symbol,
            window_start=self.observed_window_start_utc,
            window_end=self.observed_window_end_utc,
            coverage_policy_hash=self.coverage_policy_hash,
        )
        if self.pair_admission_coverage_id != expected:
            raise ValueError("PAIR_ADMISSION_COVERAGE_ID_NOT_DERIVED")
        if self.raw_authority_block_present != (self.raw_authority_block_id is not None) or (
            self.raw_authority_block_present != (self.raw_authority_block_eligible is not None)
        ):
            raise ValueError("block id and eligibility are set exactly when a block is present")
        if (self.admission_evaluation_id is None) != (self.admission_decision is None):
            raise ValueError("evaluation id and decision come together")
        if self.reason_code != REASON_BY_STATUS[self.admission_coverage_status]:
            raise ValueError("COVERAGE_REASON_CODE_MISMATCH")
        complete = self.raw_authority_coverage_status == "COMPLETE"
        eligible = self.raw_authority_block_eligible is True
        status = self.admission_coverage_status
        if (status == "INDETERMINATE_RAW_AUTHORITY_COVERAGE") == complete:
            raise ValueError("INDETERMINATE is exactly raw coverage INCOMPLETE/UNKNOWN (§7.6)")
        if status == "INDETERMINATE_RAW_AUTHORITY_COVERAGE" and (not self.replay_required or self.incident_required):
            raise ValueError("INDETERMINATE requires replay and never infers an incident (§7.6)")
        if status == "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK" and (
            eligible or self.admission_evaluation_id is not None or self.incident_required
        ):
            raise ValueError("NOT_APPLICABLE needs complete coverage and no eligible raw block (§7.6)")
        if status == "EVALUATED" and (not eligible or self.admission_evaluation_id is None or self.incident_required):
            raise ValueError("EVALUATED needs an eligible raw block with its durable evaluation")
        if status == "MISSING_EVALUATION_INCIDENT" and (
            not eligible
            or self.admission_evaluation_id is not None
            or not (self.incident_required and self.replay_required)
        ):
            raise ValueError(
                "MISSING_EVALUATION_INCIDENT needs an eligible block, no evaluation, incident + replay (§23.8)"
            )
        return self


__all__ = [
    "PAIR_ADMISSION_COVERAGE_RULE_VERSION",
    "REASON_BY_STATUS",
    "V31_PAIR_ADMISSION_COVERAGE_NAMESPACE",
    "PairAdmissionCoveragePolicyV31",
    "PairAdmissionCoverageV1",
    "PairAdmissionEvaluationRefV31",
    "RawAuthorityBlockRefV31",
    "RawAuthorityCoverageObservationV31",
    "pair_admission_coverage_id_v31",
]
