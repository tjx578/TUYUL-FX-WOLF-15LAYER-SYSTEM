"""Gap #9 acceptance: ContextEpochV31 + ContextRouteEvaluationV31 + positive receipt projection (Option A)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_context_epoch_v31 import (
    evaluate_context_route_v31,
    hypothesis_transition_for_evaluation_v31,
    project_context_route_receipt_v31,
    resolve_context_epoch_v31,
)
from analysis.strategy_5scr_pressure_hypothesis_v31 import (
    InMemoryPressureHypothesisLedgerV31,
    admit_hypothesis_v31,
    make_transition_v31,
)
from contracts.strategy_5scr_context_epoch_v31 import (
    ContextClockPolicyV31,
    ContextEpochV31,
    ContextRouteEvaluationV31,
    DirectionDomainEntryV31,
    DirectionDomainRegistryV31,
    LocationRoutePolicyV31,
    RouteRuleV31,
    with_hash,
)
from contracts.strategy_5scr_context_route_v31 import (
    ContextRouteReceiptV31,
    MaterialContextV31,
    context_route_receipt_hash_v31,
)
from contracts.strategy_5scr_pressure_hypothesis_v31 import canonical_sha256_v31
from tests.test_strategy_5scr_pressure_hypothesis_v31 import DECISION, _build


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _material(**overrides) -> MaterialContextV31:
    values = {
        "d1_source_ids": (_digest("d1-a"),),
        "h4_source_ids": (_digest("h4-a"),),
        "d1_structure": "D1_BULLISH",
        "h4_structure": "H4_BULLISH",
        "price_location": "DISCOUNT_OF_RANGE",
        "liquidity_state": "UNTESTED",
        "primary_direction_domain": "BUY_ONLY",
        "allowed_directions": ("BUY",),
        "counter_pressure_policy_hash": _digest("counter-policy"),
        "counter_pressure_observation_allowed": True,
        "counter_pressure_thesis_status": "PROOF_REQUIRED",
        "allowed_routes": ("BREAK_RETEST", "PULLBACK_CONTINUATION"),
        "blocked_routes": ("RANGE_FADE",),
        "target_map_version": "tm.v1",
        "structural_invalidation_version": "si.v1",
        "pressure_contract_status": "OPEN",
        **overrides,
    }
    return MaterialContextV31(**values)


REGISTRY = with_hash(
    DirectionDomainRegistryV31,
    "registry_hash",
    registry_version="test-domain-registry.v1",
    entries=(
        DirectionDomainEntryV31(domain="BUY_ONLY", directions=("BUY",)),
        DirectionDomainEntryV31(domain="SELL_ONLY", directions=("SELL",)),
        DirectionDomainEntryV31(domain="BOTH_CONDITIONAL", directions=("BUY", "SELL")),
        DirectionDomainEntryV31(domain="UNRESOLVED", directions=()),
        DirectionDomainEntryV31(domain="EMPTY", directions=()),
    ),
)
POLICY = with_hash(
    LocationRoutePolicyV31,
    "policy_hash",
    policy_version="test-location-route.v1",
    route_registry_version="test-routes.v1",
    routes=(
        RouteRuleV31(
            route="PULLBACK_CONTINUATION",
            direction="BUY",
            permitted_location_alignments=("FAVORABLE", "NEUTRAL"),
            requires_authoritative_quote=True,
        ),
        RouteRuleV31(
            route="BREAK_RETEST",
            direction="SELL",
            permitted_location_alignments=("FAVORABLE",),
            requires_authoritative_quote=True,
        ),
    ),
)
CLOCK = with_hash(
    ContextClockPolicyV31,
    "policy_hash",
    clock_policy_version="test-context-clock.v1",
    ttl_seconds=3600,
    clock_source="INJECTED_DECISION_CLOCK",
)


def _hypothesis():
    record = _build().hypothesis
    assert record is not None and record.direction == "BUY"
    return record


def _epoch(
    material: Any = None,
    *,
    previous: Any = None,
    previous_terminated: bool = False,
    at: Any = DECISION,
    registry: Any = REGISTRY,
    clock: Any = CLOCK,
) -> Any:
    hypothesis = _hypothesis()
    return resolve_context_epoch_v31(
        strategy_lifecycle_id=hypothesis.strategy_lifecycle_id,
        canonical_symbol="EURUSD",
        material=material or _material(),
        source_closed_through=DECISION - timedelta(seconds=60),
        registry=registry,
        clock_policy=clock,
        previous=previous,
        previous_terminated=previous_terminated,
        decision_at=at,
    )


def _evaluate(
    epoch: Any,
    *,
    direction: Any = "BUY",
    hypothesis: Any = "auto",
    pressure: Any = None,
    route: str = "PULLBACK_CONTINUATION",
    location: Any = "FAVORABLE",
    quote: bool = True,
    registry: Any = REGISTRY,
    policy: Any = POLICY,
    at: Any = DECISION,
    invalidate: str | None = None,
) -> Any:
    return evaluate_context_route_v31(
        epoch=epoch,
        evaluated_direction=direction,
        hypothesis=_hypothesis() if hypothesis == "auto" else hypothesis,
        pressure_direction=pressure,
        requested_route=route,
        location_alignment=location,
        quote_authoritative=quote,
        registry=registry,
        policy=policy,
        decision_at=at,
        invalidating_material_event_hash=invalidate,
    )


def test_same_material_gives_same_epoch_and_price_refresh_reuses_it():
    first = _epoch()
    assert first.outcome == "CREATED" and first.epoch is not None and first.epoch.context_epoch_id.version == 5
    assert _epoch().epoch == first.epoch
    refreshed = _epoch(previous=first.epoch, at=DECISION + timedelta(seconds=30))  # only time/quote moved
    assert (refreshed.outcome, refreshed.reason_code) == ("REUSED", "MATERIAL_CONTEXT_UNCHANGED")
    assert refreshed.epoch == first.epoch
    epoch = first.epoch
    assert (epoch.authority, epoch.direction_authority, epoch.execution_authority) == ("CONTEXT_ONLY", False, False)


def test_material_change_creates_new_epoch_and_supersedes_the_old_one():
    first = _epoch().epoch
    changed = _epoch(_material(h4_source_ids=(_digest("h4-b"),)), previous=first, at=DECISION + timedelta(seconds=30))
    assert changed.outcome == "CREATED" and changed.epoch is not None and first is not None
    assert changed.epoch.context_epoch_id != first.context_epoch_id
    assert changed.termination is not None
    assert (changed.termination.terminal_state, changed.termination.reason_code) == (
        "SUPERSEDED",
        "MATERIAL_CONTEXT_CHANGED",
    )
    assert changed.termination.superseded_by == changed.epoch.context_epoch_id


def test_epoch_clock_is_immutable_and_expired_epoch_is_never_revived():
    first = _epoch().epoch
    assert first is not None and first.valid_until - first.valid_from == timedelta(seconds=3600)
    late = first.valid_until + timedelta(seconds=1)
    same = _epoch(previous=first, at=late)
    assert (same.outcome, same.reason_code) == ("NOT_CREATED", "EPOCH_EXPIRED_MATERIAL_UNCHANGED")
    fresh = _epoch(_material(h4_source_ids=(_digest("h4-c"),)), previous=first, at=late)
    assert fresh.outcome == "CREATED" and fresh.epoch is not None and fresh.termination is not None
    assert (fresh.termination.terminal_state, fresh.termination.superseded_by) == ("EXPIRED", None)
    assert fresh.epoch.valid_from == late and fresh.epoch.context_epoch_id != first.context_epoch_id
    assert _evaluate(first, at=late).reason_code == "CONTEXT_EPOCH_NOT_ACTIVE"


def test_same_epoch_buy_and_sell_have_different_evaluation_ids_and_null_hypothesis_is_legal():
    epoch = _epoch(_material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))).epoch
    buy = _evaluate(epoch, hypothesis=None).evaluation
    sell = _evaluate(epoch, direction="SELL", hypothesis=None, route="BREAK_RETEST").evaluation
    with_h = _evaluate(epoch).evaluation
    assert buy is not None and sell is not None and with_h is not None
    assert len({buy.evaluation_id, sell.evaluation_id, with_h.evaluation_id}) == 3
    assert buy.pressure_hypothesis_id is None and buy.outcome == "ALIGN"


def test_stale_quote_defers_without_receipt_and_leaves_epoch_unchanged():
    epoch = _epoch().epoch
    assert epoch is not None
    decision = _evaluate(epoch, quote=False)
    evaluation = decision.evaluation
    assert evaluation is not None
    assert (evaluation.outcome, evaluation.defer_reason, evaluation.selected_route) == ("DEFER", "PRICE_QUALITY", None)
    assert project_context_route_receipt_v31(epoch, evaluation) is None
    assert _epoch(previous=epoch).epoch == epoch
    intent = hypothesis_transition_for_evaluation_v31(evaluation)
    assert intent is not None and intent.to_state == "WAITING_PRICE_QUALITY"


def test_context_conflict_never_changes_hypothesis_direction():
    ledger = InMemoryPressureHypothesisLedgerV31()
    hypothesis = admit_hypothesis_v31(ledger, _build(), decision_at=DECISION).hypothesis
    assert hypothesis is not None
    epoch = _epoch(_material(primary_direction_domain="SELL_ONLY", allowed_directions=("SELL",))).epoch
    evaluation = _evaluate(epoch, hypothesis=hypothesis).evaluation
    assert evaluation is not None and (evaluation.outcome, evaluation.context_alignment) == ("CONFLICT", "CONFLICT")
    assert project_context_route_receipt_v31(epoch, evaluation) is None
    intent = hypothesis_transition_for_evaluation_v31(evaluation)
    assert intent is not None and intent.to_state == "CONTEXT_CONFLICT"
    ledger.append_transition(
        make_transition_v31(
            record=hypothesis,
            history=ledger.transitions(hypothesis.pressure_hypothesis_id),
            to_state=intent.to_state,
            context_alignment=intent.context_alignment,
            location_alignment=intent.location_alignment,
            classification=intent.classification,
            reason_code=evaluation.reason_code,
            material_event_id=str(evaluation.evaluation_id),
            material_event_hash=evaluation.resolution_evidence_hash,
            occurred_at=DECISION + timedelta(seconds=1),
        )
    )
    stored = ledger.get_record(hypothesis.pressure_hypothesis_id)
    assert (
        stored is not None and stored == hypothesis and stored.direction == "BUY"
    )  # CONTEXT_DIRECTION_AUTHORITY = FALSE


def test_align_emits_a_valid_stable_receipt_in_the_existing_contract():
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch).evaluation
    assert epoch is not None and evaluation is not None and evaluation.outcome == "ALIGN"
    receipt = project_context_route_receipt_v31(epoch, evaluation)
    assert isinstance(receipt, ContextRouteReceiptV31)
    again = project_context_route_receipt_v31(epoch, _evaluate(epoch).evaluation)
    assert again is not None and context_route_receipt_hash_v31(receipt) == context_route_receipt_hash_v31(again)
    assert (receipt.direction, receipt.selected_route, receipt.valid_until) == (
        "BUY",
        "PULLBACK_CONTINUATION",
        epoch.valid_until,
    )
    assert (evaluation.direction_authority, evaluation.final_signal_allowed, evaluation.execution_command_allowed) == (
        False,
        False,
        False,
    )
    intent = hypothesis_transition_for_evaluation_v31(evaluation)
    assert intent is not None and intent.to_state == "CONTEXT_ALIGNED"


@pytest.mark.parametrize("route", ["RANGE_FADE", "UNKNOWN_ROUTE"])
def test_blocked_or_unknown_route_produces_no_positive_receipt(route):
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch, route=route).evaluation
    assert evaluation is not None and evaluation.outcome == "BLOCK_ROUTE"
    assert project_context_route_receipt_v31(epoch, evaluation) is None
    assert hypothesis_transition_for_evaluation_v31(evaluation) is None


def test_location_not_ready_defers_to_waiting_valid_location():
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch, location="UNFAVORABLE").evaluation
    assert evaluation is not None and (evaluation.outcome, evaluation.defer_reason) == ("DEFER", "LOCATION_NOT_READY")
    intent = hypothesis_transition_for_evaluation_v31(evaluation)
    assert intent is not None and intent.to_state == "WAITING_VALID_LOCATION"


def test_counter_pressure_route_requires_proof_and_prohibited_blocks():
    epoch = _epoch(_material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))).epoch
    counter = _evaluate(epoch, direction="SELL", hypothesis=None, pressure="BUY", route="BREAK_RETEST").evaluation
    assert counter is not None
    assert (counter.outcome, counter.counter_pressure_classification) == (
        "AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE",
        "PROOF_REQUIRED",
    )
    assert project_context_route_receipt_v31(epoch, counter) is not None
    prohibited_epoch = _epoch(
        _material(
            primary_direction_domain="BOTH_CONDITIONAL",
            allowed_directions=("BUY", "SELL"),
            counter_pressure_thesis_status="PROHIBITED",
        )
    ).epoch
    blocked = _evaluate(prohibited_epoch, direction="SELL", hypothesis=None, pressure="BUY", route="BREAK_RETEST")
    assert blocked.evaluation is not None and blocked.evaluation.outcome == "BLOCK_ROUTE"


def test_hypothesis_can_only_be_evaluated_in_its_own_direction_and_invalidate_needs_material_evidence():
    epoch = _epoch(_material(primary_direction_domain="BOTH_CONDITIONAL", allowed_directions=("BUY", "SELL"))).epoch
    wrong = _evaluate(epoch, direction="SELL", route="BREAK_RETEST")
    assert (wrong.outcome, wrong.reason_code) == ("NOT_EVALUATED", "HYPOTHESIS_DIRECTION_IS_NOT_EVALUABLE_HERE")
    invalid = _evaluate(epoch, invalidate=canonical_sha256_v31(["structural-invalidation"])).evaluation
    assert invalid is not None and invalid.outcome == "INVALIDATE" and invalid.selected_route is None
    intent = hypothesis_transition_for_evaluation_v31(invalid)
    assert intent is not None and intent.to_state == "INVALIDATED"


def test_registry_missing_or_mismatched_fails_closed():
    assert _epoch(registry=None).reason_code == "REGISTRY_MISSING"
    assert _epoch(clock=None).reason_code == "CONTEXT_CLOCK_POLICY_MISSING"
    epoch = _epoch().epoch
    assert _evaluate(epoch, policy=None).reason_code == "REGISTRY_MISSING"
    other = with_hash(
        DirectionDomainRegistryV31, "registry_hash", registry_version="other.v1", entries=REGISTRY.entries
    )
    assert _evaluate(epoch, registry=other).reason_code == "REGISTRY_VERSION_MISMATCH"
    with pytest.raises(ValueError, match="DIRECTION_DOMAIN_REGISTRY_HASH_MISMATCH"):
        DirectionDomainRegistryV31.model_validate({**REGISTRY.model_dump(), "registry_version": "tampered.v1"})
    with pytest.raises(ValueError, match="LOCATION_ROUTE_POLICY_HASH_MISMATCH"):
        LocationRoutePolicyV31.model_validate({**POLICY.model_dump(), "policy_version": "tampered.v1"})


def test_records_reject_forged_identity_and_route_without_permitting_outcome():
    epoch = _epoch().epoch
    assert epoch is not None
    with pytest.raises(ValueError, match="CONTEXT_EPOCH_ID_NOT_DERIVED"):
        ContextEpochV31.model_validate({**epoch.model_dump(), "context_epoch_id": _hypothesis().pressure_hypothesis_id})
    evaluation = _evaluate(epoch, quote=False).evaluation
    assert evaluation is not None
    with pytest.raises(ValueError, match="selected_route is set exactly"):
        ContextRouteEvaluationV31.model_validate({**evaluation.model_dump(), "selected_route": "PULLBACK_CONTINUATION"})
    forbidden = {"spread", "volume", "lot", "risk", "stop_loss", "take_profit", "final_direction"}
    assert not forbidden & set(ContextEpochV31.model_fields)
    assert not forbidden & set(ContextRouteEvaluationV31.model_fields)
