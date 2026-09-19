"""Pure PairAdmissionCoverage classifier (SSOT v3.1 §7.5–7.6, §23.8–23.10), S1B-0.

Order of truth:
1. raw coverage INCOMPLETE/UNKNOWN → INDETERMINATE_RAW_AUTHORITY_COVERAGE, replay_required (never NOT_APPLICABLE).
2. complete coverage + no eligible raw block → NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK (not an incident).
3. complete coverage + eligible block + its durable evaluation → EVALUATED.
4. complete coverage + eligible block + no evaluation after the SLA → MISSING_EVALUATION_INCIDENT (+ replay).
   Before the SLA the block is still NOT_EVALUATED, a transient state (§7.5): no coverage record is emitted.

Advisory maturity is recorded and never read. No wall clock: ``as_of`` is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    REASON_BY_STATUS,
    PairAdmissionCoveragePolicyV31,
    PairAdmissionCoverageV1,
    PairAdmissionEvaluationRefV31,
    RawAuthorityCoverageObservationV31,
    pair_admission_coverage_id_v31,
)


@dataclass(frozen=True)
class CoverageClassificationV31:
    outcome: Literal["CLASSIFIED", "NOT_CLASSIFIED"]
    reason_code: str
    coverage: PairAdmissionCoverageV1 | None = None


def _no(reason: str) -> CoverageClassificationV31:
    return CoverageClassificationV31("NOT_CLASSIFIED", reason)


def classify_pair_admission_coverage_v31(
    *,
    observation: RawAuthorityCoverageObservationV31,
    evaluation: PairAdmissionEvaluationRefV31 | None,
    advisory_pressure_maturity: Literal["IMMATURE", "MATURE", "EXTREME", "EXPIRED", "UNKNOWN"],
    policy: PairAdmissionCoveragePolicyV31 | None,
    as_of: datetime,
) -> CoverageClassificationV31:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if policy is None:
        return _no("PAIR_ADMISSION_COVERAGE_POLICY_MISSING")
    policy = PairAdmissionCoveragePolicyV31.model_validate(policy.model_dump())
    observation = RawAuthorityCoverageObservationV31.model_validate(observation.model_dump())
    if as_of < observation.observed_window_end_utc:
        return _no("COVERAGE_WINDOW_NOT_CLOSED")
    block = observation.block
    if evaluation is not None:
        evaluation = PairAdmissionEvaluationRefV31.model_validate(evaluation.model_dump())
        if evaluation.evaluated_at > as_of:
            return _no("FUTURE_LEAKAGE_BLOCK")
        if (
            block is None
            or not block.eligible
            or (evaluation.raw_authority_block_id, evaluation.canonical_symbol)
            != (block.raw_authority_block_id, observation.canonical_symbol)
        ):
            return _no("PAIR_ADMISSION_EVALUATION_SCOPE_MISMATCH")

    eligible = block is not None and block.eligible
    if observation.raw_authority_coverage_status != "COMPLETE":
        status, replay, incident = "INDETERMINATE_RAW_AUTHORITY_COVERAGE", True, False
    elif not eligible:
        status, replay, incident = "NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK", False, False
    elif evaluation is not None:
        status, replay, incident = "EVALUATED", False, False
    else:
        assert block is not None and block.eligible_at is not None
        if as_of < block.eligible_at + timedelta(seconds=policy.evaluation_sla_seconds):
            return _no("PAIR_ADMISSION_NOT_EVALUATED_WITHIN_SLA")  # §7.5 transient, not yet an incident
        status, replay, incident = "MISSING_EVALUATION_INCIDENT", True, True

    coverage = PairAdmissionCoverageV1(
        pair_admission_coverage_id=pair_admission_coverage_id_v31(
            canonical_symbol=observation.canonical_symbol,
            window_start=observation.observed_window_start_utc,
            window_end=observation.observed_window_end_utc,
            coverage_policy_hash=policy.policy_hash,
        ),
        symbol=observation.canonical_symbol,
        observed_window_start_utc=observation.observed_window_start_utc,
        observed_window_end_utc=observation.observed_window_end_utc,
        raw_authority_coverage_status=observation.raw_authority_coverage_status,
        raw_authority_block_present=block is not None,
        raw_authority_block_eligible=None if block is None else block.eligible,
        raw_authority_block_id=None if block is None else block.raw_authority_block_id,
        admission_coverage_status=status,
        admission_evaluation_id=None if evaluation is None else evaluation.admission_evaluation_id,
        admission_decision=None if evaluation is None else evaluation.decision,
        advisory_pressure_maturity=advisory_pressure_maturity,
        replay_required=replay,
        incident_required=incident,
        reason_code=REASON_BY_STATUS[status],
        coverage_policy_version=policy.policy_version,
        coverage_policy_hash=policy.policy_hash,
        coverage_evidence_hash=observation.coverage_evidence_hash,
        classified_as_of=as_of,
    )
    return CoverageClassificationV31("CLASSIFIED", coverage.reason_code, coverage)


__all__ = ["CoverageClassificationV31", "classify_pair_admission_coverage_v31"]
