"""Immutable TEST_ONLY candidate evaluation receipt, never order authority."""

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31
from contracts.strategy_5scr_capacity_v31 import CapacityProposalV31
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract

Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class CandidateRevisionAppendV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    revision_policy_id: Literal["APPEND_REEVALUATED_CANDIDATE_TEST_V1"]
    handoff: CandidateHandoffV31
    predecessor_hash: Digest | None
    reevaluation_id: UUID
    reevaluation_receipt_hash: Digest

    @model_validator(mode="after")
    def predecessor(self):
        if (self.handoff.candidate.tradeplan_revision == 1) != (self.predecessor_hash is None):
            raise ValueError("CANDIDATE_PREDECESSOR_REQUIRED")
        return self


def candidate_revision_hash_v31(request: CandidateRevisionAppendV31) -> str:
    body = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(body.encode()).hexdigest()


class StoredCandidateRevisionV31(GeometryContract):
    request: CandidateRevisionAppendV31
    request_hash: Digest

    @model_validator(mode="after")
    def integrity(self):
        if candidate_revision_hash_v31(self.request) != self.request_hash:
            raise ValueError("CANDIDATE_STORED_HASH_MISMATCH")
        return self


class CandidateCapacityPreparationV31(GeometryContract):
    """Tentative result for the same caller transaction, never a committed ACK."""

    profile: Literal["TEST_ONLY"]
    candidate_revision: StoredCandidateRevisionV31
    capacity: CapacityProposalV31
    durable_commit: Literal[False] = False
    capital_reservation_authority: Literal[False] = False
    execution_authority: Literal[False] = False

    @model_validator(mode="after")
    def identity(self):
        candidate = self.candidate_revision.request.handoff.candidate
        reservation = self.capacity.reservation
        if (
            (reservation.tradeplan_id, reservation.tradeplan_revision, reservation.thesis_id)
            != (str(candidate.tradeplan_id), candidate.tradeplan_revision, str(candidate.strategy_thesis_id))
            or candidate.analysis_admission_class != "CANONICAL_RAW"
            or reservation.strategy_candidate_receipt_hash is None
        ):
            raise ValueError("CANDIDATE_CAPACITY_PREPARATION_IDENTITY_MISMATCH")
        return self


def prepare_candidate_revision_v31(
    request: CandidateRevisionAppendV31,
    previous: StoredCandidateRevisionV31 | None,
    *,
    now: datetime,
    verify_reevaluation: Callable[[CandidateRevisionAppendV31, str], bool] | None,
) -> StoredCandidateRevisionV31:
    """Validate a new append; duplicate handling belongs to the locked store.

    The verifier must bind complete S3-S5 re-evaluation and individual authority
    clocks. Receipt references alone do not prove those domain requirements.
    """
    request = CandidateRevisionAppendV31.model_validate(request.model_dump())
    previous = StoredCandidateRevisionV31.model_validate(previous.model_dump()) if previous else None
    candidate = request.handoff.candidate
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or not candidate.decision_at <= now < request.handoff.handoff_receipt_valid_until
    ):
        raise ValueError("CANDIDATE_REVISION_RECEIPT_EXPIRED")
    if previous is None:
        if candidate.tradeplan_revision != 1:
            raise ValueError("CANDIDATE_INITIAL_REVISION_REQUIRED")
    else:
        prior = previous.request.handoff.candidate
        if (
            candidate.tradeplan_revision != prior.tradeplan_revision + 1
            or request.predecessor_hash != previous.request_hash
        ):
            raise ValueError("CANDIDATE_REVISION_PREDECESSOR_CONFLICT")
        immutable = ("tradeplan_id", "symbol", "strategy_lifecycle_id", "strategy_thesis_id", "direction")
        if any(getattr(candidate, field) != getattr(prior, field) for field in immutable):
            raise ValueError("CANDIDATE_PLAN_SCOPE_CHANGED")
        if (
            candidate.decision_at <= prior.decision_at
            or request.reevaluation_id == previous.request.reevaluation_id
            or request.reevaluation_receipt_hash == previous.request.reevaluation_receipt_hash
        ):
            raise ValueError("CANDIDATE_FRESH_REEVALUATION_REQUIRED")
        if (
            prior.analysis_admission_class == "MATURE_ADVISORY"
            and candidate.analysis_admission_class == "CANONICAL_RAW"
            and (
                candidate.strategy_analysis_admission_id == prior.strategy_analysis_admission_id
                or request.handoff.admission_receipt_hash == previous.request.handoff.admission_receipt_hash
            )
        ):
            raise ValueError("CANDIDATE_CANONICAL_ADMISSION_REBIND_REQUIRED")
    digest = candidate_revision_hash_v31(request)
    if verify_reevaluation is None or verify_reevaluation(request, digest) is not True:
        raise ValueError("CANDIDATE_REEVALUATION_VERIFICATION_REJECTED")
    if candidate_revision_hash_v31(request) != digest:
        raise ValueError("CANDIDATE_REEVALUATION_CHANGED")
    return StoredCandidateRevisionV31(request=request, request_hash=digest)
