from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_target_selection_v31 import solve_target_geometry_v31, target_universe_hash_v31
from contracts.strategy_5scr_net_geometry_v31 import NetGeometryContextV31
from contracts.strategy_5scr_target_selection_v31 import TargetUniverseV31
from tests.test_strategy_5scr_net_geometry_v31 import NOW, H, request_data

SOURCES = ("SWING", "D1_SR", "H4_SR", "H1_SR", "RANGE", "BREAKOUT", "LIQUIDITY", "FIBONACCI")


def fixture(direction="BUY"):
    context = request_data(direction)
    del context["target_price"], context["target_evidence_hash"]
    sign = 1 if direction == "BUY" else -1
    universe = {
        "profile": "TEST_ONLY",
        "symbol": "EURUSD",
        "direction": direction,
        "decision_at": NOW,
        "anchor_price": "1.1",
        "anchor_evidence_hash": H,
        "policy_hash": H,
        "required_sources": SOURCES,
        "covered_sources": SOURCES,
        "targets": [
            {
                "target_id": name,
                "source": source,
                "price": Decimal("1.1") + sign * distance,
                "evidence_hash": H,
                "formed_at": NOW - timedelta(hours=1),
                "valid_until": NOW + timedelta(hours=1),
                "consumed_at": None,
            }
            for name, source, distance in (
                ("nearest", "D1_SR", Decimal("0.0012")),
                ("farther", "H4_SR", Decimal("0.003")),
            )
        ],
    }
    return universe, context


def solve(data, context, verifier="BOUND_TEST_RECEIPT"):
    universe = TargetUniverseV31(**data)
    if verifier == "BOUND_TEST_RECEIPT":
        expected = target_universe_hash_v31(universe)

        def verifier(snapshot, digest):
            return digest == expected and snapshot.policy_hash == H

    return solve_target_geometry_v31(
        universe=universe, context=NetGeometryContextV31(**context), verify_universe=verifier
    )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_nearest_selected_before_net_solver_and_farther_never_used_to_rescue_rr(direction):
    data, context = fixture(direction)
    assert solve(data, context).geometry.status == "FEASIBLE_TEST_ONLY"
    data["targets"][0]["price"] = Decimal("1.1002") if direction == "BUY" else Decimal("1.0998")
    result = solve(data, context)
    assert result.selected_target_id == "nearest"
    assert result.geometry.status == "NO_VALID_ENTRY_DOMAIN"
    assert not result.execution_authority and not result.geometry.execution_authority
    assert not result.capital_reservation_authority and not result.hypothesis_authority
    only_far = dict(data, targets=[data["targets"][1]])
    assert solve(only_far, context).geometry.status == "FEASIBLE_TEST_ONLY"


@pytest.mark.parametrize("source", SOURCES)
def test_all_declared_legal_source_kinds_feed_same_caller(source):
    data, context = fixture()
    data["targets"][0]["source"] = source
    result = solve(data, context)
    assert result.selected_target_id == "nearest"
    assert result.geometry.status == "FEASIBLE_TEST_ONLY"


@pytest.mark.parametrize("mutation", ["expired", "consumed", "passed", "wrong_side"])
def test_ineligible_nearest_allows_next_legal_target(mutation):
    data, context = fixture()
    if mutation == "expired":
        data["targets"][0]["valid_until"] = NOW
    elif mutation == "consumed":
        data["targets"][0]["consumed_at"] = NOW
    else:
        data["targets"][0]["price"] = Decimal("1.1") if mutation == "passed" else Decimal("1.099")
    assert solve(data, context).selected_target_id == "farther"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("coverage", "TARGET_SOURCE_COVERAGE_INCOMPLETE"),
        ("policy", "TARGET_POLICY_UNBOUND_OR_MISMATCH"),
        ("symbol", "TARGET_CONTEXT_MISMATCH"),
        ("future_formed", "TARGET_FUTURE_EVIDENCE"),
        ("future_consumed", "TARGET_FUTURE_EVIDENCE"),
    ],
)
def test_bad_binding_does_not_reach_attestor_or_geometry(mutation, reason):
    data, context = fixture()
    if mutation == "coverage":
        data["covered_sources"] = SOURCES[1:]
    elif mutation == "policy":
        context["policy"] = None
    elif mutation == "symbol":
        context["symbol"] = "USDJPY"
    elif mutation == "future_formed":
        data["targets"][0]["formed_at"] = NOW + timedelta(seconds=1)
    else:
        data["targets"][0]["consumed_at"] = NOW + timedelta(seconds=1)

    def never(*args):
        pytest.fail("invalid snapshot reached attestor")

    result = solve(data, context, never)
    assert result.reason == reason
    assert result.geometry is None and result.selected_target_id is None


@pytest.mark.parametrize(
    "verifier,reason",
    [
        (None, "TARGET_ATTESTOR_UNBOUND"),
        (lambda *args: False, "TARGET_ATTESTATION_REJECTED"),
        (lambda *args: 1, "TARGET_ATTESTATION_REJECTED"),
    ],
)
def test_unbound_or_non_boolean_attestation_cannot_pass(verifier, reason):
    data, context = fixture()
    assert solve(data, context, verifier).reason == reason


def test_receipt_covers_whole_cohort_and_reordering_is_stable():
    data, context = fixture()
    pinned = target_universe_hash_v31(TargetUniverseV31(**data))
    data["targets"].reverse()
    data["covered_sources"] = tuple(reversed(SOURCES))
    assert solve(data, context, lambda snapshot, digest: digest == pinned).selected_target_id == "nearest"
    data["targets"].pop()
    assert solve(data, context, lambda snapshot, digest: digest == pinned).reason == "TARGET_ATTESTATION_REJECTED"


def test_duplicate_identity_and_off_grid_nearest_fail_without_fallback():
    data, context = fixture()
    data["targets"].append(data["targets"][0].copy())
    with pytest.raises(ValidationError):
        solve(data, context)
    data["targets"].pop()
    data["targets"][0]["price"] = Decimal("1.101201")
    with pytest.raises(ValidationError, match="tick grid"):
        solve(data, context)


def test_empty_fully_covered_source_is_distinct_from_missing_coverage():
    data, context = fixture()
    data["targets"] = []
    result = solve(data, context)
    assert result.reason == "NO_FRESH_UNCONSUMED_DIRECTIONAL_TARGET"
    assert result.geometry is None


def test_missing_cost_preserves_selected_target_without_searching_farther():
    data, context = fixture()
    context["costs"] = None
    result = solve(data, context)
    assert result.selected_target_id == "nearest"
    assert result.geometry.status == "WAIT"
    assert result.geometry.reason == "COST_EVIDENCE_UNBOUND"


def test_equal_price_tie_is_stable_and_evidence_change_changes_geometry_binding():
    data, context = fixture()
    data["targets"][1]["price"] = data["targets"][0]["price"]
    first = solve(data, context)
    data["targets"].reverse()
    assert solve(data, context) == first
    data["targets"][0]["evidence_hash"] = "sha256:" + "2" * 64
    second = solve(data, context)
    assert second.selected_target_id == first.selected_target_id
    assert second.geometry.request_hash != first.geometry.request_hash
