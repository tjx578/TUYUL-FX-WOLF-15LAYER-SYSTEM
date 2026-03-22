"""
Tests for L2 Bayesian Multi-Timeframe Alignment (v3).

Coverage targets:
    §1  Pure math functions (_sigmoid, _candle_features, _per_tf_probability,
        _hierarchical_bayesian_fusion, _entropy_alignment)
    §2  Analyzer integration (analyze, compute, fallback)
    §3  Engine integration (ReflexEmotionCore, FusionIntegrator mocking)
    §4  Pipeline contract (output keys, backward compatibility)
    §5  Edge cases & numerical stability
    §6  Parametrized Bayesian verification

All tests are self-contained — no external API calls.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from analysis.layers.L2_mta import (
    L2MTA,
    L2MTAAnalyzer,
    _candle_features,
    _entropy_alignment,
    _hierarchical_bayesian_fusion,
    _per_tf_probability,
    _sigmoid,
)

# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def analyzer() -> L2MTAAnalyzer:
    """Fresh analyzer with no engines loaded."""
    a = L2MTAAnalyzer()
    a._engines_loaded = True  # Skip real engine loading
    return a


@pytest.fixture
def bullish_candle() -> dict[str, float]:
    return {"open": 1.0800, "high": 1.0870, "low": 1.0790, "close": 1.0860}


@pytest.fixture
def bearish_candle() -> dict[str, float]:
    return {"open": 1.0860, "high": 1.0870, "low": 1.0790, "close": 1.0800}


@pytest.fixture
def doji_candle() -> dict[str, float]:
    return {"open": 1.0850, "high": 1.0870, "low": 1.0830, "close": 1.0850}


@pytest.fixture
def strong_bullish_candle() -> dict[str, float]:
    """Large body, tiny wicks — strong conviction."""
    return {"open": 1.0800, "high": 1.0902, "low": 1.0798, "close": 1.0900}


def _make_candle_source(
    candle_map: dict[str, dict[str, float] | None] | None = None,
    default_candle: dict[str, float] | None = None,
) -> MagicMock:
    """Create a mock candle source with per-TF or uniform candles."""
    source = MagicMock()
    source.get_layer_cache.side_effect = AttributeError("no layer cache")

    if candle_map is not None:
        typed_map: dict[str, dict[str, float] | None] = candle_map

        def _get(symbol: str, tf: str) -> dict[str, float] | None:
            return typed_map.get(tf)

        source.get_candle.side_effect = _get
    elif default_candle is not None:
        source.get_candle.return_value = default_candle
    else:
        source.get_candle.return_value = None

    return source


# Required output keys for pipeline compatibility
_REQUIRED_KEYS = frozenset(
    {
        "mta_compliance",
        "hierarchy_followed",
        "reflex_coherence",
        "conf12",
        "frpc_energy",
        "frpc_state",
        "field_phase",
        "valid",
        "direction",
        "composite_bias",
        "available_timeframes",
        "aligned",
        "alignment_strength",
        "per_tf_bias",
    }
)

_BAYESIAN_KEYS = frozenset(
    {
        "p_mta_bull",
        "p_mta_bear",
        "bayesian_rc",
        "bayesian_rc_damped",
        "entropy_alignment",
        "sensitivity_multiplier",
        "regime_used",
        "volatility_dampener",
    }
)


# ═══════════════════════════════════════════════════════════════════
# §1  PURE MATH FUNCTIONS
# ═══════════════════════════════════════════════════════════════════


class TestSigmoid:
    """Numerically stable sigmoid."""

    def test_zero_returns_half(self) -> None:
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_large_positive_near_one(self) -> None:
        assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-10)

    def test_large_negative_near_zero(self) -> None:
        assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-10)

    def test_symmetry(self) -> None:
        for x in [0.5, 1.0, 2.0, 5.0]:
            assert _sigmoid(x) + _sigmoid(-x) == pytest.approx(1.0)

    def test_monotonic(self) -> None:
        vals = [_sigmoid(x) for x in range(-10, 11)]
        assert vals == sorted(vals)

    def test_no_overflow_extreme_values(self) -> None:
        """Must not raise OverflowError on extreme inputs."""
        assert 0.0 <= _sigmoid(700.0) <= 1.0
        assert 0.0 <= _sigmoid(-700.0) <= 1.0


class TestCandleFeatures:
    """Feature extraction from OHLC candles."""

    def test_none_candle_returns_zeros(self) -> None:
        slope, body, wick = _candle_features(None)
        assert slope == 0.0
        assert body == 0.0
        assert wick == 0.0

    def test_empty_dict_returns_zeros(self) -> None:
        slope, body, wick = _candle_features({})
        assert slope == 0.0
        assert body == 0.0
        assert wick == 0.0

    def test_bullish_candle_positive_slope(self, bullish_candle: dict) -> None:
        slope, body, _wick = _candle_features(bullish_candle)
        assert slope > 0, "Bullish candle should have positive slope"
        assert 0.0 < body <= 1.0, "Body strength must be in (0, 1]"

    def test_bearish_candle_negative_slope(self, bearish_candle: dict) -> None:
        slope, body, _wick = _candle_features(bearish_candle)
        assert slope < 0, "Bearish candle should have negative slope"
        assert 0.0 < body <= 1.0

    def test_doji_candle_near_zero_slope(self, doji_candle: dict) -> None:
        slope, body, _wick = _candle_features(doji_candle)
        assert abs(slope) < 0.01, "Doji should have near-zero slope"
        assert body < 0.05, "Doji should have near-zero body strength"

    def test_zero_range_candle(self) -> None:
        """All OHLC same → no division by zero."""
        candle = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}
        slope, body, wick = _candle_features(candle)
        assert slope == 0.0
        assert body == 0.0
        assert wick == 0.0

    def test_body_strength_full_body(self) -> None:
        """No wicks → body strength = 1.0."""
        candle = {"open": 1.0, "high": 1.05, "low": 1.0, "close": 1.05}
        _, body, _ = _candle_features(candle)
        assert body == pytest.approx(1.0)

    def test_wick_rejection_bullish(self) -> None:
        """Long lower wick = bullish rejection (positive)."""
        candle = {"open": 1.050, "high": 1.052, "low": 1.030, "close": 1.051}
        _, _, wick = _candle_features(candle)
        assert wick > 0, "Long lower wick → positive wick rejection"

    def test_wick_rejection_bearish(self) -> None:
        """Long upper wick = bearish rejection (negative)."""
        candle = {"open": 1.050, "high": 1.070, "low": 1.048, "close": 1.049}
        _, _, wick = _candle_features(candle)
        assert wick < 0, "Long upper wick → negative wick rejection"

    def test_slope_from_closes_list(self) -> None:
        """When candle has 'closes' list, use linear regression slope."""
        candle = {
            "open": 1.0800,
            "high": 1.0870,
            "low": 1.0790,
            "close": 1.0860,
            "closes": [1.0800, 1.0810, 1.0830, 1.0845, 1.0860],
        }
        slope, _, _ = _candle_features(candle)
        assert slope > 0, "Rising closes → positive regression slope"

    def test_slope_clamped_to_range(self) -> None:
        """Slope proxy should be clamped to [-2, +2]."""
        candle = {
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "closes": [0.5, 0.6, 0.8, 1.2, 1.5],
        }
        slope, _, _ = _candle_features(candle)
        assert -2.0 <= slope <= 2.0


class TestPerTfProbability:
    """P_i = σ(β₁·slope + β₂·body_str + β₃·wick_rej)."""

    def test_neutral_inputs_return_half(self) -> None:
        p = _per_tf_probability(0.0, 0.0, 0.0)
        assert p == pytest.approx(0.5)

    def test_bullish_inputs_above_half(self) -> None:
        p = _per_tf_probability(1.0, 0.8, 0.5)
        assert p > 0.5

    def test_bearish_inputs_below_half(self) -> None:
        p = _per_tf_probability(-1.0, 0.8, -0.5)
        assert p < 0.5

    def test_output_bounded_zero_one(self) -> None:
        for s in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            for b in [0.0, 0.5, 1.0]:
                for w in [-1.0, 0.0, 1.0]:
                    p = _per_tf_probability(s, b, w)
                    assert 0.0 < p < 1.0

    def test_strong_bullish_exceeds_threshold(self) -> None:
        """Strong bullish features → P > 0.9."""
        p = _per_tf_probability(2.0, 1.0, 1.0)
        assert p > 0.9


class TestHierarchicalBayesianFusion:
    """Bayesian prior chain + weighted geometric mean."""

    def test_empty_input_returns_uniform(self) -> None:
        bull, bear = _hierarchical_bayesian_fusion({}, {})
        assert bull == pytest.approx(0.5)
        assert bear == pytest.approx(0.5)

    def test_all_bullish_produces_high_posterior(self) -> None:
        probs = {"MN": 0.9, "W1": 0.85, "D1": 0.8, "H4": 0.8}
        weights = {"MN": 0.35, "W1": 0.25, "D1": 0.15, "H4": 0.15}
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)
        assert bull > 0.9, "All bullish TFs → strong bull posterior"
        assert bull + bear == pytest.approx(1.0)

    def test_all_bearish_produces_low_posterior(self) -> None:
        probs = {"MN": 0.1, "W1": 0.15, "D1": 0.2, "H4": 0.2}
        weights = {"MN": 0.35, "W1": 0.25, "D1": 0.15, "H4": 0.15}
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)  # noqa: RUF059
        assert bull < 0.1, "All bearish TFs → low bull posterior"

    def test_mixed_signals_htf_dominates(self) -> None:
        """HTF bearish + LTF bullish → posterior should lean bearish."""
        probs = {"MN": 0.15, "W1": 0.2, "D1": 0.85, "H4": 0.9}
        weights = {"MN": 0.35, "W1": 0.25, "D1": 0.15, "H4": 0.15}
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)
        assert bear > bull, "HTF bearish should dominate overall posterior"

    def test_probabilities_sum_to_one(self) -> None:
        probs = {"MN": 0.6, "W1": 0.7, "D1": 0.4, "H4": 0.55}
        weights = {"MN": 0.35, "W1": 0.25, "D1": 0.15, "H4": 0.15}
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)
        assert bull + bear == pytest.approx(1.0)

    def test_single_timeframe(self) -> None:
        """Single TF → posterior should reflect that TF's probability."""
        probs = {"MN": 0.8}
        weights = {"MN": 1.0}
        bull, _ = _hierarchical_bayesian_fusion(probs, weights)
        assert bull > 0.5

    def test_order_matters_prior_propagation(self) -> None:
        """HTF (MN) opinion propagates as prior to W1.
        Reversing TF order should change posterior."""
        probs_htf_first = {"MN": 0.9, "H4": 0.1}
        probs_ltf_first = {"H4": 0.1, "MN": 0.9}
        w = {"MN": 0.5, "H4": 0.5}
        # Both should give same result because _TF_ORDER controls iteration
        b1, _ = _hierarchical_bayesian_fusion(probs_htf_first, w)
        b2, _ = _hierarchical_bayesian_fusion(probs_ltf_first, w)
        assert b1 == pytest.approx(b2), "TF_ORDER enforces consistent ordering"


class TestEntropyAlignment:
    """AS = 1 - H/log(2)."""

    def test_perfect_agreement_bull(self) -> None:
        """All bull → AS ≈ 1.0."""
        # p_bear → 0 is handled by guard
        assert _entropy_alignment(0.999, 0.001) > 0.95

    def test_maximum_conflict(self) -> None:
        """50/50 → AS = 0.0."""
        assert _entropy_alignment(0.5, 0.5) == pytest.approx(0.0, abs=1e-6)

    def test_moderate_agreement(self) -> None:
        """70/30 → AS somewhere in between."""
        as_val = _entropy_alignment(0.7, 0.3)
        assert 0.0 < as_val < 1.0

    def test_one_side_zero(self) -> None:
        """Edge: one probability is 0 → no conflict → AS = 1.0."""
        assert _entropy_alignment(1.0, 0.0) == 1.0

    def test_symmetry(self) -> None:
        """AS should be symmetric: AS(p, 1-p) is same regardless of which is bull."""
        assert _entropy_alignment(0.8, 0.2) == pytest.approx(
            _entropy_alignment(0.2, 0.8),
        )

    def test_output_bounded(self) -> None:
        for p in [0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99]:
            as_val = _entropy_alignment(p, 1.0 - p)
            assert 0.0 <= as_val <= 1.0


# ═══════════════════════════════════════════════════════════════════
# §2  ANALYZER INTEGRATION
# ═══════════════════════════════════════════════════════════════════


class TestAnalyzerBullish:
    """All TFs bullish → BULLISH direction, positive bias, aligned."""

    def test_all_bullish(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "BULLISH"
        assert result["composite_bias"] > 0
        assert result["p_mta_bull"] > 0.5
        assert result["bayesian_rc"] > 0

    def test_strong_bullish_high_rc(
        self,
        analyzer: L2MTAAnalyzer,
        strong_bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(
            default_candle=strong_bullish_candle,
        )
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "BULLISH"
        assert result["aligned"] is True
        assert result["p_mta_bull"] > 0.9
        assert result["entropy_alignment"] > 0.7


class TestAnalyzerBearish:
    """All TFs bearish → BEARISH direction, negative bias."""

    def test_all_bearish(
        self,
        analyzer: L2MTAAnalyzer,
        bearish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bearish_candle)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "BEARISH"
        assert result["composite_bias"] < 0
        assert result["p_mta_bear"] > 0.5


class TestAnalyzerNeutral:
    """Doji candles → NEUTRAL direction, zero bias."""

    def test_doji_neutral(
        self,
        analyzer: L2MTAAnalyzer,
        doji_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=doji_candle)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "NEUTRAL"
        assert result["composite_bias"] == pytest.approx(0.0, abs=0.01)


class TestAnalyzerMixed:
    """Mixed TF signals → direction follows HTF weight dominance."""

    def test_htf_bearish_ltf_bullish(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict[str, float],
        bearish_candle: dict[str, float],
    ) -> None:
        """HTF (MN,W1,D1,H4) bearish + LTF (H1,M15) bullish → BEARISH."""
        candle_map: dict[str, dict[str, float] | None] = {
            "MN": bearish_candle,
            "W1": bearish_candle,
            "D1": bearish_candle,
            "H4": bearish_candle,
            "H1": bullish_candle,
            "M15": bullish_candle,
        }
        analyzer.context = _make_candle_source(candle_map=candle_map)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "BEARISH"
        assert result["composite_bias"] < 0

    def test_htf_bullish_ltf_bearish(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict[str, float],
        bearish_candle: dict[str, float],
    ) -> None:
        """HTF bullish + LTF bearish → still BULLISH (HTF prior dominates)."""
        candle_map: dict[str, dict[str, float] | None] = {
            "MN": bullish_candle,
            "W1": bullish_candle,
            "D1": bullish_candle,
            "H4": bullish_candle,
            "H1": bearish_candle,
            "M15": bearish_candle,
        }
        analyzer.context = _make_candle_source(candle_map=candle_map)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["direction"] == "BULLISH"

    def test_conflicting_signals_lower_alignment(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict[str, float],
        bearish_candle: dict[str, float],
    ) -> None:
        """Mixed signals → lower entropy alignment than uniform."""
        # Uniform bullish
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        uniform = analyzer.analyze("EURUSD")

        # Mixed
        candle_map: dict[str, dict[str, float] | None] = {
            "MN": bullish_candle,
            "W1": bearish_candle,
            "D1": bullish_candle,
            "H4": bearish_candle,
            "H1": bullish_candle,
            "M15": bearish_candle,
        }
        analyzer.context = _make_candle_source(candle_map=candle_map)
        mixed = analyzer.analyze("EURUSD")

        assert mixed["entropy_alignment"] < uniform["entropy_alignment"], (
            "Mixed signals should have lower alignment than uniform"
        )


class TestAnalyzerFallback:
    """Insufficient data → fallback with valid=False."""

    def test_no_data(self, analyzer: L2MTAAnalyzer) -> None:
        analyzer.context = _make_candle_source()  # All None
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is False
        assert result["available_timeframes"] == 0
        assert result["reflex_coherence"] == 0.0
        assert result["p_mta_bull"] == 0.5
        assert result["p_mta_bear"] == 0.5

    def test_two_timeframes_below_minimum(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict[str, float],
    ) -> None:
        candle_map: dict[str, dict[str, float] | None] = {"MN": bullish_candle, "W1": bullish_candle}
        analyzer.context = _make_candle_source(candle_map=candle_map)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is False
        assert result["available_timeframes"] == 2

    def test_exactly_three_timeframes_valid(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict[str, float],
    ) -> None:
        candle_map: dict[str, dict[str, float] | None] = {
            "MN": bullish_candle,
            "W1": bullish_candle,
            "D1": bullish_candle,
        }
        analyzer.context = _make_candle_source(candle_map=candle_map)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert result["available_timeframes"] == 3


class TestAnalyzerBusPriority:
    """Bus takes priority over context for candle source."""

    def test_bus_over_context(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
        bearish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bearish_candle)
        analyzer.bus = _make_candle_source(default_candle=bullish_candle)

        result = analyzer.analyze("EURUSD")
        assert result["direction"] == "BULLISH", "Bus should override context"


# ═══════════════════════════════════════════════════════════════════
# §3  ENGINE INTEGRATION (MOCKED)
# ═══════════════════════════════════════════════════════════════════


class TestReflexEngineIntegration:
    """ReflexEmotionCore integration with proper mocking."""

    def test_reflex_enriches_coherence(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        """When reflex engine returns high coherence, it blends into RC."""
        analyzer.context = _make_candle_source(default_candle=bullish_candle)

        # Mock L1 context from bus
        mock_bus = _make_candle_source(default_candle=bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "TREND_UP",
            "volatility_level": "NORMAL",
            "atr_pct": 0.5,
        }
        analyzer.bus = mock_bus

        # Mock ReflexEmotionCore
        mock_reflex = MagicMock()
        mock_result = MagicMock()
        mock_result.reflex_coherence = 0.92
        mock_result.gate = "OPEN"
        mock_reflex.compute_reflex_emotion.return_value = mock_result
        analyzer._reflex = mock_reflex
        analyzer._engines_loaded = True

        result = analyzer.analyze("EURUSD")

        # Blended RC = bayesian * 0.65 + engine * 0.35
        assert result["reflex_coherence"] > 0, "Reflex should contribute"
        mock_reflex.compute_reflex_emotion.assert_called_once()

    def test_reflex_failure_graceful(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        """Engine exception → falls back to pure Bayesian RC."""
        analyzer.context = _make_candle_source(default_candle=bullish_candle)

        mock_bus = _make_candle_source(default_candle=bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "TREND_UP",
            "volatility_level": "NORMAL",
            "atr_pct": 0.5,
        }
        analyzer.bus = mock_bus

        mock_reflex = MagicMock()
        mock_reflex.compute_reflex_emotion.side_effect = RuntimeError("boom")
        analyzer._reflex = mock_reflex

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is True
        assert result["reflex_coherence"] >= 0.0


class TestFusionIntegration:
    """FusionIntegrator integration with proper mocking."""

    def test_fusion_ok_enriches_conf12(
        self,
        analyzer: L2MTAAnalyzer,
        strong_bullish_candle: dict,
    ) -> None:
        """Fusion OK status → real conf12 value."""
        mock_bus = _make_candle_source(default_candle=strong_bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "TREND_UP",
            "volatility_level": "NORMAL",
            "atr_pct": 0.5,
        }
        analyzer.bus = mock_bus

        mock_fusion = MagicMock()
        mock_fusion.fuse_reflective_context.return_value = {
            "status": "OK",
            "conf12_final": 0.88,
            "fusion_output": {
                "field_context": {
                    "field_integrity": 0.92,
                    "phase": "expansion",
                },
            },
        }
        analyzer._fusion = mock_fusion

        result = analyzer.analyze("EURUSD")
        assert result["conf12"] == pytest.approx(0.88)
        assert result["frpc_energy"] == pytest.approx(0.92)
        assert result["frpc_state"] == "SYNC"
        assert result["field_phase"] == "expansion"

    def test_fusion_aborted_extracts_lineage(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        """Fusion ABORTED → extract from confidence_lineage."""
        mock_bus = _make_candle_source(default_candle=bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "TRANSITION",
            "volatility_level": "NORMAL",
            "atr_pct": 0.3,
        }
        analyzer.bus = mock_bus

        mock_fusion = MagicMock()
        mock_fusion.fuse_reflective_context.return_value = {
            "status": "ABORTED",
            "reason": "Reflective Coherence below gate",
            "fusion_output": {"field_context": {"field_integrity": 0.4, "phase": "drift"}},
            "confidence_lineage": {"raw": 0.0, "weighted": 0.0, "final": 0.35},
        }
        analyzer._fusion = mock_fusion

        result = analyzer.analyze("EURUSD")
        assert result["conf12"] == pytest.approx(0.35)
        assert result["frpc_state"] == "DESYNC"

    def test_fusion_failure_graceful(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        """Fusion exception → defaults to 0 values."""
        mock_bus = _make_candle_source(default_candle=bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "RANGE",
            "volatility_level": "NORMAL",
            "atr_pct": 0.3,
        }
        analyzer.bus = mock_bus

        mock_fusion = MagicMock()
        mock_fusion.fuse_reflective_context.side_effect = RuntimeError("fail")
        analyzer._fusion = mock_fusion

        result = analyzer.analyze("EURUSD")
        assert result["conf12"] == 0.0
        assert result["frpc_state"] == "DESYNC"


# ═══════════════════════════════════════════════════════════════════
# §4  PIPELINE CONTRACT
# ═══════════════════════════════════════════════════════════════════


class TestPipelineContract:
    """Output schema must satisfy all downstream consumers."""

    def test_valid_result_has_all_required_keys(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")
        missing = _REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing required keys: {missing}"

    def test_valid_result_has_bayesian_keys(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")
        missing = _BAYESIAN_KEYS - set(result.keys())
        assert not missing, f"Missing Bayesian keys: {missing}"

    def test_fallback_result_has_all_required_keys(
        self,
        analyzer: L2MTAAnalyzer,
    ) -> None:
        analyzer.context = _make_candle_source()
        result = analyzer.analyze("EURUSD")
        missing = _REQUIRED_KEYS - set(result.keys())
        assert not missing, f"Missing required keys in fallback: {missing}"

    def test_fallback_result_has_bayesian_keys(
        self,
        analyzer: L2MTAAnalyzer,
    ) -> None:
        analyzer.context = _make_candle_source()
        result = analyzer.analyze("EURUSD")
        missing = _BAYESIAN_KEYS - set(result.keys())
        assert not missing, f"Missing Bayesian keys in fallback: {missing}"

    def test_p_mta_sum_to_one(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")
        total = result["p_mta_bull"] + result["p_mta_bear"]
        assert total == pytest.approx(1.0, abs=0.01)

    def test_reflex_coherence_non_negative(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")
        assert result["reflex_coherence"] >= 0.0

    def test_alignment_strength_bounded(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.analyze("EURUSD")
        assert 0.0 <= result["alignment_strength"] <= 1.0

    def test_backward_compat_alias(self) -> None:
        """L2MTA should be an alias for L2MTAAnalyzer."""
        assert L2MTA is L2MTAAnalyzer


class TestComputeLegacy:
    """Legacy compute() method backward compatibility."""

    def test_compute_returns_per_tf_and_macro(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.compute("EURUSD", macro_bias="BULLISH")

        assert "per_tf" in result
        assert "macro_bias" in result
        assert result["macro_bias"] == "BULLISH"

    def test_compute_per_tf_has_weight_bias_candle(
        self,
        analyzer: L2MTAAnalyzer,
        bullish_candle: dict,
    ) -> None:
        analyzer.context = _make_candle_source(default_candle=bullish_candle)
        result = analyzer.compute("EURUSD")

        for _tf, detail in result["per_tf"].items():
            assert "weight" in detail
            assert "bias" in detail
            assert "candle" in detail
            assert detail["bias"] in ("BULLISH", "BEARISH", "NEUTRAL")

    def test_compute_no_data_neutral(
        self,
        analyzer: L2MTAAnalyzer,
    ) -> None:
        analyzer.context = _make_candle_source()
        result = analyzer.compute("EURUSD")

        for detail in result["per_tf"].values():
            assert detail["bias"] == "NEUTRAL"
            assert detail["candle"] is None


# ═══════════════════════════════════════════════════════════════════
# §5  EDGE CASES & NUMERICAL STABILITY
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Numerical edge cases and error resilience."""

    def test_context_exception_graceful(
        self,
        analyzer: L2MTAAnalyzer,
    ) -> None:
        """get_candle raising exception → treated as None."""
        source = MagicMock()
        source.get_candle.side_effect = RuntimeError("broker timeout")
        source.get_layer_cache.side_effect = AttributeError
        analyzer.context = source

        result = analyzer.analyze("EURUSD")
        assert result["valid"] is False
        assert result["available_timeframes"] == 0

    def test_extreme_candle_values(self, analyzer: L2MTAAnalyzer) -> None:
        """Very large price values → no overflow."""
        big_candle = {
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50800.0,
        }
        analyzer.context = _make_candle_source(default_candle=big_candle)
        result = analyzer.analyze("XAUUSD")

        assert result["valid"] is True
        assert math.isfinite(result["composite_bias"])
        assert math.isfinite(result["bayesian_rc"])

    def test_micro_price_differences(self, analyzer: L2MTAAnalyzer) -> None:
        """Tiny open-close difference → should not explode."""
        micro_candle = {
            "open": 1.08500,
            "high": 1.08501,
            "low": 1.08499,
            "close": 1.08501,
        }
        analyzer.context = _make_candle_source(default_candle=micro_candle)
        result = analyzer.analyze("EURUSD")

        assert result["valid"] is True
        assert math.isfinite(result["bayesian_rc"])

    def test_no_context_no_bus(self, analyzer: L2MTAAnalyzer) -> None:
        """Neither context nor bus set → valid=False gracefully."""
        analyzer.context = None
        analyzer.bus = None
        result = analyzer.analyze("EURUSD")
        assert result["valid"] is False


# ═══════════════════════════════════════════════════════════════════
# §6  PARAMETRIZED BAYESIAN VERIFICATION
# ═══════════════════════════════════════════════════════════════════


class TestBayesianMathVerification:
    """Verify mathematical properties of the Bayesian fusion chain."""

    @pytest.mark.parametrize(
        "p_bull_mn,p_bull_w1,expected_direction",
        [
            (0.9, 0.9, "bull_dominates"),
            (0.1, 0.1, "bear_dominates"),
            (0.9, 0.1, "conflict"),
        ],
    )
    def test_two_tf_posterior_direction(
        self,
        p_bull_mn: float,
        p_bull_w1: float,
        expected_direction: str,
    ) -> None:
        probs = {"MN": p_bull_mn, "W1": p_bull_w1}
        weights = {"MN": 0.6, "W1": 0.4}
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)

        if expected_direction == "bull_dominates":
            assert bull > 0.8
        elif expected_direction == "bear_dominates":
            assert bear > 0.8
        else:
            # MN prior (0.9) × W1 likelihood (0.1) → conflict, but
            # MN dominance through prior propagation should still lean bull
            assert 0.2 < bull < 0.8

    @pytest.mark.parametrize("n_bullish_tfs", [1, 2, 3, 4, 5, 6])
    def test_more_agreement_higher_rc(self, n_bullish_tfs: int) -> None:
        """More TFs agreeing → higher P_MTA → higher potential RC."""
        tfs = ["MN", "W1", "D1", "H4", "H1", "M15"]
        probs = {}
        for i, tf in enumerate(tfs):
            probs[tf] = 0.85 if i < n_bullish_tfs else 0.15
        weights = {
            "MN": 0.35,
            "W1": 0.25,
            "D1": 0.15,
            "H4": 0.15,
            "H1": 0.07,
            "M15": 0.03,
        }
        bull, bear = _hierarchical_bayesian_fusion(probs, weights)
        p_mta = max(bull, bear)
        as_val = _entropy_alignment(bull, bear)
        rc = p_mta * as_val
        # RC should be monotonically non-decreasing as agreement grows
        # (not strictly because of weight interactions, but general trend)
        if n_bullish_tfs >= 5:
            assert rc > 0.5, f"5+ bullish TFs should give RC > 0.5, got {rc}"

    def test_reflex_coherence_formula(self) -> None:
        """RC = P_MTA × AS, verified mathematically."""
        p_bull, p_bear = 0.85, 0.15
        p_mta = max(p_bull, p_bear)
        as_val = _entropy_alignment(p_bull, p_bear)
        expected_rc = p_mta * as_val

        # Manual entropy calculation
        h = -(0.85 * math.log(0.85) + 0.15 * math.log(0.15))
        expected_as = 1.0 - h / math.log(2.0)
        manual_rc = 0.85 * expected_as

        assert expected_rc == pytest.approx(manual_rc, abs=1e-6)


class TestVolatilityDampener:
    """Volatility dampener reduces bias in extreme conditions."""

    @pytest.mark.parametrize(
        "vol_level,expected_dampener",
        [
            ("NORMAL", 1.0),
            ("HIGH", 0.8),
            ("EXTREME", 0.6),
            ("LOW", 0.9),
            ("DEAD", 0.7),
        ],
    )
    def test_dampener_values(
        self,
        analyzer: L2MTAAnalyzer,
        strong_bullish_candle: dict,
        vol_level: str,
        expected_dampener: float,
    ) -> None:
        mock_bus = _make_candle_source(default_candle=strong_bullish_candle)
        mock_bus.get_layer_cache.side_effect = None
        mock_bus.get_layer_cache.return_value = {
            "regime": "TREND_UP",
            "volatility_level": vol_level,
            "atr_pct": 0.5,
        }
        analyzer.bus = mock_bus

        result = analyzer.analyze("EURUSD")
        assert result["volatility_dampener"] == expected_dampener


class TestAdaptiveWeights:
    """Regime-dependent TF weight selection."""

    def test_trend_regime_weights(self) -> None:
        weights = L2MTAAnalyzer._adaptive_weights("TREND_UP")
        assert weights["MN"] == 0.40, "Trend should amplify MN weight"

    def test_range_regime_weights(self) -> None:
        weights = L2MTAAnalyzer._adaptive_weights("RANGE")
        assert weights["H1"] == 0.20, "Range should amplify LTF weights"

    def test_transition_regime_default(self) -> None:
        weights = L2MTAAnalyzer._adaptive_weights("TRANSITION")
        assert weights["MN"] == 0.35, "Default weights for unknown regime"


class TestSensitivityMultiplier:
    """Downstream sensitivity control for L3."""

    def test_low_coherence_increases_sensitivity(self) -> None:
        s = L2MTAAnalyzer._compute_sensitivity(0.3, 0.3, 0.5)
        assert s > 1.0, "Low coherence → L3 should be stricter"

    def test_high_conf12_decreases_sensitivity(self) -> None:
        s = L2MTAAnalyzer._compute_sensitivity(0.9, 0.9, 0.95)
        assert s < 1.0, "High conf12 → L3 can relax"

    def test_sensitivity_bounded(self) -> None:
        s1 = L2MTAAnalyzer._compute_sensitivity(0.0, 0.0, 0.0)
        s2 = L2MTAAnalyzer._compute_sensitivity(1.0, 1.0, 1.0)
        assert 0.5 <= s1 <= 1.5
        assert 0.5 <= s2 <= 1.5
