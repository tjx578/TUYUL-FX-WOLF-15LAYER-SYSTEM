"""D8 acceptance: native OrderedProofEvidenceV31 projection + native verifier (owner P1–P5, 2026-09-20).

Usable downstream = schema-valid + native-verifier-valid + thesis-current-status-valid (the last is a separate
subcontract). ``OrderedProofEvidenceV31`` is only the transport shape.

Requalified on #504: a projection is evidence, not permission. It may be built from either admission class,
and the containment of the lineage it came from travels beside it - never inside ordered_proof_hash.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid5

import pytest

from analysis.strategy_5scr_analysis_lifecycle_v31 import require_canonical_lineage_v31
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
from contracts.strategy_5scr_directional_thesis_v31 import thesis_record_hash_v31
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_ordered_proof_projection_v31 import (
    NATIVE_COMPONENT_RECEIPT_VERSION,
    V31_PROOF_COMPONENT_NAMESPACE,
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
    _advisory_chain,
    _chain,
    _confirm,
    _confirmed,
    _evaluation,
    _later_m15,
    _material,
    _open,
    _proof,
    _resolve,
)
from tests.test_strategy_5scr_ordered_proof_v31 import reference_policy
from tests.test_strategy_5scr_pressure_hypothesis_v31 import DECISION, _advisory_s1b, _canonical_s1b, _episode

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
    other_epoch = _resolve(chain.lifecycle, _material(target_map_version="tm.v2")).epoch
    other = Chain(
        chain.hypotheses,
        chain.hypothesis,
        other_epoch,
        _evaluation(other_epoch, chain.hypothesis, lifecycle=chain.lifecycle),
        chain.lifecycle,
        chain.s1b,
    )
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


# --- requalification containment acceptance (#502/#503/#498 lineage preserved) ------------------------------------


def _confirmed_advisory(reduction=None):
    """A MATURE_ADVISORY lineage confirmed all the way to a thesis, ready to project."""

    store = InMemoryDirectionalThesisLedgerV31()
    chain = _advisory_chain(reduction)
    thesis = _open(store, chain).thesis
    assert thesis is not None
    proof = _proof(chain)
    assert _confirm(store, chain, thesis, proof).outcome == "CONFIRMED"
    return store, chain, thesis, proof, store.transitions(thesis.strategy_thesis_id)


def test_acceptance_1_canonical_raw_projects_on_the_canonical_risk_path():
    _, chain, thesis, proof, transitions = _setup()
    assert chain.lifecycle.highest_analysis_authority == "CANONICAL_RAW"
    decision = _project(thesis, transitions, proof)
    assert (decision.outcome, decision.reason_code) == ("PROJECTED", "ORDERED_PROOF_PROJECTED")
    containment = decision.containment
    assert containment is not None
    assert (containment.analysis_admission_class, containment.promotion_eligibility) == (
        "CANONICAL_RAW",
        "CANONICAL_RISK_PATH",
    )
    assert (containment.risk_handoff_allowed, containment.direction_authority) == (True, True)
    assert containment.thesis_record_hash == thesis_record_hash_v31(thesis)


def test_acceptance_2_mature_advisory_projects_as_evidence_without_canonical_eligibility():
    """A shadow lineage may produce ordered-proof EVIDENCE. It may never imply canonical risk or execution."""

    _, chain, thesis, proof, transitions = _confirmed_advisory()
    assert chain.lifecycle.highest_analysis_authority == "MATURE_ADVISORY"
    decision = _project(thesis, transitions, proof)
    projection = decision.projection
    containment = decision.containment
    assert decision.outcome == "PROJECTED" and projection is not None and containment is not None
    assert (containment.analysis_admission_class, containment.promotion_eligibility) == (
        "MATURE_ADVISORY",
        "SHADOW_ONLY",
    )
    assert (containment.risk_handoff_allowed, containment.direction_authority) == (False, True)
    assert (
        containment.risk_authorization,
        containment.execution_authority,
        containment.broker_command_authority,
    ) == (False, False, False)
    # The verifier re-reports the containment, so a downstream consumer cannot lose it.
    verification = VERIFIER.verify(projection, proof=proof, thesis=thesis, transitions=transitions)
    assert verification.valid and verification.containment == containment


def test_acceptance_3_an_authority_upgrade_never_mutates_a_historical_projection():
    reduction = _episode()
    advisory = _advisory_s1b(reduction)
    store = InMemoryDirectionalThesisLedgerV31()
    chain = _chain(s1b=advisory)
    thesis = _open(store, chain).thesis
    assert thesis is not None
    proof = _proof(chain)
    assert _confirm(store, chain, thesis, proof).outcome == "CONFIRMED"
    transitions = store.transitions(thesis.strategy_thesis_id)
    before = _project(thesis, transitions, proof)
    assert before.projection is not None and before.containment is not None

    canonical = _canonical_s1b(reduction=reduction, ledger=advisory.ledger, decided_at=DECISION)
    assert canonical is not None
    assert canonical.lifecycle.strategy_lifecycle_id == advisory.lifecycle.strategy_lifecycle_id
    assert canonical.lifecycle.highest_analysis_authority == "CANONICAL_RAW"

    after = _project(store.get_record(thesis.strategy_thesis_id), transitions, proof)
    assert after.projection is not None
    assert ordered_proof_hash_v31(after.projection) == ordered_proof_hash_v31(before.projection)
    assert after.projection == before.projection  # byte-identical historical evidence
    assert after.containment == before.containment  # still advisory provenance
    assert after.containment is not None and after.containment.promotion_eligibility == "SHADOW_ONLY"
    # Canonical progression still demands a canonical re-evaluation of the advisory candidate (§7A.6).
    assert (
        require_canonical_lineage_v31(canonical.lifecycle, advisory.admission.strategy_analysis_admission_id)
        == "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )


def test_acceptance_4_projection_integrity_never_absorbs_the_admission_class():
    """The component ids, the receipt hashes, the native policy hash and ordered_proof_hash are all material.
    Each formula is spelled out, because widening one would shift every projection uniformly."""

    _, _, canonical_thesis, canonical_proof, canonical_transitions = _setup()
    canonical = _project(canonical_thesis, canonical_transitions, canonical_proof).projection
    _, _, advisory_thesis, advisory_proof, advisory_transitions = _confirmed_advisory()
    advisory = _project(advisory_thesis, advisory_transitions, advisory_proof).projection
    assert canonical is not None and advisory is not None

    for projection, proof in ((canonical, canonical_proof), (advisory, advisory_proof)):
        assert projection.h1_proof_id == uuid5(
            V31_PROOF_COMPONENT_NAMESPACE,
            json.dumps(["v31.native-identity.v1", str(proof.proof_id), "H1"], separators=(",", ":")),
        )
        assert projection.m15_proof_id == proof_component_id_v31(proof.proof_id, "M15")
        assert projection.pattern_policy_hash == native_projection_policy_hash_v31(proof.pattern_registry_hash)
        assert projection.h1_resolution_receipt_hash == native_h1_receipt_hash_v31(proof)
        assert projection.m15_resolution_receipt_hash == native_m15_receipt_hash_v31(proof)
        blob = json.dumps(projection.model_dump(mode="json"), default=str)
        assert "MATURE_ADVISORY" not in blob and "CANONICAL_RAW" not in blob
        assert "SHADOW_ONLY" not in blob and "CANONICAL_RISK_PATH" not in blob
    forbidden = {
        "analysis_admission_class",
        "promotion_eligibility",
        "risk_handoff_allowed",
        "strategy_analysis_admission_id",
        "admission_receipt_hash",
        "highest_analysis_authority",
    }
    assert not forbidden & set(OrderedProofEvidenceV31.model_fields)


def test_acceptance_5_the_verifier_pins_the_exact_thesis_record_not_only_its_id():
    """Containment is absent from ordered_proof_hash by design, so two records with the same id but different
    promotion eligibility derive the same projection. The record hash is how a consumer proves which one it used."""

    _, _, thesis, proof, transitions = _setup()
    projection = _project(thesis, transitions, proof).projection
    assert projection is not None
    good = VERIFIER.verify(
        projection,
        proof=proof,
        thesis=thesis,
        transitions=transitions,
        expected_thesis_record_hash=thesis_record_hash_v31(thesis),
    )
    assert (good.valid, good.reason_code) == (True, "NATIVE_PROJECTION_VERIFIED")
    _, _, advisory_thesis, _, _ = _confirmed_advisory()
    assert advisory_thesis.strategy_thesis_id == thesis.strategy_thesis_id  # identity is class-free
    assert thesis_record_hash_v31(advisory_thesis) != thesis_record_hash_v31(thesis)  # the RECORDS differ
    bad = VERIFIER.verify(
        projection,
        proof=proof,
        thesis=thesis,
        transitions=transitions,
        expected_thesis_record_hash=thesis_record_hash_v31(advisory_thesis),
    )
    assert (bad.valid, bad.reason_code) == (False, "THESIS_RECORD_HASH_MISMATCH")
    assert bad.containment is not None and bad.containment.analysis_admission_class == "CANONICAL_RAW"
    # And the lineage fields the owner listed are all re-derived, not trusted from the projection.
    # The advisory and canonical lineages here share lifecycle, epoch and thesis ids - exactly because those ids
    # are admission-class free - so the swaps must be genuinely foreign values, not the advisory ones.
    swaps = {
        "strategy_lifecycle_id": uuid5(thesis.strategy_lifecycle_id, "elsewhere"),
        "context_epoch_id": uuid5(thesis.context_epoch_id, "elsewhere"),
        "strategy_thesis_id": uuid5(thesis.strategy_thesis_id, "elsewhere"),
        "direction": "SELL",
        "selected_route": "BREAK_RETEST",
        "context_material_hash": "sha256:" + "7" * 64,
        "h1_proof_id": uuid5(proof.proof_id, "elsewhere"),
        "level_version": "tampered-level-v9",
    }
    for field, value in swaps.items():
        tampered = projection.model_copy(update={field: value})
        verdict = VERIFIER.verify(tampered, proof=proof, thesis=thesis, transitions=transitions)
        assert not verdict.valid, field


def test_acceptance_6_no_execution_or_risk_leakage_in_either_class():
    forbidden = {
        "execution_command_id",
        "execution_box_id",
        "broker_order_id",
        "risk_reservation_id",
        "tradeplan_id",
        "entry",
        "stop_loss",
        "take_profit",
        "volume",
        "lot_size",
        "spread",
        "margin",
    }
    assert not forbidden & set(OrderedProofEvidenceV31.model_fields)
    for setup in (_setup(), _confirmed_advisory()):
        _, _, thesis, proof, transitions = setup
        decision = _project(thesis, transitions, proof)
        assert decision.containment is not None
        assert (
            decision.containment.risk_authorization,
            decision.containment.execution_authority,
            decision.containment.broker_command_authority,
        ) == (False, False, False)
        assert (thesis.execution_authority, thesis.final_signal_allowed, thesis.execution_command_allowed) == (
            False,
            False,
            False,
        )


def test_native_receipt_hash_formulas_are_pinned_and_the_m15_receipt_is_chained_to_the_h1_receipt():
    """P2 spelled out: both receipts are material-only, and the M15 receipt commits to the H1 receipt hash.
    Dropping the chain still yields a self-consistent projection, so the formula is pinned literally here."""

    _, _, _, proof, _ = _setup()
    header = {
        "receipt_version": NATIVE_COMPONENT_RECEIPT_VERSION,
        "component": "H1",
        "structural_proof_id": str(proof.proof_id),
        "structural_proof_hash": proof.material_evidence_hash,
        "pattern_id": proof.pattern_id,
        "pattern_registry_hash": proof.pattern_registry_hash,
        "level_version": proof.level_version,
    }
    expected_h1 = canonical_sha256_v31(
        {
            **header,
            "source_candle_ids": [c.candle_evidence_id for c in proof.h1_source_candles],
            "closed_at": proof.h1_closed_at.isoformat(),
            "structure_evidence": proof.h1_structure_evidence.model_dump(mode="json"),
        }
    )
    assert native_h1_receipt_hash_v31(proof) == expected_h1
    m15_body = {
        **header,
        "component": "M15",
        "source_candle_ids": [c.candle_evidence_id for c in proof.m15_source_candles],
        "closed_at": proof.m15_closed_at.isoformat(),
        "break_evidence": proof.m15_break_evidence.model_dump(mode="json"),
        "completion_kind": proof.m15_completion_kind,
        "completion_candle_id": proof.m15_completion_candle_id,
    }
    # The chain: an M15 break is meaningless without the H1 confirmation it followed.
    assert native_m15_receipt_hash_v31(proof) == canonical_sha256_v31({**m15_body, "h1_receipt_hash": expected_h1})
    assert native_m15_receipt_hash_v31(proof) != canonical_sha256_v31(m15_body)
