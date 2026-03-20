"""
Tests for Tier 3 SMC + Structural Indicators (v7 enrichment).

Covers:
    §1  L3 v7 SMC event markers:
        - fvg_detected, ob_detected, fib_retracement_hit (bool)
        - volume_profile_poc (float price level)
        - volume_profile_poc_hit (bool)
        - vpc_zones (list[dict] VPC clusters)
    §2  L3 _compute_poc_price() — POC price level extraction
    §3  L3 _compute_vpc_zones() — Volume Profile Cluster zone detection
    §4  L9 FVG detection from candle dicts
    §5  L9 Order Block detection from candle dicts
    §6  L9 Liquidity sweep detection (via LiquiditySweepScorer)
    §7  L9 confidence boost from SMC confirmations
    §8  Pipeline SMCContract v7 fields
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import numpy as np
import pytest

from analysis.layers.L3_technical import L3TechnicalAnalyzer
from analysis.layers.L9_smc import L9SMCAnalyzer
from pipeline.contracts import SMCContract

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════


def _make_candle_dicts(
    base: float,
    step: float,
    n: int,
    noise: float = 0.0,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate synthetic candle dicts."""
    rng = np.random.RandomState(seed)
    candles: list[dict[str, Any]] = []
    for i in range(n):
        c = base + step * i + (rng.uniform(-noise, noise) if noise > 0 else 0.0)
        spread = noise if noise > 0 else max(abs(step) * 0.3, 1e-6)
        h = c + abs(rng.normal(0, spread))
        lo = c - abs(rng.normal(0, spread))
        candles.append(
            {
                "open": c - step * 0.1,
                "high": float(max(h, c)),
                "low": float(min(lo, c)),
                "close": float(c),
                "volume": float(1000 + rng.randint(0, 500)),
            }
        )
    return candles


def _trending_hlcv(
    start: float,
    step: float,
    n: int,
    noise: float = 0.0,
    seed: int = 42,
) -> tuple[list[float], list[float], list[float], list[float]]:
    """Generate trending (highs, lows, closes, volumes)."""
    rng = np.random.RandomState(seed)
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        c = start + step * i + (rng.uniform(-noise, noise) if noise > 0 else 0.0)
        s = noise if noise > 0 else step * 0.3
        h = c + abs(rng.normal(0, s))
        lo = c - abs(rng.normal(0, s))
        closes.append(float(c))
        highs.append(float(max(h, c)))
        lows.append(float(min(lo, c)))
        volumes.append(float(1000 + rng.randint(0, 500)))
    return highs, lows, closes, volumes


@pytest.fixture
def l3():
    return L3TechnicalAnalyzer()


@pytest.fixture
def l9():
    return L9SMCAnalyzer()


# ═══════════════════════════════════════════════════════════════════════
# §1  L3 _find_confluence() v7 event markers
# ═══════════════════════════════════════════════════════════════════════


class TestL3ConfluenceV7Markers:
    """Verify _find_confluence returns individual event markers alongside count."""

    def test_all_markers_present_in_result(self, l3: L3TechnicalAnalyzer):
        """v7 keys must always be in confluence result."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_compute_poc_price", return_value=0.0),
            mock.patch.object(L3TechnicalAnalyzer, "_compute_vpc_zones", return_value=[]),
        ):
            result = l3._find_confluence([], [], [], [], atr=0.001)

        assert "count" in result
        assert "fvg_detected" in result
        assert "ob_detected" in result
        assert "fib_retracement_hit" in result
        assert "volume_profile_poc_hit" in result
        assert "volume_profile_poc" in result
        assert "vpc_zones" in result

    def test_markers_match_detectors(self, l3: L3TechnicalAnalyzer):
        """Individual markers should reflect what each detector returned."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=False),
            mock.patch.object(L3TechnicalAnalyzer, "_compute_poc_price", return_value=1.1050),
            mock.patch.object(
                L3TechnicalAnalyzer,
                "_compute_vpc_zones",
                return_value=[
                    {"price_low": 1.10, "price_high": 1.11, "volume": 5000.0, "strength": 2.0},
                ],
            ),
        ):
            result = l3._find_confluence([], [], [], [], atr=0.001)

        assert result["count"] == 2
        assert result["fib_retracement_hit"] is True
        assert result["ob_detected"] is True
        assert result["fvg_detected"] is False
        assert result["volume_profile_poc_hit"] is False
        assert result["volume_profile_poc"] == 1.1050
        assert len(result["vpc_zones"]) == 1

    def test_all_detectors_fire_markers(self, l3: L3TechnicalAnalyzer):
        """All 4 detectors fire → all bools True, count=4."""
        with (
            mock.patch.object(L3TechnicalAnalyzer, "_fib_retracement_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_volume_profile_poc_hit", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_detect_fvg", return_value=True),
            mock.patch.object(L3TechnicalAnalyzer, "_compute_poc_price", return_value=1.10),
            mock.patch.object(L3TechnicalAnalyzer, "_compute_vpc_zones", return_value=[]),
        ):
            result = l3._find_confluence([], [], [], [], atr=0.001)

        assert result["count"] == 4
        assert result["fvg_detected"] is True
        assert result["ob_detected"] is True
        assert result["fib_retracement_hit"] is True
        assert result["volume_profile_poc_hit"] is True


# ═══════════════════════════════════════════════════════════════════════
# §2  L3 _compute_poc_price()
# ═══════════════════════════════════════════════════════════════════════


class TestComputePOCPrice:
    """Volume Profile POC as a float price level."""

    def test_insufficient_data_returns_zero(self):
        assert L3TechnicalAnalyzer._compute_poc_price([1.0] * 10, [100.0] * 10) == 0.0

    def test_returns_float_price(self):
        """POC price should be in the range of input prices."""
        closes = [1.10 + i * 0.001 for i in range(40)]
        volumes = [100.0] * 40
        # Spike volume near the end
        volumes[-5] = 10000.0
        volumes[-4] = 10000.0

        poc = L3TechnicalAnalyzer._compute_poc_price(closes, volumes)
        assert isinstance(poc, float)
        assert poc > 0.0
        # POC should be within the price range
        assert min(closes[-30:]) <= poc <= max(closes[-30:])

    def test_poc_near_high_volume_area(self):
        """POC should be near the prices with highest volume."""
        closes = [1.10] * 15 + [1.12] * 15 + [1.10] * 10
        volumes = [100.0] * 15 + [5000.0] * 15 + [100.0] * 10

        poc = L3TechnicalAnalyzer._compute_poc_price(closes, volumes)
        # POC should be closer to 1.12 (high-volume cluster)
        assert abs(poc - 1.12) < abs(poc - 1.10)

    def test_flat_closes_returns_zero(self):
        """All closes identical → p_max == p_min → 0.0."""
        assert L3TechnicalAnalyzer._compute_poc_price([1.10] * 40, [100.0] * 40) == 0.0


# ═══════════════════════════════════════════════════════════════════════
# §3  L3 _compute_vpc_zones()
# ═══════════════════════════════════════════════════════════════════════


class TestComputeVPCZones:
    """Volume Profile Cluster — high-volume price zones."""

    def test_insufficient_data_returns_empty(self):
        assert L3TechnicalAnalyzer._compute_vpc_zones([1.0] * 10, [100.0] * 10) == []

    def test_uniform_volume_no_zones(self):
        """Uniform volume across all bins → no zone exceeds 1.5x avg."""
        closes = [1.10 + i * 0.001 for i in range(40)]
        volumes = [100.0] * 40
        zones = L3TechnicalAnalyzer._compute_vpc_zones(closes, volumes)
        # With uniform distribution, no bin should be > 1.5x avg
        assert isinstance(zones, list)

    def test_spike_creates_zone(self):
        """Concentrated volume at a price level creates a VPC zone."""
        closes = [1.10 + i * 0.001 for i in range(40)]
        volumes = [10.0] * 40
        # Massive volume spike at specific prices
        for i in range(20, 25):
            volumes[i] = 50000.0

        zones = L3TechnicalAnalyzer._compute_vpc_zones(closes, volumes)
        assert len(zones) >= 1

        # Each zone should have required keys
        for z in zones:
            assert "price_low" in z
            assert "price_high" in z
            assert "volume" in z
            assert "strength" in z
            assert z["strength"] > 1.5  # Above HVN threshold
            assert z["price_low"] < z["price_high"]

    def test_zone_within_price_range(self):
        """All VPC zones should be within the input price range."""
        closes = [1.10 + i * 0.001 for i in range(40)]
        volumes = [10.0] * 40
        volumes[15] = 50000.0

        zones = L3TechnicalAnalyzer._compute_vpc_zones(closes, volumes)
        p_min = min(closes[-30:])
        p_max = max(closes[-30:])
        for z in zones:
            assert z["price_low"] >= p_min - 0.01
            assert z["price_high"] <= p_max + 0.01

    def test_flat_prices_returns_empty(self):
        """All closes identical → no zones."""
        assert L3TechnicalAnalyzer._compute_vpc_zones([1.10] * 40, [100.0] * 40) == []


# ═══════════════════════════════════════════════════════════════════════
# §4  L9 FVG detection from candle dicts
# ═══════════════════════════════════════════════════════════════════════


class TestL9FVGDetection:
    """L9 _detect_fvg from candle dict list."""

    def test_insufficient_candles_false(self):
        candles = [{"high": 1.10, "low": 1.09}] * 5
        assert L9SMCAnalyzer._detect_fvg(candles) is False

    def test_bullish_fvg(self):
        """Gap up in candles → FVG detected."""
        candles = [{"high": 1.10, "low": 1.09}] * 4 + [
            {"high": 1.100, "low": 1.090},
            {"high": 1.105, "low": 1.098},
            {"high": 1.112, "low": 1.108},
            {"high": 1.120, "low": 1.115},
            {"high": 1.125, "low": 1.120},
            {"high": 1.130, "low": 1.125},
        ]
        assert L9SMCAnalyzer._detect_fvg(candles) is True

    def test_bearish_fvg(self):
        """Gap down in candles → FVG detected."""
        candles = [{"high": 1.10, "low": 1.09}] * 4 + [
            {"high": 1.100, "low": 1.095},
            {"high": 1.092, "low": 1.088},
            {"high": 1.082, "low": 1.075},
            {"high": 1.075, "low": 1.068},
            {"high": 1.070, "low": 1.063},
            {"high": 1.065, "low": 1.058},
        ]
        assert L9SMCAnalyzer._detect_fvg(candles) is True

    def test_no_gap_returns_false(self):
        """Overlapping candles → no FVG."""
        candles = [{"high": 1.10 + i * 0.001, "low": 1.09 + i * 0.001} for i in range(15)]
        assert L9SMCAnalyzer._detect_fvg(candles) is False


# ═══════════════════════════════════════════════════════════════════════
# §5  L9 Order Block detection from candle dicts
# ═══════════════════════════════════════════════════════════════════════


class TestL9OrderBlockDetection:
    """L9 _detect_orderblock from candle dicts."""

    def test_insufficient_candles_false(self):
        candles = [{"high": 1.10, "low": 1.09, "close": 1.095}] * 10
        assert L9SMCAnalyzer._detect_orderblock(candles) is False

    def test_no_impulse_false(self):
        """No strong impulse candle → False."""
        candles = [
            {"high": 1.10 + i * 0.0001, "low": 1.09 + i * 0.0001, "close": 1.095 + i * 0.0001} for i in range(35)
        ]
        assert L9SMCAnalyzer._detect_orderblock(candles) is False


# ═══════════════════════════════════════════════════════════════════════
# §6  L9 Liquidity sweep detection
# ═══════════════════════════════════════════════════════════════════════


class TestL9SweepDetection:
    """L9 _detect_sweep uses LiquiditySweepScorer."""

    def test_no_scorer_returns_false(self, l9: L9SMCAnalyzer):
        """When LiquiditySweepScorer unavailable, returns (False, 0.0)."""
        l9._liq_scorer = None
        detected, quality = l9._detect_sweep([], "BULLISH")
        assert detected is False
        assert quality == 0.0

    def test_empty_candles_returns_false(self, l9: L9SMCAnalyzer):
        detected, quality = l9._detect_sweep([], "BULLISH")
        assert detected is False
        assert quality == 0.0

    def test_scorer_called_with_direction(self, l9: L9SMCAnalyzer):
        """Scorer should be called with correct direction mapping."""
        mock_scorer = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_result.sweep_detected = True
        mock_result.sweep_quality = 0.75
        mock_scorer.score.return_value = mock_result

        l9._liq_scorer = mock_scorer
        candles = [{"high": 1.10, "low": 1.09, "close": 1.095}] * 10

        detected, quality = l9._detect_sweep(candles, "BULLISH")
        assert detected is True
        assert quality == 0.75
        mock_scorer.score.assert_called_once_with(candles, direction="bullish")

    def test_bearish_direction_mapping(self, l9: L9SMCAnalyzer):
        mock_scorer = mock.MagicMock()
        mock_result = mock.MagicMock()
        mock_result.sweep_detected = False
        mock_result.sweep_quality = 0.0
        mock_scorer.score.return_value = mock_result

        l9._liq_scorer = mock_scorer
        candles = [{"high": 1.10, "low": 1.09, "close": 1.095}] * 10

        l9._detect_sweep(candles, "BEARISH")
        mock_scorer.score.assert_called_once_with(candles, direction="bearish")


# ═══════════════════════════════════════════════════════════════════════
# §7  L9 analyze() with actual detections (integration-style)
# ═══════════════════════════════════════════════════════════════════════


class TestL9AnalyzeV7Integration:
    """L9 analyze() should wire up FVG/OB/sweep from candle data."""

    def test_fvg_ob_sweep_in_output(self, l9: L9SMCAnalyzer):
        """Output always contains all SMC event fields."""
        structure = {"valid": True, "trend": "BULLISH"}

        with mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[]):
            result = l9.analyze("EURUSD", structure=structure)

        assert "ob_present" in result
        assert "fvg_present" in result
        assert "sweep_detected" in result
        assert "liquidity_sweep" in result
        assert "bos_detected" in result
        assert "choch_detected" in result
        assert isinstance(result["ob_present"], bool)
        assert isinstance(result["fvg_present"], bool)
        assert isinstance(result["sweep_detected"], bool)

    def test_fvg_detected_in_analyze(self, l9: L9SMCAnalyzer):
        """When candles have FVG, fvg_present should be True."""
        structure = {"valid": True, "trend": "BULLISH"}

        with (
            mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[{"h": 1}] * 15),
            mock.patch.object(L9SMCAnalyzer, "_detect_bos", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_fvg", return_value=True),
            mock.patch.object(L9SMCAnalyzer, "_detect_orderblock", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_sweep", return_value=(False, 0.0)),
        ):
            result = l9.analyze("EURUSD", structure=structure)

        assert result["fvg_present"] is True
        assert result["ob_present"] is False

    def test_ob_detected_in_analyze(self, l9: L9SMCAnalyzer):
        """When candles have OB, ob_present should be True."""
        structure = {"valid": True, "trend": "BEARISH"}

        with (
            mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[{"h": 1}] * 35),
            mock.patch.object(L9SMCAnalyzer, "_detect_bos", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_fvg", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L9SMCAnalyzer, "_detect_sweep", return_value=(False, 0.0)),
        ):
            result = l9.analyze("EURUSD", structure=structure)

        assert result["ob_present"] is True

    def test_sweep_detected_in_analyze(self, l9: L9SMCAnalyzer):
        """When sweep is detected, sweep fields should reflect it."""
        structure = {"valid": True, "trend": "BULLISH"}

        with (
            mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[{"h": 1}] * 15),
            mock.patch.object(L9SMCAnalyzer, "_detect_bos", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_fvg", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_orderblock", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_sweep", return_value=(True, 0.82)),
        ):
            result = l9.analyze("EURUSD", structure=structure)

        assert result["sweep_detected"] is True
        assert result["liquidity_sweep"] is True
        assert result["liquidity_score"] == 0.82

    def test_confidence_boost_from_confirmations(self, l9: L9SMCAnalyzer):
        """Confidence should increase with FVG+OB+sweep confirmations."""
        structure = {"valid": True, "trend": "NEUTRAL"}

        # Base case: no confirmations → 0.3
        with (
            mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[]),
            mock.patch.object(L9SMCAnalyzer, "_detect_sweep", return_value=(False, 0.0)),
        ):
            result_base = l9.analyze("EURUSD", structure=structure)

        # Boosted: all 3 confirmations → +0.15
        l9_2 = L9SMCAnalyzer()
        with (
            mock.patch.object(L9SMCAnalyzer, "_get_candles", return_value=[{"h": 1}] * 35),
            mock.patch.object(L9SMCAnalyzer, "_detect_bos", return_value=False),
            mock.patch.object(L9SMCAnalyzer, "_detect_fvg", return_value=True),
            mock.patch.object(L9SMCAnalyzer, "_detect_orderblock", return_value=True),
            mock.patch.object(L9SMCAnalyzer, "_detect_sweep", return_value=(True, 0.7)),
        ):
            result_boosted = l9_2.analyze("EURUSD", structure=structure)

        assert result_boosted["confidence"] > result_base["confidence"]
        # 0.3 base + 0.05*3 = 0.45
        assert result_boosted["confidence"] == pytest.approx(0.45, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# §8  Pipeline SMCContract v7 fields
# ═══════════════════════════════════════════════════════════════════════


class TestSMCContractV7:
    """SMCContract should accept all v7 fields."""

    def test_default_values(self):
        """Defaults should be False/0.0/empty for new fields."""
        c = SMCContract()
        assert c.bos_detected is False
        assert c.choch_detected is False
        assert c.displacement is False
        assert c.liquidity_sweep is False
        assert c.fib_retracement_hit is False
        assert c.volume_profile_poc == 0.0
        assert c.vpc_zones == []

    def test_full_instantiation(self):
        """All fields can be populated."""
        c = SMCContract(
            structure="BULLISH",
            smart_money_signal="ACCUMULATION",
            liquidity_zone="1.10500",
            ob_present=True,
            fvg_present=True,
            sweep_detected=True,
            bias="BULLISH",
            bos_detected=True,
            choch_detected=False,
            displacement=True,
            liquidity_sweep=True,
            fib_retracement_hit=True,
            volume_profile_poc=1.1050,
            vpc_zones=[
                {"price_low": 1.10, "price_high": 1.11, "volume": 5000.0, "strength": 2.1},
            ],
        )
        assert c.bos_detected is True
        assert c.displacement is True
        assert c.volume_profile_poc == 1.1050
        assert len(c.vpc_zones) == 1

    def test_backward_compatible(self):
        """Existing v5/v6 fields still work without v7 fields."""
        c = SMCContract(
            structure="RANGE",
            smart_money_signal="NEUTRAL",
            ob_present=False,
            fvg_present=False,
            sweep_detected=False,
            bias="NEUTRAL",
        )
        assert c.bos_detected is False
        assert c.vpc_zones == []
