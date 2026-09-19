"""Gap #10 acceptance: StructuralProofEvidenceV31, CONTINUATION only (authority decisions 2026-09-19)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_pressure_hypothesis_v31 import InMemoryPressureHypothesisLedgerV31, admit_hypothesis_v31
from analysis.strategy_5scr_structural_proof_v31 import build_structural_proof_v31
from contracts.strategy_5scr_context_epoch_v31 import with_hash
from contracts.strategy_5scr_structural_proof_v31 import (
    StructuralPatternRegistryV31,
    StructuralPatternV31,
    StructuralProofEvidenceV31,
)
from tests.test_strategy_5scr_context_epoch_v31 import _epoch, _evaluate, _material
from tests.test_strategy_5scr_directional_thesis_v1 import _candles, _rehash_candle
from tests.test_strategy_5scr_pressure_hypothesis_v31 import DECISION, _build


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


def _context(material=None, **evaluate):
    epoch = _epoch(material).epoch
    evaluation = _evaluate(epoch, **evaluate).evaluation
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
):
    h1, m15 = witnesses or _witnesses(direction)
    return build_structural_proof_v31(
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
