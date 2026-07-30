"""Boundary and instrument coverage for the versioned execution policy.

The floor decision is a strategy rule, so each policy's behaviour is pinned
independently: the legacy 6-pip rule and the canonical Hybrid V3 10-pip rule
both stay reproducible, and neither silently inherits the other's numbers.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_execution_policy import (
    EXECUTION_POLICIES,
    FX_LEGACY_6P_V1,
    FX_MIN_TARGET_10P_V1,
    HYBRID_V3_EXECUTION_POLICY,
    LEGACY_REPLAY_EXECUTION_POLICY,
    resolve_execution_policy,
)

JPY_PIP = 0.01
FX_PIP = 0.0001
# 5 * 0.001 = 0.005 price = 0.5 JPY pips, well below every structural floor
# under test so the structural floor is the binding constraint.
LOW_SPREAD_JPY = 0.001


def _assess(policy, symbol, target_pips, *, pip_size=JPY_PIP, spread_price=LOW_SPREAD_JPY):
    return policy.assess_target(
        symbol,
        target_distance_price=target_pips * pip_size,
        pip_size=pip_size,
        spread_price=spread_price,
    )


# --------------------------------------------------------------------------
# registry / resolution
# --------------------------------------------------------------------------


def test_both_policies_are_registered_and_distinct():
    assert set(EXECUTION_POLICIES) == {"FX_MIN_TARGET_10P_V1", "FX_LEGACY_6P_V1"}
    assert FX_MIN_TARGET_10P_V1.minimum_fx_target_pips == 10.0
    assert FX_LEGACY_6P_V1.minimum_fx_target_pips == 6.0
    assert HYBRID_V3_EXECUTION_POLICY is FX_MIN_TARGET_10P_V1
    assert LEGACY_REPLAY_EXECUTION_POLICY is FX_LEGACY_6P_V1


def test_both_policies_keep_minimum_rr_at_1_5():
    assert FX_MIN_TARGET_10P_V1.minimum_rr == 1.5
    assert FX_LEGACY_6P_V1.minimum_rr == 1.5


def test_unresolved_policy_returns_none_rather_than_guessing(monkeypatch):
    monkeypatch.delenv("STRATEGY_5SCR_EXECUTION_POLICY_ID", raising=False)
    assert resolve_execution_policy() is None
    assert resolve_execution_policy("NOT_A_REAL_POLICY") is None


def test_policy_resolves_from_env(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_EXECUTION_POLICY_ID", "FX_MIN_TARGET_10P_V1")
    assert resolve_execution_policy() is FX_MIN_TARGET_10P_V1


def test_explicit_policy_id_overrides_env(monkeypatch):
    monkeypatch.setenv("STRATEGY_5SCR_EXECUTION_POLICY_ID", "FX_MIN_TARGET_10P_V1")
    assert resolve_execution_policy("FX_LEGACY_6P_V1") is FX_LEGACY_6P_V1


def test_policies_are_frozen_so_a_floor_cannot_be_mutated_in_place():
    with pytest.raises(ValidationError):
        FX_MIN_TARGET_10P_V1.minimum_fx_target_pips = 4.0  # type: ignore[misc]


# --------------------------------------------------------------------------
# structural floor boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target_pips", "expected"),
    [
        (9.2, "BELOW_STRUCTURAL_FLOOR"),
        (9.99, "BELOW_STRUCTURAL_FLOOR"),
        (10.0, "PASS"),
        (10.1, "PASS"),
        (12.0, "PASS"),
    ],
)
def test_v3_structural_floor_boundary(target_pips, expected):
    assessment = _assess(FX_MIN_TARGET_10P_V1, "CHFJPY", target_pips)

    assert assessment.target_floor_status == expected
    assert assessment.minimum_target_pips == pytest.approx(10.0)
    assert assessment.target_distance_pips == pytest.approx(target_pips)


@pytest.mark.parametrize(
    ("target_pips", "expected"),
    [(5.9, "BELOW_STRUCTURAL_FLOOR"), (6.0, "PASS"), (9.2, "PASS")],
)
def test_legacy_structural_floor_boundary(target_pips, expected):
    assessment = _assess(FX_LEGACY_6P_V1, "CHFJPY", target_pips)

    assert assessment.target_floor_status == expected
    assert assessment.minimum_target_pips == pytest.approx(6.0)


def test_jpy_pip_arithmetic_is_correct():
    """0.092 price on a 0.01-pip pair is 9.2 pips, not 92 or 0.92."""
    assessment = FX_MIN_TARGET_10P_V1.assess_target(
        "CHFJPY",
        target_distance_price=0.092,
        pip_size=JPY_PIP,
        spread_price=LOW_SPREAD_JPY,
    )

    assert assessment.target_distance_pips == pytest.approx(9.2)
    assert assessment.target_floor_status == "BELOW_STRUCTURAL_FLOOR"


def test_five_digit_fx_pip_arithmetic_is_correct():
    assessment = FX_MIN_TARGET_10P_V1.assess_target(
        "EURUSD",
        target_distance_price=0.0012,
        pip_size=FX_PIP,
        spread_price=0.00001,
    )

    assert assessment.target_distance_pips == pytest.approx(12.0)
    assert assessment.target_floor_status == "PASS"


# --------------------------------------------------------------------------
# broker cost floor
# --------------------------------------------------------------------------


def test_cost_floor_can_bind_above_the_structural_floor():
    # spread 0.026 * 5 = 0.13 price = 13 JPY pips > the 10-pip structural floor
    assessment = _assess(FX_MIN_TARGET_10P_V1, "CHFJPY", 12.0, spread_price=0.026)

    assert assessment.broker_cost_floor_pips == pytest.approx(13.0)
    assert assessment.required_target_pips == pytest.approx(13.0)
    assert assessment.target_floor_status == "BELOW_COST_FLOOR"


def test_required_target_is_the_max_of_both_floors():
    tight = _assess(FX_MIN_TARGET_10P_V1, "CHFJPY", 20.0, spread_price=0.001)
    wide = _assess(FX_MIN_TARGET_10P_V1, "CHFJPY", 20.0, spread_price=0.026)

    assert tight.required_target_pips == pytest.approx(10.0)  # structural binds
    assert wide.required_target_pips == pytest.approx(13.0)  # cost binds
    assert tight.passed and wide.passed


# --------------------------------------------------------------------------
# instrument separation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", ["XAUUSD", "XAGUSD"])
def test_metals_do_not_inherit_the_fx_ten_pip_rule(symbol):
    """Metals are quoted in price; the FX pip floor must not apply to them."""
    policy = FX_MIN_TARGET_10P_V1
    floor = policy.execution_floor(symbol, pip_size=0.01, spread_price=0.05)

    assert policy.is_metal(symbol)
    # 5.0 absolute price, not 10 * 0.01 = 0.10
    assert floor == pytest.approx(5.0)


def test_metal_floor_is_identical_across_policies():
    """The 6->10 pip change is an FX rule and must not move the metal floor."""
    legacy = FX_LEGACY_6P_V1.execution_floor("XAUUSD", pip_size=0.01, spread_price=0.05)
    v3 = FX_MIN_TARGET_10P_V1.execution_floor("XAUUSD", pip_size=0.01, spread_price=0.05)

    assert legacy == v3 == pytest.approx(5.0)


def test_fx_floor_differs_across_policies():
    legacy = FX_LEGACY_6P_V1.execution_floor("CHFJPY", pip_size=JPY_PIP, spread_price=LOW_SPREAD_JPY)
    v3 = FX_MIN_TARGET_10P_V1.execution_floor("CHFJPY", pip_size=JPY_PIP, spread_price=LOW_SPREAD_JPY)

    assert legacy == pytest.approx(0.06)
    assert v3 == pytest.approx(0.10)


def test_assess_target_rejects_non_positive_pip_size():
    with pytest.raises(ValueError, match="pip_size must be positive"):
        FX_MIN_TARGET_10P_V1.assess_target("CHFJPY", target_distance_price=0.1, pip_size=0.0, spread_price=0.001)
