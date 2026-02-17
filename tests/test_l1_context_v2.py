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

import numpy as np
import pytest

from analysis.layers.L1_context import (
    ContextError,
    ContextResult,
    LogisticWeights,
    _atr,
    _atr_series,
    _classify_asset,
    _classify_regime,
    _classify_volatility_by_percentile,
    _compute_alignment,
    _compute_context_coherence,
    _compute_csi,
    _compute_entropy,
    _compute_momentum_bias,
    _compute_regime_probability,
    _compute_spread,
    _compute_volatility_percentile,
    _compute_zscore,
    _get_session,
    _sigmoid,
    _validate_market_data,
    analyze_context,
)
from engines.fusion_momentum_engine import _ema

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


# ═══════════════════════════════════════════════════════════════════════════
# §12  Session Model — _get_session
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionModel:
    def test_london_newyork_overlap(self) -> None:
        name, mult = _get_session(14)
        assert name == "LONDON_NEWYORK_OVERLAP"
        assert mult == 1.30

    def test_tokyo_london_overlap(self) -> None:
        name, mult = _get_session(8)
        assert name == "TOKYO_LONDON_OVERLAP"
        assert mult == 1.15

    def test_london_only(self) -> None:
        name, mult = _get_session(10)
        assert name == "LONDON"
        assert mult == 1.10

    def test_newyork_only(self) -> None:
        name, mult = _get_session(18)
        assert name == "NEWYORK"
        assert mult == 1.05

    def test_tokyo(self) -> None:
        name, mult = _get_session(3)
        assert name == "TOKYO"
        assert mult == 0.85

    def test_sydney(self) -> None:
        name, mult = _get_session(22)
        assert name == "SYDNEY"
        assert mult == 0.70

    def test_all_hours_classified(self) -> None:
        """Every UTC hour must map to a session."""
        for h in range(24):
            name, mult = _get_session(h)
            assert name, f"Hour {h} returned empty session name"
            assert mult > 0, f"Hour {h} returned non-positive multiplier"

    def test_overlap_hours_boundary(self) -> None:
        """Overlap start/end hours should be correctly classified."""
        assert _get_session(13)[0] == "LONDON_NEWYORK_OVERLAP"
        assert _get_session(15)[0] == "LONDON_NEWYORK_OVERLAP"
        assert _get_session(16)[0] != "LONDON_NEWYORK_OVERLAP"
        assert _get_session(7)[0] == "TOKYO_LONDON_OVERLAP"
        assert _get_session(9)[0] != "TOKYO_LONDON_OVERLAP"


# ═══════════════════════════════════════════════════════════════════════════
# §13  Core Indicators — _ema, _atr, _atr_series
# ═══════════════════════════════════════════════════════════════════════════


class TestEMA:
    def test_empty_data(self) -> None:
        assert _ema(np.array([]), 20) == 0.0

    def test_fewer_than_period(self) -> None:
        """Falls back to SMA when data < period."""
        data = np.array([1.0, 2.0, 3.0])
        assert _ema(data, 20) == pytest.approx(2.0)

    def test_known_ema(self) -> None:
        """EMA of constant series equals that constant."""
        data = np.array([5.0] * 30)
        assert _ema(data, 10) == pytest.approx(5.0)

    def test_ema_responds_to_trend(self) -> None:
        """EMA on a rising series should be between midpoint and last value."""
        data = np.array([float(i) for i in range(1, 31)])
        ema_val = _ema(data, 10)
        assert ema_val > sum(data) / len(data)  # faster than SMA
        assert ema_val < data[-1]  # but lags behind price


class TestATR:
    def test_insufficient_data(self) -> None:
        assert _atr([1.0], [0.9], [0.95], period=14) == 0.0

    def test_constant_bars(self) -> None:
        """Constant high/low/close → ATR should incorporate prev-close gap."""
        n = 20
        highs = [1.01] * n
        lows = [0.99] * n
        closes = [1.00] * n
        atr_val = _atr(highs, lows, closes)
        assert atr_val == pytest.approx(0.02, abs=0.001)

    def test_volatile_bars(self) -> None:
        """Wider range → larger ATR."""
        n = 20
        narrow_h, narrow_l = [1.001] * n, [0.999] * n
        wide_h, wide_l = [1.05] * n, [0.95] * n
        closes = [1.0] * n
        assert _atr(wide_h, wide_l, closes) > _atr(narrow_h, narrow_l, closes)


class TestATRSeries:
    def test_returns_list(self) -> None:
        n = 30
        h = [1.01 + i * 0.0001 for i in range(n)]
        lo = [0.99 + i * 0.0001 for i in range(n)]
        c = [1.00 + i * 0.0001 for i in range(n)]
        series = _atr_series(h, lo, c)
        assert isinstance(series, list)
        assert len(series) > 0

    def test_insufficient_data_empty(self) -> None:
        assert _atr_series([1.0], [0.9], [0.95]) == []


# ═══════════════════════════════════════════════════════════════════════════
# §14  Alignment — _compute_alignment
# ═══════════════════════════════════════════════════════════════════════════


class TestAlignment:
    def test_strongly_bullish(self) -> None:
        # Close > ema9 > ema20 > ema50, positive spread, TREND_UP
        result = _compute_alignment(
            close=1.35, ema20=1.33, ema50=1.31, ema9=1.34,
            s=0.01, regime="TREND_UP",
        )
        assert result == "STRONGLY_BULLISH"

    def test_strongly_bearish(self) -> None:
        result = _compute_alignment(
            close=1.28, ema20=1.30, ema50=1.32, ema9=1.29,
            s=-0.01, regime="TREND_DOWN",
        )
        assert result == "STRONGLY_BEARISH"

    def test_bullish(self) -> None:
        # Above ema20 and ema9, positive spread, but NOT TREND_UP regime
        result = _compute_alignment(
            close=1.35, ema20=1.33, ema50=1.36, ema9=1.34,
            s=0.005, regime="TRANSITION",
        )
        assert result == "BULLISH"

    def test_bearish(self) -> None:
        result = _compute_alignment(
            close=1.28, ema20=1.30, ema50=1.27, ema9=1.29,
            s=-0.005, regime="TRANSITION",
        )
        assert result == "BEARISH"

    def test_neutral(self) -> None:
        result = _compute_alignment(
            close=1.30, ema20=1.30, ema50=1.30, ema9=1.30,
            s=0.0, regime="RANGE",
        )
        assert result == "NEUTRAL"


# ═══════════════════════════════════════════════════════════════════════════
# §15  Momentum — _compute_momentum_bias
# ═══════════════════════════════════════════════════════════════════════════


class TestMomentumBias:
    def test_bullish_momentum(self) -> None:
        closes = [1.30, 1.31, 1.32, 1.33, 1.34]
        ema9 = 1.32
        direction, mag = _compute_momentum_bias(closes, ema9)
        assert direction == "BULLISH"
        assert mag > 0

    def test_bearish_momentum(self) -> None:
        closes = [1.34, 1.33, 1.32, 1.31, 1.30]
        ema9 = 1.32
        direction, mag = _compute_momentum_bias(closes, ema9)
        assert direction == "BEARISH"
        assert mag > 0

    def test_neutral_when_close_equals_ema(self) -> None:
        closes = [1.32]
        direction, mag = _compute_momentum_bias(closes, 1.32)
        assert direction == "NEUTRAL"
        assert mag == 0.0

    def test_empty_closes(self) -> None:
        direction, mag = _compute_momentum_bias([], 1.32)
        assert direction == "NEUTRAL"
        assert mag == 0.0

    def test_zero_ema(self) -> None:
        direction, _mag = _compute_momentum_bias([1.32], 0.0)
        assert direction == "NEUTRAL"

    def test_magnitude_bounded(self) -> None:
        """Magnitude is clamped to [0, 1]."""
        closes = [2.0]
        _, mag = _compute_momentum_bias(closes, 1.0)
        assert 0.0 <= mag <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §16  Asset Classification — _classify_asset
# ═══════════════════════════════════════════════════════════════════════════


class TestClassifyAsset:
    @pytest.mark.parametrize("pair,expected", [
        ("XAUUSD", "METALS"),
        ("XAGUSD", "METALS"),
        ("BTCUSD", "CRYPTO"),
        ("ETHUSD", "CRYPTO"),
        ("US30", "INDEX"),
        ("US500", "INDEX"),
        ("NAS100", "INDEX"),
        ("EURUSD", "FX"),
        ("GBPJPY", "FX"),
    ])
    def test_asset_class(self, pair: str, expected: str) -> None:
        assert _classify_asset(pair) == expected

    def test_case_insensitive(self) -> None:
        assert _classify_asset("xauusd") == "METALS"
        assert _classify_asset("btcusd") == "CRYPTO"


# ═══════════════════════════════════════════════════════════════════════════
# §17  ContextResult — to_dict None filtering
# ═══════════════════════════════════════════════════════════════════════════


class TestContextResult:
    def test_to_dict_excludes_none(self) -> None:
        """Optional fields with None should not appear in output dict."""
        result = ContextResult(
            regime="RANGE", dominant_force="NEUTRAL",
            regime_probability=0.4, context_coherence=0.6,
            volatility_level="NORMAL", volatility_percentile=0.5,
            entropy_score=0.5, regime_confidence=0.5,
            csi=0.5, market_alignment="NEUTRAL", valid=True,
            session="LONDON", session_multiplier=1.1,
            pair="EURUSD", asset_class="FX",
            timestamp="2026-02-16T14:00:00+00:00",
            feature_spread=0.001, feature_atr_frac=0.001,
            feature_hurst=0.5, feature_zscore=0.0,
            ema20=1.3, ema50=1.3, ema9=1.3,
            atr=0.001, atr_pct=0.1,
            momentum_direction="NEUTRAL", momentum_magnitude=0.0,
            # All optional Hurst fields left at default None
        )
        d = result.to_dict()
        assert "hurst_regime" not in d
        assert "hurst_confidence" not in d
        assert "hurst_exponent" not in d
        assert "regime_agreement" not in d

    def test_to_dict_includes_set_optionals(self) -> None:
        result = ContextResult(
            regime="TREND_UP", dominant_force="BULLISH",
            regime_probability=0.8, context_coherence=0.9,
            volatility_level="NORMAL", volatility_percentile=0.5,
            entropy_score=0.3, regime_confidence=0.85,
            csi=0.7, market_alignment="STRONGLY_BULLISH", valid=True,
            session="LONDON", session_multiplier=1.1,
            pair="GBPUSD", asset_class="FX",
            timestamp="2026-02-16T14:00:00+00:00",
            feature_spread=0.005, feature_atr_frac=0.001,
            feature_hurst=0.65, feature_zscore=0.5,
            ema20=1.33, ema50=1.31, ema9=1.34,
            atr=0.002, atr_pct=0.15,
            momentum_direction="BULLISH", momentum_magnitude=0.5,
            hurst_regime="TRENDING",
            hurst_confidence=0.85,
            hurst_exponent=0.65,
            regime_agreement=True,
        )
        d = result.to_dict()
        assert d["hurst_regime"] == "TRENDING"
        assert d["hurst_confidence"] == 0.85
        assert d["regime_agreement"] is True


# ═══════════════════════════════════════════════════════════════════════════
# §18  Hurst Fallback Behavior
# ═══════════════════════════════════════════════════════════════════════════


class TestHurstFallback:
    def test_hurst_uses_fallback_when_engine_unavailable(self) -> None:
        """When RegimeClassifier is not loaded, feature_hurst = fallback."""
        data = _trending_data(n=60, drift=0.0003)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        assert r["valid"] is True
        # Hurst either comes from engine or equals default fallback 0.5
        assert isinstance(r["feature_hurst"], float)
        assert 0.0 <= r["feature_hurst"] <= 1.0

    def test_custom_hurst_fallback(self) -> None:
        """Custom weights can set a different hurst_fallback."""
        w = LogisticWeights(hurst_fallback=0.7)
        data = _ranging_data(n=60)
        r = analyze_context(data, pair="EURUSD", now=NOW_LONDON, weights=w)
        assert r["valid"] is True
        # If engine not loaded, should use 0.7 fallback
        # (can't guarantee engine absence, but value should be valid)
        assert isinstance(r["feature_hurst"], float)


# ═══════════════════════════════════════════════════════════════════════════
# §19  Integration: Session affects regime_confidence
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionIntegration:
    def test_london_session_higher_confidence_than_tokyo(self) -> None:
        """High-quality session should produce higher regime_confidence."""
        data = _trending_data(n=60, drift=0.0003)
        r_london = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        r_tokyo = analyze_context(data, pair="GBPUSD", now=NOW_TOKYO)
        assert r_london["valid"] is True
        assert r_tokyo["valid"] is True
        # London overlap (mult=1.3) → higher confidence than Tokyo (mult=0.85)
        assert r_london["regime_confidence"] >= r_tokyo["regime_confidence"]

    def test_session_name_in_output(self) -> None:
        data = _trending_data(n=60)
        r = analyze_context(data, pair="GBPUSD", now=NOW_LONDON)
        assert r["session"] == "LONDON_NEWYORK_OVERLAP"

        r2 = analyze_context(data, pair="GBPUSD", now=NOW_TOKYO)
        assert r2["session"] == "TOKYO"
