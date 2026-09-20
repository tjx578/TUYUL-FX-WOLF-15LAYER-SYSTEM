"""Gap #10 acceptance: StructuralProofEvidenceV31, CONTINUATION only (authority decisions 2026-09-19).

Requalified on #504: every context fixture runs on a real S1B lifecycle, and the authority-upgrade acceptance
proves that structural evidence is material-only - it does not move when the lifecycle authority moves.
"""

from __future__ import annotations

import ast
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, get_args
from uuid import uuid5

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_analysis_lifecycle_v31 import require_canonical_lineage_v31
from analysis.strategy_5scr_pressure_hypothesis_v31 import InMemoryPressureHypothesisLedgerV31, admit_hypothesis_v31
from analysis.strategy_5scr_structural_proof_v31 import build_structural_proof_v31
from contracts.strategy_5scr_context_epoch_v31 import ContextOutcome, with_hash
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31
from contracts.strategy_5scr_structural_proof_v31 import (
    V31_STRUCTURAL_PROOF_NAMESPACE,
    StructuralPatternRegistryV31,
    StructuralPatternV31,
    StructuralProofEvidenceV31,
)
from tests.test_strategy_5scr_context_epoch_v31 import _epoch, _evaluate, _material, _relifecycle, _s1b
from tests.test_strategy_5scr_directional_thesis_v1 import _candles, _rehash_candle
from tests.test_strategy_5scr_pressure_hypothesis_v31 import (
    DECISION,
    _advisory_s1b,
    _build,
    _canonical_s1b,
    _episode,
    _hypothesis_from,
)


def _pattern(route: str, *, adjacent: bool = True) -> StructuralPatternV31:
    return StructuralPatternV31(
        pattern_id="ADJACENT_H1_PAIR_M15_TRIPLE_CONTINUATION_TEST_V1" if adjacent else "LOOSE_TEST_V1",
        route=route,
        proof_class="CONTINUATION",
        h1_witness_count=2,
        m15_witness_count=3,
        adjacent_witnesses_required=adjacent,
        h1_rule="CONFIRMATION_CLOSE_BEYOND_ANCHOR_EXTREME",
        m15_break_rule="BREAK_CLOSE_BEYOND_REFERENCE_EXTREME",
        completion_kinds=("ACCEPTANCE", "FAILED_RECLAIM", "RETEST"),
    )


REGISTRY = with_hash(
    StructuralPatternRegistryV31,
    "registry_hash",
    registry_version="test-pattern-registry.v1",
    patterns=(
        _pattern("PULLBACK_CONTINUATION"),
        _pattern("BREAK_RETEST"),
        _pattern("PULLBACK_CONTINUATION", adjacent=False),
    ),
)
PATTERN = "ADJACENT_H1_PAIR_M15_TRIPLE_CONTINUATION_TEST_V1"


def _witnesses(direction: str = "BUY", *, completion_close_at=DECISION - timedelta(seconds=60)):
    h1, m15 = _candles(direction)  # type: ignore[arg-type]
    offset = completion_close_at - m15[-1].close_time_utc

    def shifted(candles):
        return tuple(
            _rehash_candle(
                {
                    **c.model_dump(),
                    "symbol": "EURUSD",
                    "open_time_utc": c.open_time_utc + offset,
                    "close_time_utc": c.close_time_utc + offset,
                }
            )
            for c in candles
        )

    return shifted(h1), shifted(m15)


def _context(material=None, *, lifecycle=None, **evaluate):
    epoch = _epoch(material, lifecycle=lifecycle).epoch
    evaluation = _evaluate(epoch, lifecycle=lifecycle, **evaluate).evaluation
    assert epoch is not None and evaluation is not None
    return epoch, evaluation


def _promote(
    epoch,
    evaluation,
    *,
    direction: Any = "BUY",
    witnesses=None,
    pattern=PATTERN,
    registry: Any = REGISTRY,
    at=DECISION + timedelta(seconds=10),
    lifecycle=None,
):
    h1, m15 = witnesses or _witnesses(direction)
    return build_structural_proof_v31(
        lifecycle=_s1b().lifecycle if lifecycle is None else lifecycle,
        epoch=epoch,
        evaluation=evaluation,
        proof_direction=direction,
        h1_witnesses=h1,
        m15_witnesses=m15,
        level_version="fixture-level-v1",
        pattern_id=pattern,
        registry=registry,
        decision_at=at,
    )


def test_align_continuation_promotes_evidence_only_proof():
    epoch, evaluation = _context()
    decision = _promote(epoch, evaluation)
    proof = decision.proof
    assert (decision.outcome, decision.reason_code) == ("PROMOTED", "STRUCTURAL_PROOF_PROMOTED")
    assert proof is not None and proof.proof_id.version == 5
    assert (proof.proof_class, proof.proof_direction, proof.selected_route) == (
        "CONTINUATION",
        "BUY",
        "PULLBACK_CONTINUATION",
    )
    assert proof.authority == "STRUCTURAL_EVIDENCE_ONLY"
    assert (proof.legal_direction_authority, proof.thesis_authority) == (False, False)
    assert (proof.final_signal_allowed, proof.execution_command_allowed) == (False, False)
    assert not {"valid_until", "evaluated_at", "observed_at", "strategy_thesis_id"} & set(
        StructuralProofEvidenceV31.model_fields
    )


def test_same_material_and_later_reobservation_give_the_same_proof():
    epoch, evaluation = _context()
    first = _promote(epoch, evaluation).proof
    later = _promote(epoch, evaluation, at=DECISION + timedelta(minutes=10)).proof
    assert first is not None and first == later


def test_new_candle_evidence_gives_a_new_proof_id():
    epoch, evaluation = _context()
    h1, m15 = _witnesses()
    completion = m15[-1]
    changed = _rehash_candle({**completion.model_dump(), "high": completion.high + 0.0001})
    first = _promote(epoch, evaluation, witnesses=(h1, m15)).proof
    second = _promote(epoch, evaluation, witnesses=(h1, (*m15[:2], changed))).proof
    assert first is not None and second is not None and first.proof_id != second.proof_id


def test_chronology_is_an_invariant_not_a_sort():
    epoch, evaluation = _context()
    h1, m15 = _witnesses()
    swapped = (m15[0], m15[2], m15[1])  # completion given before the break
    decision = _promote(epoch, evaluation, witnesses=(h1, swapped), pattern="LOOSE_TEST_V1")
    assert (decision.outcome, decision.reason_code) == ("NOT_PROMOTED", "PROOF_SEQUENCE_INVALID")
    proof = _promote(epoch, evaluation).proof
    assert proof is not None
    with pytest.raises(ValidationError, match="PROOF_SEQUENCE_INVALID"):
        StructuralProofEvidenceV31.model_validate(
            {
                **proof.model_dump(),
                "m15_source_candles": (
                    proof.m15_source_candles[0],
                    *proof.m15_source_candles[2:],
                    proof.m15_source_candles[1],
                ),
            }
        )


def test_unclosed_and_future_candles_are_rejected():
    epoch, evaluation = _context()
    at = DECISION + timedelta(seconds=10)
    forming = _witnesses(completion_close_at=at + timedelta(minutes=5))  # completion still forming at `at`
    assert _promote(epoch, evaluation, witnesses=forming, at=at).reason_code == "CANDLE_NOT_CLOSED_AS_OF_DECISION"
    h1_forming = _witnesses(completion_close_at=at + timedelta(minutes=40))  # H1 confirmation closes after `at`
    assert _promote(epoch, evaluation, witnesses=h1_forming, at=at).reason_code == "CANDLE_NOT_CLOSED_AS_OF_DECISION"
    future = _witnesses(completion_close_at=at + timedelta(hours=3))
    assert _promote(epoch, evaluation, witnesses=future, at=at).reason_code == "FUTURE_LEAKAGE_BLOCK"
    h1, _ = _witnesses()
    with pytest.raises(ValidationError):
        _rehash_candle({**h1[0].model_dump(), "is_closed": False})


def test_context_defer_block_and_counter_pressure_never_promote():
    epoch, deferred = _context(quote=False)
    assert _promote(epoch, deferred).reason_code == "CONTEXT_DEFERRED_NO_PROOF_PROMOTION"
    epoch, blocked = _context(route="RANGE_FADE")
    assert _promote(epoch, blocked).reason_code == "CONTEXT_ROUTE_NOT_PERMITTED"
    both = _material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))
    epoch, counter = _context(both, direction="SELL", hypothesis=None, pressure="BUY", route="BREAK_RETEST")
    assert counter.outcome == "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE"
    decision = _promote(epoch, counter, direction="SELL")
    assert decision.reason_code == "COUNTER_PRESSURE_PROOF_NOT_IMPLEMENTED_BY_DESIGN" and decision.proof is None


def test_opposite_evidence_never_touches_the_hypothesis():
    ledger = InMemoryPressureHypothesisLedgerV31()
    hypothesis = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert hypothesis is not None and hypothesis.direction == "BUY"
    epoch, evaluation = _context(hypothesis=hypothesis)
    decision = _promote(epoch, evaluation, direction="SELL")
    assert (decision.outcome, decision.reason_code) == ("NOT_PROMOTED", "PROOF_DIRECTION_NOT_ROUTE_DIRECTION")
    assert ledger.get_record(hypothesis.pressure_hypothesis_id) == hypothesis
    assert ledger.transitions(hypothesis.pressure_hypothesis_id) == ()
    assert ledger.active(hypothesis.strategy_lifecycle_id) == hypothesis.pressure_hypothesis_id


def test_sell_continuation_is_symmetric():
    sell_only = _material(primary_direction_domain="SELL_ONLY", allowed_directions=("SELL",))
    epoch, evaluation = _context(sell_only, direction="SELL", hypothesis=None, route="BREAK_RETEST")
    decision = _promote(epoch, evaluation, direction="SELL")
    assert decision.outcome == "PROMOTED" and decision.proof is not None
    assert (decision.proof.proof_direction, decision.proof.selected_route) == ("SELL", "BREAK_RETEST")


def test_structure_predicates_use_ssot_reason_codes():
    epoch, evaluation = _context()
    h1, m15 = _witnesses()
    weak = _rehash_candle(
        {**h1[1].model_dump(), "close": h1[0].high - 0.0001, "low": min(h1[1].low, h1[0].high - 0.0002)}
    )
    assert _promote(epoch, evaluation, witnesses=((h1[0], weak), m15)).reason_code == "H1_STRUCTURE_UNCONFIRMED"


def test_registry_missing_tampered_or_unknown_pattern_fails_closed():
    epoch, evaluation = _context()
    assert _promote(epoch, evaluation, registry=None).reason_code == "STRUCTURAL_PATTERN_REGISTRY_MISSING"
    assert _promote(epoch, evaluation, pattern="NOPE").reason_code == "PATTERN_NOT_IN_REGISTRY"
    with pytest.raises(ValidationError, match="STRUCTURAL_PATTERN_REGISTRY_HASH_MISMATCH"):
        StructuralPatternRegistryV31.model_validate({**REGISTRY.model_dump(), "registry_version": "tampered.v1"})


def test_forged_identity_or_material_hash_is_rejected():
    epoch, evaluation = _context()
    proof = _promote(epoch, evaluation).proof
    assert proof is not None
    with pytest.raises(ValidationError, match="STRUCTURAL_PROOF_ID_NOT_DERIVED"):
        StructuralProofEvidenceV31.model_validate({**proof.model_dump(), "proof_direction": "SELL"})
    with pytest.raises(ValidationError, match="STRUCTURAL_PROOF_MATERIAL_HASH_MISMATCH"):
        StructuralProofEvidenceV31.model_validate(
            {**proof.model_dump(), "material_evidence_hash": "sha256:" + "1" * 64}
        )


# --- requalification acceptance on the #504 lineage --------------------------------------------------------------


def test_the_proof_lifecycle_is_the_s1b_one_and_the_epoch_must_bind_to_it():
    s1b = _s1b()
    epoch, evaluation = _context()
    proof = _promote(epoch, evaluation).proof
    assert proof is not None
    assert proof.strategy_lifecycle_id == s1b.lifecycle.strategy_lifecycle_id == s1b.receipt.strategy_lifecycle_id
    assert proof.market_episode_id == s1b.episode.market_episode_id
    assert proof.strategy_lifecycle_id == strategy_lifecycle_id_from_episode_v31(proof.market_episode_id)
    foreign_episode = uuid5(s1b.episode.market_episode_id, "a-different-market-episode")
    foreign = _relifecycle(
        s1b.lifecycle,
        market_episode_id=str(foreign_episode),
        strategy_lifecycle_id=str(strategy_lifecycle_id_from_episode_v31(foreign_episode)),
    )
    assert _promote(epoch, evaluation, lifecycle=foreign).reason_code == "EPOCH_LIFECYCLE_MISMATCH"
    terminal = _relifecycle(s1b.lifecycle, state="INVALIDATED")
    assert _promote(epoch, evaluation, lifecycle=terminal).reason_code == "LIFECYCLE_TERMINAL"
    with pytest.raises(ValidationError, match="STRUCTURAL_PROOF_LIFECYCLE_NOT_EPISODE_ROOTED"):
        StructuralProofEvidenceV31.model_validate({**proof.model_dump(), "market_episode_id": foreign_episode})


def test_structural_proof_never_reads_pair_admission_or_an_admission_class():
    forbidden_modules = ("pair_admission", "admission_identity", "per_symbol_admission", "admission_receipt")
    for path in (
        "contracts/strategy_5scr_structural_proof_v31.py",
        "analysis/strategy_5scr_structural_proof_v31.py",
    ):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not any(token in module for token in forbidden_modules), f"{path} imports {module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(token in alias.name for token in forbidden_modules)
        # The admission class must not be reachable as code either: not a name, an attribute or a literal.
        # Docstrings are exempt on purpose - the scan is over identifiers and runtime constants, not prose.
        forbidden_tokens = {"admission_class", "MATURE_ADVISORY", "CANONICAL_RAW", "SymbolAdmissionLineageV3"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_tokens, f"{path} reads name {node.id}"
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden_tokens, f"{path} reads attribute .{node.attr}"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.col_offset != 0:
                # A module/class/function docstring starts at column 0; everything else is a runtime constant.
                assert node.value not in forbidden_tokens, f"{path} holds literal {node.value}"
    assert not {
        "strategy_analysis_admission_id",
        "analysis_admission_class",
        "admission_receipt_hash",
        "admission_revision_id",
    } & set(StructuralProofEvidenceV31.model_fields)


def test_proof_identity_formula_is_pinned_and_material_only():
    """The tuple is spelled out here. A silently widened identity (an admission id, a class, a receipt hash, a
    clock) shifts every proof id uniformly and would otherwise pass every behavioural test in this suite."""

    epoch, evaluation = _context()
    proof = _promote(epoch, evaluation).proof
    assert proof is not None
    name = json.dumps(
        [
            "v31.native-identity.v1",
            str(proof.strategy_lifecycle_id),
            str(proof.context_epoch_id),
            "BUY",
            "PULLBACK_CONTINUATION",
            "fixture-level-v1",
            proof.h1_source_candles[1].candle_evidence_id,
            proof.m15_break_candle_id,
            proof.m15_completion_candle_id,
            proof.m15_completion_kind,
            proof.pattern_registry_hash,
        ],
        separators=(",", ":"),
    )
    assert proof.proof_id == uuid5(V31_STRUCTURAL_PROOF_NAMESPACE, name)
    assert proof.rule_version == "5scr.structural-proof.v31.v2"


def test_an_authority_upgrade_reproduces_the_identical_proof_and_grants_nothing():
    """MATURE_ADVISORY -> proof P; later CANONICAL_RAW on the SAME lifecycle, epoch, route and closed candles
    -> the same P. The shadow phase confers no canonical authority on the upgraded lineage."""

    reduction = _episode()
    advisory = _advisory_s1b(reduction)
    shadow_hypothesis = _hypothesis_from(advisory).hypothesis
    assert shadow_hypothesis is not None and shadow_hypothesis.analysis_admission_class == "MATURE_ADVISORY"
    epoch_a, evaluation_a = _context(lifecycle=advisory.lifecycle, hypothesis=shadow_hypothesis)
    shadow_proof = _promote(epoch_a, evaluation_a, lifecycle=advisory.lifecycle).proof
    assert shadow_proof is not None

    canonical = _canonical_s1b(reduction=reduction, ledger=advisory.ledger, decided_at=DECISION)
    assert canonical is not None
    assert canonical.lifecycle.strategy_lifecycle_id == advisory.lifecycle.strategy_lifecycle_id
    assert canonical.lifecycle.highest_analysis_authority == "CANONICAL_RAW"
    canonical_hypothesis = _hypothesis_from(canonical).hypothesis
    assert canonical_hypothesis is not None
    epoch_b, evaluation_b = _context(lifecycle=canonical.lifecycle, hypothesis=canonical_hypothesis)
    assert epoch_b == epoch_a and evaluation_b == evaluation_a  # #495 already proved this
    canonical_proof = _promote(epoch_b, evaluation_b, lifecycle=canonical.lifecycle).proof
    assert canonical_proof is not None
    assert canonical_proof.proof_id == shadow_proof.proof_id
    assert canonical_proof == shadow_proof  # byte-identical record, not merely the same id

    # Containment: the proof itself carries no authority in either phase, and the shadow candidate is still
    # required to be re-evaluated canonically - authority is never inherited through structural evidence.
    for record in (shadow_proof, canonical_proof):
        assert record.authority == "STRUCTURAL_EVIDENCE_ONLY"
        assert (record.legal_direction_authority, record.thesis_authority) == (False, False)
        assert (record.final_signal_allowed, record.execution_command_allowed) == (False, False)
    assert (
        require_canonical_lineage_v31(canonical.lifecycle, advisory.admission.strategy_analysis_admission_id)
        == "ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED"
    )


def test_context_outcomes_gate_promotion_exactly():
    for kwargs, reason in (
        ({"quote": False}, "CONTEXT_DEFERRED_NO_PROOF_PROMOTION"),
        ({"location": "UNFAVORABLE"}, "CONTEXT_DEFERRED_NO_PROOF_PROMOTION"),
        ({"route": "RANGE_FADE"}, "CONTEXT_ROUTE_NOT_PERMITTED"),
        ({"invalidate": "sha256:" + "2" * 64}, "CONTEXT_ROUTE_NOT_PERMITTED"),
    ):
        epoch, evaluation = _context(**kwargs)
        decision = _promote(epoch, evaluation)
        assert (decision.outcome, decision.reason_code, decision.proof) == ("NOT_PROMOTED", reason, None)
    sell_only = _material(primary_direction_domain="SELL_ONLY", allowed_directions=("SELL",))
    epoch, conflicting = _context(sell_only, hypothesis=None)
    assert conflicting.outcome == "CONFLICT"
    assert _promote(epoch, conflicting).reason_code == "CONTEXT_ROUTE_NOT_PERMITTED"


def test_a_tampered_candle_is_rejected_even_though_the_model_itself_accepts_it():
    """ClosedCandleAuthorityRefV1 does not self-verify its hashes, so the builder must. Content, evidence id and
    material hash are each checked: a candle whose body no longer matches its hash can never become evidence."""

    epoch, evaluation = _context()
    h1, m15 = _witnesses()
    assert _promote(epoch, evaluation, witnesses=(h1, m15)).outcome == "PROMOTED"
    silent_close = m15[1].model_copy(update={"close": m15[1].close + 0.0005})  # body moved, hashes left behind
    assert _promote(epoch, evaluation, witnesses=(h1, (m15[0], silent_close, m15[2]))).reason_code == (
        "CANDLE_HASH_MISMATCH"
    )
    forged_id = h1[0].model_copy(update={"candle_evidence_id": "sha256:" + "3" * 64})
    assert _promote(epoch, evaluation, witnesses=((forged_id, h1[1]), m15)).reason_code == "CANDLE_HASH_MISMATCH"
    forged_material = h1[1].model_copy(update={"material_candle_hash": "sha256:" + "4" * 64})
    assert _promote(epoch, evaluation, witnesses=((h1[0], forged_material), m15)).reason_code == (
        "CANDLE_HASH_MISMATCH"
    )


def test_every_non_align_outcome_is_refused_and_the_set_is_exhaustive():
    """The gate is enumerated, not sampled: if a new ContextOutcome is ever added, this test fails until its
    promotion behaviour is decided explicitly."""

    both = _material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))
    sell_only = _material(primary_direction_domain="SELL_ONLY", allowed_directions=("SELL",))
    cases = (
        (_context(quote=False), "BUY", "CONTEXT_DEFERRED_NO_PROOF_PROMOTION"),
        (_context(route="RANGE_FADE"), "BUY", "CONTEXT_ROUTE_NOT_PERMITTED"),
        (_context(sell_only, hypothesis=None), "BUY", "CONTEXT_ROUTE_NOT_PERMITTED"),
        (_context(invalidate="sha256:" + "5" * 64), "BUY", "CONTEXT_ROUTE_NOT_PERMITTED"),
        (
            _context(both, direction="SELL", hypothesis=None, pressure="BUY", route="BREAK_RETEST"),
            "SELL",
            "COUNTER_PRESSURE_PROOF_NOT_IMPLEMENTED_BY_DESIGN",
        ),
    )
    covered = set()
    for (epoch, evaluation), direction, reason in cases:
        decision = _promote(epoch, evaluation, direction=direction)
        assert (decision.outcome, decision.reason_code, decision.proof) == ("NOT_PROMOTED", reason, None)
        covered.add(evaluation.outcome)
    assert covered == set(get_args(ContextOutcome)) - {"ALIGN"}
