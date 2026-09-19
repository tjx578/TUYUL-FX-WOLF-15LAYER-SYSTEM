"""Gap #11 acceptance: DirectionalThesisV31 (owner decisions D1–D9, 2026-09-19).

THESIS_DIRECTION_AUTHORITY = TRUE only in authoritative states; THESIS_EXECUTION_AUTHORITY = FALSE always.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_context_epoch_v31 import evaluate_context_route_v31, resolve_context_epoch_v31
from analysis.strategy_5scr_directional_thesis_v31 import (
    InMemoryDirectionalThesisLedgerV31,
    confirm_thesis_v31,
    expire_thesis_clock_v31,
    invalidate_thesis_structurally_v31,
    open_thesis_v31,
    terminate_thesis_for_epoch_v31,
    thesis_status_v31,
)
from analysis.strategy_5scr_pressure_hypothesis_v31 import (
    InMemoryPressureHypothesisLedgerV31,
    admit_hypothesis_v31,
    build_pressure_hypothesis_v31,
    make_transition_v31,
    maturity_evidence_from_lineage,
)
from analysis.strategy_5scr_structural_proof_v31 import build_structural_proof_v31
from contracts.strategy_5scr_admission_identity_v31 import admission_receipt_hash_v31, build_admission_receipt_v31
from contracts.strategy_5scr_context_epoch_v31 import with_hash
from contracts.strategy_5scr_directional_thesis_v1 import ClosedCandleAuthorityRefV1
from contracts.strategy_5scr_directional_thesis_v31 import (
    DirectionalThesisStatusV31,
    DirectionalThesisTransitionV31,
    DirectionalThesisV31,
    RouteThesisClassV31,
    StructuralProofActionabilityPolicyV31,
    ThesisClassRegistryV31,
    ThesisClockPolicyV31,
    direction_authority_v31,
    thesis_id_v31,
)
from tests.test_strategy_5scr_context_epoch_v31 import CLOCK as CONTEXT_CLOCK
from tests.test_strategy_5scr_context_epoch_v31 import POLICY as ROUTE_POLICY
from tests.test_strategy_5scr_context_epoch_v31 import REGISTRY as DOMAIN_REGISTRY
from tests.test_strategy_5scr_context_epoch_v31 import _material
from tests.test_strategy_5scr_directional_thesis_v1 import _candles, _rehash_candle
from tests.test_strategy_5scr_per_symbol_admission import POLICY as ADMISSION_POLICY
from tests.test_strategy_5scr_per_symbol_admission import _evaluate as _admission
from tests.test_strategy_5scr_per_symbol_admission import _raw, _safety
from tests.test_strategy_5scr_pressure_hypothesis_v31 import CLOCK as HYPOTHESIS_CLOCK
from tests.test_strategy_5scr_pressure_hypothesis_v31 import DECISION, _authority, _maturity
from tests.test_strategy_5scr_structural_proof_v31 import PATTERN
from tests.test_strategy_5scr_structural_proof_v31 import REGISTRY as PATTERN_REGISTRY

CLASSES = with_hash(
    ThesisClassRegistryV31,
    "registry_hash",
    registry_version="test-thesis-class.v1",
    mappings=(
        RouteThesisClassV31(route="PULLBACK_CONTINUATION", thesis_class="CONTINUATION"),
        RouteThesisClassV31(route="BREAK_RETEST", thesis_class="CONTINUATION"),
    ),
)
THESIS_CLOCK = with_hash(
    ThesisClockPolicyV31,
    "policy_hash",
    clock_policy_version="test-thesis-clock.v1",
    ttl_seconds=1800,
    clock_source="INJECTED_DECISION_CLOCK",
)
ACTIONABILITY = with_hash(
    StructuralProofActionabilityPolicyV31,
    "policy_hash",
    policy_version="test-proof-actionability.v1",
    coverage_rule="CONTIGUOUS_CLOSED_CANDLES_THROUGH_DECISION",
    h1_invalidation_rule="ADJACENT_COUNTER_BREAK_CLOSE_BEYOND_ANCHOR_EXTREME",
    m15_invalidation_rule="CLOSE_BACK_THROUGH_BREAK_LEVEL",
)
COMPLETION = DECISION - timedelta(seconds=60)
BIND_AT = DECISION + timedelta(seconds=10)
FORBIDDEN_FIELDS = {
    "entry",
    "entry_price",
    "candidate_entry",
    "entry_interval",
    "stop_loss",
    "structural_sl",
    "sl",
    "take_profit",
    "tp1",
    "target_id",
    "gross_rr",
    "net_rr",
    "rr",
    "volume",
    "lot_size",
    "filled_volume",
    "spread",
    "margin",
    "execution_box_id",
    "tradeplan_id",
    "risk_reservation_id",
    "execution_command_id",
    "broker_order_id",
    "broker_symbol",
}


@dataclass
class Chain:
    hypotheses: InMemoryPressureHypothesisLedgerV31
    hypothesis: Any
    epoch: Any
    evaluation: Any


def _hypothesis(ledger, symbol: str = "EURUSD", direction: str = "BUY", *, safety=None):
    evaluation = _admission([_raw(0, symbol, direction), _raw(300, symbol, direction)], safety=safety)
    lineage = evaluation.lineages[symbol][-1]
    receipt = build_admission_receipt_v31(lineage, policy=ADMISSION_POLICY)
    decision = build_pressure_hypothesis_v31(
        admission_receipt=receipt,
        admission_receipt_hash=admission_receipt_hash_v31(receipt),
        lifecycle_anchor=f"{symbol.lower()}-lifecycle-1",
        pressure_authority=_authority(direction, symbol=symbol),
        maturity_evidence=maturity_evidence_from_lineage(lineage),
        maturity_policy=_maturity(),
        clock_policy=HYPOTHESIS_CLOCK,
        decision_at=DECISION,
    )
    return admit_hypothesis_v31(ledger, decision, decision_at=DECISION).hypothesis


def _resolve(hypothesis, material, *, previous=None, at: datetime = DECISION):
    return resolve_context_epoch_v31(
        strategy_lifecycle_id=hypothesis.strategy_lifecycle_id,
        canonical_symbol=hypothesis.canonical_symbol,
        material=material,
        source_closed_through=DECISION - timedelta(seconds=60),
        registry=DOMAIN_REGISTRY,
        clock_policy=CONTEXT_CLOCK,
        previous=previous,
        previous_terminated=False,
        decision_at=at,
    )


def _evaluation(epoch, hypothesis, *, direction=None, pressure=None, route=None, quote=True, at=DECISION):
    direction = direction or hypothesis.direction
    decision = evaluate_context_route_v31(
        epoch=epoch,
        evaluated_direction=direction,
        hypothesis=hypothesis if direction == hypothesis.direction else None,
        pressure_direction=pressure,
        requested_route=route or ("PULLBACK_CONTINUATION" if direction == "BUY" else "BREAK_RETEST"),
        location_alignment="FAVORABLE",
        quote_authoritative=quote,
        registry=DOMAIN_REGISTRY,
        policy=ROUTE_POLICY,
        decision_at=at,
    )
    assert decision.evaluation is not None, decision.reason_code
    return decision.evaluation


def _sell_material():
    return _material(primary_direction_domain="SELL_ONLY", allowed_directions=("SELL",))


def _chain(symbol: str = "EURUSD", direction: str = "BUY", *, ledger=None, material=None, safety=None) -> Chain:
    ledger = ledger or InMemoryPressureHypothesisLedgerV31()
    hypothesis = _hypothesis(ledger, symbol, direction, safety=safety)
    epoch = _resolve(hypothesis, material or (_material() if direction == "BUY" else _sell_material())).epoch
    return Chain(ledger, hypothesis, epoch, _evaluation(epoch, hypothesis))


def _witnesses(symbol: str, direction: str = "BUY", *, completion_close_at: datetime = COMPLETION, high_bump=0.0):
    h1, m15 = _candles(direction)  # type: ignore[arg-type]
    offset = completion_close_at - m15[-1].close_time_utc

    def shifted(candles):
        return tuple(
            _rehash_candle(
                {
                    **c.model_dump(),
                    "symbol": symbol,
                    "open_time_utc": c.open_time_utc + offset,
                    "close_time_utc": c.close_time_utc + offset,
                }
            )
            for c in candles
        )

    h1s, m15s = shifted(h1), shifted(m15)
    if high_bump:
        last = m15s[-1]
        m15s = (*m15s[:2], _rehash_candle({**last.model_dump(), "high": last.high + high_bump}))
    return h1s, m15s


def _proof(chain: Chain, *, direction: str | None = None, at: datetime = BIND_AT, high_bump=0.0, evaluation=None):
    direction = direction or str(chain.hypothesis.direction)
    h1, m15 = _witnesses(chain.epoch.canonical_symbol, direction, high_bump=high_bump)
    decision = build_structural_proof_v31(
        epoch=chain.epoch,
        evaluation=evaluation or chain.evaluation,
        proof_direction=direction,  # type: ignore[arg-type]
        h1_witnesses=h1,
        m15_witnesses=m15,
        level_version="fixture-level-v1",
        pattern_id=PATTERN,
        registry=PATTERN_REGISTRY,
        decision_at=at,
    )
    assert decision.proof is not None, decision.reason_code
    return decision.proof


def _later_m15(proof, close: float) -> ClosedCandleAuthorityRefV1:
    """The next M15 candle after the proof completion, closing at ``close``."""

    last = proof.m15_source_candles[-1]
    return _rehash_candle(
        {
            **last.model_dump(),
            "open_time_utc": last.close_time_utc,
            "close_time_utc": last.close_time_utc + timedelta(minutes=15),
            "open": last.close,
            "high": max(last.close, close) + 0.0005,
            "low": min(last.close, close) - 0.0005,
            "close": close,
        }
    )


def _open(store, chain: Chain, **overrides):
    values: dict[str, Any] = {
        "epoch": chain.epoch,
        "evaluation": chain.evaluation,
        "hypothesis": chain.hypothesis,
        "hypothesis_store": chain.hypotheses,
        "class_registry": CLASSES,
        "clock_policy": THESIS_CLOCK,
        "decision_at": DECISION,
        **overrides,
    }
    return open_thesis_v31(store, **values)


def _confirm(store, chain: Chain, thesis, proof, **overrides):
    values: dict[str, Any] = {
        "strategy_thesis_id": thesis.strategy_thesis_id,
        "proof": proof,
        "epoch": chain.epoch,
        "evaluation": chain.evaluation,
        "hypothesis_store": chain.hypotheses,
        "actionability_policy": ACTIONABILITY,
        "later_h1": (),
        "later_m15": (),
        "decision_at": BIND_AT,
        **overrides,
    }
    return confirm_thesis_v31(store, **values)


def _confirmed(store=None, chain=None):
    store = store or InMemoryDirectionalThesisLedgerV31()
    chain = chain or _chain()
    thesis = _open(store, chain).thesis
    assert thesis is not None
    proof = _proof(chain)
    assert _confirm(store, chain, thesis, proof).outcome == "CONFIRMED"
    return store, chain, thesis, proof


def test_align_with_active_same_direction_hypothesis_opens_pending_thesis_without_authority():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    decision = _open(store, chain)
    thesis = decision.thesis
    assert (decision.outcome, decision.reason_code) == ("CREATED", "THESIS_OPENED_PENDING_H1")
    assert thesis is not None and thesis.strategy_thesis_id.version == 5
    status = thesis_status_v31(store, thesis.strategy_thesis_id)
    assert (status.state, status.direction_authority, status.bound_structural_proof_id) == ("PENDING_H1", False, None)
    assert (thesis.direction, thesis.thesis_class, thesis.selected_route) == (
        "BUY",
        "CONTINUATION",
        "PULLBACK_CONTINUATION",
    )
    assert (thesis.execution_authority, thesis.final_signal_allowed, thesis.execution_command_allowed) == (
        False,
        False,
        False,
    )
    assert store.active(chain.epoch.strategy_lifecycle_id) == thesis.strategy_thesis_id


def test_complete_actionable_proof_confirms_and_direction_authority_is_born():
    store, chain, thesis, proof = _confirmed()
    status = thesis_status_v31(store, thesis.strategy_thesis_id)
    assert (status.state, status.direction, status.direction_authority) == ("STRUCTURALLY_CONFIRMED", "BUY", True)
    assert (status.bound_structural_proof_id, status.bound_structural_proof_hash) == (
        proof.proof_id,
        proof.material_evidence_hash,
    )
    assert (status.execution_authority, status.final_signal_allowed, status.execution_command_allowed) == (
        False,
        False,
        False,
    )
    (transition,) = store.transitions(thesis.strategy_thesis_id)
    assert (transition.from_state, transition.to_state, transition.reason_code) == (
        "PENDING_H1",
        "STRUCTURALLY_CONFIRMED",
        "STRUCTURAL_PROOF_BOUND",
    )
    assert transition.resolution_evidence_hash is not None


def test_direction_authority_is_derived_and_never_execution_authority():
    assert [
        s
        for s in ("PENDING_H1", "PENDING_M15", "STRUCTURALLY_CONFIRMED", "GEOMETRY_PENDING", "EXPIRED")
        if direction_authority_v31(s)
    ] == [
        "STRUCTURALLY_CONFIRMED",
        "GEOMETRY_PENDING",
    ]
    store, _, thesis, _ = _confirmed()
    status = thesis_status_v31(store, thesis.strategy_thesis_id)
    with pytest.raises(ValidationError, match="DIRECTION_AUTHORITY_IS_DERIVED_FROM_STATE"):
        DirectionalThesisStatusV31.model_validate({**status.model_dump(), "state": "PENDING_H1"})
    with pytest.raises(ValidationError):
        DirectionalThesisStatusV31.model_validate({**status.model_dump(), "execution_authority": True})


def test_thesis_identity_is_proof_independent_and_reobservation_is_idempotent():
    store, chain, thesis, proof = _confirmed()
    assert thesis.strategy_thesis_id == thesis_id_v31(
        strategy_lifecycle_id=chain.epoch.strategy_lifecycle_id,
        context_epoch_id=chain.epoch.context_epoch_id,
        direction="BUY",
        thesis_class="CONTINUATION",
        selected_route="PULLBACK_CONTINUATION",
        pressure_hypothesis_id=chain.hypothesis.pressure_hypothesis_id,
    )
    reopened = _open(store, chain, decision_at=DECISION + timedelta(seconds=30))
    assert (reopened.outcome, reopened.thesis) == ("ALREADY_OPEN", thesis)
    same = _confirm(store, chain, thesis, _proof(chain, at=BIND_AT + timedelta(minutes=5)))
    assert (same.outcome, same.reason_code) == ("ALREADY_CONFIRMED", "SAME_PROOF_ALREADY_BOUND")
    other = _proof(chain, high_bump=0.0001)
    assert other.proof_id != proof.proof_id
    additional = _confirm(store, chain, thesis, other)
    assert (additional.outcome, additional.reason_code) == (
        "ALREADY_CONFIRMED",
        "ADDITIONAL_PROOF_NOT_BOUND_CHILD_TRIGGER_OUT_OF_SCOPE",
    )
    assert len(store.transitions(thesis.strategy_thesis_id)) == 1
    assert thesis_status_v31(store, thesis.strategy_thesis_id).bound_structural_proof_id == proof.proof_id


def test_a_different_proof_confirms_the_same_pending_thesis_id():
    first_store, chain, first, _ = _confirmed()
    second_store = InMemoryDirectionalThesisLedgerV31()
    second = _open(second_store, chain).thesis
    assert (
        second is not None
        and _confirm(second_store, chain, second, _proof(chain, high_bump=0.0001)).outcome == "CONFIRMED"
    )
    assert first.strategy_thesis_id == second.strategy_thesis_id


def test_proof_lineage_mismatch_is_rejected_without_writes():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    thesis = _open(store, chain).thesis
    assert thesis is not None
    other_epoch = _resolve(chain.hypothesis, _material(target_map_version="tm.v2")).epoch
    other = Chain(chain.hypotheses, chain.hypothesis, other_epoch, _evaluation(other_epoch, chain.hypothesis))
    decision = _confirm(store, chain, thesis, _proof(other))
    assert (decision.outcome, decision.reason_code) == ("NOT_CONFIRMED", "PROOF_LINEAGE_MISMATCH")
    assert store.transitions(thesis.strategy_thesis_id) == ()


def test_opposite_direction_is_counter_pressure_not_implemented_and_hypothesis_is_untouched():
    both = _material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain(material=both)
    counter = _evaluation(chain.epoch, chain.hypothesis, direction="SELL", pressure="BUY", route="BREAK_RETEST")
    assert counter.outcome == "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE"
    decision = _open(store, chain, evaluation=counter)
    assert decision.reason_code == "COUNTER_PRESSURE_THESIS_NOT_IMPLEMENTED_BY_DESIGN" and decision.thesis is None

    thesis = _open(store, chain).thesis
    assert thesis is not None
    before = (
        chain.hypotheses.transitions(chain.hypothesis.pressure_hypothesis_id),
        chain.hypotheses.active(chain.hypothesis.strategy_lifecycle_id),
    )
    sell = _chain("EURUSD", "SELL")
    sell_proof = _proof(sell)
    assert _confirm(store, chain, thesis, sell_proof).reason_code == "COUNTER_PRESSURE_THESIS_NOT_IMPLEMENTED_BY_DESIGN"
    assert (
        chain.hypotheses.transitions(chain.hypothesis.pressure_hypothesis_id),
        chain.hypotheses.active(chain.hypothesis.strategy_lifecycle_id),
    ) == before
    assert _open(store, chain, hypothesis=None).reason_code == "THESIS_WITHOUT_HYPOTHESIS_NOT_IMPLEMENTED_BY_DESIGN"


def test_defer_or_conflict_never_opens_and_a_current_defer_blocks_confirmation():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    deferred = _evaluation(chain.epoch, chain.hypothesis, quote=False)
    assert _open(store, chain, evaluation=deferred).reason_code == "CONTEXT_DEFERRED_NO_THESIS"
    sell_only = _chain(material=_sell_material())
    assert sell_only.evaluation.outcome == "CONFLICT"
    assert _open(store, sell_only).reason_code == "CONTEXT_CONFLICT"

    thesis = _open(store, chain).thesis
    assert thesis is not None
    now_deferred = _evaluation(chain.epoch, chain.hypothesis, quote=False, at=BIND_AT)
    assert now_deferred.evaluation_id == thesis.context_route_evaluation_id
    decision = _confirm(store, chain, thesis, _proof(chain), evaluation=now_deferred)
    assert decision.reason_code == "CONTEXT_DEFERRED_NO_THESIS_CONFIRMATION"
    assert store.transitions(thesis.strategy_thesis_id) == ()


def test_proof_actionability_requires_full_later_coverage_and_no_invalidating_evidence():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    thesis = _open(store, chain).thesis
    assert thesis is not None
    proof = _proof(chain)
    later = COMPLETION + timedelta(minutes=15, seconds=5)  # one more M15 candle has closed
    assert (
        _confirm(store, chain, thesis, proof, decision_at=later).reason_code
        == "PROOF_ACTIONABILITY_EVIDENCE_INCOMPLETE"
    )
    level = proof.m15_break_evidence.level
    failed = _later_m15(proof, level)  # closes back at the break level
    assert (
        _confirm(store, chain, thesis, proof, decision_at=later, later_m15=(failed,)).reason_code
        == "PROOF_NOT_ACTIONABLE_M15_BREAK_LEVEL_FAILED"
    )
    assert store.transitions(thesis.strategy_thesis_id) == ()
    holding = _later_m15(proof, level + 0.0020)
    decision = _confirm(store, chain, thesis, proof, decision_at=later, later_m15=(holding,))
    assert decision.outcome == "CONFIRMED"
    assert proof == _proof(chain)  # the #497 record is untouched


def test_structural_invalidation_of_a_confirmed_thesis():
    store, chain, thesis, proof = _confirmed()
    later = COMPLETION + timedelta(minutes=15, seconds=5)
    kwargs: dict[str, Any] = {
        "strategy_thesis_id": thesis.strategy_thesis_id,
        "proof": proof,
        "actionability_policy": ACTIONABILITY,
        "later_h1": (),
        "decision_at": later,
    }
    assert (
        invalidate_thesis_structurally_v31(store, later_m15=(), **kwargs).reason_code
        == "PROOF_ACTIONABILITY_EVIDENCE_INCOMPLETE"
    )
    holding = _later_m15(proof, proof.m15_break_evidence.level + 0.0020)
    assert (
        invalidate_thesis_structurally_v31(store, later_m15=(holding,), **kwargs).reason_code == "STRUCTURE_STILL_VALID"
    )
    failed = _later_m15(proof, proof.m15_break_evidence.level - 0.0010)
    decision = invalidate_thesis_structurally_v31(store, later_m15=(failed,), **kwargs)
    assert (decision.outcome, decision.transition and decision.transition.reason_code) == (
        "TERMINATED",
        "THESIS_INVALIDATED",
    )
    status = thesis_status_v31(store, thesis.strategy_thesis_id)
    assert (status.state, status.direction_authority) == ("INVALIDATED", False)
    assert store.active(chain.epoch.strategy_lifecycle_id) is None


def test_epoch_supersession_supersedes_and_one_active_thesis_per_lifecycle():
    store, chain, thesis, _ = _confirmed()
    at = DECISION + timedelta(seconds=120)
    changed = _material(target_map_version="tm.v2")
    resolution = _resolve(chain.hypothesis, changed, previous=chain.epoch, at=at)
    assert resolution.termination is not None and resolution.termination.terminal_state == "SUPERSEDED"
    new = Chain(
        chain.hypotheses, chain.hypothesis, resolution.epoch, _evaluation(resolution.epoch, chain.hypothesis, at=at)
    )
    blocked = _open(store, new, decision_at=at)
    assert (blocked.outcome, blocked.reason_code) == ("NOT_CREATED", "ACTIVE_THESIS_EXISTS")

    ended = terminate_thesis_for_epoch_v31(
        store, strategy_thesis_id=thesis.strategy_thesis_id, termination=resolution.termination
    )
    assert (ended.outcome, ended.reason_code) == ("TERMINATED", "THESIS_SUPERSEDED")
    assert thesis_status_v31(store, thesis.strategy_thesis_id).direction_authority is False
    successor = _open(store, new, decision_at=at)
    assert successor.outcome == "CREATED" and successor.thesis is not None
    assert successor.thesis.strategy_thesis_id != thesis.strategy_thesis_id
    assert _open(store, chain, decision_at=at).reason_code == "TERMINAL_THESIS_NOT_REVIVED"


def test_epoch_expiry_expires_the_thesis_and_the_thesis_clock_is_bounded_by_the_epoch():
    long_clock = with_hash(
        ThesisClockPolicyV31,
        "policy_hash",
        clock_policy_version="test-thesis-clock-long.v1",
        ttl_seconds=7200,
        clock_source="INJECTED_DECISION_CLOCK",
    )
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    thesis = _open(store, chain, clock_policy=long_clock).thesis
    assert thesis is not None
    assert (thesis.valid_until, thesis.valid_until_bound) == (chain.epoch.valid_until, "CONTEXT_EPOCH_DEADLINE")
    at = chain.epoch.valid_until + timedelta(seconds=1)
    resolution = _resolve(chain.hypothesis, _material(target_map_version="tm.v3"), previous=chain.epoch, at=at)
    assert resolution.termination is not None and resolution.termination.terminal_state == "EXPIRED"
    ended = terminate_thesis_for_epoch_v31(
        store, strategy_thesis_id=thesis.strategy_thesis_id, termination=resolution.termination
    )
    assert ended.outcome == "TERMINATED" and ended.transition is not None
    assert (ended.transition.to_state, ended.transition.reason_code) == ("EXPIRED", "CONTEXT_EPOCH_EXPIRED")
    with pytest.raises(ValidationError, match="THESIS_VALID_UNTIL_NOT_DERIVED"):
        DirectionalThesisV31.model_validate({**thesis.model_dump(), "valid_until": at})


def test_thesis_clock_expiry_is_terminal_and_hypothesis_expiry_does_not_expire_a_confirmed_thesis():
    store, chain, thesis, _ = _confirmed()
    hypothesis = chain.hypothesis
    chain.hypotheses.append_transition(
        make_transition_v31(
            record=hypothesis,
            history=chain.hypotheses.transitions(hypothesis.pressure_hypothesis_id),
            to_state="EXPIRED",
            context_alignment="ALIGNED",
            location_alignment="FAVORABLE",
            reason_code="HYPOTHESIS_CLOCK_EXPIRED",
            material_event_id="clock-expiry:test",
            material_event_hash="sha256:" + "a" * 64,
            occurred_at=hypothesis.valid_until,
        )
    )
    assert thesis_status_v31(store, thesis.strategy_thesis_id).state == "STRUCTURALLY_CONFIRMED"
    early = expire_thesis_clock_v31(
        store, strategy_thesis_id=thesis.strategy_thesis_id, decision_at=thesis.valid_until - timedelta(seconds=1)
    )
    assert early.reason_code == "THESIS_CLOCK_ACTIVE"
    ended = expire_thesis_clock_v31(store, strategy_thesis_id=thesis.strategy_thesis_id, decision_at=thesis.valid_until)
    assert ended.transition is not None and (ended.transition.to_state, ended.transition.reason_code) == (
        "EXPIRED",
        "THESIS_CLOCK_EXPIRED",
    )
    assert _confirm(store, chain, thesis, _proof(chain)).reason_code == "THESIS_TERMINAL"


def test_pending_thesis_cannot_confirm_after_its_hypothesis_is_no_longer_active():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    thesis = _open(store, chain).thesis
    assert thesis is not None
    chain.hypotheses.swap_active(
        chain.hypothesis.strategy_lifecycle_id, expected=chain.hypothesis.pressure_hypothesis_id, new=None
    )
    assert _confirm(store, chain, thesis, _proof(chain)).reason_code == "HYPOTHESIS_NOT_ACTIVE"


@pytest.mark.parametrize("override", [{"kill_switch_active": True}, {"database_and_governance_ok": False}])
def test_global_safety_toggle_leaves_the_thesis_record_unchanged(override):
    baseline = _open(InMemoryDirectionalThesisLedgerV31(), _chain()).thesis
    vetoed = _open(InMemoryDirectionalThesisLedgerV31(), _chain(safety=_safety(**override))).thesis
    assert baseline is not None and baseline == vetoed


def test_thesis_supersession_is_pair_local():
    store, hypotheses = InMemoryDirectionalThesisLedgerV31(), InMemoryPressureHypothesisLedgerV31()
    eurusd = _chain("EURUSD", ledger=hypotheses)
    gbpusd = _chain("GBPUSD", ledger=hypotheses)
    eur = _open(store, eurusd).thesis
    _, _, gbp, _ = _confirmed(store, gbpusd)
    assert eur is not None and eur.canonical_symbol == "EURUSD" and gbp.canonical_symbol == "GBPUSD"
    snapshot = (
        store.get_record(gbp.strategy_thesis_id),
        store.transitions(gbp.strategy_thesis_id),
        store.active(gbp.strategy_lifecycle_id),
    )
    at = DECISION + timedelta(seconds=120)
    resolution = _resolve(eurusd.hypothesis, _material(target_map_version="tm.v2"), previous=eurusd.epoch, at=at)
    assert resolution.termination is not None
    terminate_thesis_for_epoch_v31(store, strategy_thesis_id=eur.strategy_thesis_id, termination=resolution.termination)
    assert thesis_status_v31(store, eur.strategy_thesis_id).state == "SUPERSEDED"
    assert (
        store.get_record(gbp.strategy_thesis_id),
        store.transitions(gbp.strategy_thesis_id),
        store.active(gbp.strategy_lifecycle_id),
    ) == snapshot
    assert thesis_status_v31(store, gbp.strategy_thesis_id).direction_authority is True


def test_registry_clock_and_policy_fail_closed():
    store, chain = InMemoryDirectionalThesisLedgerV31(), _chain()
    assert _open(store, chain, class_registry=None).reason_code == "THESIS_CLASS_REGISTRY_MISSING"
    assert _open(store, chain, clock_policy=None).reason_code == "THESIS_CLOCK_POLICY_MISSING"
    unmapped = with_hash(
        ThesisClassRegistryV31,
        "registry_hash",
        registry_version="test-thesis-class-unmapped.v1",
        mappings=(RouteThesisClassV31(route="BREAK_RETEST", thesis_class="CONTINUATION"),),
    )
    assert _open(store, chain, class_registry=unmapped).reason_code == "THESIS_CLASS_MAPPING_MISSING"
    breakout = with_hash(
        ThesisClassRegistryV31,
        "registry_hash",
        registry_version="test-thesis-class-breakout.v1",
        mappings=(RouteThesisClassV31(route="PULLBACK_CONTINUATION", thesis_class="BREAKOUT"),),
    )
    assert _open(store, chain, class_registry=breakout).reason_code == "THESIS_CLASS_NOT_IMPLEMENTED_BY_DESIGN"
    with pytest.raises(ValidationError, match="THESIS_CLASS_REGISTRY_HASH_MISMATCH"):
        ThesisClassRegistryV31.model_validate({**CLASSES.model_dump(), "registry_version": "tampered.v1"})
    thesis = _open(store, chain).thesis
    assert thesis is not None
    assert (
        _confirm(store, chain, thesis, _proof(chain), actionability_policy=None).reason_code
        == "PROOF_ACTIONABILITY_POLICY_MISSING"
    )


def test_contracts_reject_forged_identity_unreachable_states_and_misplaced_binding():
    store, _, thesis, _ = _confirmed()
    with pytest.raises(ValidationError, match="THESIS_ID_NOT_DERIVED"):
        DirectionalThesisV31.model_validate({**thesis.model_dump(), "direction": "SELL"})
    (transition,) = store.transitions(thesis.strategy_thesis_id)
    body = transition.model_dump()
    for to_state in ("GEOMETRY_PENDING", "PENDING_M15", "PENDING_CONTEXT", "DORMANT"):
        with pytest.raises(ValidationError, match="THESIS_TRANSITION_NOT_PERMITTED"):
            DirectionalThesisTransitionV31.model_validate({**body, "to_state": to_state})
    with pytest.raises(ValidationError, match="CONFIRMATION_REQUIRES_COMPLETE_PROOF_BINDING"):
        DirectionalThesisTransitionV31.model_validate({**body, "bound_structural_proof_id": None})
    with pytest.raises(ValidationError, match="PROOF_BINDING_ONLY_ON_CONFIRMATION"):
        DirectionalThesisTransitionV31.model_validate(
            {**body, "to_state": "INVALIDATED", "reason_code": "THESIS_INVALIDATED"}
        )
    with pytest.raises(ValidationError, match="THESIS_TRANSITION_HASH_MISMATCH"):
        DirectionalThesisTransitionV31.model_validate(
            {**body, "occurred_at": body["occurred_at"] + timedelta(seconds=1)}
        )


def test_thesis_is_not_a_tradeplan_by_contract():
    for model in (DirectionalThesisV31, DirectionalThesisTransitionV31, DirectionalThesisStatusV31):
        assert FORBIDDEN_FIELDS.isdisjoint(model.model_fields), model.__name__
    assert DirectionalThesisV31.model_fields["execution_authority"].default is False
    _, _, thesis, _ = _confirmed()
    with pytest.raises(ValidationError):
        DirectionalThesisV31.model_validate({**thesis.model_dump(), "entry": 1.1})
    with pytest.raises(ValidationError):
        DirectionalThesisV31.model_validate({**thesis.model_dump(), "execution_authority": True})
