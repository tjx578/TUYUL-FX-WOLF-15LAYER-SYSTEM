"""AnalysisLifecycleV31 + append-only admission/attachment/upgrade ledgers (S1B-2, SSOT v3.1 §4.2, §7A.6, §8).

- The lifecycle id is derived from the market episode (S1B-0) and never from an admission. Class changes,
  deployment and restart therefore never change it (§8.3).
- Admissions attach to the lifecycle (1..N, §4.2). ``highest_analysis_authority`` and the active admission are
  DERIVED from the attached lineage and re-verified by the validator; they are never free fields.
- CANONICAL_RAW > MATURE_ADVISORY. An advisory → canonical attach appends an authority upgrade that forces a
  canonical re-evaluation; advisory candidates are never reused as canonical (§7A.6, §8.6). No downgrade (§8.6):
  expiry of a grant never removes historical canonical lineage.
- Admission decisions are revisions of a stable logical admission id: append-only, hash-chained, never overwritten.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.strategy_5scr_analysis_admission_v31 import AdmissionClass, AdmissionStatus
from contracts.strategy_5scr_market_episode_v31 import (
    IDENTITY_ENCODING_VERSION,
    DirectionState,
    canonical_sha256_v31,
    strategy_lifecycle_id_from_episode_v31,
)

ANALYSIS_LIFECYCLE_V31_RULE_VERSION = "5scr.analysis-lifecycle.v31.v1"
V31_ADMISSION_REVISION_NAMESPACE = UUID("7761d6fe-ae9a-42b2-8a5d-9db44c7a130a")

LifecycleState = Literal[  # §8.4 minimum; this increment emits ANALYSIS_OPEN only
    "ANALYSIS_QUEUED",
    "ANALYSIS_OPEN",
    "WAITING_PRICE_COVERAGE",
    "WAITING_PRICE_QUALITY",
    "WAITING_CONTEXT",
    "WAITING_STRUCTURE",
    "CONDITIONAL_SETUP",
    "TRADEPLAN_READY_NON_EXECUTABLE",
    "TRANSITION_PENDING",
    "TERMINAL_NO_TRADE",
    "INVALIDATED",
    "SUPERSEDED",
    "SUSPENDED_DATA_QUALITY",
]
AUTHORITY_RANK: dict[str, int] = {"MATURE_ADVISORY": 1, "CANONICAL_RAW": 2}
_DIGEST = r"^sha256:[0-9a-f]{64}$"


def _aware(*moments: datetime | None) -> None:
    for moment in moments:
        if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")


def _body_hash(model: BaseModel, hash_field: str) -> str:
    return canonical_sha256_v31({k: v for k, v in model.model_dump(mode="json").items() if k != hash_field})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def derive_highest_authority_v31(classes: tuple[str, ...]) -> AdmissionClass:
    if not classes:
        raise ValueError("a lifecycle is opened only by a GRANTED admission (§8.1)")
    return "CANONICAL_RAW" if "CANONICAL_RAW" in classes else "MATURE_ADVISORY"


def admission_revision_id_v31(*, strategy_analysis_admission_id: UUID, revision_number: int) -> UUID:
    name = json.dumps(
        [IDENTITY_ENCODING_VERSION, str(strategy_analysis_admission_id), revision_number], separators=(",", ":")
    )
    return uuid5(V31_ADMISSION_REVISION_NAMESPACE, name)


class AdmissionRevisionV31(_Strict):
    """One append-only decision revision of a stable logical admission id. Never overwritten."""

    strategy_analysis_admission_id: UUID
    market_episode_id: UUID
    admission_class: AdmissionClass
    revision_number: int = Field(ge=1)
    revision_id: UUID
    supersedes_revision_id: UUID | None
    previous_revision_hash: str | None = Field(pattern=_DIGEST)
    recorded_at: datetime
    admission_status: AdmissionStatus
    reason_code: str = Field(min_length=3, max_length=200)
    admission_record_hash: str | None = Field(pattern=_DIGEST)  # None only for the terminal EXPIRED revision
    revision_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _chained(self) -> AdmissionRevisionV31:
        _aware(self.recorded_at)
        expected = admission_revision_id_v31(
            strategy_analysis_admission_id=self.strategy_analysis_admission_id, revision_number=self.revision_number
        )
        if self.revision_id != expected:
            raise ValueError("ADMISSION_REVISION_ID_NOT_DERIVED")
        first = self.revision_number == 1
        if first != (self.supersedes_revision_id is None) or first != (self.previous_revision_hash is None):
            raise ValueError("only revision 1 supersedes nothing")
        if (self.admission_status == "EXPIRED") != (self.admission_record_hash is None):
            raise ValueError("EXPIRED is the only revision without a decision record")
        if self.admission_status == "PENDING":
            raise ValueError("PENDING is not a durable decision revision")
        if self.revision_hash != _body_hash(self, "revision_hash"):
            raise ValueError("ADMISSION_REVISION_HASH_MISMATCH")
        return self


class LifecycleAttachmentV31(_Strict):
    strategy_lifecycle_id: UUID
    market_episode_id: UUID
    sequence: int = Field(ge=1)
    strategy_analysis_admission_id: UUID
    admission_class: AdmissionClass
    attached_revision_id: UUID
    attached_at: datetime
    previous_attachment_hash: str | None = Field(pattern=_DIGEST)
    attachment_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _chained(self) -> LifecycleAttachmentV31:
        _aware(self.attached_at)
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("ATTACHMENT_LIFECYCLE_NOT_DERIVED_FROM_EPISODE")
        if (self.sequence == 1) != (self.previous_attachment_hash is None):
            raise ValueError("only the first attachment has no predecessor")
        if self.attachment_hash != _body_hash(self, "attachment_hash"):
            raise ValueError("ATTACHMENT_HASH_MISMATCH")
        return self


class AuthorityUpgradeV31(_Strict):
    """§7A.6/§8.6: append-only; forces canonical re-evaluation; advisory candidates are never reused."""

    strategy_lifecycle_id: UUID
    market_episode_id: UUID
    symbol: str
    from_authority: Literal["MATURE_ADVISORY"]
    to_authority: Literal["CANONICAL_RAW"]
    trigger_admission_id: UUID
    superseded_active_admission_id: UUID
    occurred_at: datetime
    reason_code: Literal["ADVISORY_TO_CANONICAL_AUTHORITY_UPGRADE"] = "ADVISORY_TO_CANONICAL_AUTHORITY_UPGRADE"
    required_action: Literal["ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"] = (
        "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )
    advisory_candidate_reused_as_canonical: Literal[False] = False
    upgrade_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _bound(self) -> AuthorityUpgradeV31:
        _aware(self.occurred_at)
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("UPGRADE_LIFECYCLE_NOT_DERIVED_FROM_EPISODE")
        if self.trigger_admission_id == self.superseded_active_admission_id:
            raise ValueError("an upgrade needs a distinct canonical admission")
        if self.upgrade_hash != _body_hash(self, "upgrade_hash"):
            raise ValueError("UPGRADE_HASH_MISMATCH")
        return self


class AnalysisLifecycleV31(_Strict):
    """SSOT §8.2 AnalysisLifecycleV3_1 as a verified read view over the ledgers."""

    lifecycle_rule_version: Literal["5scr.analysis-lifecycle.v31.v1"] = ANALYSIS_LIFECYCLE_V31_RULE_VERSION
    strategy_lifecycle_id: UUID
    market_episode_id: UUID
    symbol: str = Field(pattern=r"^[A-Z0-9._-]{3,32}$")
    state: LifecycleState
    highest_analysis_authority: AdmissionClass
    active_strategy_analysis_admission_id: UUID
    admission_lineage_ids: tuple[UUID, ...] = Field(min_length=1)
    admission_lineage_classes: tuple[AdmissionClass, ...] = Field(min_length=1)  # audit: aligned with the ids
    direction_state: DirectionState
    opened_at_utc: datetime
    last_event_at_utc: datetime
    last_material_event_at_utc: datetime
    active_context_epoch_id: UUID | None  # wired after the #495 rebase
    active_pressure_hypothesis_id: UUID | None  # wired after the #494 rebase
    execution_authority: Literal[False] = False
    material_state_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _derived(self) -> AnalysisLifecycleV31:
        _aware(self.opened_at_utc, self.last_event_at_utc, self.last_material_event_at_utc)
        if self.strategy_lifecycle_id != strategy_lifecycle_id_from_episode_v31(self.market_episode_id):
            raise ValueError("LIFECYCLE_ID_NOT_DERIVED_FROM_EPISODE")
        if len(self.admission_lineage_ids) != len(self.admission_lineage_classes) or len(
            set(self.admission_lineage_ids)
        ) != len(self.admission_lineage_ids):
            raise ValueError("admission lineage must be unique and class-aligned")
        highest = derive_highest_authority_v31(self.admission_lineage_classes)
        if self.highest_analysis_authority != highest:
            raise ValueError("HIGHEST_ANALYSIS_AUTHORITY_NOT_DERIVED")
        active = next(
            i
            for i, c in reversed(tuple(zip(self.admission_lineage_ids, self.admission_lineage_classes)))
            if c == highest
        )
        if self.active_strategy_analysis_admission_id != active:
            raise ValueError("ACTIVE_ADMISSION_NOT_DERIVED")
        if self.material_state_hash != _body_hash(self, "material_state_hash"):
            raise ValueError("LIFECYCLE_MATERIAL_STATE_HASH_MISMATCH")
        return self


__all__ = [
    "ANALYSIS_LIFECYCLE_V31_RULE_VERSION",
    "AUTHORITY_RANK",
    "V31_ADMISSION_REVISION_NAMESPACE",
    "AdmissionRevisionV31",
    "AnalysisLifecycleV31",
    "AuthorityUpgradeV31",
    "LifecycleAttachmentV31",
    "admission_revision_id_v31",
    "derive_highest_authority_v31",
]
