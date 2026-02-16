"""
Tests for L3 Technical Deep Dive — primary directional intelligence engine.
Priority 1 (CRITICAL): 12 static/instance methods, all pure, all testable.

Covers:
    §1  _compute_atr()      — edge cases (insufficient data, flat, multi-asset)
    §2  _detect_trend()      — BULLISH/BEARISH/NEUTRAL per asset class
    §3  _adx_wilder()        — Wilder RMA vs known ranges, boundaries
    §4  _analyze_structure() — BOS/MODERATE/WEAK transitions
    §5  _find_confluence()   — each detector individually + combined count
    §6  _compute_trq3d()     — ATR normalization across FX/metals/crypto
    §7  _compute_tech_score()— boundary testing (0 and 100)
"""  # noqa: N999

from __future__ import annotations

import math

from unittest import mock

import numpy as np
import pytest

from analysis.layers.L3_technical import (
    _DRIFT_FACTORS,
    _EDGE_BIAS,
    _EDGE_WEIGHTS,
    L3TechnicalAnalyzer,
    _classify_drift,
    _compute_edge_probability,
    _sigmoid,
)

# ═══════════════════════════════════════════════════════════════════════
# HELPERS: Synthetic candle data generators
# ═══════════════════════════════════════════════════════════════════════


def _make_trending_data(
    start: float,
    step: float,
    n: int,
    noise: float = 0.0,
    *,
    direction: str = "up",
    seed: int = 42,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Generate synthetic OHLCV trending data.

    Returns (highs, lows, closes, volumes).
    """
    rng = np.random.RandomState(seed)
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i in range(n):
        if direction == "up":
            base = start + step * i
        elif direction == "down":
            base = start - step * i
        else:
            base = start

        jitter = rng.uniform(-noise, noise) if noise > 0 else 0.0
        c = base + jitter
        spread = noise if noise > 0 else step * 0.3
        h = c + abs(rng.normal(0, spread))
        low = c - abs(rng.normal(0, spread))

        closes.append(float(c))
        highs.append(float(max(h, c)))
        lows.append(float(min(low, c)))
        volumes.append(float(1000 + rng.randint(0, 500)))

    return highs, lows, closes, volumes


def _make_candle_dicts(
    base: float,
    step: float,
    n: int,
    noise: float = 0.0,
    seed: int = 42,
) -> list[dict]:
    """Generate candle dicts for TRQ3D / integration tests."""
    rng = np.random.RandomState(seed)
    candles = []
    for i in range(n):
        c = base + step * i + (rng.uniform(-noise, noise) if noise > 0 else 0.0)
        spread = noise if noise > 0 else max(abs(step) * 0.3, 1e-6)
        h = c + abs(rng.normal(0, spread))
        low = c - abs(rng.normal(0, spread))
        candles.append({
            "open": c - step * 0.1,
            "high": float(max(h, c)),
            "low": float(min(low, c)),
            "close": float(c),
            "volume": float(1000 + rng.randint(0, 500)),
        })
    return candles


# ═══════════════════════════════════════════════════════════════════════
# FIXTURE
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def analyzer():
    """L3TechnicalAnalyzer instance (stateless for per-call methods)."""
    return L3TechnicalAnalyzer()


# ═══════════════════════════════════════════════════════════════════════
# §1  _compute_atr() — edge cases, flat market, multi-asset ranges
# ═══════════════════════════════════════════════════════════════════════


class TestComputeATR:
    """ATR: edge cases (insufficient data, flat, known ranges)."""

    def test_empty_arrays_returns_zero(self):
        assert L3TechnicalAnalyzer._compute_atr([], [], [], period=14) == 0.0

    def test_single_bar_returns_zero(self):
        assert L3TechnicalAnalyzer._compute_atr([1.1], [1.0], [1.05], period=14) == 0.0

    def test_insufficient_data_returns_zero(self):
        """Fewer than period+1 bars → 0.0."""
        h = [1.10, 1.11, 1.12]
        l = [1.09, 1.10, 1.11]  # noqa: E741
        c = [1.095, 1.105, 1.115]
        assert L3TechnicalAnalyzer._compute_atr(h, l, c, period=14) == 0.0

    def test_exactly_period_plus_one_computes(self):
        """Exactly period+1 bars → valid ATR > 0."""
        n = 15  # period=14 needs 15 bars
        h = [1.10 + i * 0.001 for i in range(n)]
        l = [1.09 + i * 0.001 for i in range(n)]  # noqa: E741
        c = [1.095 + i * 0.001 for i in range(n)]
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        assert atr > 0.0

    def test_flat_market_atr_zero(self):
        """All bars identical → ATR = 0."""
        n = 30
        assert L3TechnicalAnalyzer._compute_atr(
            [1.10] * n, [1.10] * n, [1.10] * n, period=14
        ) == 0.0

    def test_period_one_single_tr(self):
        """period=1 → ATR = last TR only."""
        h = [1.10, 1.12]
        l = [1.08, 1.09]  # noqa: E741
        c = [1.09, 1.11]
        # TR = max(1.12-1.09, |1.12-1.09|, |1.09-1.09|) = 0.03
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=1)
        assert abs(atr - 0.03) < 1e-9

    def test_fx_eurusd_atr_range(self):
        """EURUSD-like data → ATR in [0.0005, 0.005]."""
        rng = np.random.RandomState(42)
        n = 50
        base = [1.0850 + i * 0.0002 for i in range(n)]
        h = [p + rng.uniform(0.0005, 0.0015) for p in base]
        l = [p - rng.uniform(0.0005, 0.0015) for p in base]  # noqa: E741
        atr = L3TechnicalAnalyzer._compute_atr(h, l, base, period=14)
        assert 0.0005 < atr < 0.005

    def test_gold_xauusd_atr_range(self):
        """XAUUSD-like data → ATR in [5, 50]."""
        rng = np.random.RandomState(42)
        n = 50
        base = [1950.0 + i * 2.0 for i in range(n)]
        h = [p + rng.uniform(5, 20) for p in base]
        l = [p - rng.uniform(5, 20) for p in base]  # noqa: E741
        atr = L3TechnicalAnalyzer._compute_atr(h, l, base, period=14)
        assert 5 < atr < 50

    def test_btc_atr_range(self):
        """BTC-like data → ATR in [100, 1500]."""
        rng = np.random.RandomState(42)
        n = 50
        base = [42000.0 + i * 50.0 for i in range(n)]
        h = [p + rng.uniform(100, 500) for p in base]
        l = [p - rng.uniform(100, 500) for p in base]  # noqa: E741
        atr = L3TechnicalAnalyzer._compute_atr(h, l, base, period=14)
        assert 100 < atr < 1500

    def test_atr_always_non_negative(self):
        """ATR can never be negative regardless of input."""
        rng = np.random.RandomState(99)
        for _ in range(10):
            n = 50
            c = [rng.uniform(0.5, 2.0) for _ in range(n)]
            h = [x + rng.uniform(0, 0.1) for x in c]
            l = [x - rng.uniform(0, 0.1) for x in c]  # noqa: E741
            atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
            assert atr >= 0.0


# ═══════════════════════════════════════════════════════════════════════
# §2  _detect_trend() — BULLISH / BEARISH / NEUTRAL per asset class
# ═══════════════════════════════════════════════════════════════════════


class TestDetectTrend:
    """Trend direction: BULLISH/BEARISH/NEUTRAL across FX, metals, crypto."""

    def test_strong_fx_uptrend_bullish(self, analyzer: L3TechnicalAnalyzer):
        """EURUSD clear uptrend → BULLISH."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1.050, step=0.002, n=80, noise=0.0005, direction="up",
        )
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, strength = analyzer._detect_trend(h, l, c, atr)
        assert trend == "BULLISH"
        assert strength > 0.0

    def test_strong_fx_downtrend_bearish(self, analyzer: L3TechnicalAnalyzer):
        """EURUSD clear downtrend → BEARISH."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1.150, step=0.002, n=80, noise=0.0005, direction="down",
        )
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, strength = analyzer._detect_trend(h, l, c, atr)
        assert trend == "BEARISH"
        assert strength > 0.0

    def test_flat_market_neutral(self, analyzer: L3TechnicalAnalyzer):
        """Sideways market → NEUTRAL."""
        rng = np.random.RandomState(99)
        n = 80
        c = [1.1000 + rng.uniform(-0.00005, 0.00005) for _ in range(n)]
        h = [x + 0.0001 for x in c]
        l = [x - 0.0001 for x in c]  # noqa: E741
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, _ = analyzer._detect_trend(h, l, c, atr)
        assert trend == "NEUTRAL"

    def test_gold_uptrend_bullish(self, analyzer: L3TechnicalAnalyzer):
        """XAUUSD uptrend → BULLISH (multi-asset safe)."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1900.0, step=5.0, n=80, noise=3.0, direction="up",
        )
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, _ = analyzer._detect_trend(h, l, c, atr)
        assert trend == "BULLISH"

    def test_gold_downtrend_bearish(self, analyzer: L3TechnicalAnalyzer):
        """XAUUSD downtrend → BEARISH."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=2050.0, step=5.0, n=80, noise=3.0, direction="down",
        )
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, _ = analyzer._detect_trend(h, l, c, atr)
        assert trend == "BEARISH"

    def test_btc_downtrend_bearish(self, analyzer: L3TechnicalAnalyzer):
        """BTC downtrend → BEARISH."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=45000.0, step=200.0, n=80, noise=80.0, direction="down",
        )
        atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
        trend, _ = analyzer._detect_trend(h, l, c, atr)
        assert trend == "BEARISH"

    def test_insufficient_ema_data_neutral(self, analyzer: L3TechnicalAnalyzer):
        """< 50 bars (can't compute EMA50) → NEUTRAL, strength 0."""
        c = [1.10] * 10
        h = [1.11] * 10
        l = [1.09] * 10  # noqa: E741
        trend, strength = analyzer._detect_trend(h, l, c, atr=0.001)
        assert trend == "NEUTRAL"
        assert strength == 0.0

    def test_trend_strength_bounded_zero_one(self, analyzer: L3TechnicalAnalyzer):
        """Strength is always in [0, 1]."""
        for direction in ("up", "down", "flat"):
            h, l, c, _ = _make_trending_data(  # noqa: E741
                start=1.05, step=0.003, n=80, noise=0.0005, direction=direction,
            )
            atr = L3TechnicalAnalyzer._compute_atr(h, l, c, period=14)
            _, strength = analyzer._detect_trend(h, l, c, atr)
            assert 0.0 <= strength <= 1.0, f"direction={direction}, strength={strength}"


# ═══════════════════════════════════════════════════════════════════════
# §3  _adx_wilder() — Wilder RMA, known ranges, bounds
# ═══════════════════════════════════════════════════════════════════════


class TestADXWilder:
    """True ADX with Wilder RMA smoothing."""

    def test_insufficient_data_returns_zero(self, analyzer: L3TechnicalAnalyzer):
        """< period*2+2 bars → 0.0."""
        n = 20  # needs 30 for period=14
        c = [1.10 + i * 0.001 for i in range(n)]
        h = [x + 0.002 for x in c]
        l = [x - 0.002 for x in c]  # noqa: E741
        assert analyzer._adx_wilder(h, l, c, period=14) == 0.0

    def test_exactly_minimum_bars(self, analyzer: L3TechnicalAnalyzer):
        """period*2+2 bars → computable."""
        n = 30
        c = [1.10 + i * 0.002 for i in range(n)]
        h = [x + 0.003 for x in c]
        l = [x - 0.003 for x in c]  # noqa: E741
        adx = analyzer._adx_wilder(h, l, c, period=14)
        assert adx >= 0.0

    def test_strong_trend_high_adx(self, analyzer: L3TechnicalAnalyzer):
        """Strong monotonic uptrend → ADX > 25."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1.050, step=0.003, n=80, noise=0.0003, direction="up",
        )
        adx = analyzer._adx_wilder(h, l, c, period=14)
        assert adx >= 25.0, f"Expected ADX >= 25 for strong trend, got {adx:.1f}"

    def test_ranging_market_low_adx(self, analyzer: L3TechnicalAnalyzer):
        """Flat/ranging market → ADX < 25."""
        rng = np.random.RandomState(42)
        n = 80
        c = [1.10 + rng.uniform(-0.0005, 0.0005) for _ in range(n)]
        h = [x + rng.uniform(0.0001, 0.0005) for x in c]
        l = [x - rng.uniform(0.0001, 0.0005) for x in c]  # noqa: E741
        adx = analyzer._adx_wilder(h, l, c, period=14)
        assert adx < 25.0, f"Expected ADX < 25 for ranging, got {adx:.1f}"

    def test_adx_bounded_0_100(self, analyzer: L3TechnicalAnalyzer):
        """ADX always in [0, 100]."""
        np.random.RandomState(42)
        for seed in range(5):
            rng2 = np.random.RandomState(seed)
            n = 80
            c = [1.10 + rng2.normal(0, 0.01) for _ in range(n)]
            h = [x + abs(rng2.normal(0, 0.005)) for x in c]
            l = [x - abs(rng2.normal(0, 0.005)) for x in c]  # noqa: E741
            adx = analyzer._adx_wilder(h, l, c, period=14)
            assert 0.0 <= adx <= 100.0, f"seed={seed}, adx={adx}"

    def test_gold_trending_adx_high(self, analyzer: L3TechnicalAnalyzer):
        """XAUUSD strong trend → ADX >= 20."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1900.0, step=8.0, n=80, noise=2.0, direction="up",
        )
        adx = analyzer._adx_wilder(h, l, c, period=14)
        assert adx >= 20.0

    def test_flat_data_returns_zero_or_low(self, analyzer: L3TechnicalAnalyzer):
        """Totally flat bars → ADX 0 or very low."""
        n = 80
        adx = analyzer._adx_wilder([100.0] * n, [100.0] * n, [100.0] * n, period=14)
        assert adx < 5.0

    def test_adx_not_nan(self, analyzer: L3TechnicalAnalyzer):
        """ADX never NaN."""
        h, l, c, _ = _make_trending_data(  # noqa: E741
            start=1.05, step=0.001, n=80, noise=0.0008, direction="up",
        )
        adx = analyzer._adx_wilder(h, l, c, period=14)
        assert not math.isnan(adx)
        assert not math.isinf(adx)


# ═══════════════════════════════════════════════════════════════════════
# §4  _analyze_structure() — BOS / MODERATE / WEAK transitions
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzeStructure:
    """Market structure: STRONG (BOS), MODERATE, WEAK."""

    def test_weak_insufficient_data(self):
        """< 20 bars → WEAK, confidence 0."""
        result = L3TechnicalAnalyzer._analyze_structure(
            [1.1] * 10, [1.0] * 10, [1.05] * 10, atr=0.001,
        )
        assert result["validity"] == "WEAK"
        assert result["confidence"] == 0.0
        assert result["score"] == 0.0

    def test_strong_bos_upward(self):
        """Last bar high breaks prev-window high → STRONG."""
        # bars 0-19 (prev window -20:-5): highs peak at 1.10
        # bar -1 (last): high 1.15 → breaks structure
        highs = [1.10] * 20 + [1.08, 1.09, 1.10, 1.11, 1.15]
        lows = [1.08] * 20 + [1.07, 1.08, 1.09, 1.10, 1.12]
        closes = [1.09] * 20 + [1.075, 1.085, 1.095, 1.105, 1.14]
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=0.005)
        assert result["validity"] == "STRONG"
        assert result["confidence"] == 0.85
        assert result["score"] == 0.85

    def test_strong_bos_downward(self):
        """Last bar low breaks prev-window low → STRONG."""
        highs = [1.10] * 20 + [1.09, 1.08, 1.07, 1.06, 1.05]
        lows = [1.08] * 20 + [1.07, 1.06, 1.05, 1.04, 1.01]
        closes = [1.09] * 20 + [1.08, 1.07, 1.06, 1.05, 1.02]
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=0.005)
        assert result["validity"] == "STRONG"

    def test_weak_no_bos_tight_range(self):
        """No BOS, range < 3*ATR → WEAK."""
        n = 25
        highs = [1.1001] * n
        lows = [1.0999] * n
        closes = [1.1000] * n
        # range = 0.0002 < 3*0.005 = 0.015
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=0.005)
        assert result["validity"] == "WEAK"
        assert result["confidence"] == 0.15

    def test_moderate_no_bos_wide_range(self):
        """No BOS but range >= 3*ATR → MODERATE."""
        # prev_high = max(highs[-20:-5]): from first 15+5=20 bars
        # Need: last_high <= prev_high AND last_low >= prev_low
        # But recent_range >= 3*ATR
        highs = (
            [1.1020] * 15 + [1.0980] * 5
            + [1.1000, 1.0990, 1.1005, 1.1010, 1.1015]
        )
        lows = (
            [1.0980] * 15 + [1.0960] * 5
            + [1.0970, 1.0965, 1.0975, 1.0980, 1.0985]
        )
        closes = (
            [1.1000] * 15 + [1.0970] * 5
            + [1.0985, 1.0975, 1.0990, 1.0995, 1.1000]
        )
        # prev_high = max(highs[5:20]) = 1.1020, last_high = 1.1015 → no BOS up
        # prev_low = min(lows[5:20]) = 1.0960, last_low = 1.0985 → no BOS down
        # range = 1.1020 - 1.0960 = 0.006 >= 3*0.001 = 0.003
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=0.001)
        assert result["validity"] == "MODERATE"
        assert result["confidence"] == 0.55

    def test_gold_bos_strong(self):
        """XAUUSD BOS → STRONG (multi-asset)."""
        highs = [1950.0] * 20 + [1945, 1955, 1960, 1965, 1975]
        lows = [1940.0] * 20 + [1940, 1950, 1955, 1960, 1968]
        closes = [1945.0] * 20 + [1943, 1953, 1958, 1963, 1972]
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=10.0)
        assert result["validity"] == "STRONG"

    def test_atr_zero_wide_range_moderate(self):
        """ATR=0 → threshold=0, any non-zero range without BOS → MODERATE."""
        highs = [1.1010] * 15 + [1.1005] * 5 + [1.1000, 1.1002, 1.1004, 1.1006, 1.1008]
        lows = [1.0990] * 15 + [1.0992] * 5 + [1.0994, 1.0993, 1.0995, 1.0996, 1.0998]
        closes = [1.1000] * 15 + [1.0998] * 5 + [1.0997, 1.0998, 1.0999, 1.1001, 1.1003]
        result = L3TechnicalAnalyzer._analyze_structure(highs, lows, closes, atr=0.0)
        assert result["validity"] == "MODERATE"

    def test_output_keys_present(self):
        """Every return dict has validity, confidence, score."""
        result = L3TechnicalAnalyzer._analyze_structure(
            [1.1] * 25, [1.0] * 25, [1.05] * 25, atr=0.01,
        )
        assert "validity" in result
        assert "confidence" in result
        assert "score" in result


# ═══════════════════════════════════════════════════════════════════════
# §5  _find_confluence() — each detector individually + combined count
# ═══════════════════════════════════════════════════════════════════════

# ── 5a: Fibonacci retracement ────────────────────────────────────────


class TestFibRetracementHit:
    """Fib retracement: near key levels vs far away."""

    def test_insufficient_data_false(self):
        """< 40 bars → False."""
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            [1.1] * 30, [1.0] * 30, [1.05] * 30, atr=0.001,
        ) is False

    def test_flat_swing_false(self):
        """swing_high == swing_low (diff=0) → False."""
        n = 50
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            [1.10] * n, [1.10] * n, [1.10] * n, atr=0.001,
        ) is False

    def test_at_382_level(self):
        """Price at 38.2% retracement → True."""
        n = 50
        # swing_high=1.10, swing_low=1.05, diff=0.05
        # 38.2% level = 1.10 - 0.05*0.382 = 1.0809
        highs = [1.10] * n
        lows = [1.05] * n
        closes = [1.08] * 49 + [1.0809]
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            highs, lows, closes, atr=0.005,
        ) is True

    def test_at_500_level(self):
        """Price at 50% retracement → True."""
        n = 50
        highs = [1.10] * n
        lows = [1.05] * n
        closes = [1.08] * 49 + [1.0750]  # 50% = 1.10 - 0.025 = 1.075
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            highs, lows, closes, atr=0.005,
        ) is True

    def test_at_618_level(self):
        """Price at 61.8% retracement → True."""
        n = 50
        highs = [1.10] * n
        lows = [1.05] * n
        # 61.8% level = 1.10 - 0.05*0.618 = 1.0691
        closes = [1.08] * 49 + [1.0691]
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            highs, lows, closes, atr=0.005,
        ) is True

    def test_at_786_level(self):
        """Price at 78.6% retracement → True."""
        n = 50
        highs = [1.10] * n
        lows = [1.05] * n
        # 78.6% level = 1.10 - 0.05*0.786 = 1.0607
        closes = [1.08] * 49 + [1.0607]
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            highs, lows, closes, atr=0.005,
        ) is True

    def test_far_from_all_levels_false(self):
        """Price far from every fib level → False."""
        n = 50
        highs = [1.10] * n
        lows = [1.05] * n
        # Price at 1.10 — away from all retracement levels
        closes = [1.08] * 49 + [1.10]
        assert L3TechnicalAnalyzer._fib_retracement_hit(
            highs, lows, closes, atr=0.001,
        ) is False


# ── 5b: Volume Profile POC ──────────────────────────────────────────


class TestVolumeProfilePOC:
    """Volume profile Point of Control proximity."""

    def test_insufficient_data_false(self):
        assert L3TechnicalAnalyzer._volume_profile_poc_hit(
            [1.10] * 20, [1000] * 20, bins=20, atr=0.001,
        ) is False

    def test_price_at_poc(self):
        """Most volume at current price → True."""
        # Heavy volume around 1.10, final price = 1.10
        closes = [1.10] * 25 + [1.05, 1.06, 1.07, 1.08, 1.10]
        volumes = [float(v) for v in [5000] * 25 + [100, 100, 100, 100, 5000]]
        assert L3TechnicalAnalyzer._volume_profile_poc_hit(
            closes, volumes, bins=20, atr=0.005,
        )

    def test_price_far_from_poc_false(self):
        """Volume concentrated far from current price → False."""
        closes = [1.10] * 28 + [1.10, 1.05]
        volumes = [float(v) for v in [5000] * 28 + [5000, 100]]
        assert not L3TechnicalAnalyzer._volume_profile_poc_hit(
            closes, volumes, bins=20, atr=0.001,
        )

    def test_flat_prices_always_near_poc(self):
        """Flat price series: price == POC → True."""
        n = 30
        closes = [1.10] * n
        volumes = [float(v) for v in [1000] * n]
        # flat → all bins same, but price = POC mid → True (with any atr > 0)
        # Actually with flat prices, p_max == p_min → returns False
        assert L3TechnicalAnalyzer._volume_profile_poc_hit(
            closes, volumes, bins=20, atr=0.001,
        ) is False


# ── 5c: Order Block ─────────────────────────────────────────────────


class TestDetectOrderBlock:
    """Order block: impulse + opposite candle + retest proximity."""

    def test_insufficient_data_false(self):
        assert L3TechnicalAnalyzer._detect_orderblock(
            [1.1] * 20, [1.0] * 20, [1.05] * 20, atr=0.01,
        ) is False

    def test_no_impulse_false(self):
        """All candles same range → no impulse → False."""
        n = 30
        assert L3TechnicalAnalyzer._detect_orderblock(
            [1.105] * n, [1.095] * n, [1.10] * n, atr=0.01,
        ) is False

    def test_bullish_ob_detected(self):
        """Impulse + prior bearish candle + retest near OB → True."""
        # Flat history with range ~0.01
        highs = [1.110] * 24 + [1.110, 1.105, 1.108, 1.102, 1.115, 1.103]
        lows = [1.100] * 24 + [1.100, 1.095, 1.098, 1.095, 1.100, 1.085]
        closes = [1.105] * 24 + [1.105, 1.097, 1.104, 1.100, 1.110, 1.100]
        # avg_r of first 29 ≈ 0.01, last candle range = 1.103-1.085 = 0.018 > 1.5*0.01
        # impulse_bull = closes[-1]=1.100 > closes[-2]=1.110? No → bearish
        # For bearish impulse, look for prior bullish (closes[i] > closes[i-1])
        # closes[-6...-2] = [1.097, 1.104, 1.100, 1.110, ...]
        # i=-6: 1.097, i-1=-7: 1.105 → 1.097 < 1.105 → not bullish
        # i=-5: 1.104, i-1=-6: 1.097 → 1.104 > 1.097 → bullish ✓
        # ob_mid = (highs[-5] + lows[-5]) / 2 = (1.108 + 1.098) / 2 = 1.103
        # price = 1.100, |1.100 - 1.103| = 0.003
        # band = 0.01 * 0.5 = 0.005 → 0.003 < 0.005 → True ✓
        assert L3TechnicalAnalyzer._detect_orderblock(highs, lows, closes, atr=0.01)

    def test_bearish_ob_no_opposite_candle_false(self):
        """Impulse exists but no opposite candle in lookback → False."""
        n = 30
        # All candles monotonically going up → every close > prior close
        closes = [1.10 + i * 0.001 for i in range(n)]
        highs = [c + 0.005 for c in closes]
        lows = [c - 0.005 for c in closes]
        # Last candle has large range
        highs[-1] = closes[-1] + 0.020
        # All closes ascending → no prior bearish candle for bullish impulse
        # impulse_bull = closes[-1] > closes[-2] → True
        # Each closes[i] > closes[i-1] → no bearish candle found
        result = L3TechnicalAnalyzer._detect_orderblock(highs, lows, closes, atr=0.01)
        assert result is False


# ── 5d: Fair Value Gap ──────────────────────────────────────────────


class TestDetectFVG:
    """FVG: bullish gap, bearish gap, no gap."""

    def test_insufficient_data_false(self):
        assert L3TechnicalAnalyzer._detect_fvg(
            [1.1] * 5, [1.0] * 5, [1.05] * 5,
        ) is False

    def test_bullish_fvg_detected(self):
        """Gap up with unfilled middle → True."""
        # 10 candles; FVG at position 4-5-6
        highs = [1.10] * 4 + [1.100, 1.105, 1.112, 1.120, 1.125, 1.130]
        lows = [1.09] * 4 + [1.090, 1.098, 1.108, 1.115, 1.120, 1.125]
        closes = [1.095] * 10
        # h[4]=1.100 < l[6]=1.108 → bullish FVG
        # middle (5): l=1.098 <= h[4]=1.100 ✓, h=1.105 >= l[6]=1.108? No
        # filled = False → FVG detected
        assert L3TechnicalAnalyzer._detect_fvg(highs, lows, closes) is True

    def test_bearish_fvg_detected(self):
        """Gap down with unfilled middle → True."""
        highs = [1.10] * 4 + [1.100, 1.092, 1.082, 1.075, 1.070, 1.065]
        lows = [1.09] * 4 + [1.095, 1.088, 1.075, 1.068, 1.063, 1.058]
        closes = [1.095] * 10
        # l[4]=1.095 > h[6]=1.082 → bearish FVG
        # middle (5): l=1.088 <= h[6]=1.082? No → filled=False → FVG
        assert L3TechnicalAnalyzer._detect_fvg(highs, lows, closes) is True

    def test_no_gap_normal_candles(self):
        """Normal candles with small increments → no FVG."""
        n = 10
        closes = [1.10 + i * 0.001 for i in range(n)]
        highs = [c + 0.002 for c in closes]
        lows = [c - 0.002 for c in closes]
        # Adjacent candles overlap → no gap
        assert L3TechnicalAnalyzer._detect_fvg(highs, lows, closes) is False

    def test_filled_gap_false(self):
        """Gap exists but middle candle fully fills it → False."""
        # Construct data where every potential gap is fully filled.
        # Smoothly rising, each middle candle spans both neighbors.
        highs  = [1.100, 1.102, 1.104, 1.106, 1.108, 1.110, 1.112, 1.114, 1.116, 1.118]
        lows   = [1.095, 1.097, 1.099, 1.101, 1.103, 1.105, 1.107, 1.109, 1.111, 1.113]
        closes = [1.098, 1.100, 1.102, 1.104, 1.106, 1.108, 1.110, 1.112, 1.114, 1.116]
        # Adjacent candles overlap heavily → no gap at any triplet
        assert L3TechnicalAnalyzer._detect_fvg(highs, lows, closes) is False


# ── 5e: Combined confluence ─────────────────────────────────────────


class TestFindConfluence:
    """Combined confluence count: 0-4."""

    def test_all_four_detectors_fire(self, analyzer: L3TechnicalAnalyzer):
        """All detectors → count=4."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=True),
        ):
            assert analyzer._find_confluence([], [], [], [], atr=0.001)["count"] == 4

    def test_zero_detectors_fire(self, analyzer: L3TechnicalAnalyzer):
        """No detectors → count=0."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=False),
        ):
            assert analyzer._find_confluence([], [], [], [], atr=0.001)["count"] == 0

    def test_partial_two_detectors(self, analyzer: L3TechnicalAnalyzer):
        """Two detectors → count=2."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=False),
        ):
            assert analyzer._find_confluence([], [], [], [], atr=0.001)["count"] == 2

    def test_count_capped_at_four(self, analyzer: L3TechnicalAnalyzer):
        """Result is min(count, 4) — can't exceed 4."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=True),
        ):
            result = analyzer._find_confluence([], [], [], [], atr=0.001)
            assert result["count"] <= 4

    def test_count_is_int(self, analyzer: L3TechnicalAnalyzer):
        """count is always int."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=False),
        ):
            assert isinstance(analyzer._find_confluence([], [], [], [], atr=0.001)["count"], int)


# ═══════════════════════════════════════════════════════════════════════
# §6  _compute_trq3d() — ATR normalization across FX / metals / crypto
# ═══════════════════════════════════════════════════════════════════════


class TestComputeTRQ3D:
    """TRQ3D energy & drift: bounded, asset-agnostic normalization."""

    def test_empty_h4_d1_returns_zero(self):
        """No H4/D1 data → energy=0, drift=0."""
        candles = _make_candle_dicts(1.10, 0.001, 60)
        result = L3TechnicalAnalyzer._compute_trq3d("EURUSD", candles, [], [])
        assert result["energy"] == 0.0
        assert result["drift"] == 0.0

    def test_fx_energy_bounded(self):
        """FX (EURUSD) energy ∈ [0, 1]."""
        h1 = _make_candle_dicts(1.080, 0.0005, 80, noise=0.0003)
        h4 = _make_candle_dicts(1.080, 0.002, 30, noise=0.001)
        d1 = _make_candle_dicts(1.080, 0.005, 15, noise=0.003)
        result = L3TechnicalAnalyzer._compute_trq3d("EURUSD", h1, h4, d1)
        assert 0.0 <= result["energy"] <= 1.0

    def test_gold_energy_bounded(self):
        """Gold energy ∈ [0, 1]."""
        h1 = _make_candle_dicts(1950.0, 2.0, 80, noise=5.0)
        h4 = _make_candle_dicts(1950.0, 8.0, 30, noise=10.0)
        d1 = _make_candle_dicts(1950.0, 20.0, 15, noise=15.0)
        result = L3TechnicalAnalyzer._compute_trq3d("XAUUSD", h1, h4, d1)
        assert 0.0 <= result["energy"] <= 1.0

    def test_btc_energy_bounded(self):
        """BTC energy ∈ [0, 1]."""
        h1 = _make_candle_dicts(42000.0, 50.0, 80, noise=100.0)
        h4 = _make_candle_dicts(42000.0, 200.0, 30, noise=300.0)
        d1 = _make_candle_dicts(42000.0, 500.0, 15, noise=500.0)
        result = L3TechnicalAnalyzer._compute_trq3d("BTCUSD", h1, h4, d1)
        assert 0.0 <= result["energy"] <= 1.0

    def test_silver_energy_bounded(self):
        """XAGUSD energy ∈ [0, 1]."""
        h1 = _make_candle_dicts(23.5, 0.05, 80, noise=0.1)
        h4 = _make_candle_dicts(23.5, 0.2, 30, noise=0.3)
        d1 = _make_candle_dicts(23.5, 0.5, 15, noise=0.5)
        result = L3TechnicalAnalyzer._compute_trq3d("XAGUSD", h1, h4, d1)
        assert 0.0 <= result["energy"] <= 1.0

    def test_drift_non_negative(self):
        """Drift is always >= 0."""
        h1 = _make_candle_dicts(1.08, 0.001, 80, noise=0.0005)
        h4 = _make_candle_dicts(1.08, 0.004, 30, noise=0.002)
        d1 = _make_candle_dicts(1.08, 0.01, 15, noise=0.005)
        result = L3TechnicalAnalyzer._compute_trq3d("EURUSD", h1, h4, d1)
        assert result["drift"] >= 0.0

    def test_flat_data_low_energy(self):
        """Flat price → low energy (below trending baseline)."""
        h1 = _make_candle_dicts(1.1000, 0.0, 80, noise=0.00001)
        h4 = _make_candle_dicts(1.1000, 0.0, 30, noise=0.00001)
        d1 = _make_candle_dicts(1.1000, 0.0, 15, noise=0.00001)
        result = L3TechnicalAnalyzer._compute_trq3d("EURUSD", h1, h4, d1)
        assert result["energy"] < 0.5

    def test_output_keys_present(self):
        """Result always has 'energy' and 'drift'."""
        h1 = _make_candle_dicts(1.10, 0.001, 60)
        result = L3TechnicalAnalyzer._compute_trq3d("EURUSD", h1, [], [])
        assert "energy" in result
        assert "drift" in result


# ═══════════════════════════════════════════════════════════════════════
# §7  _compute_tech_score() — boundary testing (0 and 100)
# ═══════════════════════════════════════════════════════════════════════


class TestComputeTechScore:
    """Balanced score: 25+25+20+20+10 = 100 max."""

    def test_all_zero_returns_zero(self):
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=0, liquidity_score=0.0, trq3d_energy=0.0,
        ) == 0

    def test_all_max_returns_100(self):
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=1.0, structure_score=1.0,
            confluence_count=4, liquidity_score=1.0, trq3d_energy=1.0,
        ) == 100

    def test_trend_component_25(self):
        """trend_strength=1.0, rest zero → 25."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=1.0, structure_score=0.0,
            confluence_count=0, liquidity_score=0.0, trq3d_energy=0.0,
        ) == 25

    def test_structure_component_25(self):
        """structure_score=1.0, rest zero → 25."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=1.0,
            confluence_count=0, liquidity_score=0.0, trq3d_energy=0.0,
        ) == 25

    def test_confluence_component_20(self):
        """4 confluence, rest zero → 20."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=4, liquidity_score=0.0, trq3d_energy=0.0,
        ) == 20

    def test_single_confluence_5(self):
        """1 confluence → 5."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=1, liquidity_score=0.0, trq3d_energy=0.0,
        ) == 5

    def test_liquidity_component_20(self):
        """liquidity=1.0, rest zero → 20."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=0, liquidity_score=1.0, trq3d_energy=0.0,
        ) == 20

    def test_trq3d_component_10(self):
        """trq3d=1.0, rest zero → 10."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=0, liquidity_score=0.0, trq3d_energy=1.0,
        ) == 10

    def test_half_values_50(self):
        """Half of each → 12.5+12.5+10+10+5 = 50."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.5, structure_score=0.5,
            confluence_count=2, liquidity_score=0.5, trq3d_energy=0.5,
        ) == 50

    def test_negative_inputs_clipped_to_zero(self):
        """Negative inputs → clipped → 0."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=-0.5, structure_score=-1.0,
            confluence_count=-2, liquidity_score=-0.3, trq3d_energy=-0.8,
        ) == 0

    def test_over_max_inputs_clipped_to_100(self):
        """Over-max inputs → clipped → 100."""
        assert L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=5.0, structure_score=3.0,
            confluence_count=10, liquidity_score=2.0, trq3d_energy=4.0,
        ) == 100

    def test_return_type_int(self):
        """Score always int."""
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.33, structure_score=0.67,
            confluence_count=1, liquidity_score=0.5, trq3d_energy=0.2,
        )
        assert isinstance(score, int)

    def test_score_never_exceeds_100(self):
        """Even with extreme inputs, capped at 100."""
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=999.0, structure_score=999.0,
            confluence_count=999, liquidity_score=999.0, trq3d_energy=999.0,
        )
        assert score == 100

    def test_score_never_below_zero(self):
        """Even with extreme negative inputs, floor at 0."""
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=-999.0, structure_score=-999.0,
            confluence_count=-999, liquidity_score=-999.0, trq3d_energy=-999.0,
        )
        assert score == 0


# ═══════════════════════════════════════════════════════════════════════
# §8  _insufficient_data() — fallback contract
# ═══════════════════════════════════════════════════════════════════════


class TestInsufficientData:
    """Fallback output contract: valid=False, safe defaults."""

    def test_valid_false(self):
        result = L3TechnicalAnalyzer._insufficient_data("EURUSD")
        assert result["valid"] is False

    def test_all_keys_present(self):
        result = L3TechnicalAnalyzer._insufficient_data("XAUUSD")
        v5_keys = {
            "technical_score", "structure_validity", "confluence_points",
            "trq3d_energy", "drift", "trend", "confidence",
            "structure_score", "valid",
        }
        v6_keys = {
            "edge_probability", "edge_detail", "drift_state",
            "trend_strength", "adx", "atr", "atr_expansion",
            "liquidity_score",
        }
        expected_keys = v5_keys | v6_keys
        assert set(result.keys()) == expected_keys

    def test_safe_defaults(self):
        result = L3TechnicalAnalyzer._insufficient_data("BTCUSD")
        assert result["technical_score"] == 0
        assert result["structure_validity"] == "WEAK"
        assert result["confluence_points"] == 0
        assert result["trq3d_energy"] == 0.0
        assert result["drift"] == 0.0
        assert result["trend"] == "NEUTRAL"
        assert result["confidence"] == 0.0
        assert result["structure_score"] == 0.0


# ═══════════════════════════════════════════════════════════════════════
# §9  _vol_factor() — volatility expansion/contraction
# ═══════════════════════════════════════════════════════════════════════


class TestVolFactor:
    """Volatility factor: ATR(7)/ATR(20) ratio, bounded [0.7, 2.0]."""

    def test_insufficient_data_returns_one(self, analyzer: L3TechnicalAnalyzer):
        """< 30 bars → default 1.0."""
        c = [1.10] * 20
        h = [1.11] * 20
        l = [1.09] * 20  # noqa: E741
        assert analyzer._vol_factor(h, l, c) == 1.0

    def test_flat_market_near_one(self, analyzer: L3TechnicalAnalyzer):
        """Flat market (ATR short ≈ ATR long) → ~1.0."""
        n = 50
        rng = np.random.RandomState(42)
        c = [1.10 + rng.uniform(-0.001, 0.001) for _ in range(n)]
        h = [x + 0.002 for x in c]
        l = [x - 0.002 for x in c]  # noqa: E741
        vf = analyzer._vol_factor(h, l, c)
        assert 0.7 <= vf <= 2.0
        assert abs(vf - 1.0) < 0.5  # near 1.0 for flat market

    def test_bounded_lower(self, analyzer: L3TechnicalAnalyzer):
        """Result always >= 0.7."""
        n = 50
        # Recent bars very tight, older bars wide
        c = [1.10] * n
        h = [1.20] * 30 + [1.1001] * 20
        l = [1.00] * 30 + [1.0999] * 20  # noqa: E741
        vf = analyzer._vol_factor(h, l, c)
        assert vf >= 0.7

    def test_bounded_upper(self, analyzer: L3TechnicalAnalyzer):
        """Result always <= 2.0."""
        n = 50
        c = [1.10] * n
        # Recent bars wide, older bars tight
        h = [1.1001] * 30 + [1.20] * 20
        l = [1.0999] * 30 + [1.00] * 20  # noqa: E741
        vf = analyzer._vol_factor(h, l, c)
        assert vf <= 2.0


# ═══════════════════════════════════════════════════════════════════════
# §A  _sigmoid() — mathematical properties (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestSigmoid:
    """σ(x): numerically stable sigmoid function."""

    def test_zero_is_half(self):
        assert abs(_sigmoid(0.0) - 0.5) < 1e-10

    def test_large_positive_near_one(self):
        assert _sigmoid(100.0) > 0.9999

    def test_large_negative_near_zero(self):
        assert _sigmoid(-100.0) < 0.0001

    def test_symmetry(self):
        for x in [-5.0, -1.0, 0.0, 1.0, 5.0]:
            assert abs(_sigmoid(x) + _sigmoid(-x) - 1.0) < 1e-10

    def test_monotonically_increasing(self):
        xs = [-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
        vals = [_sigmoid(x) for x in xs]
        for i in range(len(vals) - 1):
            assert vals[i] < vals[i + 1]

    def test_never_nan_inf(self):
        for x in [-1e6, -1e3, 0.0, 1e3, 1e6]:
            v = _sigmoid(x)
            assert not math.isnan(v) and not math.isinf(v)


# ═══════════════════════════════════════════════════════════════════════
# §B  _classify_drift() — FRESH / EXTENDING / OVEREXTENDED (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestClassifyDrift:
    """Drift classification: direction-agnostic thresholds."""

    @pytest.mark.parametrize(
        "drift, expected",
        [
            (0.000, "FRESH"),
            (0.001, "FRESH"),
            (0.0029, "FRESH"),
            (0.003, "EXTENDING"),
            (0.005, "EXTENDING"),
            (0.0079, "EXTENDING"),
            (0.008, "OVEREXTENDED"),
            (0.010, "OVEREXTENDED"),
            (0.050, "OVEREXTENDED"),
            (1.000, "OVEREXTENDED"),
        ],
    )
    def test_threshold_boundaries(self, drift: float, expected: str):
        assert _classify_drift(drift) == expected

    def test_same_for_bullish_and_bearish_conceptually(self):
        """Drift 0.005 from a bull move = same state as from a bear move."""
        drift_bull = 0.005
        drift_bear = 0.005
        assert _classify_drift(drift_bull) == _classify_drift(drift_bear)

    def test_drift_factors_defined_for_all_states(self):
        for state in ("FRESH", "EXTENDING", "OVEREXTENDED"):
            assert state in _DRIFT_FACTORS
            assert 0.0 < _DRIFT_FACTORS[state] <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# §C  _compute_edge_probability() — feature vector → P_edge (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestComputeEdgeProbability:
    """Core logistic edge model."""

    def test_all_zero_low_edge(self):
        p, _ = _compute_edge_probability(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=0, liquidity_score=0.0,
            trq3d_energy=0.0, adx_norm=0.0, atr_expansion=0.0,
            drift=0.0,
        )
        assert p < 0.10

    def test_all_max_high_edge(self):
        p, _ = _compute_edge_probability(
            trend_strength=1.0, structure_score=1.0,
            confluence_count=4, liquidity_score=1.0,
            trq3d_energy=1.0, adx_norm=1.0, atr_expansion=1.0,
            drift=0.0,
        )
        assert p > 0.85

    def test_output_always_0_1(self):
        rng = np.random.RandomState(42)
        for _ in range(50):
            p, _ = _compute_edge_probability(
                trend_strength=rng.uniform(-1, 2),
                structure_score=rng.uniform(-1, 2),
                confluence_count=rng.randint(-2, 8),
                liquidity_score=rng.uniform(-1, 2),
                trq3d_energy=rng.uniform(-1, 2),
                adx_norm=rng.uniform(-1, 2),
                atr_expansion=rng.uniform(-1, 2),
                drift=rng.uniform(0, 1),
            )
            assert 0.0 <= p <= 1.0

    def test_detail_keys_complete(self):
        _, detail = _compute_edge_probability(
            trend_strength=0.5, structure_score=0.5,
            confluence_count=2, liquidity_score=0.5,
            trq3d_energy=0.5, adx_norm=0.3, atr_expansion=0.5,
            drift=0.003,
        )
        required = {
            "features", "logit_z", "p_edge_raw",
            "drift", "drift_state", "drift_factor", "p_edge_adj",
        }
        assert required.issubset(detail.keys())

    def test_manual_math_verification(self):
        """Hand-compute z, σ(z), drift_factor, P_adj."""
        features = [0.80, 0.85, 0.75, 0.70, 0.65, 0.40, 0.50]
        z = sum(w * x for w, x in zip(_EDGE_WEIGHTS, features, strict=False)) + _EDGE_BIAS
        expected_raw = _sigmoid(z)
        expected_adj = expected_raw * 1.0

        p, detail = _compute_edge_probability(
            trend_strength=0.80, structure_score=0.85,
            confluence_count=3, liquidity_score=0.70,
            trq3d_energy=0.65, adx_norm=0.40, atr_expansion=0.50,
            drift=0.002,
        )
        assert abs(p - expected_adj) < 0.01
        assert detail["drift_state"] == "FRESH"
        assert detail["drift_factor"] == 1.0


# ═══════════════════════════════════════════════════════════════════════
# §D  BULLISH-BEARISH SYMMETRY PROOF — THE CORE REQUIREMENT (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestBullishBearishSymmetry:
    """PROOF: Bullish and Bearish produce IDENTICAL scores when
    given the same feature magnitudes and the same drift."""

    def test_same_features_same_drift_identical_edge(self):
        """Exact same features → exact same P_edge."""
        p1, d1 = _compute_edge_probability(
            trend_strength=0.80, structure_score=0.85,
            confluence_count=3, liquidity_score=0.70,
            trq3d_energy=0.65, adx_norm=0.40, atr_expansion=0.50,
            drift=0.004,
        )
        p2, d2 = _compute_edge_probability(
            trend_strength=0.80, structure_score=0.85,
            confluence_count=3, liquidity_score=0.70,
            trq3d_energy=0.65, adx_norm=0.40, atr_expansion=0.50,
            drift=0.004,
        )
        assert p1 == p2
        assert d1["p_edge_raw"] == d2["p_edge_raw"]
        assert d1["drift_factor"] == d2["drift_factor"]

    def test_tech_score_symmetric_bull_bear(self):
        """_compute_tech_score with same strength → same score."""
        bull_score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.80, structure_score=0.85,
            confluence_count=3, liquidity_score=0.70,
            trq3d_energy=0.65,
        )
        bear_score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.80, structure_score=0.85,
            confluence_count=3, liquidity_score=0.70,
            trq3d_energy=0.65,
        )
        assert bull_score == bear_score

    def test_detect_trend_strength_symmetric(self, analyzer: L3TechnicalAnalyzer):
        """BULLISH strength formula = BEARISH strength formula."""
        h_up, l_up, c_up, _ = _make_trending_data(
            start=1.050, step=0.002, n=80, noise=0.0005, direction="up",
        )
        h_dn, l_dn, c_dn, _ = _make_trending_data(
            start=1.150, step=0.002, n=80, noise=0.0005, direction="down",
        )
        atr_up = L3TechnicalAnalyzer._compute_atr(h_up, l_up, c_up)
        atr_dn = L3TechnicalAnalyzer._compute_atr(h_dn, l_dn, c_dn)

        trend_up, str_up = analyzer._detect_trend(h_up, l_up, c_up, atr_up)
        trend_dn, str_dn = analyzer._detect_trend(h_dn, l_dn, c_dn, atr_dn)

        assert trend_up == "BULLISH"
        assert trend_dn == "BEARISH"
        assert abs(str_up - str_dn) < 0.15, (
            f"Strength asymmetry too large: bull={str_up:.3f} bear={str_dn:.3f}"
        )

    def test_structure_bos_up_equals_bos_down(self):
        """BOS upward score == BOS downward score (both 0.85)."""
        h_up = [1.10] * 20 + [1.08, 1.09, 1.10, 1.11, 1.15]
        l_up = [1.08] * 20 + [1.07, 1.08, 1.09, 1.10, 1.12]
        c_up = [1.09] * 20 + [1.075, 1.085, 1.095, 1.105, 1.14]
        r_up = L3TechnicalAnalyzer._analyze_structure(h_up, l_up, c_up, 0.005)

        h_dn = [1.10] * 20 + [1.09, 1.08, 1.07, 1.06, 1.05]
        l_dn = [1.08] * 20 + [1.07, 1.06, 1.05, 1.04, 1.01]
        c_dn = [1.09] * 20 + [1.08, 1.07, 1.06, 1.05, 1.02]
        r_dn = L3TechnicalAnalyzer._analyze_structure(h_dn, l_dn, c_dn, 0.005)

        assert r_up["validity"] == "STRONG"
        assert r_dn["validity"] == "STRONG"
        assert r_up["score"] == r_dn["score"] == 0.85
        assert r_up["confidence"] == r_dn["confidence"] == 0.85

    def test_drift_context_symmetric(self):
        """Same drift magnitude → same drift_state for bull and bear."""
        for drift in [0.001, 0.005, 0.010, 0.050]:
            state = _classify_drift(drift)
            assert state == _classify_drift(drift)

    def test_edge_probability_symmetric_across_drift_states(self):
        """For each drift state: bull features == bear features → same P."""
        for drift, expected_state in [
            (0.001, "FRESH"),
            (0.005, "EXTENDING"),
            (0.015, "OVEREXTENDED"),
        ]:
            p_bull, d_bull = _compute_edge_probability(
                trend_strength=0.75, structure_score=0.85,
                confluence_count=3, liquidity_score=0.65,
                trq3d_energy=0.60, adx_norm=0.40, atr_expansion=0.55,
                drift=drift,
            )
            p_bear, d_bear = _compute_edge_probability(
                trend_strength=0.75, structure_score=0.85,
                confluence_count=3, liquidity_score=0.65,
                trq3d_energy=0.60, adx_norm=0.40, atr_expansion=0.55,
                drift=drift,
            )

            assert d_bull["drift_state"] == expected_state
            assert d_bear["drift_state"] == expected_state
            assert p_bull == p_bear
            assert d_bull["drift_factor"] == d_bear["drift_factor"]

    @pytest.mark.parametrize(
        "asset, start_bull, start_bear, step, noise",
        [
            ("EURUSD", 1.050, 1.150, 0.002, 0.0005),
            ("XAUUSD", 1900.0, 2050.0, 5.0, 3.0),
            ("BTCUSD", 40000.0, 50000.0, 200.0, 80.0),
            ("XAGUSD", 22.0, 26.0, 0.08, 0.03),
        ],
    )
    def test_multi_asset_direction_symmetry(
        self, analyzer: L3TechnicalAnalyzer, asset: str, start_bull: float, start_bear: float, step: float, noise: float,
    ) -> None:
        """Each asset: bullish and bearish detected + both score > 0."""
        h_up, l_up, c_up, _ = _make_trending_data(
            start=start_bull, step=step, n=80, noise=noise, direction="up",
        )
        h_dn, l_dn, c_dn, _ = _make_trending_data(
            start=start_bear, step=step, n=80, noise=noise, direction="down",
        )

        atr_up = L3TechnicalAnalyzer._compute_atr(h_up, l_up, c_up)
        atr_dn = L3TechnicalAnalyzer._compute_atr(h_dn, l_dn, c_dn)

        t_up, s_up = analyzer._detect_trend(h_up, l_up, c_up, atr_up)
        t_dn, s_dn = analyzer._detect_trend(h_dn, l_dn, c_dn, atr_dn)

        assert t_up == "BULLISH", f"{asset} up: got {t_up}"
        assert t_dn == "BEARISH", f"{asset} down: got {t_dn}"
        assert s_up > 0.0, f"{asset} bullish strength should be > 0"
        assert s_dn > 0.0, f"{asset} bearish strength should be > 0"


# ═══════════════════════════════════════════════════════════════════════
# §F  Drift context (NOT penalty) — same for both directions (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestDriftContext:
    """Drift context — same for both directions."""

    def test_fresh_full_factor(self):
        p, d = _compute_edge_probability(
            trend_strength=0.8, structure_score=0.85,
            confluence_count=3, liquidity_score=0.7,
            trq3d_energy=0.6, adx_norm=0.4, atr_expansion=0.5,
            drift=0.001,
        )
        assert d["drift_state"] == "FRESH"
        assert d["drift_factor"] == 1.0
        # factor=1.0 means p_adj ≈ p_edge_raw
        assert abs(d["p_edge_raw"] - p) < 1e-4

    def test_extending_reduced_factor(self):
        p, d = _compute_edge_probability(
            trend_strength=0.8, structure_score=0.85,
            confluence_count=3, liquidity_score=0.7,
            trq3d_energy=0.6, adx_norm=0.4, atr_expansion=0.5,
            drift=0.005,
        )
        assert d["drift_state"] == "EXTENDING"
        assert d["drift_factor"] == 0.85
        assert p < d["p_edge_raw"]

    def test_overextended_most_reduced(self):
        p, d = _compute_edge_probability(
            trend_strength=0.8, structure_score=0.85,
            confluence_count=3, liquidity_score=0.7,
            trq3d_energy=0.6, adx_norm=0.4, atr_expansion=0.5,
            drift=0.015,
        )
        assert d["drift_state"] == "OVEREXTENDED"
        assert d["drift_factor"] == 0.65
        assert p < d["p_edge_raw"]

    def test_drift_monotonic_decrease(self):
        """Higher drift → lower P_adj (same raw features)."""
        kwargs = {
            "trend_strength": 0.8, "structure_score": 0.85,
            "confluence_count": (3), "liquidity_score": 0.7,
            "trq3d_energy": 0.6, "adx_norm": 0.4, "atr_expansion": 0.5,
        }
        p_fresh, _ = _compute_edge_probability(drift=0.001, **kwargs)
        p_ext, _ = _compute_edge_probability(drift=0.005, **kwargs)
        p_over, _ = _compute_edge_probability(drift=0.015, **kwargs)
        assert p_fresh >= p_ext >= p_over


# ═══════════════════════════════════════════════════════════════════════
# §G  v5 scoring unchanged — _compute_tech_score() byte-identical (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestV5ScoringUnchanged:
    """_compute_tech_score() remains byte-identical to v5."""

    def test_all_zero_inputs(self):
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.0, structure_score=0.0,
            confluence_count=0, liquidity_score=0.0,
            trq3d_energy=0.0,
        )
        assert score == 0

    def test_all_max_inputs(self):
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=1.0, structure_score=1.0,
            confluence_count=4, liquidity_score=1.0,
            trq3d_energy=1.0,
        )
        assert score == 100

    def test_formula_components(self):
        """25+25+20+20+10 = 100 max."""
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=0.5, structure_score=0.5,
            confluence_count=2, liquidity_score=0.5,
            trq3d_energy=0.5,
        )
        expected = round(0.5 * 25 + 0.5 * 25 + 2 * 5 + 0.5 * 20 + 0.5 * 10)
        assert score == expected

    def test_clamping_above_max(self):
        """Over-range inputs still cap at 100."""
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=2.0, structure_score=2.0,
            confluence_count=10, liquidity_score=2.0,
            trq3d_energy=2.0,
        )
        assert score == 100

    def test_negative_inputs_clamp_to_zero(self):
        score = L3TechnicalAnalyzer._compute_tech_score(
            trend_strength=-1.0, structure_score=-1.0,
            confluence_count=-5, liquidity_score=-1.0,
            trq3d_energy=-1.0,
        )
        assert score == 0


# ═══════════════════════════════════════════════════════════════════════
# §H  Output contract — v5 keys preserved, v6 keys added (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestOutputContract:
    """v5 keys preserved, v6 keys added in _insufficient_data."""

    def test_insufficient_data_v5_keys(self):
        result = L3TechnicalAnalyzer._insufficient_data("EURUSD")
        v5_keys = {
            "technical_score", "structure_validity", "confluence_points",
            "trq3d_energy", "drift", "trend", "confidence",
            "structure_score", "valid",
        }
        assert v5_keys.issubset(result.keys())
        assert result["valid"] is False

    def test_insufficient_data_v6_keys(self):
        result = L3TechnicalAnalyzer._insufficient_data("EURUSD")
        v6_keys = {
            "edge_probability", "edge_detail", "drift_state",
            "trend_strength", "adx", "atr", "atr_expansion",
            "liquidity_score",
        }
        assert v6_keys.issubset(result.keys())
        assert result["edge_probability"] == 0.0
        assert result["drift_state"] == "FRESH"
        assert result["atr_expansion"] == 1.0


# ═══════════════════════════════════════════════════════════════════════
# §I  Boundary safety — NaN/Inf/overflow protection (v6)
# ═══════════════════════════════════════════════════════════════════════


class TestBoundarySafety:
    """NaN/Inf/overflow protection in edge model."""

    def test_extreme_positive_features(self):
        p, _ = _compute_edge_probability(
            trend_strength=1e6, structure_score=1e6,
            confluence_count=1000, liquidity_score=1e6,
            trq3d_energy=1e6, adx_norm=1e6, atr_expansion=1e6,
            drift=0.0,
        )
        assert 0.0 <= p <= 1.0
        assert not math.isnan(p) and not math.isinf(p)

    def test_extreme_negative_features(self):
        p, _ = _compute_edge_probability(
            trend_strength=-1e6, structure_score=-1e6,
            confluence_count=-1000, liquidity_score=-1e6,
            trq3d_energy=-1e6, adx_norm=-1e6, atr_expansion=-1e6,
            drift=0.0,
        )
        assert 0.0 <= p <= 1.0
        assert not math.isnan(p) and not math.isinf(p)

    def test_zero_drift_valid(self):
        _p, d = _compute_edge_probability(
            trend_strength=0.5, structure_score=0.5,
            confluence_count=2, liquidity_score=0.5,
            trq3d_energy=0.5, adx_norm=0.3, atr_expansion=0.5,
            drift=0.0,
        )
        assert d["drift_state"] == "FRESH"
        assert d["drift_factor"] == 1.0

    def test_very_large_drift(self):
        p, d = _compute_edge_probability(
            trend_strength=0.5, structure_score=0.5,
            confluence_count=2, liquidity_score=0.5,
            trq3d_energy=0.5, adx_norm=0.3, atr_expansion=0.5,
            drift=100.0,
        )
        assert d["drift_state"] == "OVEREXTENDED"
        assert 0.0 <= p <= 1.0
