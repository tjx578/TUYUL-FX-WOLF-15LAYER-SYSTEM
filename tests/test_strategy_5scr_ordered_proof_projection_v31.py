"""D8 acceptance: native OrderedProofEvidenceV31 projection + native verifier (owner P1–P5, 2026-09-20).

Usable downstream = schema-valid + native-verifier-valid + thesis-current-status-valid (the last is a separate
subcontract). ``OrderedProofEvidenceV31`` is only the transport shape.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_context_epoch_v31 import project_context_route_receipt_v31
from analysis.strategy_5scr_directional_thesis_v31 import (
    InMemoryDirectionalThesisLedgerV31,
    invalidate_thesis_structurally_v31,
)
from analysis.strategy_5scr_ordered_proof_projection_v31 import (
    NativeOrderedProofVerifierV31,
    project_ordered_proof_v31,
)
from analysis.strategy_5scr_reference_pattern_v31 import (
    ReferencePatternHandoffVerifierV31,
    derive_reference_pattern_v31,
    reference_pattern_policy_hash,
)
from contracts.strategy_5scr_candidate_handoff_v31 import CandidateHandoffV31
from contracts.strategy_5scr_context_route_v31 import context_route_receipt_hash_v31
from contracts.strategy_5scr_ordered_proof_projection_v31 import (
    native_h1_receipt_hash_v31,
    native_m15_receipt_hash_v31,
    native_projection_policy_hash_v31,
    proof_component_id_v31,
)
from contracts.strategy_5scr_ordered_proof_v31 import OrderedProofEvidenceV31, ordered_proof_hash_v31
from tests.test_strategy_5scr_candidate_handoff_v31 import bundle
from tests.test_strategy_5scr_directional_thesis_v31 import (
    ACTIONABILITY,
    BIND_AT,
    COMPLETION,
    Chain,
    _chain,
    _confirmed,
    _evaluation,
    _later_m15,
    _material,
    _open,
    _proof,
    _resolve,
)
from tests.test_strategy_5scr_ordered_proof_v31 import reference_policy

AT = BIND_AT + timedelta(seconds=30)
VERIFIER = NativeOrderedProofVerifierV31()


def _setup():
    store, chain, thesis, proof = _confirmed()
    return store, chain, thesis, proof, store.transitions(thesis.strategy_thesis_id)


def _project(thesis, transitions, proof, at=AT):
    return project_ordered_proof_v31(thesis=thesis, transitions=transitions, proof=proof, projected_at=at)


def _projected():
    store, chain, thesis, proof, transitions = _setup()
    projection = _project(thesis, transitions, proof).projection
    assert projection is not None
    return store, chain, thesis, proof, transitions, projection


def test_authoritative_thesis_projects_a_schema_valid_native_projection():
    _, _, thesis, proof, transitions, projection = _projected()
    assert OrderedProofEvidenceV31.model_validate(projection.model_dump()) == projection
    assert (projection.strategy_thesis_id, projection.direction, projection.symbol) == (
        thesis.strategy_thesis_id,
        thesis.direction,
        thesis.canonical_symbol,
    )
    assert (projection.h1_proof_id, projection.m15_proof_id) == (
        proof_component_id_v31(proof.proof_id, "H1"),
        proof_component_id_v31(proof.proof_id, "M15"),
    )
    assert projection.h1_proof_id != projection.m15_proof_id != proof.proof_id
    assert (projection.h1_source_candles, projection.m15_source_candles) == (
        proof.h1_source_candles,
        proof.m15_source_candles,
    )
    assert VERIFIER.verify(projection, proof=proof, thesis=thesis, transitions=transitions).valid


def test_pending_thesis_is_never_projected():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    thesis = _open(store, chain).thesis
    assert thesis is not None
    decision = _project(thesis, store.transitions(thesis.strategy_thesis_id), _proof(chain))
    assert (decision.outcome, decision.reason_code) == ("NOT_PROJECTED", "THESIS_NOT_AUTHORITATIVE")


def test_non_authoritative_as_of_projection_time_is_rejected():
    store, chain, thesis, proof, transitions = _setup()
    before_confirmation = BIND_AT - timedelta(seconds=1)
    assert _project(thesis, transitions, proof, at=before_confirmation).reason_code == "THESIS_NOT_AUTHORITATIVE"
    later = COMPLETION + timedelta(minutes=15, seconds=5)
    failed = _later_m15(proof, proof.m15_break_evidence.level - 0.0010)
    invalidate_thesis_structurally_v31(
        store,
        strategy_thesis_id=thesis.strategy_thesis_id,
        proof=proof,
        actionability_policy=ACTIONABILITY,
        later_h1=(),
        later_m15=(failed,),
        decision_at=later,
    )
    transitions = store.transitions(thesis.strategy_thesis_id)
    assert _project(thesis, transitions, proof, at=later).reason_code == "THESIS_NOT_AUTHORITATIVE"
    # As-of replay: a projection made before the invalidation is still derivable at its own time.
    assert _project(thesis, transitions, proof, at=AT).outcome == "PROJECTED"


def test_proof_that_is_not_the_bound_proof_is_rejected():
    _, chain, thesis, _, transitions = _setup()
    additional = _proof(chain, high_bump=0.0001)  # valid, same scope, never bound to this thesis
    assert _project(thesis, transitions, additional).reason_code == "PROOF_NOT_BOUND_TO_THESIS"


def test_direction_and_lineage_mismatch_are_rejected():
    _, chain, thesis, _, transitions = _setup()
    sell = _proof(_chain("EURUSD", "SELL"))
    assert _project(thesis, transitions, sell).reason_code == "PROJECTION_DIRECTION_MISMATCH"
    other_epoch = _resolve(chain.hypothesis, _material(target_map_version="tm.v2")).epoch
    other = Chain(chain.hypotheses, chain.hypothesis, other_epoch, _evaluation(other_epoch, chain.hypothesis))
    assert _project(thesis, transitions, _proof(other)).reason_code == "PROJECTION_SCOPE_MISMATCH"
    gbpusd = _proof(_chain("GBPUSD"))
    assert _project(thesis, transitions, gbpusd).reason_code == "PROJECTION_SCOPE_MISMATCH"


def test_receipts_and_component_ids_are_material_only_while_projection_hash_is_instance_integrity():
    _, _, thesis, proof, transitions = _setup()
    first = _project(thesis, transitions, proof, at=AT).projection
    later = _project(thesis, transitions, proof, at=AT + timedelta(minutes=7)).projection
    assert first is not None and later is not None
    stable = ("h1_proof_id", "m15_proof_id", "h1_resolution_receipt_hash", "m15_resolution_receipt_hash")
    assert [getattr(first, f) for f in stable] == [getattr(later, f) for f in stable]
    assert (first.h1_resolution_receipt_hash, first.m15_resolution_receipt_hash) == (
        native_h1_receipt_hash_v31(proof),
        native_m15_receipt_hash_v31(proof),
    )
    assert first.h1_resolution_receipt_hash != first.m15_resolution_receipt_hash
    assert ordered_proof_hash_v31(first) != ordered_proof_hash_v31(later)  # evaluated_at is instance metadata
    assert first.valid_until == later.valid_until == thesis.valid_until  # P3: no new TTL


def test_projection_clock_is_bounded_by_the_thesis_deadline():
    _, _, thesis, proof, transitions = _setup()
    assert _project(thesis, transitions, proof, at=thesis.valid_until).reason_code == "PROJECTION_CLOCK_INVALID"
    last = thesis.valid_until - timedelta(microseconds=1)
    projection = _project(thesis, transitions, proof, at=last).projection
    assert projection is not None and projection.valid_until == thesis.valid_until


def test_native_projection_never_claims_reference_policy_semantics():
    _, _, _, proof, _, projection = _projected()
    reference_hash = reference_pattern_policy_hash(reference_policy())
    assert projection.pattern_policy_hash == native_projection_policy_hash_v31(proof.pattern_registry_hash)
    assert projection.pattern_policy_hash not in {proof.pattern_registry_hash, reference_hash}
    with pytest.raises(ValueError, match="REFERENCE_PATTERN_POLICY_MISMATCH"):
        derive_reference_pattern_v31(projection, policy=reference_policy())


@pytest.mark.parametrize(
    "field,value",
    [
        ("pattern_policy_hash", "sha256:" + "1" * 64),
        ("h1_resolution_receipt_hash", "sha256:" + "2" * 64),
        ("m15_resolution_receipt_hash", "sha256:" + "3" * 64),
        ("level_version", "tampered-level"),
        ("selected_route", "BREAK_RETEST"),
        ("context_material_hash", "sha256:" + "4" * 64),
        ("valid_until", "+1s"),
        ("h1_proof_id", "swap"),
        ("strategy_thesis_id", "swap"),
    ],
)
def test_native_verifier_rejects_any_tampered_projection_field(field: str, value: Any):
    _, _, thesis, proof, transitions, projection = _projected()
    if value == "+1s":
        value = projection.valid_until + timedelta(seconds=1)
    elif value == "swap":
        value = projection.m15_proof_id
    tampered = projection.model_copy(update={field: value})
    result = VERIFIER.verify(tampered, proof=proof, thesis=thesis, transitions=transitions)
    assert result.valid is False


def test_native_verifier_rejects_tampered_proof_thesis_or_transition_chain():
    _, _, thesis, proof, transitions, projection = _projected()

    def verify(**kwargs: Any) -> str:
        inputs: dict[str, Any] = {"proof": proof, "thesis": thesis, "transitions": transitions, **kwargs}
        result = VERIFIER.verify(projection, **inputs)
        assert result.valid is False
        return result.reason_code

    assert verify(proof=proof.model_copy(update={"level_version": "tampered"})) == "NATIVE_INPUT_INVALID"
    assert verify(thesis=thesis.model_copy(update={"valid_until": thesis.valid_until + timedelta(seconds=1)})) == (
        "NATIVE_INPUT_INVALID"
    )
    forged_material = thesis.model_copy(update={"material_context_hash": "sha256:" + "5" * 64})
    assert verify(thesis=forged_material) == "PROJECTION_CONTEXT_MATERIAL_NOT_BOUND"
    (link,) = transitions
    assert verify(transitions=(link.model_copy(update={"occurred_at": link.occurred_at - timedelta(seconds=1)}),)) == (
        "THESIS_TRANSITION_CHAIN_INVALID"
    )
    assert verify(transitions=()) == "THESIS_NOT_AUTHORITATIVE"
    # Every link individually valid, but it belongs to another thesis: the chain itself must be rejected.
    gbp_store, _, gbp_thesis, _ = _confirmed(chain=_chain("GBPUSD"))
    assert verify(transitions=gbp_store.transitions(gbp_thesis.strategy_thesis_id)) == "THESIS_TRANSITION_CHAIN_INVALID"


def test_candidate_handoff_accepts_the_native_projection_shape_and_reference_verifier_rejects_it():
    _, chain, thesis, _, _, projection = _projected()
    _, handoff, _ = bundle("BUY")
    body = handoff.model_dump()
    receipt = project_context_route_receipt_v31(chain.epoch, chain.evaluation)
    assert receipt is not None
    candidate = {
        **body["candidate"],
        "strategy_thesis_id": thesis.strategy_thesis_id,
        "strategy_lifecycle_id": thesis.strategy_lifecycle_id,
        "strategy_analysis_admission_id": thesis.strategy_analysis_admission_id,
        "pressure_hypothesis_id": thesis.pressure_hypothesis_id,
        "context_epoch_id": thesis.context_epoch_id,
        "decision_at": AT,
    }
    native_handoff = CandidateHandoffV31.model_validate(
        {
            **body,
            "candidate": candidate,
            "thesis_structural_proof": projection,
            "thesis_structural_proof_hash": ordered_proof_hash_v31(projection),
            "context_route_receipt": receipt,
            "context_route_receipt_hash": context_route_receipt_hash_v31(receipt),
            "handoff_receipt_valid_until": AT + timedelta(seconds=1),
        }
    )
    assert native_handoff.thesis_structural_proof == projection
    reference = ReferencePatternHandoffVerifierV31(policy=reference_policy(), attest_remaining=lambda *_: True)
    with pytest.raises(ValueError, match="REFERENCE_PATTERN_POLICY_MISMATCH"):
        reference(native_handoff, "sha256:" + "0" * 64)
