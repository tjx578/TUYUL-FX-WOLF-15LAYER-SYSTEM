"""ExecutionBoxV31 acceptance — A3 (RATIFIED 2026-09-22), owner implementation GO 2026-09-22.

Every positive case is built from the REAL native lineage (S1B → lifecycle → hypothesis → epoch → route evaluation
→ thesis opened and confirmed by a real structural proof), plus a real PressureRangeV31 and a real canonical
StructuralTarget selection. Route/pattern/class registries for BREAK_RETEST and BREAKOUT_ACCEPTANCE are fixture DATA
(R3), not authority.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Literal, get_args

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_context_epoch_v31 import evaluate_context_route_v31
from analysis.strategy_5scr_directional_thesis_v31 import InMemoryDirectionalThesisLedgerV31, thesis_status_v31
from analysis.strategy_5scr_execution_box_v31 import (
    boundary_level_v31,
    build_execution_box_v31,
    canonical_price_v31,
    post_freeze_invalidation_v31,
    requires_box_reevaluation_for_range_change_v31,
    requires_box_reevaluation_for_target_fact_v31,
    retire_execution_box_v31,
)
from analysis.strategy_5scr_structural_proof_v31 import build_structural_proof_v31
from analysis.strategy_5scr_structural_target_canonical_v31 import select_structural_target_v31
from contracts.strategy_5scr_context_epoch_v31 import LocationRoutePolicyV31, RouteRuleV31, with_hash
from contracts.strategy_5scr_directional_thesis_v31 import RouteThesisClassV31, ThesisClassRegistryV31
from contracts.strategy_5scr_execution_box_v31 import (
    BOX_POLICIES_V31,
    CANONICAL_ROUTES_V31,
    ExecutionBoxMaterialV31,
    ExecutionBoxState,
    ExecutionBoxTransitionV31,
    ExecutionBoxVersionV31,
    canonical_price_text_v31,
    execution_box_id_v31,
    material_box_hash_v31,
)
from contracts.strategy_5scr_structural_proof_v31 import StructuralPatternRegistryV31
from contracts.strategy_5scr_structural_target_canonical_v31 import (
    DecisionPriceV31,
    StructuralTargetSelectionRequestV31,
)
from tests import test_strategy_5scr_directional_thesis_v31 as thesis_fx
from tests.test_strategy_5scr_context_epoch_v31 import REGISTRY as DOMAIN_REGISTRY
from tests.test_strategy_5scr_context_epoch_v31 import _material
from tests.test_strategy_5scr_pressure_hypothesis_v31 import START
from tests.test_strategy_5scr_pressure_range_v31 import _evidence, _materialize, _periods
from tests.test_strategy_5scr_structural_proof_v31 import _pattern
from tests.test_strategy_5scr_structural_target_canonical_v31 import _candidate, _h

ROUTES = ("BREAKOUT_ACCEPTANCE", "BREAK_RETEST")  # sorted: context identities must be sorted-unique
ROUTE_POLICY = with_hash(
    LocationRoutePolicyV31,
    "policy_hash",
    policy_version="test-box-routes.v1",
    route_registry_version="test-box-routes.v1",
    routes=tuple(
        RouteRuleV31(
            route=r, direction=d, permitted_location_alignments=("FAVORABLE",), requires_authoritative_quote=True
        )
        for r in ROUTES
        for d in ("BUY", "SELL")
    ),
)
CLASSES = with_hash(
    ThesisClassRegistryV31,
    "registry_hash",
    registry_version="test-box-classes.v1",
    mappings=tuple(
        RouteThesisClassV31(route=r, thesis_class="CONTINUATION") for r in (*ROUTES, "PULLBACK_CONTINUATION")
    ),
)
PATTERNS = with_hash(
    StructuralPatternRegistryV31,
    "registry_hash",
    registry_version="test-box-patterns.v1",
    patterns=tuple(_pattern(r) for r in (*ROUTES, "PULLBACK_CONTINUATION")),
)
BOX_DECISION = START + timedelta(minutes=15)
Direction = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class Lineage:
    thesis: Any
    status: Any
    proof: Any
    evaluation: Any
    lifecycle: Any


def _witnesses(direction: str, kind: str):
    h1, m15 = thesis_fx._witnesses("EURUSD", direction)
    if kind == "RETEST":
        return h1, m15
    last = m15[-1]
    # An acceptance candle never trades back to L (BUY L = 1.1010, SELL L = 1.1000).
    changed = {"open": 1.1013, "low": 1.1012} if direction == "BUY" else {"open": 1.0994, "high": 1.0995}
    return h1, (*m15[:2], thesis_fx._rehash_candle({**last.model_dump(), **changed}))


@cache
def _lineage(direction: Direction = "BUY", route: str = "BREAK_RETEST", kind: str = "RETEST") -> Lineage:
    material = (
        _material(allowed_routes=(*ROUTES, "PULLBACK_CONTINUATION"), blocked_routes=())
        if direction == "BUY"
        else _material(
            primary_direction_domain="SELL_ONLY",
            allowed_directions=("SELL",),
            allowed_routes=(*ROUTES, "PULLBACK_CONTINUATION"),
            blocked_routes=(),
            d1_structure="D1_BEARISH",
            h4_structure="H4_BEARISH",
            price_location="PREMIUM_OF_RANGE",
        )
    )
    chain = thesis_fx._chain(direction=direction, material=material)
    policy = ROUTE_POLICY
    if route == "PULLBACK_CONTINUATION":
        policy = with_hash(
            LocationRoutePolicyV31,
            "policy_hash",
            policy_version="test-box-routes-pullback.v1",
            route_registry_version="test-box-routes.v1",
            routes=(
                RouteRuleV31(
                    route=route,
                    direction=direction,
                    permitted_location_alignments=("FAVORABLE",),
                    requires_authoritative_quote=True,
                ),
            ),
        )
    decision = evaluate_context_route_v31(
        lifecycle=chain.lifecycle,
        epoch=chain.epoch,
        evaluated_direction=direction,
        hypothesis=chain.hypothesis,
        pressure_direction=None,
        requested_route=route,
        location_alignment="FAVORABLE",
        quote_authoritative=True,
        registry=DOMAIN_REGISTRY,
        policy=policy,
        decision_at=thesis_fx.DECISION,
    )
    assert decision.evaluation is not None, decision.reason_code
    chain = thesis_fx.Chain(
        chain.hypotheses, chain.hypothesis, chain.epoch, decision.evaluation, chain.lifecycle, chain.s1b
    )
    store = InMemoryDirectionalThesisLedgerV31()
    opened = thesis_fx._open(store, chain, class_registry=CLASSES)
    assert opened.thesis is not None, opened.reason_code
    h1, m15 = _witnesses(direction, kind)
    built = build_structural_proof_v31(
        lifecycle=chain.lifecycle,
        epoch=chain.epoch,
        evaluation=decision.evaluation,
        proof_direction=direction,
        h1_witnesses=h1,
        m15_witnesses=m15,
        level_version="fixture-level-v1",
        pattern_id=thesis_fx.PATTERN,
        registry=PATTERNS,
        decision_at=thesis_fx.BIND_AT,
    )
    assert built.proof is not None and built.proof.m15_completion_kind == kind, built.reason_code
    assert thesis_fx._confirm(store, chain, opened.thesis, built.proof).outcome == "CONFIRMED"
    return Lineage(
        thesis=store.get_record(opened.thesis.strategy_thesis_id),
        status=thesis_status_v31(store, opened.thesis.strategy_thesis_id),
        proof=built.proof,
        evaluation=decision.evaluation,
        lifecycle=chain.lifecycle,
    )


def _range(lineage: Lineage, *, complete: bool = True):
    evidence = (_evidence(0, low=1.0990, high=1.1030), _evidence(1, low=1.1000, high=1.1010))
    decision = _materialize(
        lifecycle=lineage.lifecycle, evidence=evidence if complete else evidence[:1], expected=_periods(2)
    )
    assert decision.range is not None, decision.reason_code
    return decision.range


def _selection(lineage: Lineage, *, anchor: str = "t", price: str | None = None, fresh: bool = True):
    direction = lineage.thesis.direction
    candidate = _candidate(
        anchor,
        price=price or ("1.1100" if direction == "BUY" else "1.0900"),
        direction=direction,
        freshness="FRESH" if fresh else "NOT_FRESH",
        formed_at=START,
        valid_until=START + timedelta(hours=1),
        observed_through=START + timedelta(minutes=10),
    )
    decision_time = START + timedelta(minutes=12)
    return select_structural_target_v31(
        StructuralTargetSelectionRequestV31(
            canonical_symbol="EURUSD",
            strategy_thesis_id=lineage.thesis.strategy_thesis_id,
            thesis_direction=direction,
            decision_time=decision_time,
            decision_price=DecisionPriceV31(
                canonical_symbol="EURUSD",
                origin="STRATEGY_CLOSED_PRICE_AUTHORITY",
                price=Decimal("1.1016") if direction == "BUY" else Decimal("1.0988"),
                observed_at=decision_time - timedelta(minutes=1),
                evidence_hash=_h(f"box-decision-price:{direction}"),
            ),
            candidates=(candidate,),
            pressure_range=None,
        )
    )


def _build(lineage: Lineage, **overrides: Any):
    values: dict[str, Any] = {
        "thesis": lineage.thesis,
        "thesis_status": lineage.status,
        "proof": lineage.proof,
        "route_evaluation": lineage.evaluation,
        "pressure_range": _range(lineage),
        "target_selection": _selection(lineage),
        "decision_time": BOX_DECISION,
        **overrides,
    }
    return build_execution_box_v31(**values)


def _built(direction: Direction = "BUY", route: str = "BREAK_RETEST", kind: str = "RETEST"):
    decision = _build(_lineage(direction, route, kind))
    assert decision.outcome == "BOX_BUILT_AND_FROZEN", decision.reason_code
    return decision


def _with_material(version: ExecutionBoxVersionV31, **material: Any) -> ExecutionBoxVersionV31:
    """A predecessor of the same logical box whose projection differed (e.g. an earlier derivation)."""

    changed = ExecutionBoxMaterialV31.model_validate({**version.material.model_dump(), **material})
    return ExecutionBoxVersionV31.model_validate(
        {**version.model_dump(), "material": changed, "material_box_hash": material_box_hash_v31(changed)}
    )


# --- identity -------------------------------------------------------------------------------------------------


def test_identity_is_deterministic_and_pinned():
    thesis = _lineage().thesis
    kwargs = {
        "strategy_thesis_id": thesis.strategy_thesis_id,
        "route": "BREAK_RETEST",
        "box_policy_id": "5scr.box-policy.break-retest",
        "box_policy_version": "v1",
    }
    assert execution_box_id_v31(**kwargs) == execution_box_id_v31(**kwargs)
    version = _built().version
    assert version is not None and version.execution_box_id == execution_box_id_v31(**kwargs)
    assert version.box_version == 1 and version.previous_box_version is None


def test_identity_ignores_deployment_request_lineage_and_clocks():
    first = _built().version
    lineage = _lineage()
    other = _build(
        lineage,
        target_selection=_selection(lineage, anchor="another-target", price="1.1200"),
        decision_time=BOX_DECISION + timedelta(minutes=30),
    ).version
    assert first is not None and other is not None
    assert first.execution_box_id == other.execution_box_id
    assert first.material_box_hash == other.material_box_hash  # lineage-only change, same projection
    assert first.lineage.target_id != other.lineage.target_id


def test_a_route_change_or_a_policy_change_is_a_new_logical_box():
    thesis_id = _lineage().thesis.strategy_thesis_id
    base = execution_box_id_v31(
        strategy_thesis_id=thesis_id,
        route="BREAK_RETEST",
        box_policy_id="5scr.box-policy.break-retest",
        box_policy_version="v1",
    )
    other_route = execution_box_id_v31(
        strategy_thesis_id=thesis_id,
        route="BREAKOUT_ACCEPTANCE",
        box_policy_id="5scr.box-policy.breakout-acceptance",
        box_policy_version="v1",
    )
    other_policy = execution_box_id_v31(
        strategy_thesis_id=thesis_id,
        route="BREAK_RETEST",
        box_policy_id="5scr.box-policy.break-retest",
        box_policy_version="v2",
    )
    assert len({base, other_route, other_policy}) == 3


def test_versions_start_at_one_step_by_exactly_one_and_never_skip():
    version = _built().version
    assert version is not None
    body = version.model_dump()
    with pytest.raises(ValidationError, match="FIRST_BOX_VERSION_HAS_NO_PREDECESSOR"):
        ExecutionBoxVersionV31.model_validate({**body, "previous_box_version": 0})
    for skipped in (3, 4):
        with pytest.raises(ValidationError, match="BY_EXACTLY_ONE"):
            ExecutionBoxVersionV31.model_validate(
                {**body, "box_version": skipped, "previous_box_version": 1, "previous_material_box_hash": _h("p")}
            )
    with pytest.raises(ValidationError, match="EXECUTION_BOX_ID_NOT_DERIVED"):
        ExecutionBoxVersionV31.model_validate({**body, "strategy_thesis_id": _other_uuid()})


def _other_uuid():
    from uuid import UUID

    return UUID("00000000-0000-4000-8000-000000000001")


# --- prerequisites: no canonical BUILDING box ----------------------------------------------------------------


def test_pressure_range_without_structural_authority_builds_no_box():
    lineage = _lineage()
    partial = _range(lineage, complete=False)
    assert partial.structural_authority is False
    decision = _build(lineage, pressure_range=partial)
    assert (decision.outcome, decision.reason_code) == (
        "NO_CANONICAL_BOX",
        "PRESSURE_RANGE_WITHOUT_STRUCTURAL_AUTHORITY",
    )
    assert decision.version is None and decision.transitions == ()


def test_a_target_that_is_not_selected_builds_no_box():
    lineage = _lineage()
    unselected = _selection(lineage, fresh=False)
    assert unselected.status == "NO_ELIGIBLE_TARGET"
    assert _build(lineage, target_selection=unselected).reason_code == "STRUCTURAL_TARGET_NOT_SELECTED"


def test_a_not_yet_defined_route_builds_no_box_and_an_unknown_route_is_rejected():
    pullback = _lineage("BUY", "PULLBACK_CONTINUATION")
    assert _build(pullback).reason_code == "ROUTE_NOT_YET_DEFINED_NO_CANONICAL_BOX"
    lineage = _lineage()
    unknown = lineage.thesis.model_construct(**{**lineage.thesis.__dict__, "selected_route": "GENERIC_INTERVAL"})
    assert _build(lineage, thesis=unknown).reason_code == "ROUTE_UNKNOWN_REJECTED"
    assert set(CANONICAL_ROUTES_V31) - set(BOX_POLICIES_V31) == {
        "PULLBACK_CONTINUATION",
        "FAILED_BREAKOUT_SELL",
        "FAILED_BREAKDOWN_BUY",
        "RANGE_FADE",
    }


def test_failed_reclaim_is_unmapped_and_builds_no_box():
    lineage = _lineage()
    reclaim = lineage.proof.model_construct(**{**lineage.proof.__dict__, "m15_completion_kind": "FAILED_RECLAIM"})
    assert _build(lineage, proof=reclaim).reason_code == "FAILED_RECLAIM_UNMAPPED_NO_CANONICAL_BOX"


def test_a_proof_not_bound_to_the_thesis_or_a_foreign_lineage_builds_no_box():
    buy, sell = _lineage("BUY"), _lineage("SELL")
    assert _build(buy, proof=sell.proof).reason_code == "PROOF_NOT_BOUND_TO_THESIS"
    assert _build(buy, route_evaluation=sell.evaluation).reason_code == "UPSTREAM_LINEAGE_MISMATCH"


def test_a_completion_kind_outside_the_route_policy_builds_no_box():
    # A RETEST proof on the BREAKOUT_ACCEPTANCE route is a legal proof but not the policy's proof form.
    assert _build(_lineage("BUY", "BREAKOUT_ACCEPTANCE", "RETEST")).reason_code == (
        "PROOF_FORM_NOT_ELIGIBLE_FOR_ROUTE_POLICY"
    )


def test_future_evidence_builds_no_box():
    lineage = _lineage()
    too_early = thesis_fx.COMPLETION - timedelta(seconds=1)
    assert _build(lineage, decision_time=too_early).reason_code == "FUTURE_EVIDENCE_REJECTED"


# --- geometry ------------------------------------------------------------------------------------------------


def test_break_retest_geometry_buy_and_sell():
    buy = _built("BUY").version
    sell = _built("SELL").version
    assert buy is not None and sell is not None
    # BUY: L = reference high 1.1010, C.low = 1.1008 → [C.low, L]
    assert (buy.material.box_low, buy.material.box_high) == (Decimal("1.1008"), Decimal("1.101"))
    # SELL: L = reference low 1.1000, C.high = 1.1002 → [L, C.high]
    assert (sell.material.box_low, sell.material.box_high) == (Decimal("1.1"), Decimal("1.1002"))
    assert buy.material.freeze_evidence_id == _lineage("BUY").proof.m15_completion_candle_id


def test_breakout_acceptance_geometry_buy_and_sell():
    buy = _built("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE").version
    sell = _built("SELL", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE").version
    assert buy is not None and sell is not None
    assert (buy.material.box_low, buy.material.box_high) == (Decimal("1.101"), Decimal("1.1012"))  # [L, C.low]
    assert (sell.material.box_low, sell.material.box_high) == (Decimal("1.0995"), Decimal("1.1"))  # [C.high, L]


def test_an_acceptance_side_failure_builds_no_box_and_never_the_full_candle():
    lineage = _lineage("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE")
    candles = list(lineage.proof.m15_source_candles)
    touching = candles[-1].model_construct(**{**candles[-1].__dict__, "low": 1.1010})  # C.low == L: not strictly above
    proof = lineage.proof.model_construct(**{**lineage.proof.__dict__, "m15_source_candles": (*candles[:2], touching)})
    decision = _build(lineage, proof=proof)
    assert (decision.outcome, decision.reason_code) == ("NO_CANONICAL_BOX", "ACCEPTANCE_SIDE_GUARD_FAILED")


def test_same_close_building_then_frozen_in_deterministic_order():
    decision = _built()
    building, frozen = decision.transitions
    assert (building.from_state, building.to_state, frozen.from_state, frozen.to_state) == (
        None,
        "BUILDING",
        "BUILDING",
        "FROZEN",
    )
    assert building.authority_time == frozen.authority_time == thesis_fx.COMPLETION
    assert (building.ordinal, frozen.ordinal) == (0, 1)
    assert frozen.reason_code == "M15_RETEST_COMPLETION_CLOSED"
    assert frozen.evidence_id == decision.version.material.freeze_evidence_id  # type: ignore[union-attr]


# --- decimal boundary ----------------------------------------------------------------------------------------


def test_float_evidence_crosses_once_into_canonical_decimal_without_rounding():
    assert canonical_price_v31(1.1) == Decimal("1.1")  # published decimal, not the binary artifact
    # A binary-float artifact does not fit Price: it is rejected, never rounded into something that looks canonical.
    with pytest.raises(ValueError, match="PRICE_DOES_NOT_FIT_CANONICAL_PRICE"):
        canonical_price_v31(0.1 + 0.2)
    with pytest.raises(ValueError, match="PRICE_DOES_NOT_FIT_CANONICAL_PRICE"):
        canonical_price_v31(Decimal("1.1234567890123"))  # 13 dp: rejected, never rounded
    with pytest.raises(TypeError):
        canonical_price_v31(1)
    assert canonical_price_text_v31(Decimal("1.1000")) == canonical_price_text_v31(Decimal("1.1")) == "1.1"
    assert canonical_price_text_v31(Decimal("10")) == "10"


def test_no_broker_tick_size_normalization_anywhere():
    for module in ("analysis/strategy_5scr_execution_box_v31.py", "contracts/strategy_5scr_execution_box_v31.py"):
        source = Path(module).read_text(encoding="utf-8")
        for forbidden in ("tick_size", "quantize(", "ROUND_", "round("):
            assert forbidden not in source, (module, forbidden)


# --- re-evaluation and versioning ----------------------------------------------------------------------------


def test_pressure_range_reevaluation_with_the_same_material_appends_no_version():
    assert requires_box_reevaluation_for_range_change_v31("MATERIAL_RANGE_CHANGE") is True
    assert requires_box_reevaluation_for_range_change_v31("NO_MATERIAL_CHANGE") is False
    lineage = _lineage()
    first = _built().version
    wider = _materialize(
        lifecycle=lineage.lifecycle,
        evidence=(_evidence(0, low=1.0950, high=1.1030), _evidence(1, low=1.1000, high=1.1010)),
        expected=_periods(2),
    ).range
    assert wider is not None and wider.low != _range(lineage).low
    again = _build(lineage, pressure_range=wider, previous=first, previous_state="FROZEN")
    assert (again.outcome, again.version, again.transitions) == ("NO_MATERIAL_CHANGE", None, ())


def test_a_changed_material_projection_appends_exactly_the_next_version_and_supersedes_the_old():
    lineage = _lineage()
    current = _built().version
    assert current is not None
    earlier = _with_material(current, box_low=Decimal("1.1005"))
    decision = _build(lineage, previous=earlier, previous_state="FROZEN", next_ordinal=2)
    assert decision.outcome == "NEW_BOX_VERSION"
    version = decision.version
    assert version is not None and version.execution_box_id == earlier.execution_box_id
    assert (version.box_version, version.previous_box_version) == (2, 1)
    assert version.previous_material_box_hash == earlier.material_box_hash
    superseded, building, frozen = decision.transitions
    assert (superseded.box_version, superseded.to_state, superseded.reason_code) == (1, "SUPERSEDED", "BOX_SUPERSEDED")
    assert [t.ordinal for t in decision.transitions] == [2, 3, 4]
    assert (building.to_state, frozen.to_state) == ("BUILDING", "FROZEN")


def test_a_target_change_with_the_same_material_appends_no_version_but_a_new_projection_does():
    lineage = _lineage()
    first = _built().version
    new_target = _selection(lineage, anchor="replacement-target", price="1.1150")
    same = _build(lineage, target_selection=new_target, previous=first, previous_state="FROZEN")
    assert same.outcome == "NO_MATERIAL_CHANGE"
    assert requires_box_reevaluation_for_target_fact_v31("TARGET_MATERIAL_CHANGE") is True
    assert requires_box_reevaluation_for_target_fact_v31("TARGET_UNCHANGED") is False
    earlier = _with_material(first, box_low=Decimal("1.1001"))  # type: ignore[arg-type]
    moved = _build(lineage, target_selection=new_target, previous=earlier, previous_state="FROZEN")
    assert moved.outcome == "NEW_BOX_VERSION"
    assert moved.version.lineage.target_id == new_target.selected_target.target_id  # type: ignore[union-attr]


def test_a_target_fact_never_maps_straight_to_a_box_state():
    import analysis.strategy_5scr_execution_box_v31 as box

    source = Path(box.__file__).read_text(encoding="utf-8")
    body = source[source.index("def requires_box_reevaluation_for_target_fact_v31") :]
    body = body[: body.index("\ndef ")]
    for state in ("INVALIDATED", "SUPERSEDED", "FROZEN", "BUILDING"):
        assert f'"{state}"' not in body, state  # no box-state literal anywhere in the fact function
    for fact in ("TARGET_INVALIDATED", "TARGET_NO_LONGER_ELIGIBLE", "TARGET_MATERIAL_CHANGE"):
        assert requires_box_reevaluation_for_target_fact_v31(fact) is True  # an obligation (bool), never a state
    with pytest.raises(ValueError):
        requires_box_reevaluation_for_target_fact_v31("TARGET_CONSUMED")


def test_a_terminal_box_is_never_reevaluated_or_resurrected():
    lineage = _lineage()
    first = _built().version
    for terminal in ("SUPERSEDED", "INVALIDATED"):
        with pytest.raises(ValueError, match="TERMINAL_BOX_IS_NEVER_RESURRECTED"):
            _build(lineage, previous=first, previous_state=terminal)
        with pytest.raises(ValueError, match="TERMINAL_BOX_IS_NEVER_RESURRECTED"):
            retire_execution_box_v31(first, terminal, successor=None, authority_time=BOX_DECISION, ordinal=5)  # type: ignore[arg-type]


# --- SUPERSEDED vs INVALIDATED ------------------------------------------------------------------------------


def test_a_replacement_supersedes_and_no_replacement_invalidates():
    current = _built().version
    assert current is not None
    successor = _built("BUY", "BREAKOUT_ACCEPTANCE", "ACCEPTANCE").version
    assert successor is not None
    successor = successor.model_validate(  # same thesis, different route = a new logical box (A3-08)
        {
            **successor.model_dump(),
            "strategy_thesis_id": current.strategy_thesis_id,
            "execution_box_id": execution_box_id_v31(
                strategy_thesis_id=current.strategy_thesis_id,
                route="BREAKOUT_ACCEPTANCE",
                box_policy_id="5scr.box-policy.breakout-acceptance",
                box_policy_version="v1",
            ),
        }
    )
    superseded = retire_execution_box_v31(
        current, "FROZEN", successor=successor, authority_time=BOX_DECISION, ordinal=2
    )
    assert (superseded.to_state, superseded.reason_code) == ("SUPERSEDED", "BOX_SUPERSEDED")
    invalidated = retire_execution_box_v31(
        current, "FROZEN", successor=None, authority_time=BOX_DECISION, ordinal=2, evidence_id=_h("basis-lost")
    )
    assert (invalidated.to_state, invalidated.reason_code) == ("INVALIDATED", "BOX_INVALIDATED")


def test_loss_and_replacement_in_the_same_transaction_is_superseded():
    lineage = _lineage()
    current = _built().version
    earlier = _with_material(current, box_low=Decimal("1.1003"))  # type: ignore[arg-type]
    decision = _build(lineage, previous=earlier, previous_state="FROZEN")
    assert decision.transitions[0].to_state == "SUPERSEDED"
    assert "INVALIDATED" not in {t.to_state for t in decision.transitions}


# --- post-freeze invalidation (not SL) ---------------------------------------------------------------------


def _after(lineage: Lineage, close: float):
    return thesis_fx._later_m15(lineage.proof, close)


@pytest.mark.parametrize(
    ("direction", "close", "invalidated"),
    [
        ("BUY", 1.1009, True),
        ("BUY", 1.1010, False),
        ("BUY", 1.1015, False),
        ("SELL", 1.1001, True),
        ("SELL", 1.1000, False),
    ],
)
def test_a_post_freeze_close_beyond_l_invalidates_and_equality_does_not(direction, close, invalidated):
    lineage = _lineage(direction)
    version = _built(direction).version
    candle = _after(lineage, close)
    assert boundary_level_v31(version) == (Decimal("1.101") if direction == "BUY" else Decimal("1.1"))  # type: ignore[arg-type]
    assert (
        post_freeze_invalidation_v31(
            version,  # type: ignore[arg-type]
            "FROZEN",
            candle,
            decision_time=candle.close_time_utc,
        )
        is invalidated
    )


def test_same_or_future_invalidation_evidence_is_rejected():
    lineage = _lineage()
    version = _built().version
    assert version is not None
    completion = next(
        c for c in lineage.proof.m15_source_candles if c.candle_evidence_id == lineage.proof.m15_completion_candle_id
    )
    with pytest.raises(ValueError, match="FREEZE_EVIDENCE_CANNOT_INVALIDATE_ITS_OWN_BOX"):
        post_freeze_invalidation_v31(version, "FROZEN", completion, decision_time=BOX_DECISION)
    later = _after(lineage, 1.1000)
    with pytest.raises(ValueError, match="FUTURE_INVALIDATION_EVIDENCE_REJECTED"):
        post_freeze_invalidation_v31(
            version, "FROZEN", later, decision_time=later.close_time_utc - timedelta(seconds=1)
        )
    earlier = later.model_construct(
        **{**later.__dict__, "close_time_utc": completion.close_time_utc, "candle_evidence_id": _h("x")}
    )
    with pytest.raises(ValueError, match="INVALIDATION_EVIDENCE_NOT_AFTER_FREEZE"):
        post_freeze_invalidation_v31(version, "FROZEN", earlier, decision_time=BOX_DECISION)
    with pytest.raises(ValueError, match="POST_FREEZE_INVALIDATION_REQUIRES_A_FROZEN_BOX"):
        post_freeze_invalidation_v31(version, "BUILDING", later, decision_time=later.close_time_utc)


# --- material hash -------------------------------------------------------------------------------------------


def test_lineage_never_moves_the_material_hash_but_authority_material_does():
    version = _built().version
    assert version is not None
    base = version.material_box_hash
    assert set(version.material.model_dump()) == {
        "box_low",
        "box_high",
        "structural_proof_id",
        "context_epoch_id",
        "freeze_evidence_id",
    }
    for field, value in (
        ("freeze_evidence_id", _h("other-freeze")),
        ("context_epoch_id", _other_uuid()),
        ("structural_proof_id", _other_uuid()),
    ):
        changed = ExecutionBoxMaterialV31.model_validate({**version.material.model_dump(), field: value})
        assert material_box_hash_v31(changed) != base, field
    assert "pressure_range_id" not in version.material.model_dump() and "target_id" not in version.material.model_dump()


# --- boundaries ------------------------------------------------------------------------------------------------


def test_no_consumed_no_expired_and_no_clock():
    assert set(get_args(ExecutionBoxState)) == {"BUILDING", "FROZEN", "SUPERSEDED", "INVALIDATED"}
    fields = set(ExecutionBoxVersionV31.model_fields)
    assert not {f for f in fields if "valid_until" in f or "expire" in f or "ttl" in f}
    with pytest.raises(ValidationError):
        ExecutionBoxTransitionV31(
            execution_box_id=_other_uuid(),
            box_version=1,
            ordinal=0,
            from_state="FROZEN",
            to_state="CONSUMED",  # type: ignore[arg-type]
            reason_code="X_CONSUMED",
            authority_time=BOX_DECISION,
            evidence_id=None,
        )
    with pytest.raises(ValidationError, match="EXECUTION_BOX_TRANSITION_NOT_ALLOWED"):
        ExecutionBoxTransitionV31(
            execution_box_id=_other_uuid(),
            box_version=1,
            ordinal=0,
            from_state="SUPERSEDED",
            to_state="FROZEN",
            reason_code="RESURRECT",
            authority_time=BOX_DECISION,
            evidence_id=None,
        )


def test_no_broker_risk_execution_or_legacy_box_imports_and_no_authority():
    for module in ("analysis/strategy_5scr_execution_box_v31.py", "contracts/strategy_5scr_execution_box_v31.py"):
        tree = ast.parse(Path(module).read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        for forbidden in ("broker", "risk", "execution_box_v1", "order", "mt5", "execution_queue", "net_geometry_v31"):
            hits = {m for m in imported if forbidden in m} - {"contracts.strategy_5scr_net_geometry_v31"}
            assert not hits, (module, hits)
    version = _built().version
    assert version is not None
    assert (version.valid_for_execution, version.risk_authority, version.execution_authority) == (False, False, False)
    assert version.runtime_status == "RUNTIME_DISABLED"
    assert {p.runtime_status for p in BOX_POLICIES_V31.values()} == {"RUNTIME_DISABLED"}


def test_m1_is_never_freeze_authority():
    assert {p.closed_candle_authority for p in BOX_POLICIES_V31.values()} == {"M15"}
    lineage = _lineage()
    candles = list(lineage.proof.m15_source_candles)
    m1 = candles[-1].model_construct(**{**candles[-1].__dict__, "timeframe": "M1"})
    with pytest.raises(ValueError, match="INVALIDATION_EVIDENCE_MUST_BE_SAME_SYMBOL_M15"):
        post_freeze_invalidation_v31(_built().version, "FROZEN", m1, decision_time=BOX_DECISION)  # type: ignore[arg-type]


# --- guards added after mutation testing ---------------------------------------------------------------------


def test_the_identity_formula_is_pinned_and_the_route_alone_separates_boxes():
    thesis_id = _other_uuid()
    policy = {"box_policy_id": "5scr.box-policy.break-retest", "box_policy_version": "v1"}
    pinned = execution_box_id_v31(strategy_thesis_id=thesis_id, route="BREAK_RETEST", **policy)
    # Any change to the namespace, derivation version or tuple must be a deliberate, versioned change.
    assert str(pinned) == "1a327da4-cf23-5fd1-9574-ca0edc09d562"
    assert pinned != execution_box_id_v31(strategy_thesis_id=thesis_id, route="BREAKOUT_ACCEPTANCE", **policy)


def test_a_thesis_without_direction_authority_builds_no_box():
    lineage = _lineage()
    invalidated = lineage.status.model_validate(
        {**lineage.status.model_dump(), "state": "INVALIDATED", "direction_authority": False}
    )
    assert _build(lineage, thesis_status=invalidated).reason_code == "THESIS_NOT_AUTHORITATIVE"


def test_reevaluation_never_crosses_logical_boxes():
    buy = _lineage("BUY")
    foreign = _built("SELL").version
    with pytest.raises(ValueError, match="REEVALUATION_ACROSS_DIFFERENT_LOGICAL_BOXES"):
        _build(buy, previous=foreign, previous_state="FROZEN")
