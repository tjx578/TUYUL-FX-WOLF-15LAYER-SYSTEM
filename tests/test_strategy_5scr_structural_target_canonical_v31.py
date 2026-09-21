"""Canonical StructuralTarget V31 adapter acceptance: SSOT v3.1 §17 + A2-01 … A2-07 (owner GO 2026-09-21).

Tests 1–26 are the owner's acceptance list in order; the identity and precedence tests below them pin what the
list depends on. `valid_until` defaults to BEFORE the decision time in every fixture, so any test that selects a
target also proves that a wall-clock TTL is not freshness authority.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_structural_target_canonical_v31 import (
    apply_target_interaction_v31,
    classify_target_revision_v31,
    select_structural_target_v31,
)
from contracts.strategy_5scr_structural_target_canonical_v31 import (
    ELIGIBILITY_PREDICATES_V31,
    REVISION_FACT_PRECEDENCE_V31,
    CanonicalStructuralTargetV31,
    DecisionPriceV31,
    LegacyTargetLevelV31,
    SourcePolicyRefV31,
    StructuralTargetSelectionRequestV31,
    StructuralTargetSelectionV31,
    TargetInteractionV31,
    TargetRevisionV31,
    structural_target_id_v31,
)
from contracts.strategy_5scr_target_selection_v31 import StructuralTargetV31

T0 = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)
DECISION = T0 + timedelta(hours=2)
LATER = DECISION + timedelta(hours=1)
THESIS = UUID("0b6a3f52-9d1c-4c0e-8f7e-2a1d6c4b5e90")


def _h(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


FRESHNESS = SourcePolicyRefV31(policy_id="test.swing-freshness", policy_version="v1", policy_hash=_h("freshness"))
COMPLETION = SourcePolicyRefV31(policy_id="test.swing-completion", policy_version="v1", policy_hash=_h("completion"))


def _candidate(
    anchor: str = "a",
    *,
    price: str = "1.1050",
    direction: str = "BUY",
    source: str = "SWING",
    timeframe: str = "H1",
    basis: str = "STRUCTURAL",
    authority: str = "AUTHORITATIVE",
    freshness: str = "FRESH",
    tested: int = 0,
    formed_at: datetime = T0,
    valid_until: datetime = T0 + timedelta(hours=1),  # already past at DECISION, on purpose
    consumed_at: datetime | None = None,
    invalidated_at: datetime | None = None,
    completion_policy: SourcePolicyRefV31 | None = COMPLETION,
    freshness_policy: SourcePolicyRefV31 = FRESHNESS,
    observed_through: datetime = DECISION - timedelta(minutes=1),
    evidence: str | None = None,
) -> CanonicalStructuralTargetV31:
    anchor_id = _h(f"anchor:{anchor}")
    target_id = structural_target_id_v31(
        canonical_symbol="EURUSD",
        source=source,  # type: ignore[arg-type]
        source_timeframe=timeframe,  # type: ignore[arg-type]
        thesis_direction=direction,  # type: ignore[arg-type]
        structural_anchor_id=anchor_id,
    )
    target = StructuralTargetV31(
        target_id=str(target_id),
        source=source,  # type: ignore[arg-type]
        price=Decimal(price),
        evidence_hash=_h(evidence or f"evidence:{anchor}"),
        formed_at=formed_at,
        valid_until=valid_until,
        consumed_at=consumed_at,
    )
    return CanonicalStructuralTargetV31(
        canonical_symbol="EURUSD",
        thesis_direction=direction,  # type: ignore[arg-type]
        source_timeframe=timeframe,  # type: ignore[arg-type]
        structural_anchor_id=anchor_id,
        source_bar_ids=(_h(f"bar:{anchor}"),),
        target=target,
        structural_basis=basis,  # type: ignore[arg-type]
        authority=authority,  # type: ignore[arg-type]
        freshness_status=freshness,  # type: ignore[arg-type]
        tested_count=tested,
        freshness_policy=freshness_policy,
        completion_policy=completion_policy,
        completion_evidence_hash=None if consumed_at is None else _h(f"completion:{anchor}"),
        invalidated_at=invalidated_at,
        invalidation_evidence_hash=None if invalidated_at is None else _h(f"invalidation:{anchor}"),
        observed_through_utc=observed_through,
    )


def _request(
    *candidates: CanonicalStructuralTargetV31,
    direction: str = "BUY",
    price: str = "1.1000",
    decision: datetime = DECISION,
    pressure_range: Any = None,
    price_observed_at: datetime | None = None,
) -> StructuralTargetSelectionRequestV31:
    return StructuralTargetSelectionRequestV31(
        canonical_symbol="EURUSD",
        strategy_thesis_id=THESIS,
        thesis_direction=direction,  # type: ignore[arg-type]
        decision_time=decision,
        decision_price=DecisionPriceV31(
            canonical_symbol="EURUSD",
            origin="STRATEGY_CLOSED_PRICE_AUTHORITY",
            price=Decimal(price),
            observed_at=price_observed_at or decision - timedelta(minutes=1),
            evidence_hash=_h(f"decision-price:{price}:{decision.isoformat()}"),
        ),
        candidates=candidates,
        pressure_range=pressure_range,
    )


def _failed(selection: StructuralTargetSelectionV31, candidate: CanonicalStructuralTargetV31) -> tuple[str, ...]:
    (row,) = [e for e in selection.eligibility if e.target_id == candidate.target.target_id]
    return row.failed_predicates


def _selected_id(selection: StructuralTargetSelectionV31) -> str | None:
    return None if selection.selected_target is None else selection.selected_target.target_id


def _interaction(candidate: CanonicalStructuralTargetV31, kind: str, at: datetime, **overrides: Any) -> Any:
    body = {
        "target_id": candidate.target.target_id,
        "kind": kind,
        "observed_at": at,
        "evidence_hash": _h(f"{kind}:{at.isoformat()}"),
        "authority": "AUTHORITATIVE",
        "policy": FRESHNESS if kind == "TEST" else COMPLETION,
        "freshness_status_after": "FRESH",
    }
    return TargetInteractionV31(**{**body, **overrides})


# --- 1..8: the six predicates -------------------------------------------------------------------------------


def test_1_buy_target_below_or_equal_to_decision_price_is_rejected():
    below, equal = _candidate("below", price="1.0990"), _candidate("equal", price="1.1000")
    selection = select_structural_target_v31(_request(below, equal))
    assert selection.status == "NO_ELIGIBLE_TARGET"
    assert _failed(selection, below) == _failed(selection, equal) == ("NOT_PASSED_AT_DECISION_TIME",)


def test_2_sell_target_above_or_equal_to_decision_price_is_rejected():
    above = _candidate("above", price="1.1010", direction="SELL")
    equal = _candidate("equal", price="1.1000", direction="SELL")
    selection = select_structural_target_v31(_request(above, equal, direction="SELL"))
    assert selection.status == "NO_ELIGIBLE_TARGET"
    assert _failed(selection, above) == _failed(selection, equal) == ("NOT_PASSED_AT_DECISION_TIME",)


def test_3_a_non_structural_target_is_rejected_and_a_bare_float_cannot_enter():
    non_structural = _candidate("n", basis="NON_STRUCTURAL")
    selection = select_structural_target_v31(_request(non_structural))
    assert _failed(selection, non_structural) == ("STRUCTURAL",)
    legacy = LegacyTargetLevelV31(label="key_support", value=1.1050)
    assert (legacy.conformance, legacy.structural_authority) == ("NONCONFORMANT_LEGACY", False)
    with pytest.raises(ValidationError):
        _request(legacy)  # type: ignore[arg-type]


def test_4_a_non_authoritative_target_is_rejected():
    candidate = _candidate(authority="NON_AUTHORITATIVE")
    assert _failed(select_structural_target_v31(_request(candidate)), candidate) == ("AUTHORITATIVE",)


def test_5_a_target_for_the_other_thesis_direction_is_rejected():
    # Above the BUY decision price, so only the thesis-direction predicate can reject it.
    candidate = _candidate(direction="SELL", price="1.1050")
    assert _failed(select_structural_target_v31(_request(candidate)), candidate) == ("IN_THESIS_DIRECTION",)


def test_6_a_non_fresh_target_is_rejected():
    candidate = _candidate(freshness="NOT_FRESH")
    assert _failed(select_structural_target_v31(_request(candidate)), candidate) == ("FRESH",)


def test_7_a_consumed_target_is_rejected():
    candidate = _candidate(consumed_at=T0 + timedelta(minutes=30))
    assert _failed(select_structural_target_v31(_request(candidate)), candidate) == ("UNCONSUMED",)


def test_8_a_target_passed_by_the_decision_price_is_rejected():
    # Above price when it formed; by decision time price has gone through it.
    candidate = _candidate(price="1.1050")
    selection = select_structural_target_v31(_request(candidate, price="1.1060"))
    assert _failed(selection, candidate) == ("NOT_PASSED_AT_DECISION_TIME",)


# --- 9..13: nearest and the tie policy ----------------------------------------------------------------------


def test_9_the_nearest_eligible_target_is_selected():
    near, mid, far = _candidate("n", price="1.1020"), _candidate("m", price="1.1050"), _candidate("f", price="1.1090")
    selection = select_structural_target_v31(_request(far, near, mid))
    assert (selection.status, _selected_id(selection)) == ("SELECTED", near.target.target_id)
    assert selection.selected_directional_distance == Decimal("0.0020")


def test_10_a_farther_target_is_never_selected_however_much_better_its_rr_would_be():
    near, far = _candidate("n", price="1.1003"), _candidate("f", price="1.1200")
    assert _selected_id(select_structural_target_v31(_request(near, far))) == near.target.target_id
    # The selector has no RR, SL, cost or geometry input it could shop with.
    fields = set(StructuralTargetSelectionRequestV31.model_fields)
    assert not {f for f in fields if any(k in f for k in ("rr", "stop", "sl", "cost", "geometry", "entry"))}
    assert select_structural_target_v31(_request(near, far)).geometry_solved is False


def test_11_an_equal_distance_tie_resolves_to_the_smallest_stable_target_id_in_any_input_order():
    tied = (_candidate("x", price="1.1030"), _candidate("y", price="1.1030"), _candidate("z", price="1.1030"))
    winner = min(c.target.target_id for c in tied)
    for order in permutations(tied):
        assert _selected_id(select_structural_target_v31(_request(*order))) == winner


def test_12_formed_at_never_changes_the_winner_or_the_identity():
    early, late = T0 - timedelta(days=5), T0
    first = [_candidate("x", price="1.1030", formed_at=early), _candidate("y", price="1.1030", formed_at=late)]
    swapped = [_candidate("x", price="1.1030", formed_at=late), _candidate("y", price="1.1030", formed_at=early)]
    assert [c.target.target_id for c in first] == [c.target.target_id for c in swapped]
    assert _selected_id(select_structural_target_v31(_request(*first))) == _selected_id(
        select_structural_target_v31(_request(*swapped))
    )


def test_13_target_source_creates_no_hidden_precedence():
    # Non-tie: the nearest wins whatever its source.
    for near_source, far_source in (("FIBONACCI", "D1_SR"), ("D1_SR", "FIBONACCI"), ("RANGE", "SWING")):
        near = _candidate("n", price="1.1020", source=near_source)
        far = _candidate("f", price="1.1040", source=far_source)
        assert _selected_id(select_structural_target_v31(_request(far, near))) == near.target.target_id
    # Tie: the winner is always the smallest target_id, never a preferred source.
    for pair in (("D1_SR", "FIBONACCI"), ("FIBONACCI", "D1_SR"), ("SWING", "LIQUIDITY")):
        tied = [_candidate(f"t{i}", price="1.1030", source=s) for i, s in enumerate(pair)]
        expected = min(c.target.target_id for c in tied)
        assert _selected_id(select_structural_target_v31(_request(*tied))) == expected


# --- 14..16: freshness is source-policy state ----------------------------------------------------------------


def test_14_wall_clock_ttl_expiry_alone_does_not_make_a_canonical_target_stale():
    expired = _candidate("e", valid_until=T0 + timedelta(minutes=1))
    assert expired.target.valid_until < DECISION
    assert _selected_id(select_structural_target_v31(_request(expired))) == expired.target.target_id
    unexpired_but_not_fresh = _candidate("u", freshness="NOT_FRESH", valid_until=LATER + timedelta(days=30))
    assert _failed(select_structural_target_v31(_request(unexpired_but_not_fresh)), unexpired_but_not_fresh) == (
        "FRESH",
    )
    assert expired.valid_until_semantics == "NON_CANONICAL_ADVISORY_ONLY"


def test_15_tested_count_alone_imposes_no_hidden_threshold():
    for tested in (0, 1, 2, 3, 10, 500):
        candidate = _candidate(tested=tested)
        assert _selected_id(select_structural_target_v31(_request(candidate))) == candidate.target.target_id


def test_16_each_source_policys_own_freshness_verdict_is_respected():
    liquidity_policy = SourcePolicyRefV31(policy_id="test.liquidity-fresh", policy_version="v3", policy_hash=_h("l"))
    swing = _candidate("s", source="SWING", freshness="NOT_FRESH", tested=0, price="1.1010")
    liquidity = _candidate(
        "l", source="LIQUIDITY", freshness="FRESH", tested=9, price="1.1040", freshness_policy=liquidity_policy
    )
    selection = select_structural_target_v31(_request(swing, liquidity))
    assert _failed(selection, swing) == ("FRESH",)
    assert _selected_id(selection) == liquidity.target.target_id
    assert liquidity.freshness_policy.policy_version == "v3"


# --- 17..18: TEST is not CONSUME ------------------------------------------------------------------------------


def test_17_a_test_increments_tested_count_and_never_consumes():
    candidate = _candidate()
    tested = apply_target_interaction_v31(candidate, _interaction(candidate, "TEST", T0 + timedelta(minutes=40)))
    assert (tested.tested_count, tested.target.consumed_at, tested.completion_evidence_hash) == (1, None, None)
    assert tested.target.target_id == candidate.target.target_id
    assert _selected_id(select_structural_target_v31(_request(tested))) == candidate.target.target_id


def test_18_authoritative_completion_evidence_consumes_the_target():
    candidate = _candidate()
    first, second = T0 + timedelta(minutes=50), T0 + timedelta(minutes=20)
    consumed = apply_target_interaction_v31(candidate, _interaction(candidate, "COMPLETION", first))
    assert consumed.target.consumed_at == first and consumed.completion_evidence_hash is not None
    # Earlier authoritative evidence arriving late wins: consumed_at is the FIRST completion evidence.
    earlier = apply_target_interaction_v31(consumed, _interaction(candidate, "COMPLETION", second))
    assert earlier.target.consumed_at == second
    assert _failed(select_structural_target_v31(_request(earlier)), earlier) == ("UNCONSUMED",)
    with pytest.raises(ValueError, match="TARGET_INTERACTION_NOT_AUTHORITATIVE"):
        apply_target_interaction_v31(
            candidate, _interaction(candidate, "COMPLETION", first, authority="NON_AUTHORITATIVE")
        )
    with pytest.raises(ValueError, match="TARGET_WITHOUT_COMPLETION_RULE_CANNOT_BE_CONSUMED"):
        ruleless = _candidate(completion_policy=None)
        apply_target_interaction_v31(ruleless, _interaction(ruleless, "COMPLETION", first))
    with pytest.raises(ValueError, match="TARGET_COMPLETION_POLICY_MISMATCH"):
        apply_target_interaction_v31(candidate, _interaction(candidate, "COMPLETION", first, policy=FRESHNESS))


# --- 19..22: A2-07 revision facts ----------------------------------------------------------------------------


def _previous(*candidates: CanonicalStructuralTargetV31) -> StructuralTargetSelectionV31:
    selection = select_structural_target_v31(_request(*candidates))
    assert selection.status == "SELECTED"
    return selection


def _later(*candidates: CanonicalStructuralTargetV31) -> StructuralTargetSelectionRequestV31:
    return _request(*candidates, decision=LATER)


def test_19_a_new_nearer_target_is_a_material_change():
    old = _candidate("old", price="1.1050")
    newer = _candidate(
        "new",
        price="1.1020",
        formed_at=DECISION + timedelta(minutes=5),
        valid_until=LATER + timedelta(hours=1),
        observed_through=LATER,
    )
    revision = classify_target_revision_v31(previous=_previous(old), current_request=_later(old, newer))
    assert revision.fact == "TARGET_MATERIAL_CHANGE"
    assert (revision.current_selected_target_id, revision.failed_predicates) == (newer.target.target_id, ())


def test_20_the_current_target_consumed_is_no_longer_eligible():
    old = _candidate("old")
    consumed = _candidate("old", consumed_at=DECISION + timedelta(minutes=10), observed_through=LATER)
    revision = classify_target_revision_v31(previous=_previous(old), current_request=_later(consumed))
    assert (revision.fact, revision.failed_predicates) == ("TARGET_NO_LONGER_ELIGIBLE", ("UNCONSUMED",))


def test_21_the_current_target_invalidated_by_its_source_is_invalidated():
    old = _candidate("old")
    invalidated = _candidate("old", invalidated_at=DECISION + timedelta(minutes=10), observed_through=LATER)
    revision = classify_target_revision_v31(previous=_previous(old), current_request=_later(invalidated))
    assert revision.fact == "TARGET_INVALIDATED"


def test_22_a_materially_unchanged_target_is_unchanged():
    old = _candidate("old")
    tested = _candidate("old", tested=4, observed_through=LATER)  # a TEST is not a material change
    revision = classify_target_revision_v31(previous=_previous(old), current_request=_later(tested))
    assert (revision.fact, revision.material_fields_changed) == ("TARGET_UNCHANGED", ())


# --- 23..26: time, origin and boundaries ---------------------------------------------------------------------


def test_23_future_evidence_is_rejected():
    future_state = _candidate(observed_through=DECISION + timedelta(minutes=1))
    assert select_structural_target_v31(_request(future_state)).reason == "TARGET_FUTURE_EVIDENCE"
    future_price = _request(_candidate(), price_observed_at=DECISION + timedelta(seconds=1))
    assert select_structural_target_v31(future_price).reason == "DECISION_PRICE_FUTURE_EVIDENCE"
    with pytest.raises(ValidationError, match="STRUCTURAL_TARGET_STATE_AFTER_OBSERVATION"):
        _candidate(consumed_at=DECISION, observed_through=DECISION - timedelta(minutes=1))


def test_24_a_broker_quote_can_never_become_the_decision_price():
    for origin in ("BROKER_QUOTE", "BROKER_BID", "BROKER_ASK", "FILL_PRICE", "ROUTE_ENTRY", "RR_REFERENCE"):
        with pytest.raises(ValidationError):
            DecisionPriceV31(
                canonical_symbol="EURUSD",
                origin=origin,  # type: ignore[arg-type]
                price=Decimal("1.1000"),
                observed_at=DECISION,
                evidence_hash=_h("quote"),
            )


def test_25_pressure_range_is_read_only_context_and_never_an_eligibility_predicate():
    from tests.test_strategy_5scr_pressure_range_v31 import _complete

    pressure_range = _complete()  # [1.0990, 1.1030]
    before = pressure_range.model_dump()
    inside, outside = _candidate("in", price="1.1020"), _candidate("out", price="1.1080")
    with_range = select_structural_target_v31(_request(inside, outside, pressure_range=pressure_range))
    without = select_structural_target_v31(_request(inside, outside))
    assert pressure_range.model_dump() == before
    # A target inside the range is still the nearest eligible target: no seventh predicate exists.
    assert _selected_id(with_range) == _selected_id(without) == inside.target.target_id
    assert with_range.eligibility == without.eligibility
    assert with_range.pressure_range_id == pressure_range.pressure_range_id
    assert ELIGIBILITY_PREDICATES_V31 == (
        "STRUCTURAL",
        "AUTHORITATIVE",
        "IN_THESIS_DIRECTION",
        "FRESH",
        "UNCONSUMED",
        "NOT_PASSED_AT_DECISION_TIME",
    )


def test_26_no_execution_box_reaction_and_no_authority_is_emitted():
    selection = select_structural_target_v31(_request(_candidate()))
    assert (selection.geometry_solved, selection.risk_authority, selection.execution_authority) == (False, False, False)
    for model in (StructuralTargetSelectionV31, TargetRevisionV31):
        assert not [f for f in model.model_fields if "box" in f.lower() or "order" in f.lower()]
    assert set(TargetRevisionV31.model_fields) == {
        "previous_target_id",
        "current_selected_target_id",
        "fact",
        "failed_predicates",
        "material_fields_changed",
    }
    import ast

    import analysis.strategy_5scr_structural_target_canonical_v31 as adapter
    import contracts.strategy_5scr_structural_target_canonical_v31 as contract

    for module in (adapter, contract):
        tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        for forbidden in ("execution_box", "net_geometry_v31", "broker", "risk", "order", "target_selection_v31"):
            hits = {m for m in imported if forbidden in m}
            # The contract may reuse the StructuralTargetV31 record and the Price type, nothing that solves or acts.
            allowed = {"contracts.strategy_5scr_target_selection_v31", "contracts.strategy_5scr_net_geometry_v31"}
            assert not (hits - allowed if module is contract else hits), (module.__name__, hits)


# --- identity (A2-06) ----------------------------------------------------------------------------------------


def test_target_id_formula_is_pinned_and_deterministic():
    kwargs = {
        "canonical_symbol": "EURUSD",
        "source": "SWING",
        "source_timeframe": "H1",
        "thesis_direction": "BUY",
        "structural_anchor_id": _h("anchor:a"),
    }
    first = structural_target_id_v31(**kwargs)  # type: ignore[arg-type]
    assert first == structural_target_id_v31(**kwargs)  # type: ignore[arg-type]
    # Pinned: any change to the namespace, the version string or the tuple must be a deliberate, versioned change.
    assert str(first) == "3cd56727-6942-56e6-8323-a5e2074cf671"


def test_every_identity_part_separates_targets_and_no_material_or_clock_field_does():
    base = _candidate("a")
    distinct = [
        _candidate("b"),
        _candidate("a", source="D1_SR"),
        _candidate("a", timeframe="H4"),
        _candidate("a", direction="SELL", price="1.0950"),
    ]
    assert len({base.target.target_id, *(c.target.target_id for c in distinct)}) == 5
    same = [
        _candidate("a", price="1.1070"),
        _candidate("a", evidence="revised-evidence"),
        _candidate("a", formed_at=T0 - timedelta(days=1)),
        _candidate("a", valid_until=LATER),
        _candidate("a", tested=7, freshness="NOT_FRESH", authority="NON_AUTHORITATIVE"),
    ]
    assert {c.target.target_id for c in same} == {base.target.target_id}


def test_a_caller_supplied_target_id_is_never_trusted():
    body = _candidate().model_dump()
    body["target"]["target_id"] = "caller-chosen-id"
    with pytest.raises(ValidationError, match="STRUCTURAL_TARGET_ID_NOT_DERIVED"):
        CanonicalStructuralTargetV31.model_validate(body)


# --- A2-07 precedence and scope ------------------------------------------------------------------------------


def test_invalidation_outranks_ineligibility_and_ineligibility_outranks_a_material_change():
    assert REVISION_FACT_PRECEDENCE_V31 == (
        "TARGET_INVALIDATED",
        "TARGET_NO_LONGER_ELIGIBLE",
        "TARGET_MATERIAL_CHANGE",
        "TARGET_UNCHANGED",
    )
    old = _candidate("old")
    both = _candidate(
        "old",
        consumed_at=DECISION + timedelta(minutes=5),
        invalidated_at=DECISION + timedelta(minutes=6),
        observed_through=LATER,
        price="1.1060",
    )
    assert classify_target_revision_v31(previous=_previous(old), current_request=_later(both)).fact == (
        "TARGET_INVALIDATED"
    )
    consumed_and_replaced = _candidate("old", consumed_at=DECISION + timedelta(minutes=5), observed_through=LATER)
    replacement = _candidate("new", price="1.1030", observed_through=LATER)
    revision = classify_target_revision_v31(
        previous=_previous(old), current_request=_later(consumed_and_replaced, replacement)
    )
    assert (revision.fact, revision.current_selected_target_id) == (
        "TARGET_NO_LONGER_ELIGIBLE",
        replacement.target.target_id,
    )


def test_a_price_revision_under_the_same_id_is_a_material_change():
    old = _candidate("old", price="1.1050")
    revised = _candidate("old", price="1.1045", evidence="revised", observed_through=LATER)
    revision = classify_target_revision_v31(previous=_previous(old), current_request=_later(revised))
    assert (revision.fact, revision.material_fields_changed) == ("TARGET_MATERIAL_CHANGE", ("price", "evidence_hash"))


def test_a_revision_needs_a_previous_selection_and_the_same_thesis():
    empty = select_structural_target_v31(_request(_candidate(freshness="NOT_FRESH")))
    with pytest.raises(ValueError, match="TARGET_REVISION_REQUIRES_PREVIOUS_SELECTION"):
        classify_target_revision_v31(previous=empty, current_request=_later(_candidate()))
    with pytest.raises(ValueError, match="TARGET_REVISION_PREVIOUS_TARGET_RECORD_MISSING"):
        classify_target_revision_v31(previous=_previous(_candidate("old")), current_request=_later(_candidate("b")))
    sell = _request(_candidate(direction="SELL", price="1.0950"), direction="SELL", decision=LATER)
    with pytest.raises(ValueError, match="TARGET_REVISION_ACROSS_DIFFERENT_THESES"):
        classify_target_revision_v31(previous=_previous(_candidate("old")), current_request=sell)


def test_selection_is_independent_of_input_order():
    candidates = (_candidate("a", price="1.1020"), _candidate("b", price="1.1040"), _candidate("c", price="1.0990"))
    results = {select_structural_target_v31(_request(*order)).model_dump_json() for order in permutations(candidates)}
    assert len(results) == 1


def test_a_source_invalidated_target_is_never_selected():
    """Invalidation removes the structure: the target fails STRUCTURAL and the next eligible target wins."""

    invalidated = _candidate("inv", price="1.1010", invalidated_at=T0 + timedelta(minutes=30))
    other = _candidate("ok", price="1.1040")
    selection = select_structural_target_v31(_request(invalidated, other))
    assert _failed(selection, invalidated) == ("STRUCTURAL",)
    assert _selected_id(selection) == other.target.target_id


def test_consumption_and_invalidation_each_require_their_own_evidence():
    consumed = _candidate(consumed_at=T0 + timedelta(minutes=30))
    for field, error in (
        ("completion_evidence_hash", "CONSUMPTION_REQUIRES_COMPLETION_EVIDENCE"),
        ("invalidation_evidence_hash", "INVALIDATION_REQUIRES_SOURCE_EVIDENCE"),
    ):
        body = consumed.model_dump()
        body[field] = None if field == "completion_evidence_hash" else _h("orphan-evidence")
        with pytest.raises(ValidationError, match=error):
            CanonicalStructuralTargetV31.model_validate(body)
    orphan = _candidate().model_dump()
    orphan["completion_evidence_hash"] = _h("completion-without-consumption")
    with pytest.raises(ValidationError, match="CONSUMPTION_REQUIRES_COMPLETION_EVIDENCE"):
        CanonicalStructuralTargetV31.model_validate(orphan)
