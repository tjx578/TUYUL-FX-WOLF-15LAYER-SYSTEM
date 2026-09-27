"""StrategyAnalysisAdmissionReceiptV31: the analysis-authority receipt consumed downstream (#493 replacement).

SUPERSEDES #493 ``AdmissionReceiptV31``, which was built from a PairAdmission lineage and derived both
``strategy_analysis_admission_id`` and ``strategy_lifecycle_id`` from it: that collapsed three v3.1 objects
(PairAdmission ≠ StrategyAnalysisAdmission ≠ AnalysisLifecycle, §2.4) into one.

The replacement binds, and never derives:
    StrategyAnalysisAdmissionV31 (#502) + its GRANTED revision and lifecycle attachment (#503)
    + AnalysisLifecycleV31 (#503, id from MarketEpisodeV31 #501) + PairAdmissionCoverageV1 (#501)
    + the class source: a PairAdmission evaluation (CANONICAL_RAW) or advisory evidence (MATURE_ADVISORY).
PairAdmission is only one possible source of a CANONICAL_RAW admission; a MATURE_ADVISORY receipt carries no
PairAdmission at all. Only GRANTED, attached admissions have receipts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_analysis_admission_v31 import (
    AdmissionClass,
    AnalysisAuthority,
    PressureDirection,
    PromotionEligibility,
    SourceAuthority,
)
from contracts.strategy_5scr_identity_v31 import IDENTITY_ENCODING_VERSION, canonical_sha256_v31
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31

ADMISSION_RECEIPT_V31_RULE_VERSION = "5scr.strategy-analysis-admission-receipt.v31.v2"
_DIGEST = r"^sha256:[0-9a-f]{64}$"
_CLASS_SCOPE: dict[str, tuple[str, str, str]] = {
    "CANONICAL_RAW": ("FULL_CANONICAL_ANALYSIS", "RAW_SIGNALTHROTTLE_LEDGER", "CANONICAL_RISK_PATH"),
    "MATURE_ADVISORY": ("FULL_SHADOW_ANALYSIS", "DERIVED_PRESSURE_ADVISORY", "SHADOW_ONLY"),
}


class StrategyAnalysisAdmissionReceiptV31(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    rule_version: Literal["5scr.strategy-analysis-admission-receipt.v31.v2"] = ADMISSION_RECEIPT_V31_RULE_VERSION
    identity_encoding_version: Literal["v31.native-identity.v1"] = IDENTITY_ENCODING_VERSION
    admission_contract_version: Literal["strategy-analysis-admission.v31.v1"]
    # admission record + revision identity (#502/#503)
    strategy_analysis_admission_id: UUID
    admission_record_hash: str = Field(pattern=_DIGEST)
    admission_revision_id: UUID
    admission_revision_number: int = Field(ge=1)
    admission_revision_hash: str = Field(pattern=_DIGEST)
    # lifecycle binding (#501/#503)
    market_episode_id: UUID
    strategy_lifecycle_id: UUID
    lifecycle_attachment_hash: str = Field(pattern=_DIGEST)
    symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    # admission semantics (§7A.4)
    admission_class: AdmissionClass
    admission_status: Literal["GRANTED"]
    analysis_authority: AnalysisAuthority
    source_authority: SourceAuthority
    promotion_eligibility: PromotionEligibility
    pressure_direction: PressureDirection
    # sources
    pair_admission_coverage_id: UUID
    coverage_record_hash: str = Field(pattern=_DIGEST)
    pair_admission_evaluation_id: UUID | None
    pair_admission_evaluation_hash: str | None = Field(pattern=_DIGEST)
    advisory_evidence_hash: str | None = Field(pattern=_DIGEST)
    advisory_maturity_policy_hash: str | None = Field(pattern=_DIGEST)
    granted_at_utc: datetime
    expires_at_utc: datetime
    risk_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def _bound(self) -> StrategyAnalysisAdmissionReceiptV31:
        for moment in (self.granted_at_utc, self.expires_at_utc):
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError("timestamps must be timezone-aware")
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("RECEIPT_LIFECYCLE_NOT_DERIVED_FROM_EPISODE")
        if (self.analysis_authority, self.source_authority, self.promotion_eligibility) != _CLASS_SCOPE[
            self.admission_class
        ]:
            raise ValueError("RECEIPT_CLASS_SCOPE_MISMATCH")
        canonical = self.admission_class == "CANONICAL_RAW"
        if canonical != (self.pair_admission_evaluation_id is not None) or canonical != (
            self.pair_admission_evaluation_hash is not None
        ):
            raise ValueError("only CANONICAL_RAW receipts bind a PairAdmission evaluation")
        if canonical == (self.advisory_evidence_hash is not None) or canonical == (
            self.advisory_maturity_policy_hash is not None
        ):
            raise ValueError("only MATURE_ADVISORY receipts bind advisory evidence and maturity policy")
        if self.pressure_direction not in {"BUY", "SELL"} or not self.granted_at_utc < self.expires_at_utc:
            raise ValueError("a GRANTED receipt carries a definite direction and a positive validity window")
        return self


def admission_receipt_hash_v31(receipt: StrategyAnalysisAdmissionReceiptV31) -> str:
    return canonical_sha256_v31(receipt.model_dump(mode="json"))


__all__ = ["ADMISSION_RECEIPT_V31_RULE_VERSION", "StrategyAnalysisAdmissionReceiptV31", "admission_receipt_hash_v31"]
