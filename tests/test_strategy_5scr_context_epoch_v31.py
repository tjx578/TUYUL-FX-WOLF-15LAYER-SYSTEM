"""Gap #9 acceptance: ContextEpochV31 + ContextRouteEvaluationV31 + positive receipt projection (Option A).

Requalified on #504: every fixture runs on a real #492 -> S1B (#501-#503) lineage, so the lifecycle under test is
the MarketEpisode-rooted one and both admission classes are exercised.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid5

import pytest

from analysis.strategy_5scr_context_epoch_v31 import (
    context_progression_allowed_v31,
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
from contracts.strategy_5scr_analysis_lifecycle_v31 import AnalysisLifecycleV31
from contracts.strategy_5scr_context_epoch_v31 import (
    V31_CONTEXT_EPOCH_NAMESPACE,
    V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE,
    ContextClockPolicyV31,
    ContextEpochV31,
    ContextRouteEvaluationV31,
    DirectionDomainEntryV31,
    DirectionDomainRegistryV31,
    LocationRoutePolicyV31,
    RouteRuleV31,
    context_epoch_id_v31,
    context_route_evaluation_id_v31,
    with_hash,
)
from contracts.strategy_5scr_context_route_v31 import (
    ContextRouteReceiptV31,
    MaterialContextV31,
    context_route_receipt_hash_v31,
)
from contracts.strategy_5scr_identity_v31 import canonical_sha256_v31
from contracts.strategy_5scr_market_episode_v31 import strategy_lifecycle_id_from_episode_v31
from tests.test_strategy_5scr_per_symbol_admission import _safety
from tests.test_strategy_5scr_pressure_hypothesis_v31 import (
    DECISION,
    _advisory_s1b,
    _build,
    _canonical_s1b,
    _episode,
    _hypothesis_from,
)


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


def _s1b():
    """The canonical S1B lineage that #494's default hypothesis is built on: same episode, same lifecycle."""

    s1b = _canonical_s1b()
    assert s1b is not None
    return s1b


def _hypothesis():
    record = _build().hypothesis
    assert record is not None and record.direction == "BUY"
    return record


def _relifecycle(lifecycle: AnalysisLifecycleV31, **overrides: Any) -> AnalysisLifecycleV31:
    """Rebuild a lifecycle view with a different derived state, keeping the material hash honest."""

    body = {**lifecycle.model_dump(mode="json"), **overrides}
    body["material_state_hash"] = canonical_sha256_v31({k: v for k, v in body.items() if k != "material_state_hash"})
    return AnalysisLifecycleV31.model_validate(body)


def _foreign_lifecycle(lifecycle: AnalysisLifecycleV31) -> AnalysisLifecycleV31:
    """A lifecycle rooted in a DIFFERENT market episode, derived exactly as section 8.1 requires."""

    episode = uuid5(lifecycle.market_episode_id, "a-different-market-episode")
    return _relifecycle(
        lifecycle,
        market_episode_id=str(episode),
        strategy_lifecycle_id=str(strategy_lifecycle_id_from_episode_v31(episode)),
    )


def _epoch(
    material: Any = None,
    *,
    previous: Any = None,
    previous_terminated: bool = False,
    at: Any = DECISION,
    registry: Any = REGISTRY,
    clock: Any = CLOCK,
    lifecycle: Any = None,
) -> Any:
    return resolve_context_epoch_v31(
        lifecycle=_s1b().lifecycle if lifecycle is None else lifecycle,
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
    lifecycle: Any = None,
) -> Any:
    return evaluate_context_route_v31(
        lifecycle=_s1b().lifecycle if lifecycle is None else lifecycle,
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
    assert evaluation.outcome != "BLOCK_ROUTE" and evaluation.context_alignment == "ALIGNED"
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


# --- requalification acceptance on the #504 lineage --------------------------------------------------------------


def test_the_epoch_lifecycle_comes_from_the_s1b_lineage_and_is_episode_rooted():
    s1b = _s1b()
    epoch = _epoch().epoch
    assert epoch is not None
    assert epoch.strategy_lifecycle_id == s1b.lifecycle.strategy_lifecycle_id == s1b.receipt.strategy_lifecycle_id
    assert epoch.market_episode_id == s1b.episode.market_episode_id
    assert epoch.strategy_lifecycle_id == strategy_lifecycle_id_from_episode_v31(epoch.market_episode_id)
    assert epoch.canonical_symbol == s1b.lifecycle.symbol
    # There is no way to hand a free lifecycle (or symbol) to either producer any more.
    for producer in (resolve_context_epoch_v31, evaluate_context_route_v31):
        names = set(inspect.signature(producer).parameters)
        assert "lifecycle" in names and not names & {"strategy_lifecycle_id", "canonical_symbol"}
    evaluation = _evaluate(epoch).evaluation
    assert evaluation is not None and evaluation.market_episode_id == epoch.market_episode_id


def test_a_mature_advisory_hypothesis_is_evaluable_and_carries_no_admission_class():
    advisory = _advisory_s1b()
    hypothesis = _hypothesis_from(advisory).hypothesis
    assert hypothesis is not None and hypothesis.analysis_admission_class == "MATURE_ADVISORY"
    epoch = _epoch(lifecycle=advisory.lifecycle).epoch
    assert epoch is not None
    decision = _evaluate(epoch, hypothesis=hypothesis, lifecycle=advisory.lifecycle)
    evaluation = decision.evaluation
    assert evaluation is not None and evaluation.outcome == "ALIGN"
    assert project_context_route_receipt_v31(epoch, evaluation) is not None  # analysis handoff, never a risk handoff
    assert (evaluation.direction_authority, evaluation.final_signal_allowed, evaluation.execution_command_allowed) == (
        False,
        False,
        False,
    )
    # The class is neither stored nor identity-bearing, so it can never silently upgrade a route.
    blob = str(epoch.model_dump(mode="json")) + str(evaluation.model_dump(mode="json"))
    assert "MATURE_ADVISORY" not in blob and "CANONICAL_RAW" not in blob
    assert not {"analysis_admission_class", "strategy_analysis_admission_id", "admission_receipt_hash"} & (
        set(ContextEpochV31.model_fields) | set(ContextRouteEvaluationV31.model_fields)
    )


def test_authority_upgrade_keeps_the_same_epoch_and_evaluation_and_only_re_evaluates_progression():
    reduction = _episode()
    advisory = _advisory_s1b(reduction)
    hypothesis = _hypothesis_from(advisory).hypothesis
    assert hypothesis is not None
    epoch_before = _epoch(lifecycle=advisory.lifecycle).epoch
    evaluation_before = _evaluate(epoch_before, hypothesis=hypothesis, lifecycle=advisory.lifecycle).evaluation
    assert epoch_before is not None and evaluation_before is not None

    canonical = _canonical_s1b(reduction=reduction, ledger=advisory.ledger, decided_at=DECISION)
    assert canonical is not None
    assert canonical.lifecycle.strategy_lifecycle_id == advisory.lifecycle.strategy_lifecycle_id  # SAME lifecycle L
    assert canonical.lifecycle.highest_analysis_authority == "CANONICAL_RAW"
    upgraded_hypothesis = _hypothesis_from(canonical).hypothesis
    assert upgraded_hypothesis is not None
    assert upgraded_hypothesis.pressure_hypothesis_id == hypothesis.pressure_hypothesis_id  # same material evidence

    # Same material context after the upgrade: the epoch is REUSED, not re-created and not superseded.
    reused = _epoch(previous=epoch_before, lifecycle=canonical.lifecycle)
    assert (reused.outcome, reused.reason_code) == ("REUSED", "MATERIAL_CONTEXT_UNCHANGED")
    assert reused.epoch == epoch_before and reused.termination is None
    evaluation_after = _evaluate(epoch_before, hypothesis=upgraded_hypothesis, lifecycle=canonical.lifecycle).evaluation
    assert evaluation_after is not None and evaluation_after == evaluation_before  # byte-identical record

    # Only genuinely different material context creates a new epoch.
    moved = _epoch(
        _material(h4_structure="H4_RANGE"), previous=epoch_before, lifecycle=canonical.lifecycle, at=DECISION
    )
    assert moved.outcome == "CREATED" and moved.epoch is not None
    assert moved.epoch.context_epoch_id != epoch_before.context_epoch_id
    assert moved.epoch.strategy_lifecycle_id == epoch_before.strategy_lifecycle_id


def test_context_modules_never_read_pair_admission_directly():
    forbidden_modules = ("pair_admission", "admission_identity")
    for path in (
        "contracts/strategy_5scr_context_epoch_v31.py",
        "analysis/strategy_5scr_context_epoch_v31.py",
    ):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not any(token in module for token in forbidden_modules), f"{path} imports {module}"
                names = {alias.name for alias in node.names}
                assert not {n for n in names if "PairAdmission" in n or "pair_admission" in n}, f"{path}: {names}"
                if module.endswith("strategy_5scr_per_symbol_admission"):
                    # Only the global safety overlay may come from the #492 module; nothing pair-local.
                    assert names == {"GlobalSafetyStateV1"}, f"{path}: {names}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(token in alias.name for token in forbidden_modules)


def test_a_global_veto_is_an_overlay_and_never_touches_the_epoch_or_the_evaluation():
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch).evaluation
    assert epoch is not None and evaluation is not None and evaluation.outcome == "ALIGN"
    allowed, vetoes = context_progression_allowed_v31(evaluation, _safety())
    assert (allowed, vetoes) == (True, ())
    stopped, reasons = context_progression_allowed_v31(evaluation, _safety(kill_switch_active=True))
    assert stopped is False and reasons == ("KILL_SWITCH_ACTIVE",)
    # Re-resolving and re-evaluating under the veto yields the very same records: history is untouched.
    assert _epoch(previous=epoch).epoch == epoch
    assert _evaluate(epoch).evaluation == evaluation
    assert project_context_route_receipt_v31(epoch, evaluation) is not None


def test_epoch_and_lifecycle_must_bind_exactly_and_a_terminal_lifecycle_stops_analysis():
    s1b = _s1b()
    epoch = _epoch().epoch
    assert epoch is not None
    other = _foreign_lifecycle(s1b.lifecycle)
    assert other.strategy_lifecycle_id != s1b.lifecycle.strategy_lifecycle_id
    assert _evaluate(epoch, lifecycle=other).reason_code == "EPOCH_LIFECYCLE_MISMATCH"
    foreign_epoch = _epoch(lifecycle=other).epoch
    assert foreign_epoch is not None
    assert _epoch(previous=foreign_epoch).reason_code == "PREVIOUS_EPOCH_LIFECYCLE_MISMATCH"
    terminal = _relifecycle(s1b.lifecycle, state="INVALIDATED")
    assert _epoch(lifecycle=terminal).reason_code == "LIFECYCLE_TERMINAL"
    assert _evaluate(epoch, lifecycle=terminal).reason_code == "LIFECYCLE_TERMINAL"


def test_records_reject_an_episode_binding_that_is_not_the_lifecycle_root():
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch).evaluation
    assert epoch is not None and evaluation is not None
    stranger = _foreign_lifecycle(_s1b().lifecycle).market_episode_id
    with pytest.raises(ValueError, match="CONTEXT_EPOCH_LIFECYCLE_NOT_EPISODE_ROOTED"):
        ContextEpochV31.model_validate({**epoch.model_dump(), "market_episode_id": stranger})
    with pytest.raises(ValueError, match="CONTEXT_EVALUATION_LIFECYCLE_NOT_EPISODE_ROOTED"):
        ContextRouteEvaluationV31.model_validate({**evaluation.model_dump(), "market_episode_id": stranger})
    assert (epoch.rule_version, evaluation.rule_version) == (
        "5scr.context-epoch.v31.v2",
        "5scr.context-route-evaluation.v31.v2",
    )


def test_context_identity_formulas_are_pinned_and_admission_free():
    """Both tuples are spelled out here. A silently widened identity (an admission class, a clock, a policy
    version) changes every id uniformly and would otherwise pass every behavioural test in this suite."""

    s1b = _s1b()
    epoch = _epoch().epoch
    evaluation = _evaluate(epoch).evaluation
    assert epoch is not None and evaluation is not None

    epoch_name = json.dumps(
        [
            "v31.native-identity.v1",
            str(s1b.lifecycle.strategy_lifecycle_id),
            epoch.material_context_hash,
        ],
        separators=(",", ":"),
    )
    assert epoch.context_epoch_id == uuid5(V31_CONTEXT_EPOCH_NAMESPACE, epoch_name)

    evaluation_name = json.dumps(
        [
            "v31.native-identity.v1",
            str(epoch.context_epoch_id),
            "BUY",
            str(evaluation.pressure_hypothesis_id),
        ],
        separators=(",", ":"),
    )
    assert evaluation.evaluation_id == uuid5(V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE, evaluation_name)
    assert context_route_evaluation_id_v31(
        context_epoch_id=epoch.context_epoch_id, evaluated_direction="BUY", pressure_hypothesis_id=None
    ) == uuid5(
        V31_CONTEXT_ROUTE_EVALUATION_NAMESPACE,
        json.dumps(["v31.native-identity.v1", str(epoch.context_epoch_id), "BUY", None], separators=(",", ":")),
    )
    assert (
        context_epoch_id_v31(
            strategy_lifecycle_id=s1b.lifecycle.strategy_lifecycle_id, material_context_hash=epoch.material_context_hash
        )
        == epoch.context_epoch_id
    )
