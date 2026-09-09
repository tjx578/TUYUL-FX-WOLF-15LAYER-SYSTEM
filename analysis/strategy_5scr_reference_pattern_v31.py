"""Explicit TEST_ONLY reference-pattern derivation from the repo V1 predicates.

This evaluates one supplied H1 pair and M15 triple. Selecting the latest witness,
feed/session completeness, active policy and later invalidation remain external.
"""

from typing import Literal

from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31
from contracts.strategy_5scr_context_route_v31 import Label, content_hash
from contracts.strategy_5scr_directional_thesis_v1 import classify_m15_completion
from contracts.strategy_5scr_net_geometry_v31 import GeometryContract
from contracts.strategy_5scr_ordered_proof_v31 import OrderedProofEvidenceV31


class ReferencePatternPolicyV31(GeometryContract):
    profile: Literal["TEST_ONLY"]
    rule_id: Literal["ADJACENT_H1_PAIR_M15_TRIPLE_TEST_V1"]
    source_rule: Literal["5scr.directional-thesis.v1"]
    selected_route: Label


def reference_pattern_policy_hash(policy):
    policy = ReferencePatternPolicyV31.model_validate(policy.model_dump())
    return content_hash(policy.model_dump(mode="json"))


def derive_reference_pattern_v31(proof, *, policy):
    proof = OrderedProofEvidenceV31.model_validate(proof.model_dump())
    policy = ReferencePatternPolicyV31.model_validate(policy.model_dump())
    if (
        proof.pattern_policy_hash != reference_pattern_policy_hash(policy)
        or proof.selected_route != policy.selected_route
    ):
        raise ValueError("REFERENCE_PATTERN_POLICY_MISMATCH")
    if len(proof.h1_source_candles) != 2 or len(proof.m15_source_candles) != 3:
        raise ValueError("REFERENCE_PATTERN_WITNESS_COUNT_INVALID")
    anchor, confirmation = proof.h1_source_candles
    reference, breaking, completion = proof.m15_source_candles
    if (
        anchor.close_time_utc != confirmation.open_time_utc
        or reference.close_time_utc != breaking.open_time_utc
        or breaking.close_time_utc != completion.open_time_utc
    ):
        raise ValueError("REFERENCE_PATTERN_WITNESS_GAP")
    if breaking.open_time_utc < proof.h1_closed_at:
        raise ValueError("REFERENCE_PATTERN_BREAK_PRECEDES_H1")
    if (proof.m15_break_candle_id, proof.m15_completion_candle_id) != (
        breaking.candle_evidence_id,
        completion.candle_evidence_id,
    ):
        raise ValueError("REFERENCE_PATTERN_WITNESS_REFERENCE_MISMATCH")
    h1_level = anchor.high if proof.direction == "BUY" else anchor.low
    m15_level = reference.high if proof.direction == "BUY" else reference.low
    if not (confirmation.close > h1_level if proof.direction == "BUY" else confirmation.close < h1_level):
        raise ValueError("REFERENCE_PATTERN_H1_BREAK_MISSING")
    if not (breaking.close > m15_level if proof.direction == "BUY" else breaking.close < m15_level):
        raise ValueError("REFERENCE_PATTERN_M15_BREAK_MISSING")
    kind = classify_m15_completion(proof.direction, completion, m15_level)
    if kind is None:
        raise ValueError("REFERENCE_PATTERN_COMPLETION_MISSING")
    scope = {
        key: value
        for key, value in proof.model_dump(mode="json").items()
        if key
        in (
            "profile",
            "strategy_thesis_id",
            "strategy_lifecycle_id",
            "context_epoch_id",
            "symbol",
            "direction",
            "selected_route",
            "context_material_hash",
            "pattern_policy_hash",
            "level_version",
            "evaluated_at",
            "valid_until",
        )
    }
    h1 = {
        **scope,
        "proof_id": str(proof.h1_proof_id),
        "closed_at": proof.h1_closed_at.isoformat(),
        "source_ids": [c.candle_evidence_id for c in proof.h1_source_candles],
        "reference_level": h1_level,
        "confirmation_close": confirmation.close,
        "resolution": "REFERENCE_CLOSE_BREAK_TEST_ONLY",
    }
    m15 = {
        **scope,
        "proof_id": str(proof.m15_proof_id),
        "h1_resolution_hash": content_hash(h1),
        "closed_at": proof.m15_closed_at.isoformat(),
        "source_ids": [c.candle_evidence_id for c in proof.m15_source_candles],
        "reference_level": m15_level,
        "break_close": breaking.close,
        "completion_close": completion.close,
        "completion_kind": kind,
    }
    return h1, m15


def build_reference_pattern_receipts_v31(proof, *, policy):
    """Derive resolution claims; do not select a policy or grant authority."""
    proof = OrderedProofEvidenceV31.model_validate(proof.model_dump())
    h1, m15 = derive_reference_pattern_v31(proof, policy=policy)
    return OrderedProofEvidenceV31.model_validate(
        {
            **proof.model_dump(),
            "m15_completion_kind": m15["completion_kind"],
            "h1_resolution_receipt_hash": content_hash(h1),
            "m15_resolution_receipt_hash": content_hash(m15),
        }
    )


class ReferencePatternHandoffVerifierV31:
    """Compose actual pattern checks with mandatory remaining-domain attestation.

    Inject explicitly into the existing handoff verifier slot. This does not
    register a runtime policy, source attestor or service endpoint.
    """

    def __init__(self, *, policy, attest_remaining):
        self.policy = ReferencePatternPolicyV31.model_validate(policy.model_dump())
        if not callable(attest_remaining):
            raise ValueError("REFERENCE_PATTERN_ATTESTOR_REQUIRED")
        self.attest_remaining = attest_remaining

    def __call__(self, handoff, digest):
        handoff = CandidateHandoffV31.model_validate(handoff.model_dump())
        proof = handoff.thesis_structural_proof
        h1, m15 = derive_reference_pattern_v31(proof, policy=self.policy)
        if (proof.h1_resolution_receipt_hash, proof.m15_resolution_receipt_hash, proof.m15_completion_kind) != (
            content_hash(h1),
            content_hash(m15),
            m15["completion_kind"],
        ):
            return False
        before = content_hash(handoff.model_dump(mode="json"))
        accepted = self.attest_remaining(handoff, digest) is True
        return accepted and content_hash(handoff.model_dump(mode="json")) == before
