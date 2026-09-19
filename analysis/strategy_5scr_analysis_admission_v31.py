"""Pure S1B-1 evaluators: StrategyAnalysisAdmissionV31 for CANONICAL_RAW and MATURE_ADVISORY (SSOT v3.1 §7A).

Fail closed, no wall clock, no defaults, no I/O. Nothing here reaches enqueue, ARM, risk, command or broker code.
Missing inputs or scope problems return NOT_EVALUATED (no record). A record is REJECTED/SUSPENDED only with an
explicit §21.2 reason code (§7A.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from contracts.strategy_5scr_analysis_admission_v31 import (
    AdvisoryPressureEvidenceV31,
    AdvisoryPressureMaturityPolicyV31,
    StrategyAnalysisAdmissionPolicyV31,
    StrategyAnalysisAdmissionReceiptV31,
    StrategyAnalysisAdmissionV31,
    strategy_analysis_admission_hash_v31,
    strategy_analysis_admission_id_v31,
)
from contracts.strategy_5scr_market_episode_v31 import (
    MarketEpisodeStateV31,
    MarketEpisodeV31,
    canonical_sha256_v31,
    strategy_lifecycle_id_from_episode_v31,
)
from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    PairAdmissionCoverageV1,
    PairAdmissionEvaluationRefV31,
)


@dataclass(frozen=True)
class AdmissionDecisionV31:
    outcome: Literal["DECIDED", "NOT_EVALUATED"]
    reason_code: str
    admission: StrategyAnalysisAdmissionV31 | None = None


def _no(reason: str) -> AdmissionDecisionV31:
    return AdmissionDecisionV31("NOT_EVALUATED", reason)


def _aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("decision_at must be timezone-aware")


def classify_advisory_maturity_v31(
    evidence: AdvisoryPressureEvidenceV31, policy: AdvisoryPressureMaturityPolicyV31
) -> Literal["IMMATURE", "MATURE", "EXTREME"]:
    """Highest policy tier whose every threshold is met. All numbers come from the policy."""

    met = [
        tier.status
        for tier in policy.tiers
        if evidence.duration_seconds >= tier.min_duration_seconds
        and evidence.effective_events >= tier.min_effective_events
        and evidence.pulse_count >= tier.min_pulse_count
        and evidence.direction_persistence >= tier.min_direction_persistence
        and evidence.continuity_quality >= tier.min_continuity_quality
        and evidence.source_quality >= tier.min_source_quality
    ]
    if "EXTREME" in met:
        return "EXTREME"
    return "MATURE" if "MATURE" in met else "IMMATURE"


def _episode_gate(
    episode: MarketEpisodeV31, state: MarketEpisodeStateV31, decision_at: datetime
) -> tuple[MarketEpisodeV31, str | None]:
    episode = MarketEpisodeV31.model_validate(episode.model_dump())
    state = MarketEpisodeStateV31.model_validate(state.model_dump())
    if state.market_episode_id != episode.market_episode_id:
        return episode, "EPISODE_STATE_MISMATCH"
    if state.state == "CLOSED":
        return episode, "MARKET_EPISODE_CLOSED"  # §7A.3 lifecycle candidate must not be terminal
    if decision_at < episode.opened_at:
        return episode, "DECISION_PRECEDES_MARKET_EPISODE"
    return episode, None


def evaluate_canonical_raw_admission_v31(
    *,
    episode: MarketEpisodeV31,
    episode_state: MarketEpisodeStateV31,
    coverage: PairAdmissionCoverageV1,
    evaluation: PairAdmissionEvaluationRefV31,
    pressure_direction: Literal["BUY", "SELL", "CONFLICT", "INCOMPLETE"],
    direction_lineage_alignment: Literal["ALIGNED", "CONFLICT", "UNAVAILABLE"],
    direction_evidence_hash: str,
    policy: StrategyAnalysisAdmissionPolicyV31 | None,
    decision_at: datetime,
) -> AdmissionDecisionV31:
    """§7A.2 CANONICAL_RAW: an EVALUATED coverage bound to a GRANTED PairAdmission evaluation."""

    _aware(decision_at)
    if policy is None:
        return _no("STRATEGY_ANALYSIS_ADMISSION_POLICY_MISSING")
    policy = StrategyAnalysisAdmissionPolicyV31.model_validate(policy.model_dump())
    episode, failure = _episode_gate(episode, episode_state, decision_at)
    if failure:
        return _no(failure)
    coverage = PairAdmissionCoverageV1.model_validate(coverage.model_dump())
    evaluation = PairAdmissionEvaluationRefV31.model_validate(evaluation.model_dump())
    if not episode.canonical_symbol == coverage.symbol == evaluation.canonical_symbol:
        return _no("SYMBOL_SCOPE_MISMATCH")
    if coverage.classified_as_of > decision_at or evaluation.evaluated_at > decision_at:
        return _no("FUTURE_LEAKAGE_BLOCK")
    if coverage.admission_coverage_status != "EVALUATED":
        return _no("PAIR_ADMISSION_COVERAGE_NOT_EVALUATED")
    if (coverage.admission_evaluation_id, coverage.raw_authority_block_id, coverage.admission_decision) != (
        evaluation.admission_evaluation_id,
        evaluation.raw_authority_block_id,
        evaluation.decision,
    ):
        return _no("COVERAGE_EVALUATION_MISMATCH")
    if evaluation.decision != "GRANTED":
        return _no("PAIR_ADMISSION_NOT_GRANTED")  # the canonical source is a GRANTED PairAdmission only
    granted = pressure_direction in {"BUY", "SELL"} and direction_lineage_alignment == "ALIGNED"
    admission = StrategyAnalysisAdmissionV31(
        strategy_analysis_admission_id=strategy_analysis_admission_id_v31(
            market_episode_id=episode.market_episode_id,
            admission_class="CANONICAL_RAW",
            source_anchor=str(evaluation.admission_evaluation_id),
        ),
        symbol=episode.canonical_symbol,
        market_episode_id=episode.market_episode_id,
        admission_class="CANONICAL_RAW",
        admission_status="GRANTED" if granted else "SUSPENDED",
        analysis_authority="FULL_CANONICAL_ANALYSIS",
        source_authority="RAW_SIGNALTHROTTLE_LEDGER",
        pair_admission_evaluation_id=evaluation.admission_evaluation_id,
        pair_admission_coverage_id=coverage.pair_admission_coverage_id,
        pressure_direction=pressure_direction,
        direction_lineage_alignment=direction_lineage_alignment,
        advisory_maturity=coverage.advisory_pressure_maturity,
        advisory_maturity_policy_version=None,
        context_resolution_allowed=granted,
        structural_evidence_prefetch_required=granted,
        tradeplan_candidate_allowed=granted,
        promotion_eligibility="CANONICAL_RISK_PATH",
        reason_code="STRATEGY_ANALYSIS_ADMISSION_CANONICAL_RAW_GRANTED"
        if granted
        else "STRATEGY_ANALYSIS_ADMISSION_SUSPENDED",
        evidence_hash=canonical_sha256_v31(
            {
                "coverage_record_hash": canonical_sha256_v31(coverage.model_dump(mode="json")),
                "evaluation_hash": evaluation.evaluation_hash,
                "direction_evidence_hash": direction_evidence_hash,
                "pressure_direction": pressure_direction,
                "direction_lineage_alignment": direction_lineage_alignment,
            }
        ),
        granted_at_utc=decision_at if granted else None,
        expires_at_utc=decision_at + timedelta(seconds=policy.canonical_admission_ttl_seconds) if granted else None,
        advisory_maturity_policy_hash=None,
        admission_policy_version=policy.policy_version,
        admission_policy_hash=policy.policy_hash,
        decided_at_utc=decision_at,
    )
    return AdmissionDecisionV31("DECIDED", admission.reason_code, admission)


def evaluate_mature_advisory_admission_v31(
    *,
    episode: MarketEpisodeV31,
    episode_state: MarketEpisodeStateV31,
    coverage: PairAdmissionCoverageV1,
    evidence: AdvisoryPressureEvidenceV31,
    maturity_policy: AdvisoryPressureMaturityPolicyV31 | None,
    policy: StrategyAnalysisAdmissionPolicyV31 | None,
    decision_at: datetime,
) -> AdmissionDecisionV31:
    """§7A.2–7A.3 MATURE_ADVISORY. Any coverage status is acceptable: PairAdmission is neither needed nor faked."""

    _aware(decision_at)
    if maturity_policy is None:
        return _no("ADVISORY_MATURITY_POLICY_MISSING")
    if policy is None:
        return _no("STRATEGY_ANALYSIS_ADMISSION_POLICY_MISSING")
    maturity_policy = AdvisoryPressureMaturityPolicyV31.model_validate(maturity_policy.model_dump())
    policy = StrategyAnalysisAdmissionPolicyV31.model_validate(policy.model_dump())
    episode, failure = _episode_gate(episode, episode_state, decision_at)
    if failure:
        return _no(failure)
    coverage = PairAdmissionCoverageV1.model_validate(coverage.model_dump())
    evidence = AdvisoryPressureEvidenceV31.model_validate(evidence.model_dump())
    if not episode.canonical_symbol == coverage.symbol == evidence.canonical_symbol:
        return _no("SYMBOL_SCOPE_MISMATCH")
    if evidence.market_episode_id != episode.market_episode_id:
        return _no("EVIDENCE_EPISODE_MISMATCH")
    if coverage.classified_as_of > decision_at or evidence.observed_until > decision_at:
        return _no("FUTURE_LEAKAGE_BLOCK")

    expired = evidence.pressure_valid_until <= decision_at
    maturity = "EXPIRED" if expired else classify_advisory_maturity_v31(evidence, maturity_policy)
    status, reason = "GRANTED", "STRATEGY_ANALYSIS_ADMISSION_MATURE_ADVISORY_GRANTED"
    if evidence.source_family not in maturity_policy.admissible_source_families:
        status, reason = "REJECTED", "ADVISORY_SOURCE_FAMILY_NOT_ADMISSIBLE"
    elif evidence.direction_lineage_alignment == "CONFLICT":
        status, reason = "SUSPENDED", "ADVISORY_DIRECTION_LINEAGE_CONFLICT"
    elif expired:
        status, reason = "REJECTED", "ADVISORY_PRESSURE_EXPIRED"
    elif evidence.pressure_direction not in {"BUY", "SELL"} or evidence.direction_lineage_alignment != "ALIGNED":
        status, reason = "SUSPENDED", "STRATEGY_ANALYSIS_ADMISSION_SUSPENDED"
    elif not evidence.evidence_coverage_sufficient:
        status, reason = "REJECTED", "ADVISORY_EVIDENCE_COVERAGE_INSUFFICIENT"
    elif not evidence.eligible_for_context_resolution:
        status, reason = "REJECTED", "ADVISORY_CONTEXT_RESOLUTION_INELIGIBLE"
    elif maturity == "IMMATURE":
        status, reason = "REJECTED", "ADVISORY_PRESSURE_IMMATURE"
    granted = status == "GRANTED"
    admission = StrategyAnalysisAdmissionV31(
        strategy_analysis_admission_id=strategy_analysis_admission_id_v31(
            market_episode_id=episode.market_episode_id,
            admission_class="MATURE_ADVISORY",
            source_anchor=maturity_policy.policy_hash,
        ),
        symbol=episode.canonical_symbol,
        market_episode_id=episode.market_episode_id,
        admission_class="MATURE_ADVISORY",
        admission_status=status,
        analysis_authority="FULL_SHADOW_ANALYSIS",
        source_authority="DERIVED_PRESSURE_ADVISORY",
        pair_admission_evaluation_id=None,
        pair_admission_coverage_id=coverage.pair_admission_coverage_id,
        pressure_direction=evidence.pressure_direction,
        direction_lineage_alignment=evidence.direction_lineage_alignment,
        advisory_maturity=maturity,
        advisory_maturity_policy_version=maturity_policy.policy_version,
        context_resolution_allowed=granted,
        structural_evidence_prefetch_required=granted,
        tradeplan_candidate_allowed=granted,  # SHADOW_ONLY candidate (§7A.2)
        promotion_eligibility="SHADOW_ONLY",
        reason_code=reason,
        evidence_hash=evidence.evidence_hash,
        granted_at_utc=decision_at if granted else None,
        expires_at_utc=decision_at + timedelta(seconds=policy.advisory_analysis_ttl_seconds) if granted else None,
        advisory_maturity_policy_hash=maturity_policy.policy_hash,
        admission_policy_version=policy.policy_version,
        admission_policy_hash=policy.policy_hash,
        decided_at_utc=decision_at,
    )
    return AdmissionDecisionV31("DECIDED", reason, admission)


def build_admission_receipt_v31(
    *,
    admission: StrategyAnalysisAdmissionV31,
    episode: MarketEpisodeV31,
    coverage: PairAdmissionCoverageV1,
    evaluation: PairAdmissionEvaluationRefV31 | None,
    evidence: AdvisoryPressureEvidenceV31 | None,
) -> StrategyAnalysisAdmissionReceiptV31:
    """Bind the admission to exactly the inputs it names. Raises on any mismatch (never a partial receipt)."""

    admission = StrategyAnalysisAdmissionV31.model_validate(admission.model_dump())
    episode = MarketEpisodeV31.model_validate(episode.model_dump())
    coverage = PairAdmissionCoverageV1.model_validate(coverage.model_dump())
    if (admission.market_episode_id, admission.pair_admission_coverage_id) != (
        episode.market_episode_id,
        coverage.pair_admission_coverage_id,
    ):
        raise ValueError("RECEIPT_EPISODE_OR_COVERAGE_MISMATCH")
    canonical = admission.admission_class == "CANONICAL_RAW"
    if canonical:
        if evaluation is None or evidence is not None:
            raise ValueError("CANONICAL_RAW receipt binds its evaluation and no advisory evidence")
        if evaluation.admission_evaluation_id != admission.pair_admission_evaluation_id:
            raise ValueError("RECEIPT_EVALUATION_MISMATCH")
    else:
        if evidence is None or evaluation is not None:
            raise ValueError("MATURE_ADVISORY receipt binds its evidence and no PairAdmission evaluation")
        if evidence.evidence_hash != admission.evidence_hash:
            raise ValueError("RECEIPT_EVIDENCE_MISMATCH")
    return StrategyAnalysisAdmissionReceiptV31(
        strategy_analysis_admission_id=admission.strategy_analysis_admission_id,
        admission_record_hash=strategy_analysis_admission_hash_v31(admission),
        market_episode_id=episode.market_episode_id,
        strategy_lifecycle_id=strategy_lifecycle_id_from_episode_v31(episode.market_episode_id),
        symbol=admission.symbol,
        admission_class=admission.admission_class,
        admission_status=admission.admission_status,
        analysis_authority=admission.analysis_authority,
        promotion_eligibility=admission.promotion_eligibility,
        pressure_direction=admission.pressure_direction,
        pair_admission_coverage_id=coverage.pair_admission_coverage_id,
        coverage_record_hash=canonical_sha256_v31(coverage.model_dump(mode="json")),
        pair_admission_evaluation_id=None if evaluation is None else evaluation.admission_evaluation_id,
        pair_admission_evaluation_hash=None if evaluation is None else evaluation.evaluation_hash,
        advisory_evidence_hash=None if evidence is None else evidence.evidence_hash,
        advisory_maturity_policy_hash=admission.advisory_maturity_policy_hash,
        granted_at_utc=admission.granted_at_utc,
        expires_at_utc=admission.expires_at_utc,
    )


__all__ = [
    "AdmissionDecisionV31",
    "build_admission_receipt_v31",
    "classify_advisory_maturity_v31",
    "evaluate_canonical_raw_admission_v31",
    "evaluate_mature_advisory_admission_v31",
]
