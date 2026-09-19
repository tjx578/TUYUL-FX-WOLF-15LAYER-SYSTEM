"""Native derivations for projecting #497 proof + #498 thesis into ``OrderedProofEvidenceV31`` (D8, owner P1–P5).

``OrderedProofEvidenceV31`` is an existing transport/handoff SHAPE. It gains no authority from this module:
evidence authority stays with ``StructuralProofEvidenceV31.proof_id`` and direction authority with the thesis.

- P1: ``pattern_policy_hash`` is a domain-separated NATIVE policy hash over the #497 registry hash. It never
  claims ``ReferencePatternPolicyV31`` semantics, so the reference verifier rejects a native projection by design.
- P2: H1/M15 receipts are material-only (no evaluated_at, valid_until, thesis clock or runtime timestamp); the M15
  receipt is chained to the H1 receipt. The same proof always yields the same receipts.
- P4: H1/M15 "proof ids" are deterministic COMPONENT ids of the one proof bundle, not new proof objects.

Identity hierarchy: proof_id = evidence identity; thesis_id = direction-authority identity;
ordered_proof_hash = projection-instance integrity (it includes evaluated_at, so it is never an identity key).
"""

from __future__ import annotations

import json
from typing import Literal
from uuid import UUID, uuid5

from contracts.strategy_5scr_admission_identity_v31 import IDENTITY_ENCODING_VERSION
from contracts.strategy_5scr_pressure_hypothesis_v31 import canonical_sha256_v31
from contracts.strategy_5scr_structural_proof_v31 import StructuralProofEvidenceV31

V31_PROOF_COMPONENT_NAMESPACE = UUID("8a20958f-83aa-4112-a434-7fb9182addd0")
NATIVE_PROJECTION_POLICY_VERSION = "v31.native-structural-proof-projection.v1"
NATIVE_COMPONENT_RECEIPT_VERSION = "5scr.native-proof-component-receipt.v31.v1"
ProofComponent = Literal["H1", "M15"]


def native_projection_policy_hash_v31(structural_pattern_registry_hash: str) -> str:
    """P1: domain-separated; never equal to a raw registry hash or a ReferencePatternPolicyV31 hash."""

    return canonical_sha256_v31(
        {
            "policy_version": NATIVE_PROJECTION_POLICY_VERSION,
            "structural_pattern_registry_hash": structural_pattern_registry_hash,
        }
    )


def proof_component_id_v31(proof_id: UUID, component: ProofComponent) -> UUID:
    """P4: points into the SAME proof bundle; the authoritative identity remains ``proof_id``."""

    name = json.dumps([IDENTITY_ENCODING_VERSION, str(proof_id), component], separators=(",", ":"))
    return uuid5(V31_PROOF_COMPONENT_NAMESPACE, name)


def _material_header(proof: StructuralProofEvidenceV31, component: ProofComponent) -> dict[str, object]:
    return {
        "receipt_version": NATIVE_COMPONENT_RECEIPT_VERSION,
        "component": component,
        "structural_proof_id": str(proof.proof_id),
        "structural_proof_hash": proof.material_evidence_hash,
        "pattern_id": proof.pattern_id,
        "pattern_registry_hash": proof.pattern_registry_hash,
        "level_version": proof.level_version,
    }


def native_h1_receipt_hash_v31(proof: StructuralProofEvidenceV31) -> str:
    anchor, confirmation = proof.h1_source_candles
    return canonical_sha256_v31(
        {
            **_material_header(proof, "H1"),
            "source_candle_ids": [anchor.candle_evidence_id, confirmation.candle_evidence_id],
            "closed_at": proof.h1_closed_at.isoformat(),  # candle material, not a runtime clock
            "structure_evidence": proof.h1_structure_evidence.model_dump(mode="json"),
        }
    )


def native_m15_receipt_hash_v31(proof: StructuralProofEvidenceV31) -> str:
    return canonical_sha256_v31(
        {
            **_material_header(proof, "M15"),
            "h1_receipt_hash": native_h1_receipt_hash_v31(proof),
            "source_candle_ids": [c.candle_evidence_id for c in proof.m15_source_candles],
            "closed_at": proof.m15_closed_at.isoformat(),
            "break_evidence": proof.m15_break_evidence.model_dump(mode="json"),
            "completion_kind": proof.m15_completion_kind,
            "completion_candle_id": proof.m15_completion_candle_id,
        }
    )


__all__ = [
    "NATIVE_COMPONENT_RECEIPT_VERSION",
    "NATIVE_PROJECTION_POLICY_VERSION",
    "V31_PROOF_COMPONENT_NAMESPACE",
    "native_h1_receipt_hash_v31",
    "native_m15_receipt_hash_v31",
    "native_projection_policy_hash_v31",
    "proof_component_id_v31",
]
