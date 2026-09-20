"""D8: NativeOrderedProofProjectionV31 + NativeOrderedProofVerifierV31 (owner P1–P5, 2026-09-20).

    #497 StructuralProofEvidenceV31 + authoritative #498 DirectionalThesisV31 → OrderedProofEvidenceV31 (shape)

Pure and fail-closed. Nothing is trusted from the projection input: the verifier re-derives every field from the
proof, the thesis record and its transition chain, then compares byte-exact. Thesis state is evaluated AS OF the
projection time (replayable). A later SUPERSEDED/INVALIDATED/EXPIRED is not visible here; current-status
revalidation at downstream use is a separate subcontract (P3). Usable downstream =
schema-valid + native-verifier-valid + thesis-current-status-valid.

Requalified on #504 (2026-09-20): a projection may be built from EITHER admission class, because it is
evidence, not permission. The containment of the lineage it came from (promotion eligibility, risk handoff,
admission class) is reported beside the projection and re-reported by the verifier, so no consumer can read
the transport shape alone and assume canonical risk or execution eligibility. None of it enters
``ordered_proof_hash``: an authority upgrade must never rewrite a historical projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from contracts.strategy_5scr_context_epoch_v31 import context_epoch_id_v31
from contracts.strategy_5scr_directional_thesis_v31 import (
    DirectionalThesisTransitionV31,
    DirectionalThesisV31,
    direction_authority_v31,
    thesis_record_hash_v31,
)
from contracts.strategy_5scr_ordered_proof_projection_v31 import (
    native_h1_receipt_hash_v31,
    native_m15_receipt_hash_v31,
    native_projection_policy_hash_v31,
    proof_component_id_v31,
)
from contracts.strategy_5scr_ordered_proof_v31 import OrderedProofEvidenceV31, ordered_proof_hash_v31
from contracts.strategy_5scr_structural_proof_v31 import StructuralProofEvidenceV31


@dataclass(frozen=True)
class ProjectionContainmentV31:
    """What the projected evidence is allowed to mean downstream. Derived from the thesis record; grants nothing.

    It deliberately lives outside ``OrderedProofEvidenceV31`` and outside ``ordered_proof_hash``: the transport
    shape is historical evidence, while containment is read from the lineage the evidence came from.
    """

    analysis_admission_class: Literal["CANONICAL_RAW", "MATURE_ADVISORY"]
    promotion_eligibility: Literal["CANONICAL_RISK_PATH", "SHADOW_ONLY"]
    risk_handoff_allowed: bool
    thesis_record_hash: str
    direction_authority: bool  # ANALYSIS direction authority, from the thesis state as of the projection time
    risk_authorization: Literal[False] = False
    execution_authority: Literal[False] = False
    broker_command_authority: Literal[False] = False


def _containment(thesis: DirectionalThesisV31, *, direction_authority: bool) -> ProjectionContainmentV31:
    return ProjectionContainmentV31(
        analysis_admission_class=thesis.analysis_admission_class,
        promotion_eligibility=thesis.promotion_eligibility,
        risk_handoff_allowed=thesis.risk_handoff_allowed,
        thesis_record_hash=thesis_record_hash_v31(thesis),
        direction_authority=direction_authority,
    )


@dataclass(frozen=True)
class NativeOrderedProofProjectionV31:
    outcome: Literal["PROJECTED", "NOT_PROJECTED"]
    reason_code: str
    projection: OrderedProofEvidenceV31 | None = None
    containment: ProjectionContainmentV31 | None = None


def _no(reason: str) -> NativeOrderedProofProjectionV31:
    return NativeOrderedProofProjectionV31("NOT_PROJECTED", reason)


def _verified_chain(
    thesis: DirectionalThesisV31, transitions: tuple[DirectionalThesisTransitionV31, ...]
) -> tuple[DirectionalThesisTransitionV31, ...] | None:
    """Re-validate every link (its own hash) and the chain (sequence, previous hash, thesis id)."""

    previous: str | None = None
    checked: list[DirectionalThesisTransitionV31] = []
    for sequence, raw in enumerate(transitions, start=1):
        try:
            link = DirectionalThesisTransitionV31.model_validate(raw.model_dump())
        except ValidationError:
            return None
        if (link.strategy_thesis_id, link.sequence, link.previous_transition_hash) != (
            thesis.strategy_thesis_id,
            sequence,
            previous,
        ):
            return None
        previous = link.transition_hash
        checked.append(link)
    return tuple(checked)


def project_ordered_proof_v31(
    *,
    thesis: DirectionalThesisV31,
    transitions: tuple[DirectionalThesisTransitionV31, ...],
    proof: StructuralProofEvidenceV31,
    projected_at: datetime,
) -> NativeOrderedProofProjectionV31:
    if projected_at.tzinfo is None or projected_at.utcoffset() is None:
        raise ValueError("projected_at must be timezone-aware")
    try:
        thesis = DirectionalThesisV31.model_validate(thesis.model_dump())
        proof = StructuralProofEvidenceV31.model_validate(proof.model_dump())
    except ValidationError:
        return _no("NATIVE_INPUT_INVALID")
    chain = _verified_chain(thesis, transitions)
    if chain is None:
        return _no("THESIS_TRANSITION_CHAIN_INVALID")
    as_of = tuple(link for link in chain if link.occurred_at <= projected_at)
    state = as_of[-1].to_state if as_of else "PENDING_H1"
    if not direction_authority_v31(state):
        return _no("THESIS_NOT_AUTHORITATIVE")
    confirmation = next(link for link in as_of if link.to_state == "STRUCTURALLY_CONFIRMED")
    if proof.proof_direction != thesis.direction:
        return _no("PROJECTION_DIRECTION_MISMATCH")
    if (
        proof.strategy_lifecycle_id,
        proof.context_epoch_id,
        proof.canonical_symbol,
        proof.selected_route,
        proof.context_route_evaluation_id,
        proof.proof_class,
    ) != (
        thesis.strategy_lifecycle_id,
        thesis.context_epoch_id,
        thesis.canonical_symbol,
        thesis.selected_route,
        thesis.context_route_evaluation_id,
        thesis.thesis_class,
    ):
        return _no("PROJECTION_SCOPE_MISMATCH")
    if (proof.proof_id, proof.material_evidence_hash) != (
        confirmation.bound_structural_proof_id,
        confirmation.bound_structural_proof_hash,
    ):
        return _no("PROOF_NOT_BOUND_TO_THESIS")
    # The epoch id is UUIDv5 over (lifecycle, material hash): this binds context_material_hash cryptographically.
    if thesis.context_epoch_id != context_epoch_id_v31(
        strategy_lifecycle_id=thesis.strategy_lifecycle_id, material_context_hash=thesis.material_context_hash
    ):
        return _no("PROJECTION_CONTEXT_MATERIAL_NOT_BOUND")
    if not max(proof.m15_closed_at, confirmation.occurred_at) <= projected_at < thesis.valid_until:
        return _no("PROJECTION_CLOCK_INVALID")
    try:
        projection = OrderedProofEvidenceV31.model_validate(
            {
                "profile": "TEST_ONLY",
                "strategy_thesis_id": thesis.strategy_thesis_id,
                "strategy_lifecycle_id": thesis.strategy_lifecycle_id,
                "context_epoch_id": thesis.context_epoch_id,
                "symbol": thesis.canonical_symbol,
                "direction": thesis.direction,
                "selected_route": thesis.selected_route,
                "context_material_hash": thesis.material_context_hash,
                "pattern_policy_hash": native_projection_policy_hash_v31(proof.pattern_registry_hash),
                "level_version": proof.level_version,
                "h1_proof_id": proof_component_id_v31(proof.proof_id, "H1"),
                "m15_proof_id": proof_component_id_v31(proof.proof_id, "M15"),
                "h1_source_candles": proof.h1_source_candles,
                "m15_source_candles": proof.m15_source_candles,
                "h1_closed_at": proof.h1_closed_at,
                "m15_closed_at": proof.m15_closed_at,
                "m15_break_candle_id": proof.m15_break_candle_id,
                "m15_completion_candle_id": proof.m15_completion_candle_id,
                "m15_completion_kind": proof.m15_completion_kind,
                "h1_resolution_receipt_hash": native_h1_receipt_hash_v31(proof),
                "m15_resolution_receipt_hash": native_m15_receipt_hash_v31(proof),
                "evaluated_at": projected_at,  # projection-event metadata; not identity
                "valid_until": thesis.valid_until,  # P3: max actionability deadline, not proof expiry; no new TTL
            }
        )
    except ValidationError:
        return _no("PROJECTION_SHAPE_INVALID")
    return NativeOrderedProofProjectionV31(
        "PROJECTED", "ORDERED_PROOF_PROJECTED", projection, _containment(thesis, direction_authority=True)
    )


@dataclass(frozen=True)
class NativeOrderedProofVerificationV31:
    valid: bool
    reason_code: str
    containment: ProjectionContainmentV31 | None = None


class NativeOrderedProofVerifierV31:
    """Re-derive the projection from native authority at its own ``evaluated_at`` and compare byte-exact.

    It grants nothing. It never accepts ReferencePatternPolicyV31 semantics, and it does not check current thesis
    status (separate subcontract).
    """

    def verify(
        self,
        projection: OrderedProofEvidenceV31,
        *,
        proof: StructuralProofEvidenceV31,
        thesis: DirectionalThesisV31,
        transitions: tuple[DirectionalThesisTransitionV31, ...],
        expected_thesis_record_hash: str | None = None,
    ) -> NativeOrderedProofVerificationV31:
        """``expected_thesis_record_hash`` pins the EXACT thesis record, not merely its id.

        The containment fields are absent from ``ordered_proof_hash`` by design, so two thesis records with the
        same id but different promotion eligibility would both re-derive the same projection. A consumer that
        stored the record hash beside the projection can therefore prove which lineage object it verified against.
        """

        try:
            projection = OrderedProofEvidenceV31.model_validate(projection.model_dump())
        except ValidationError:
            return NativeOrderedProofVerificationV31(False, "PROJECTION_SHAPE_INVALID")
        derived = project_ordered_proof_v31(
            thesis=thesis, transitions=transitions, proof=proof, projected_at=projection.evaluated_at
        )
        if derived.projection is None:
            return NativeOrderedProofVerificationV31(False, derived.reason_code)
        if derived.projection != projection or ordered_proof_hash_v31(derived.projection) != ordered_proof_hash_v31(
            projection
        ):
            # Field-by-field AND by hash: the record comparison does not depend on what the transport hash covers.
            return NativeOrderedProofVerificationV31(False, "PROJECTION_NOT_NATIVELY_DERIVED")
        containment = derived.containment
        assert containment is not None
        if expected_thesis_record_hash is not None and expected_thesis_record_hash != containment.thesis_record_hash:
            return NativeOrderedProofVerificationV31(False, "THESIS_RECORD_HASH_MISMATCH", containment)
        return NativeOrderedProofVerificationV31(True, "NATIVE_PROJECTION_VERIFIED", containment)


__all__ = [
    "NativeOrderedProofProjectionV31",
    "ProjectionContainmentV31",
    "NativeOrderedProofVerificationV31",
    "NativeOrderedProofVerifierV31",
    "project_ordered_proof_v31",
]
