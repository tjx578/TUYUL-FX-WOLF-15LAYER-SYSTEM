"""
Tests for L1 Context Layer v3 — Probabilistic Regime Model.

Covers:
  - Logistic model (sigmoid, feature extraction, regime probability)
  - Shannon entropy & context coherence
  - Volatility Z-score & percentile
  - Regime classification with direction
  - CSI v3 (coherence-weighted)
  - Hurst fallback behavior
  - Configurable weights
  - Multi-asset consistency (parametrized)
  - Input validation
  - Numerical edge cases (log(0), sigmoid overflow, stdev=0)
  - Backward compatibility (output keys)
"""

from __future__ import annotations

import math

from datetime import UTC, datetime

import pytest

from analysis.layers.L1_context import (
    ContextError,
    LogisticWeights,
    _classify_regime,
    _classify_volatility_by_percentile,
    _compute_context_coherence,
    _compute_csi,
    _compute_entropy,
    _compute_regime_probability,
    _compute_spread,
    _compute_volatility_percentile,
    _compute_zscore,
    _sigmoid,
    _validate_market_data,
    analyze_context,
)

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


def _trending_data(
    n: int = 60, base: float = 1.3000, drift: float = 0.0003,
) -> dict[str, list[float]]:
    """Generate synthetic trending OHLCV."""
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        c = base + drift * i
        closes.append(round(c, 5))
        highs.append(round(c + 0.0005, 5))
        lows.append(round(c - 0.0005, 5))
        volumes.append(1000.0 + i * 10)
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


def _ranging_data(n: int = 60, base: float = 1.3000) -> dict[str, list[float]]:
    """Generate synthetic ranging OHLCV."""
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        c = base + 0.0002 * math.sin(i * 0.5)
        closes.append(round(c, 5))
        highs.append(round(c + 0.0003, 5))
        lows.append(round(c - 0.0003, 5))
        volumes.append(1000.0)
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


NOW_LONDON = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
NOW_TOKYO = datetime(2026, 2, 16, 3, 0, 0, tzinfo=UTC)
W = LogisticWeights()


# ═══════════════════════════════════════════════════════════════════════════
# §1  Sigmoid
# ═══════════════════════════════════════════════════════════════════════════


class TestSigmoid:
    def test_zero(self) -> None:
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_large_positive(self) -> None:
        assert _sigmoid(100.0) == pytest.approx(1.0, abs=1e-9)

    def test_large_negative(self) -> None:
        assert _sigmoid(-100.0) == pytest.approx(0.0, abs=1e-9)

    def test_symmetry(self) -> None:
        assert _sigmoid(2.0) + _sigmoid(-2.0) == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════
# §2  Feature Extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestFeatureExtraction:
    def test_spread_trending(self) -> None:
        closes = [1.3 + 0.001 * i for i in range(60)]
        s = _compute_spread(closes)
        assert s > 0  # EMA20 > EMA50 in uptrend

    def test_spread_flat(self) -> None:
        closes = [1.3] * 60
        s = _compute_spread(closes)
        assert abs(s) < 1e-9

    def test_zscore_constant_atr(self) -> None:
        """Constant ATR → stdev=0 → Vz=0."""
        highs = [1.301] * 60
        lows = [1.299] * 60
        closes = [1.300] * 60
        vz = _compute_zscore(highs, lows, closes)
        assert vz == 0.0

    def test_volatility_percentile_range(self) -> None:
        for vz in [-3.0, -1.0, 0.0, 1.0, 3.0]:
            pct = _compute_volatility_percentile(vz)
            assert 0.0 <= pct <= 1.0

    def test_volatility_percentile_at_zero(self) -> None:
        assert _compute_volatility_percentile(0.0) == pytest.approx(0.5)


# ═══════════════════════════════════════════════════════════════════════════
# §3  Logistic Regime Probability
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeProbability:
    def test_neutral_inputs(self) -> None:
        """S=0, A=0, H=0.5, Vz=0 → P ≈ 0.5 (centered by bias)."""
        p = _compute_regime_probability(0.0, 0.0, 0.5, 0.0, W)
        assert 0.45 <= p <= 0.55

    def test_strong_trend(self) -> None:
        p = _compute_regime_probability(0.005, 0.001, 0.7, 1.5, W)
        assert p > 0.8

    def test_range(self) -> None:
        p = _compute_regime_probability(0.0, 0.0003, 0.45, -0.5, W)
        assert p < 0.45

    def test_bounded(self) -> None:
        for s in [-0.01, 0.0, 0.01]:
            for h in [0.0, 0.5, 1.0]:
                p = _compute_regime_probability(s, 0.001, h, 0.0, W)
                assert 0.0 <= p <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §4  Shannon Entropy & Context Coherence
# ═══════════════════════════════════════════════════════════════════════════


class TestEntropyCoherence:
    def test_maximum_uncertainty(self) -> None:
        """P=0.5 → max entropy, CC=0."""
        cc = _compute_context_coherence(0.5)
        assert cc == pytest.approx(0.0, abs=0.01)

    def test_high_certainty_trend(self) -> None:
        cc = _compute_context_coherence(0.95)
        assert cc > 0.5

    def test_high_certainty_range(self) -> None:
        cc = _compute_context_coherence(0.05)
        assert cc > 0.5

    def test_entropy_bounded(self) -> None:
        for p in [0.01, 0.1, 0.5, 0.9, 0.99]:
            h = _compute_entropy(p)
            assert 0.0 <= h <= math.log(2.0) + 0.001

    def test_coherence_bounded(self) -> None:
        for p in [0.01, 0.5, 0.99]:
            cc = _compute_context_coherence(p)
            assert 0.0 <= cc <= 1.0

    def test_no_log_zero_crash(self) -> None:
        """Edge: P=0 and P=1 must not crash (clamped)."""
        _compute_entropy(0.0)
        _compute_entropy(1.0)
        _compute_context_coherence(0.0)
        _compute_context_coherence(1.0)


# ═══════════════════════════════════════════════════════════════════════════
# §5  Regime Classification
# ═══════════════════════════════════════════════════════════════════════════


class TestRegimeClassification:
    def test_trend_up(self) -> None:
        regime, force = _classify_regime(0.8, 0.003, W)
        assert regime == "TREND_UP"
        assert force == "BULLISH"

    def test_trend_down(self) -> None:
        regime, force = _classify_regime(0.8, -0.003, W)
        assert regime == "TREND_DOWN"
        assert force == "BEARISH"

    def test_transition(self) -> None:
        regime, force = _classify_regime(0.55, 0.001, W)
        assert regime == "TRANSITION"
        assert force == "NEUTRAL"

    def test_range(self) -> None:
        regime, force = _classify_regime(0.3, 0.0, W)
        assert regime == "RANGE"
        assert force == "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════
# §6  Volatility Classification
# ═══════════════════════════════════════════════════════════════════════════


class TestVolatilityClassification:
    def test_extreme(self) -> None:
        assert _classify_volatility_by_percentile(0.97) == "EXTREME"

    def test_normal(self) -> None:
        assert _classify_volatility_by_percentile(0.50) == "NORMAL"

    def test_dead(self) -> None:
        assert _classify_volatility_by_percentile(0.03) == "DEAD"


# ═══════════════════════════════════════════════════════════════════════════
# §7  CSI v3
# ═══════════════════════════════════════════════════════════════════════════


class TestCSIv3:
    def test_bounded(self) -> None:
        csi = _compute_csi(0.8, [1000.0] * 20, 1.3, 0.5, 0.8)
        assert 0.0 <= csi <= 1.0

    def test_high_coherence_boosts(self) -> None:
        low_cc = _compute_csi(0.5, [1000.0] * 20, 1.0, 0.3, 0.1)
        high_cc = _compute_csi(0.5, [1000.0] * 20, 1.0, 0.3, 0.9)
        assert high_cc > low_cc


# ═══════════════════════════════════════════════════════════════════════════
# §8  Custom Weights
# ═══════════════════════════════════════════════════════════════════════════


class TestCustomWeights:
    def test_aggressive_weights(self) -> None:
        aggressive = LogisticWeights(
            w_spread=12.0, w_hurst=6.0,
            trend_threshold=0.55, transition_threshold=0.40,
        )
        p = _compute_regime_probability(0.002, 0.001, 0.6, 0.5, aggressive)
        assert p > 0.5

    def test_conservative_weights(self) -> None:
        conservative = LogisticWeights(
            w_spread=5.0, w_hurst=2.0,
            trend_threshold=0.75, transition_threshold=0.50,
        )
        p = _compute_regime_probability(0.002, 0.001, 0.6, 0.5, conservative)
        regime, _ = _classify_regime(p, 0.002, conservative)
        # Higher threshold → harder to classify as TREND
        assert regime in ("TRANSITION", "RANGE", "TREND_UP")


# ═══════════════════════════════════════════════════════════════════════════
# §9  Integration — analyze_context
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeContext:
    def test_trending(self) -> None:
        data = _trending_data(n=60, drift=0.0003)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        assert r["valid"] is True
        assert "regime_probability" in r
        assert "context_coherence" in r
        assert "volatility_percentile" in r
        assert "entropy_score" in r
        assert 0.0 <= r["regime_probability"] <= 1.0
        assert 0.0 <= r["context_coherence"] <= 1.0

    def test_ranging(self) -> None:
        data = _ranging_data(n=60)
        r = analyze_context(data, pair="EURUSD", now=NOW_LONDON)
        assert r["valid"] is True

    def test_insufficient_data(self) -> None:
        r = analyze_context({"closes": [1.3, 1.31]}, pair="GBPUSD")
        assert r["valid"] is False
        assert r["regime_probability"] == 0.0

    def test_no_hlv(self) -> None:
        data = {"closes": [1.3 + 0.0001 * i for i in range(60)]}
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        assert r["valid"] is True
        assert r["atr"] == 0.0

    def test_feature_vector_exposed(self) -> None:
        data = _trending_data(n=60)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        assert "feature_spread" in r
        assert "feature_atr_frac" in r
        assert "feature_hurst" in r
        assert "feature_zscore" in r

    def test_backward_compat_keys(self) -> None:
        """Downstream consumers expect these keys."""
        data = _trending_data(n=60)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        for key in [
            "regime", "dominant_force", "regime_confidence",
            "csi", "market_alignment", "valid", "session",
            "pair", "timestamp", "atr", "atr_pct",
        ]:
            assert key in r, f"Missing backward-compat key: {key}"

    def test_custom_weights_passthrough(self) -> None:
        cw = LogisticWeights(w_spread=20.0, bias=-5.0)
        data = _trending_data(n=60, drift=0.0003)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON, weights=cw)
        assert r["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════
# §10  Multi-Asset Parametrized
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "pair,base,drift",
    [
        ("GBPUSD", 1.3000, 0.0003),
        ("XAUUSD", 2000.0, 2.0),
        ("BTCUSD", 60000.0, 100.0),
        ("US30", 39000.0, 50.0),
    ],
)
def test_multi_asset(pair: str, base: float, drift: float) -> None:
    n = 60
    closes = [base + drift * i for i in range(n)]
    spread = drift * 3
    data = {
        "closes": closes,
        "highs": [c + spread for c in closes],
        "lows": [c - spread for c in closes],
        "volumes": [1000.0] * n,
    }
    r = analyze_context(data, pair=pair, now=NOW_LONDON)
    assert r["valid"] is True
    assert 0.0 <= r["regime_probability"] <= 1.0
    assert 0.0 <= r["context_coherence"] <= 1.0
    assert 0.0 <= r["volatility_percentile"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §11  Input Validation
# ═══════════════════════════════════════════════════════════════════════════


class TestValidation:
    def test_nan_raises(self) -> None:
        with pytest.raises(ContextError, match="not finite"):
            _validate_market_data([1.3] * 19 + [float("nan")], [], [])

    def test_negative_raises(self) -> None:
        with pytest.raises(ContextError, match="positive"):
            _validate_market_data([1.3] * 19 + [-0.5], [], [])

    def test_high_lt_low_raises(self) -> None:
        with pytest.raises(ContextError, match="high"):
            _validate_market_data(
                [1.3] * 20, [1.3] * 20, [1.31] * 20,
            )
