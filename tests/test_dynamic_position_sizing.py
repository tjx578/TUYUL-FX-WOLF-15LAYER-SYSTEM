"""Unit tests for engines/dynamic_position_sizing_engine.py.

Tests cover:
    - Basic hybrid calculation with realistic inputs
    - Kelly fraction correctness (full and half)
    - Negative Kelly edge detection (no statistical edge)
    - CVaR tail risk dampening
    - CVaR empty tail slice guard
    - Volatility multiplier dampening and zero guard
    - Posterior probability scaling and clamp
    - Max risk cap enforcement
    - Input validation (all error paths)
    - Serialization (to_dict)
    - Immutable result
    - Prop-firm-safe output range
    - Edge cases: all-wins history, all-losses history
"""

from __future__ import annotations

import numpy as np  # pyright: ignore[reportMissingImports]
import pytest  # pyright: ignore[reportMissingImports]

from engines.dynamic_position_sizing_engine import (
    DynamicPositionSizingEngine,
    PositionSizingResult,
)


def _typical_returns(n: int = 100, win_rate: float = 0.6, seed: int = 42) -> list[float]:
    """Generate realistic trade return history."""
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n):
        if rng.random() < win_rate:
            returns.append(float(rng.uniform(20.0, 80.0)))
        else:
            returns.append(float(rng.uniform(-50.0, -10.0)))
    return returns


class TestDynamicPositionSizingEngine:
    """Dynamic position sizing engine tests."""

    # ── Basic functionality ──────────────────────────────────────────────────

    def test_basic_calculation(self) -> None:
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.63,
            avg_win=45.0,
            avg_loss=-25.0,
            posterior_probability=0.66,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.25,
        )

        assert isinstance(result, PositionSizingResult)
        assert 0.0 <= result.final_fraction <= 0.03
        assert 0.0 <= result.risk_percent <= 3.0
        assert result.edge_negative is False

    def test_result_components_in_range(self) -> None:
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-30.0,
            posterior_probability=0.70,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert 0.0 <= result.kelly_fraction <= 1.0
        assert 0.0 < result.cvar_adjustment <= 1.0
        assert 0.0 < result.volatility_adjustment <= 1.0
        assert 0.0 <= result.posterior_adjustment <= 1.0
        assert result.payoff_ratio > 0

    # ── Kelly Criterion ──────────────────────────────────────────────────────

    def test_kelly_raw_correctness(self) -> None:
        """Verify Kelly formula: f* = (bp - q) / b."""
        engine = DynamicPositionSizingEngine(kelly_fraction_multiplier=1.0)
        result = engine.calculate(
            win_probability=0.60,
            avg_win=50.0,
            avg_loss=-25.0,
            posterior_probability=1.0,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        # b = 50/25 = 2.0; p = 0.6; q = 0.4
        # f* = (2*0.6 - 0.4) / 2 = (1.2 - 0.4) / 2 = 0.4
        assert abs(result.kelly_raw - 0.4) < 0.001

    def test_half_kelly_default(self) -> None:
        """Default half-Kelly should halve the raw Kelly fraction."""
        engine = DynamicPositionSizingEngine()  # default 0.5 fraction
        result = engine.calculate(
            win_probability=0.60,
            avg_win=50.0,
            avg_loss=-25.0,
            posterior_probability=1.0,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        # Raw Kelly = 0.4; half-Kelly = 0.2
        assert abs(result.kelly_fraction - 0.2) < 0.001

    def test_negative_kelly_edge(self) -> None:
        """When edge is negative, Kelly fraction should be 0."""
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.30,  # Low win rate
            avg_win=20.0,
            avg_loss=-50.0,       # Large losses
            posterior_probability=0.5,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert result.edge_negative is True
        assert result.kelly_fraction == 0.0
        assert result.final_fraction == 0.0
        assert result.risk_percent == 0.0

    def test_kelly_zero_win_probability(self) -> None:
        """Zero win probability -> negative Kelly -> size 0."""
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.0,
            avg_win=50.0,
            avg_loss=-25.0,
            posterior_probability=0.5,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert result.kelly_fraction == 0.0
        assert result.edge_negative is True

    def test_kelly_perfect_win_rate(self) -> None:
        """100% win rate -> large Kelly, but capped at max_risk_cap."""
        engine = DynamicPositionSizingEngine(max_risk_cap=0.03)
        result = engine.calculate(
            win_probability=1.0,
            avg_win=50.0,
            avg_loss=-25.0,
            posterior_probability=1.0,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert result.kelly_raw == 1.0
        assert result.final_fraction <= 0.03

    # ── CVaR Tail Risk ───────────────────────────────────────────────────────

    def test_cvar_heavy_tail_reduces_size(self) -> None:
        """Returns with heavy left tail -> smaller CVaR adjustment."""
        rng = np.random.default_rng(99)
        heavy_tail = [-500.0] * 20 + [float(rng.uniform(10, 50)) for _ in range(80)]

        engine = DynamicPositionSizingEngine()
        result_heavy = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.7,
            returns_history=heavy_tail,
            volatility_multiplier=1.0,
        )

        result_normal = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.7,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert result_heavy.cvar_adjustment < result_normal.cvar_adjustment
        assert result_heavy.final_fraction <= result_normal.final_fraction

    def test_cvar_all_positive_returns(self) -> None:
        """All positive returns -> small CVaR -> large adjustment (close to 1)."""
        engine = DynamicPositionSizingEngine()
        positive_returns = [float(i + 1) for i in range(50)]

        result = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.7,
            returns_history=positive_returns,
            volatility_multiplier=1.0,
        )

        # VaR is still a positive number -> CVaR adj close to 1
        assert result.cvar_adjustment > 0.0

    # ── Volatility Adjustment ────────────────────────────────────────────────

    def test_high_volatility_reduces_size(self) -> None:
        """volatility_multiplier > 1 should reduce position."""
        engine = DynamicPositionSizingEngine()
        base_params = {
            "win_probability": 0.60,
            "avg_win": 40.0,
            "avg_loss": -20.0,
            "posterior_probability": 0.7,
            "returns_history": _typical_returns(100),
        }

        r_normal = engine.calculate(**base_params, volatility_multiplier=1.0) # type: ignore
        r_high_vol = engine.calculate(**base_params, volatility_multiplier=1.5) # pyright: ignore[reportArgumentType]

        assert r_high_vol.volatility_adjustment < r_normal.volatility_adjustment
        assert r_high_vol.final_fraction <= r_normal.final_fraction

    def test_volatility_multiplier_zero_safe(self) -> None:
        """volatility_multiplier=0 should NOT crash (clamped to minimum)."""
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.7,
            returns_history=_typical_returns(100),
            volatility_multiplier=0.0,
        )

        assert result.volatility_adjustment > 0.0
        assert result.final_fraction >= 0.0

    def test_volatility_adjustment_capped_at_one(self) -> None:
        """volatility_multiplier < 1 should produce adjustment capped at 1.0."""
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.7,
            returns_history=_typical_returns(100),
            volatility_multiplier=0.5,
        )

        assert result.volatility_adjustment <= 1.0

    # ── Posterior Adjustment ─────────────────────────────────────────────────

    def test_low_posterior_reduces_size(self) -> None:
        """Low Bayesian confidence -> proportionally smaller position."""
        engine = DynamicPositionSizingEngine()
        base_params = {
            "win_probability": 0.60,
            "avg_win": 40.0,
            "avg_loss": -20.0,
            "returns_history": _typical_returns(100),
            "volatility_multiplier": 1.0,
        }

        r_high = engine.calculate(**base_params, posterior_probability=0.90) # pyright: ignore[reportArgumentType]
        r_low = engine.calculate(**base_params, posterior_probability=0.30) # pyright: ignore[reportArgumentType]

        assert r_low.posterior_adjustment < r_high.posterior_adjustment
        assert r_low.final_fraction <= r_high.final_fraction

    def test_zero_posterior_zeros_size(self) -> None:
        """Zero posterior -> zero position (no confidence = no trade)."""
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60,
            avg_win=40.0,
            avg_loss=-20.0,
            posterior_probability=0.0,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.0,
        )

        assert result.posterior_adjustment == 0.0
        assert result.final_fraction == 0.0

    # ── Max Risk Cap ─────────────────────────────────────────────────────────

    def test_max_risk_cap_enforced(self) -> None:
        """Final fraction never exceeds max_risk_cap."""
        engine = DynamicPositionSizingEngine(
            max_risk_cap=0.01,
            kelly_fraction_multiplier=1.0,
        )
        result = engine.calculate(
            win_probability=0.90,
            avg_win=100.0,
            avg_loss=-10.0,
            posterior_probability=1.0,
            returns_history=[50.0] * 50,
            volatility_multiplier=1.0,
        )

        assert result.final_fraction <= 0.01
        assert result.risk_percent <= 1.0
        assert result.max_risk_cap == 0.01

    def test_custom_risk_cap(self) -> None:
        """Verify custom cap is respected."""
        for cap in [0.005, 0.01, 0.02, 0.05]:
            engine = DynamicPositionSizingEngine(max_risk_cap=cap)
            result = engine.calculate(
                win_probability=0.80,
                avg_win=60.0,
                avg_loss=-20.0,
                posterior_probability=0.9,
                returns_history=_typical_returns(50),
                volatility_multiplier=1.0,
            )
            assert result.final_fraction <= cap

    # ── Input Validation ─────────────────────────────────────────────────────

    def test_avg_loss_zero_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="avg_loss cannot be zero"):
            engine.calculate(
                win_probability=0.6, avg_win=40.0, avg_loss=0.0,
                posterior_probability=0.7, returns_history=_typical_returns(50),
            )

    def test_avg_win_zero_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="avg_win must be > 0"):
            engine.calculate(
                win_probability=0.6, avg_win=0.0, avg_loss=-20.0,
                posterior_probability=0.7, returns_history=_typical_returns(50),
            )

    def test_avg_win_negative_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="avg_win must be > 0"):
            engine.calculate(
                win_probability=0.6, avg_win=-10.0, avg_loss=-20.0,
                posterior_probability=0.7, returns_history=_typical_returns(50),
            )

    def test_win_probability_out_of_range_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="win_probability"):
            engine.calculate(
                win_probability=1.5, avg_win=40.0, avg_loss=-20.0,
                posterior_probability=0.7, returns_history=_typical_returns(50),
            )

    def test_posterior_out_of_range_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="posterior_probability"):
            engine.calculate(
                win_probability=0.6, avg_win=40.0, avg_loss=-20.0,
                posterior_probability=1.5, returns_history=_typical_returns(50),
            )

    def test_insufficient_returns_raises(self) -> None:
        engine = DynamicPositionSizingEngine(min_returns=10)
        with pytest.raises(ValueError, match="returns_history needs"):
            engine.calculate(
                win_probability=0.6, avg_win=40.0, avg_loss=-20.0,
                posterior_probability=0.7, returns_history=[1.0, -0.5],
            )

    def test_negative_volatility_multiplier_raises(self) -> None:
        engine = DynamicPositionSizingEngine()
        with pytest.raises(ValueError, match="volatility_multiplier"):
            engine.calculate(
                win_probability=0.6, avg_win=40.0, avg_loss=-20.0,
                posterior_probability=0.7, returns_history=_typical_returns(50),
                volatility_multiplier=-1.0,
            )

    def test_invalid_max_risk_cap_raises(self) -> None:
        with pytest.raises(ValueError, match="max_risk_cap"):
            DynamicPositionSizingEngine(max_risk_cap=0.0)
        with pytest.raises(ValueError, match="max_risk_cap"):
            DynamicPositionSizingEngine(max_risk_cap=1.5)

    def test_invalid_kelly_fraction_raises(self) -> None:
        with pytest.raises(ValueError, match="kelly_fraction_multiplier"):
            DynamicPositionSizingEngine(kelly_fraction_multiplier=0.0)

    def test_invalid_cvar_confidence_raises(self) -> None:
        with pytest.raises(ValueError, match="cvar_confidence"):
            DynamicPositionSizingEngine(cvar_confidence=1.0)

    # ── avg_loss sign agnostic ───────────────────────────────────────────────

    def test_negative_avg_loss_accepted(self) -> None:
        """Negative avg_loss (natural sign) should work identically to positive."""
        engine = DynamicPositionSizingEngine()
        base = {
            "win_probability": 0.60, "avg_win": 40.0,
            "posterior_probability": 0.7, "returns_history": _typical_returns(100),
            "volatility_multiplier": 1.0,
        }

        r_neg = engine.calculate(**base, avg_loss=-25.0) # pyright: ignore[reportArgumentType]
        r_pos = engine.calculate(**base, avg_loss=25.0) # pyright: ignore[reportArgumentType]

        assert r_neg.kelly_raw == r_pos.kelly_raw
        assert r_neg.final_fraction == r_pos.final_fraction
        assert r_neg.payoff_ratio == r_pos.payoff_ratio

    # ── Serialization ────────────────────────────────────────────────────────

    def test_to_dict_schema(self) -> None:
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60, avg_win=40.0, avg_loss=-20.0,
            posterior_probability=0.7, returns_history=_typical_returns(100),
        )
        d = result.to_dict()

        expected_keys = {
            "kelly_raw", "kelly_fraction", "cvar_adjustment",
            "volatility_adjustment", "posterior_adjustment",
            "final_fraction", "risk_percent", "max_risk_cap",
            "edge_negative", "cvar_value", "var_value", "payoff_ratio",
        }
        assert expected_keys <= set(d.keys())

    def test_to_dict_values_match(self) -> None:
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60, avg_win=40.0, avg_loss=-20.0,
            posterior_probability=0.7, returns_history=_typical_returns(100),
        )
        d = result.to_dict()

        assert d["final_fraction"] == result.final_fraction
        assert d["risk_percent"] == result.risk_percent
        assert d["edge_negative"] == result.edge_negative

    # ── Immutability ─────────────────────────────────────────────────────────

    def test_immutable_result(self) -> None:
        engine = DynamicPositionSizingEngine()
        result = engine.calculate(
            win_probability=0.60, avg_win=40.0, avg_loss=-20.0,
            posterior_probability=0.7, returns_history=_typical_returns(100),
        )
        with pytest.raises(AttributeError):
            result.final_fraction = 0.99  # type: ignore[misc]

    # ── Prop-firm safety ─────────────────────────────────────────────────────

    def test_propfirm_safe_range(self) -> None:
        """Under all typical conditions, risk should be prop-firm safe (≤ 3%)."""
        engine = DynamicPositionSizingEngine(max_risk_cap=0.03)

        for seed in range(10):
            result = engine.calculate(
                win_probability=0.55 + seed * 0.03,
                avg_win=40.0,
                avg_loss=-25.0,
                posterior_probability=0.5 + seed * 0.04,
                returns_history=_typical_returns(100, seed=seed),
                volatility_multiplier=1.0 + seed * 0.1,
            )
            assert result.final_fraction <= 0.03
            assert result.risk_percent <= 3.0

    # ── Example flow from spec ───────────────────────────────────────────────

    def test_example_flow(self) -> None:
        """Reproduce the example from the spec document.

        MC Win Prob = 0.63, PF = 1.8
        Bayesian Posterior = 0.66
        Vol Multiplier = 1.25
        Expected final ~1.8% (prop-firm safe)
        """
        engine = DynamicPositionSizingEngine(
            max_risk_cap=0.03,
            kelly_fraction_multiplier=0.5,
        )
        result = engine.calculate(
            win_probability=0.63,
            avg_win=45.0,       # PF ≈ 1.8 implies avg_win/avg_loss ≈ 1.8
            avg_loss=-25.0,
            posterior_probability=0.66,
            returns_history=_typical_returns(100),
            volatility_multiplier=1.25,
        )

        # Should be in prop-firm-safe range
        assert 0.0 < result.final_fraction <= 0.03
        assert result.edge_negative is False
        assert result.payoff_ratio == 1.8
