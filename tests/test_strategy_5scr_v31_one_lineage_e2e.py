"""Native V31 one-lineage end-to-end: PairAdmission -> ... -> OrderedProofProjection (owner, 2026-09-20).

This is the gate that has to pass before gap #12 `ExecutionBoxV31` may be opened. It runs the REAL producers of
#492 -> #501 -> #502 -> #503 -> #504 -> #494 -> #495 -> #497 -> #498 -> #499 on one market episode at a time and
compares the three cases through one deterministic lineage receipt instead of merely asserting "no exception":

- Case A  CANONICAL_RAW    : full chain, CANONICAL_RISK_PATH, direction authority, no risk/execution authority.
- Case B  MATURE_ADVISORY  : full chain on a different symbol, SHADOW_ONLY, no risk handoff, no execution.
- Case C  authority upgrade: advisory then canonical on the SAME lifecycle; every identity is stable, the
                             historical advisory projection stays advisory, and the candidate must be
                             re-evaluated canonically.

`CANONICAL_RISK_PATH` means "may be handed to the risk layer next", never "risk has been authorised". At this
stage RISK_AUTHORIZATION, EXECUTION_AUTHORITY and BROKER_EFFECT are all zero for every case.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_analysis_lifecycle_v31 import require_canonical_lineage_v31
from analysis.strategy_5scr_directional_thesis_v31 import (
    InMemoryDirectionalThesisLedgerV31,
    thesis_status_v31,
)
from analysis.strategy_5scr_ordered_proof_projection_v31 import (
    NativeOrderedProofVerifierV31,
    project_ordered_proof_v31,
)
from analysis.strategy_5scr_pressure_hypothesis_v31 import build_pressure_hypothesis_v31
from contracts.strategy_5scr_directional_thesis_v31 import thesis_record_hash_v31
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31
from contracts.strategy_5scr_ordered_proof_v31 import ordered_proof_hash_v31
from tests.test_strategy_5scr_directional_thesis_v31 import (
    BIND_AT,
    _chain,
    _confirm,
    _open,
    _proof,
)
from tests.test_strategy_5scr_pressure_hypothesis_v31 import (
    CLOCK as HYPOTHESIS_CLOCK,
)
from tests.test_strategy_5scr_pressure_hypothesis_v31 import (
    DECISION,
    _advisory_s1b,
    _authority,
    _canonical_s1b,
    _episode,
    _maturity,
    maturity_evidence_from_lineage,
)

PROJECT_AT = BIND_AT + timedelta(seconds=30)
VERIFIER = NativeOrderedProofVerifierV31()


@dataclass(frozen=True)
class LineageReceipt:
    """One deterministic row per case, so A/B/C are compared by value rather than by "the test passed"."""

    case: str
    canonical_symbol: str
    market_episode_id: str
    strategy_lifecycle_id: str
    strategy_analysis_admission_id: str
    analysis_admission_class: str
    pressure_hypothesis_id: str
    context_epoch_id: str
    structural_proof_id: str
    strategy_thesis_id: str
    ordered_proof_hash: str
    thesis_state: str
    direction_authority: bool
    promotion_eligibility: str
    risk_handoff_allowed: bool
    risk_authorization: bool
    execution_authority: bool
    broker_command_authority: bool
    broker_effect: int
    authority_leaks: tuple[str, ...]


_AUTHORITY_TOKENS = ("execution", "broker", "command", "final_signal", "risk_authoriz", "order_")
# `risk_handoff_allowed` is an eligibility CAP, not an authorisation, so it is asserted separately per case.
_CAP_FIELDS = frozenset({"risk_handoff_allowed", "promotion_eligibility"})


def _authority_leaks(*records: Any) -> dict[str, Any]:
    """Walk every record in the lineage and collect any authority-shaped field that is not falsy.

    This is the BROKER_EFFECT = 0 assertion done structurally rather than by trusting one summary flag: if any
    producer ever stops pinning its execution fields to False, the whole lineage reports it here.
    """

    leaks: dict[str, Any] = {}
    for record in records:
        dump = record.model_dump(mode="json") if hasattr(record, "model_dump") else asdict(record)
        for field, value in dump.items():
            if field in _CAP_FIELDS or not any(token in field for token in _AUTHORITY_TOKENS):
                continue
            if value not in (False, None, "", 0):
                leaks[f"{type(record).__name__}.{field}"] = value
    return leaks


@dataclass(frozen=True)
class Lineage:
    receipt: LineageReceipt
    s1b: Any
    chain: Any
    thesis: Any
    proof: Any
    projection: Any
    containment: Any
    transitions: Any
    store: Any


def _run_lineage(case: str, s1b: Any, *, hypothesis_ledger: Any = None) -> Lineage:
    """Drive the real producers from an S1B lineage all the way to a verified ordered-proof projection."""

    chain = _chain(s1b=s1b, ledger=hypothesis_ledger)
    store = InMemoryDirectionalThesisLedgerV31()
    thesis = _open(store, chain).thesis
    assert thesis is not None, "thesis must open"
    proof = _proof(chain)
    assert _confirm(store, chain, thesis, proof).outcome == "CONFIRMED"
    transitions = store.transitions(thesis.strategy_thesis_id)
    decision = project_ordered_proof_v31(thesis=thesis, transitions=transitions, proof=proof, projected_at=PROJECT_AT)
    projection, containment = decision.projection, decision.containment
    assert decision.outcome == "PROJECTED" and projection is not None and containment is not None

    verification = VERIFIER.verify(
        projection,
        proof=proof,
        thesis=thesis,
        transitions=transitions,
        expected_thesis_record_hash=thesis_record_hash_v31(thesis),
    )
    assert verification.valid, verification.reason_code

    status = thesis_status_v31(store, thesis.strategy_thesis_id)
    leaks = _authority_leaks(
        s1b.receipt,
        s1b.admission,
        chain.lifecycle,
        chain.hypothesis,
        chain.epoch,
        chain.evaluation,
        proof,
        thesis,
        status,
        projection,
        containment,
    )
    receipt = LineageReceipt(
        case=case,
        canonical_symbol=chain.lifecycle.symbol,
        market_episode_id=str(s1b.episode.market_episode_id),
        strategy_lifecycle_id=str(chain.lifecycle.strategy_lifecycle_id),
        strategy_analysis_admission_id=str(s1b.admission.strategy_analysis_admission_id),
        analysis_admission_class=containment.analysis_admission_class,
        pressure_hypothesis_id=str(chain.hypothesis.pressure_hypothesis_id),
        context_epoch_id=str(chain.epoch.context_epoch_id),
        structural_proof_id=str(proof.proof_id),
        strategy_thesis_id=str(thesis.strategy_thesis_id),
        ordered_proof_hash=ordered_proof_hash_v31(projection),
        thesis_state=status.state,
        direction_authority=status.direction_authority,
        promotion_eligibility=containment.promotion_eligibility,
        risk_handoff_allowed=containment.risk_handoff_allowed,
        risk_authorization=containment.risk_authorization,
        execution_authority=containment.execution_authority,
        broker_command_authority=containment.broker_command_authority,
        # BROKER_EFFECT counted from the records themselves, never asserted as a constant.
        broker_effect=len(leaks),
        authority_leaks=tuple(sorted(leaks)),
    )
    return Lineage(receipt, s1b, chain, thesis, proof, projection, containment, transitions, store)


def _case_a() -> Lineage:
    s1b = _canonical_s1b()
    assert s1b is not None
    return _run_lineage("A_CANONICAL_RAW", s1b)


def _case_b() -> Lineage:
    return _run_lineage("B_MATURE_ADVISORY", _advisory_s1b(symbol="GBPUSD"))


def _case_c() -> tuple[Lineage, Any, Any]:
    """Advisory first, then a canonical admission attached to the SAME market episode."""

    reduction = _episode((30, "BUY"), (150, "BUY"))
    advisory = _advisory_s1b(reduction)
    before = _run_lineage("C_ADVISORY_BEFORE_UPGRADE", advisory)
    canonical = _canonical_s1b(reduction=reduction, ledger=advisory.ledger, decided_at=DECISION)
    assert canonical is not None
    return before, advisory, canonical


def _no_authority(receipt: LineageReceipt) -> None:
    """The invariant every case shares: analysis may progress, authority to act never appears."""

    assert receipt.risk_authorization is False
    assert receipt.execution_authority is False
    assert receipt.broker_command_authority is False
    assert receipt.authority_leaks == (), receipt.authority_leaks
    assert receipt.broker_effect == 0


# --- Case A ------------------------------------------------------------------------------------------------------


def test_case_a_canonical_raw_runs_the_whole_lineage_on_the_canonical_risk_path():
    lineage = _case_a()
    receipt = lineage.receipt
    assert receipt.analysis_admission_class == "CANONICAL_RAW"
    assert (receipt.thesis_state, receipt.direction_authority) == ("STRUCTURALLY_CONFIRMED", True)
    assert receipt.promotion_eligibility == "CANONICAL_RISK_PATH"  # may be handed on, NOT authorised
    assert receipt.risk_handoff_allowed is True
    _no_authority(receipt)
    # One lineage: every object names the same episode-rooted lifecycle.
    lifecycle_id = receipt.strategy_lifecycle_id
    assert lifecycle_id == str(strategy_lifecycle_id_from_episode_v31(lineage.s1b.episode.market_episode_id))
    for record in (lineage.s1b.receipt, lineage.chain.hypothesis, lineage.chain.epoch, lineage.proof, lineage.thesis):
        assert str(record.strategy_lifecycle_id) == lifecycle_id
    assert str(lineage.projection.strategy_lifecycle_id) == lifecycle_id
    assert lineage.s1b.receipt.pair_admission_evaluation_id is not None  # canonical path came through #492


# --- Case B ------------------------------------------------------------------------------------------------------


def test_case_b_mature_advisory_runs_the_whole_lineage_but_stays_shadow_only():
    """Full analysis, up to and including a structurally confirmed thesis and an ordered proof, with no
    execution authority anywhere. This is what v3.1 means by a shadow lineage."""

    lineage = _case_b()
    receipt = lineage.receipt
    assert receipt.canonical_symbol == "GBPUSD"
    assert receipt.analysis_admission_class == "MATURE_ADVISORY"
    assert (receipt.thesis_state, receipt.direction_authority) == ("STRUCTURALLY_CONFIRMED", True)
    assert receipt.promotion_eligibility == "SHADOW_ONLY"
    assert receipt.risk_handoff_allowed is False
    _no_authority(receipt)
    assert lineage.s1b.receipt.pair_admission_evaluation_id is None  # no PairAdmission in a shadow lineage
    assert lineage.chain.hypothesis.analysis_authority == "FULL_SHADOW_ANALYSIS"
    assert lineage.thesis.analysis_authority == "FULL_SHADOW_ANALYSIS"
    # Case A and Case B run the SAME material payload on different symbols: the context hash must still differ,
    # otherwise two symbols in the same structural state would share a context epoch.
    other = _case_a()
    assert lineage.chain.epoch.material == other.chain.epoch.material
    assert lineage.chain.epoch.material_context_hash != other.chain.epoch.material_context_hash


# --- Case C ------------------------------------------------------------------------------------------------------


def test_case_c_authority_upgrade_keeps_one_lineage_and_every_identity_stable():
    before, advisory, canonical = _case_c()

    assert advisory.admission.strategy_analysis_admission_id != canonical.admission.strategy_analysis_admission_id
    assert advisory.admission.admission_class == "MATURE_ADVISORY"
    assert canonical.admission.admission_class == "CANONICAL_RAW"
    assert canonical.lifecycle.highest_analysis_authority == "CANONICAL_RAW"
    assert canonical.lifecycle.strategy_lifecycle_id == advisory.lifecycle.strategy_lifecycle_id

    # A canonical re-evaluation is a FRESH evaluation of the same material, not a reuse of the advisory
    # candidate: it runs its own hypothesis ledger and produces its own records.
    after = _run_lineage("C_CANONICAL_AFTER_UPGRADE", canonical)
    stable = (
        "market_episode_id",
        "strategy_lifecycle_id",
        "pressure_hypothesis_id",
        "context_epoch_id",
        "structural_proof_id",
        "strategy_thesis_id",
    )
    for field in stable:
        assert getattr(before.receipt, field) == getattr(after.receipt, field), field
    assert before.receipt.strategy_analysis_admission_id != after.receipt.strategy_analysis_admission_id

    # DUPLICATE_LIFECYCLE = 0: the shared ledger holds exactly one lifecycle, and it is keyed by lifecycle id.
    lifecycle_id = advisory.lifecycle.strategy_lifecycle_id
    assert set(advisory.ledger.attachments) == {lifecycle_id}
    assert set(advisory.ledger.episodes) == {lifecycle_id}
    assert advisory.ledger.episodes[lifecycle_id].market_episode_id == advisory.episode.market_episode_id
    assert len(advisory.ledger.attachments[lifecycle_id]) == 2  # two admissions, one lifecycle

    # The upgrade is recorded and demands a fresh canonical evaluation; it never reuses the advisory candidate.
    upgrades = advisory.ledger.upgrades[advisory.lifecycle.strategy_lifecycle_id]
    assert len(upgrades) == 1
    assert upgrades[0].required_action == "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    assert upgrades[0].advisory_candidate_reused_as_canonical is False
    assert (
        require_canonical_lineage_v31(canonical.lifecycle, advisory.admission.strategy_analysis_admission_id)
        == "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )


def test_case_c_the_historical_advisory_projection_never_becomes_canonical():
    before, advisory, canonical = _case_c()
    replayed = project_ordered_proof_v31(
        thesis=before.thesis, transitions=before.transitions, proof=before.proof, projected_at=PROJECT_AT
    )
    assert replayed.projection is not None and replayed.containment is not None
    assert replayed.projection == before.projection  # byte-identical historical evidence
    assert ordered_proof_hash_v31(replayed.projection) == before.receipt.ordered_proof_hash
    assert replayed.containment == before.containment
    assert replayed.containment.promotion_eligibility == "SHADOW_ONLY"
    assert replayed.containment.risk_handoff_allowed is False
    _no_authority(before.receipt)

    # A fresh canonical evaluation produces its OWN containment; it does not mutate the advisory artefact.
    after = _run_lineage("C_CANONICAL_AFTER_UPGRADE", canonical)
    assert after.containment.promotion_eligibility == "CANONICAL_RISK_PATH"
    assert after.containment.thesis_record_hash != before.containment.thesis_record_hash
    assert before.thesis.promotion_eligibility == "SHADOW_ONLY"  # the stored advisory thesis is untouched
    _no_authority(after.receipt)


# --- lineage-wide comparison --------------------------------------------------------------------------------------


def test_the_three_cases_differ_only_where_the_admission_class_should_make_them_differ():
    rows = {case.receipt.case: asdict(case.receipt) for case in (_case_a(), _case_b(), _case_c()[0])}
    assert set(rows) == {"A_CANONICAL_RAW", "B_MATURE_ADVISORY", "C_ADVISORY_BEFORE_UPGRADE"}
    for row in rows.values():
        assert row["thesis_state"] == "STRUCTURALLY_CONFIRMED"
        assert row["direction_authority"] is True
        assert (row["risk_authorization"], row["execution_authority"], row["broker_command_authority"]) == (
            False,
            False,
            False,
        )
        assert row["broker_effect"] == 0
    containment = {case: (row["promotion_eligibility"], row["risk_handoff_allowed"]) for case, row in rows.items()}
    assert containment == {
        "A_CANONICAL_RAW": ("CANONICAL_RISK_PATH", True),
        "B_MATURE_ADVISORY": ("SHADOW_ONLY", False),
        "C_ADVISORY_BEFORE_UPGRADE": ("SHADOW_ONLY", False),
    }
    # CROSS_SYMBOL_CONTAMINATION = 0: three separate episodes, no identity shared between any two cases.
    identity_fields = (
        "market_episode_id",
        "strategy_lifecycle_id",
        "strategy_analysis_admission_id",
        "pressure_hypothesis_id",
        "context_epoch_id",
        "structural_proof_id",
        "strategy_thesis_id",
        "ordered_proof_hash",
    )
    for field in identity_fields:
        values = [row[field] for row in rows.values()]
        assert len(set(values)) == 3, field


# --- negative acceptance ------------------------------------------------------------------------------------------


def test_negative_a_pair_admission_can_no_longer_be_an_admission_for_the_hypothesis():
    """#493's PairAdmission-receipt authority root is gone. A #492 lineage is still read for canonical pressure
    MATURITY evidence (§10.2) - that is pressure observation, not an admission decision - but it can never be
    presented as the admission itself."""

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("contracts.strategy_5scr_admission_identity_v31")
    names = set(inspect.signature(build_pressure_hypothesis_v31).parameters)
    assert {"receipt", "admission", "lifecycle"} <= names
    assert not names & {"admission_receipt", "lineage", "pair_admission", "lifecycle_anchor"}
    s1b = _canonical_s1b()
    assert s1b is not None
    with pytest.raises(ValidationError):  # a raw #492 lineage is not a StrategyAnalysisAdmissionReceiptV31
        build_pressure_hypothesis_v31(
            receipt=s1b.lineage,
            admission=s1b.admission,
            lifecycle=s1b.lifecycle,
            pressure_authority=_authority(),
            maturity_evidence=maturity_evidence_from_lineage(s1b.lineage),
            maturity_policy=_maturity(),
            clock_policy=HYPOTHESIS_CLOCK,
            decision_at=DECISION,
        )


def test_negative_a_foreign_lifecycle_is_rejected_at_every_stage():
    a, b = _case_a(), _case_b()
    assert a.chain.lifecycle.strategy_lifecycle_id != b.chain.lifecycle.strategy_lifecycle_id
    assert (
        _open(InMemoryDirectionalThesisLedgerV31(), a.chain, lifecycle=b.chain.lifecycle).reason_code
        == "EPOCH_LIFECYCLE_MISMATCH"
    )
    # Confirmation is checked on a thesis that is still PENDING_H1, so the lineage gate is the one that speaks.
    pending_store = InMemoryDirectionalThesisLedgerV31()
    pending = _open(pending_store, a.chain).thesis
    assert pending is not None
    assert _confirm(pending_store, a.chain, pending, a.proof, lifecycle=b.chain.lifecycle).reason_code == (
        "EPOCH_LIFECYCLE_MISMATCH"
    )
    assert thesis_status_v31(pending_store, pending.strategy_thesis_id).state == "PENDING_H1"
    # Cross-symbol material can never be projected onto the other lineage's thesis either.
    assert (
        project_ordered_proof_v31(
            thesis=a.thesis, transitions=a.transitions, proof=b.proof, projected_at=PROJECT_AT
        ).reason_code
        == "PROJECTION_SCOPE_MISMATCH"
    )


def test_negative_an_advisory_receipt_presented_as_canonical_is_rejected():
    advisory = _advisory_s1b()
    canonical_inputs = build_pressure_hypothesis_v31(
        receipt=advisory.receipt,
        admission=advisory.admission,
        lifecycle=advisory.lifecycle,
        pressure_authority=_authority(),
        maturity_evidence=None,
        maturity_policy=_maturity(),  # canonical-only policy on an advisory receipt
        clock_policy=HYPOTHESIS_CLOCK,
        decision_at=DECISION,
    )
    assert canonical_inputs.reason_code == "CANONICAL_MATURITY_INPUT_NOT_APPLICABLE"
    assert canonical_inputs.hypothesis is None
    # And the thesis refuses to treat an advisory-born lineage as the canonical risk path.
    lineage = _run_lineage("ADVISORY", advisory)
    assert lineage.thesis.promotion_eligibility == "SHADOW_ONLY"
    assert lineage.containment.risk_handoff_allowed is False


def test_definition_of_done_for_gap_12_is_met():
    """The owner's gate, evaluated as one statement rather than spread across the suite."""

    a, b = _case_a(), _case_b()
    before, advisory, canonical = _case_c()
    after = _run_lineage("C_CANONICAL_AFTER_UPGRADE", canonical)
    gate = {
        "CASE_A_CANONICAL_RAW": a.receipt.promotion_eligibility == "CANONICAL_RISK_PATH",
        "CASE_B_MATURE_ADVISORY": b.receipt.promotion_eligibility == "SHADOW_ONLY",
        "CASE_C_AUTHORITY_UPGRADE": (
            before.receipt.strategy_lifecycle_id == after.receipt.strategy_lifecycle_id
            and before.receipt.promotion_eligibility == "SHADOW_ONLY"
            and after.receipt.promotion_eligibility == "CANONICAL_RISK_PATH"
        ),
        "ONE_LINEAGE": len(
            {
                before.receipt.strategy_lifecycle_id,
                after.receipt.strategy_lifecycle_id,
                str(advisory.lifecycle.strategy_lifecycle_id),
                str(canonical.lifecycle.strategy_lifecycle_id),
            }
        )
        == 1,
        "DUPLICATE_LIFECYCLE": len(advisory.ledger.attachments) == 1,
        "CROSS_SYMBOL_CONTAMINATION": len(
            {a.receipt.strategy_lifecycle_id, b.receipt.strategy_lifecycle_id, before.receipt.strategy_lifecycle_id}
        )
        == 3,
        "RISK_AUTHORITY": not any(
            row.risk_authorization or row.risk_handoff_allowed and row.promotion_eligibility == "SHADOW_ONLY"
            for row in (a.receipt, b.receipt, before.receipt, after.receipt)
        ),
        "EXECUTION_AUTHORITY": not any(
            row.execution_authority or row.broker_command_authority
            for row in (a.receipt, b.receipt, before.receipt, after.receipt)
        ),
        "BROKER_EFFECT": sum(row.broker_effect for row in (a.receipt, b.receipt, before.receipt, after.receipt)) == 0,
    }
    assert gate == dict.fromkeys(gate, True), {k: v for k, v in gate.items() if v is not True}


def test_negative_an_advisory_candidate_is_never_silently_reused_as_canonical():
    """The other half of Case C: inside ONE hypothesis ledger the advisory candidate stays active, so re-running
    the chain after the upgrade does NOT quietly hand the shadow lineage a canonical risk path. Canonical
    progression must be a fresh evaluation, and §7A.6 keeps saying so."""

    before, advisory, canonical = _case_c()
    reused = _run_lineage("C_REUSED_CANDIDATE", canonical, hypothesis_ledger=before.chain.hypotheses)
    assert reused.chain.hypothesis == before.chain.hypothesis  # ALREADY_ACTIVE returned the advisory record
    assert reused.receipt.promotion_eligibility == "SHADOW_ONLY"
    assert reused.receipt.risk_handoff_allowed is False
    assert reused.thesis.analysis_admission_class == "MATURE_ADVISORY"
    _no_authority(reused.receipt)
    assert (
        require_canonical_lineage_v31(canonical.lifecycle, advisory.admission.strategy_analysis_admission_id)
        == "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )
