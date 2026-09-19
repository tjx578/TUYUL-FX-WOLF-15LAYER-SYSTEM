"""Build StrategyAnalysisAdmissionReceiptV31 by binding (never deriving) the S1B lineage (#493 replacement).

Every input is re-validated. Any mismatch raises ``ValueError`` with a reason code; a partial receipt is never
returned. No lifecycle or admission identity is computed here: both come from their authority objects.
"""

from __future__ import annotations

from contracts.strategy_5scr_admission_receipt_v31 import StrategyAnalysisAdmissionReceiptV31
from contracts.strategy_5scr_analysis_admission_v31 import (
    AdvisoryPressureEvidenceV31,
    StrategyAnalysisAdmissionV31,
    strategy_analysis_admission_hash_v31,
)
from contracts.strategy_5scr_analysis_lifecycle_v31 import (
    AdmissionRevisionV31,
    AnalysisLifecycleV31,
    LifecycleAttachmentV31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_market_episode_v31 import MarketEpisodeV31
from contracts.strategy_5scr_pair_admission_coverage_v31 import (
    PairAdmissionCoverageV1,
    PairAdmissionEvaluationRefV31,
)


def build_strategy_analysis_admission_receipt_v31(
    *,
    admission: StrategyAnalysisAdmissionV31,
    revision: AdmissionRevisionV31,
    attachment: LifecycleAttachmentV31,
    lifecycle: AnalysisLifecycleV31,
    episode: MarketEpisodeV31,
    coverage: PairAdmissionCoverageV1,
    evaluation: PairAdmissionEvaluationRefV31 | None,
    evidence: AdvisoryPressureEvidenceV31 | None,
) -> StrategyAnalysisAdmissionReceiptV31:
    admission = StrategyAnalysisAdmissionV31.model_validate(admission.model_dump())
    revision = AdmissionRevisionV31.model_validate(revision.model_dump())
    attachment = LifecycleAttachmentV31.model_validate(attachment.model_dump())
    lifecycle = AnalysisLifecycleV31.model_validate(lifecycle.model_dump())
    episode = MarketEpisodeV31.model_validate(episode.model_dump())
    coverage = PairAdmissionCoverageV1.model_validate(coverage.model_dump())
    admission_id = admission.strategy_analysis_admission_id
    record_hash = strategy_analysis_admission_hash_v31(admission)

    if admission.admission_status != "GRANTED":
        raise ValueError("RECEIPT_REQUIRES_GRANTED_ADMISSION")
    if (
        revision.strategy_analysis_admission_id != admission_id
        or revision.admission_status != "GRANTED"
        or revision.admission_record_hash != record_hash
        or revision.admission_class != admission.admission_class
    ):
        raise ValueError("ADMISSION_REVISION_MISMATCH")
    # Lifecycle authority (#501/#503): bound and cross-checked, never derived here.
    if not admission.market_episode_id == episode.market_episode_id == lifecycle.market_episode_id:
        raise ValueError("RECEIPT_MARKET_EPISODE_MISMATCH")
    if not episode.strategy_lifecycle_id == lifecycle.strategy_lifecycle_id == attachment.strategy_lifecycle_id:
        raise ValueError("RECEIPT_LIFECYCLE_MISMATCH")
    if (attachment.strategy_analysis_admission_id, attachment.attached_revision_id, attachment.admission_class) != (
        admission_id,
        revision.revision_id,
        admission.admission_class,
    ):
        raise ValueError("RECEIPT_ATTACHMENT_MISMATCH")
    lineage = dict(zip(lifecycle.admission_lineage_ids, lifecycle.admission_lineage_classes, strict=True))
    if lineage.get(admission_id) != admission.admission_class:
        raise ValueError("ADMISSION_NOT_IN_LIFECYCLE_LINEAGE")
    if admission.pair_admission_coverage_id != coverage.pair_admission_coverage_id:
        raise ValueError("RECEIPT_COVERAGE_MISMATCH")
    if admission.admission_class == "CANONICAL_RAW":
        if evaluation is None or evidence is not None:
            raise ValueError("CANONICAL_RAW receipt binds its PairAdmission evaluation and no advisory evidence")
        evaluation = PairAdmissionEvaluationRefV31.model_validate(evaluation.model_dump())
        if (evaluation.admission_evaluation_id, evaluation.admission_evaluation_id) != (
            admission.pair_admission_evaluation_id,
            coverage.admission_evaluation_id,
        ):
            raise ValueError("RECEIPT_EVALUATION_MISMATCH")
    else:
        if evidence is None or evaluation is not None:
            raise ValueError("MATURE_ADVISORY receipt binds advisory evidence and no PairAdmission evaluation")
        evidence = AdvisoryPressureEvidenceV31.model_validate(evidence.model_dump())
        if (evidence.evidence_hash, evidence.market_episode_id) != (
            admission.evidence_hash,
            admission.market_episode_id,
        ):
            raise ValueError("RECEIPT_EVIDENCE_MISMATCH")
    assert admission.granted_at_utc is not None and admission.expires_at_utc is not None
    return StrategyAnalysisAdmissionReceiptV31(
        admission_contract_version=admission.contract_version,
        strategy_analysis_admission_id=admission_id,
        admission_record_hash=record_hash,
        admission_revision_id=revision.revision_id,
        admission_revision_number=revision.revision_number,
        admission_revision_hash=revision.revision_hash,
        market_episode_id=episode.market_episode_id,
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        lifecycle_attachment_hash=attachment.attachment_hash,
        symbol=admission.symbol,
        admission_class=admission.admission_class,
        admission_status="GRANTED",
        analysis_authority=admission.analysis_authority,
        source_authority=admission.source_authority,
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


__all__ = ["build_strategy_analysis_admission_receipt_v31"]
