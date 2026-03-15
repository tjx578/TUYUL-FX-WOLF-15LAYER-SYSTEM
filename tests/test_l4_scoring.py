"""
Tests for Layer 4 — Multi-Factor Scoring Engine.
Zone: Analysis. No execution side-effects.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from analysis.l4_scoring import (
    DEFAULT_PASS_THRESHOLD,
    FactorScores,
    L4Result,
    ScoreGrade,
    ScoringWeights,
    classify_grade,
    compute_composite,
    score,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_weights() -> ScoringWeights:
    return ScoringWeights()


@pytest.fixture
def perfect_factors() -> FactorScores:
    return FactorScores(
        trend_alignment=100.0,
        structure_quality=100.0,
        momentum=100.0,
        volume_confirmation=100.0,
        multi_timeframe_confluence=100.0,
        key_level_proximity=100.0,
    )


@pytest.fixture
def zero_factors() -> FactorScores:
    return FactorScores(
        trend_alignment=0.0,
        structure_quality=0.0,
        momentum=0.0,
        volume_confirmation=0.0,
        multi_timeframe_confluence=0.0,
        key_level_proximity=0.0,
    )


@pytest.fixture
def mixed_factors() -> FactorScores:
    return FactorScores(
        trend_alignment=80.0,
        structure_quality=60.0,
        momentum=70.0,
        volume_confirmation=40.0,
        multi_timeframe_confluence=90.0,
        key_level_proximity=50.0,
    )


# ---------------------------------------------------------------------------
# ScoringWeights validation
# ---------------------------------------------------------------------------

class TestScoringWeights:
    def test_default_weights_sum_to_one(self, default_weights: ScoringWeights) -> None:
        total = (
            default_weights.trend_alignment
            + default_weights.structure_quality
            + default_weights.momentum
            + default_weights.volume_confirmation
            + default_weights.multi_timeframe_confluence
            + default_weights.key_level_proximity
        )
        assert abs(total - 1.0) < 1e-6

    def test_custom_weights_valid(self) -> None:
        w = ScoringWeights(
            trend_alignment=0.50,
            structure_quality=0.10,
            momentum=0.10,
            volume_confirmation=0.10,
            multi_timeframe_confluence=0.10,
            key_level_proximity=0.10,
        )
        assert w.trend_alignment == 0.50

    def test_custom_weights_invalid_sum_raises(self) -> None:
        with pytest.raises(ValueError, match="must sum to 1.0"):
            ScoringWeights(
                trend_alignment=0.50,
                structure_quality=0.50,
                momentum=0.50,
                volume_confirmation=0.0,
                multi_timeframe_confluence=0.0,
                key_level_proximity=0.0,
            )


# ---------------------------------------------------------------------------
# FactorScores validation
# ---------------------------------------------------------------------------

class TestFactorScores:
    def test_valid_factors(self) -> None:
        f = FactorScores(
            trend_alignment=50.0,
            structure_quality=50.0,
            momentum=50.0,
            volume_confirmation=50.0,
            multi_timeframe_confluence=50.0,
            key_level_proximity=50.0,
        )
        assert f.trend_alignment == 50.0

    @pytest.mark.parametrize("field_name", [
        "trend_alignment",
        "structure_quality",
        "momentum",
        "volume_confirmation",
        "multi_timeframe_confluence",
        "key_level_proximity",
    ])
    def test_factor_below_zero_raises(self, field_name: str) -> None:
        kwargs = {
            "trend_alignment": 50.0,
            "structure_quality": 50.0,
            "momentum": 50.0,
            "volume_confirmation": 50.0,
            "multi_timeframe_confluence": 50.0,
            "key_level_proximity": 50.0,
        }
        kwargs[field_name] = -1.0
        with pytest.raises(ValueError, match="must be 0–100"):
            FactorScores(**kwargs)

    @pytest.mark.parametrize("field_name", [
        "trend_alignment",
        "structure_quality",
        "momentum",
        "volume_confirmation",
        "multi_timeframe_confluence",
        "key_level_proximity",
    ])
    def test_factor_above_100_raises(self, field_name: str) -> None:
        kwargs = {
            "trend_alignment": 50.0,
            "structure_quality": 50.0,
            "momentum": 50.0,
            "volume_confirmation": 50.0,
            "multi_timeframe_confluence": 50.0,
            "key_level_proximity": 50.0,
        }
        kwargs[field_name] = 101.0
        with pytest.raises(ValueError, match="must be 0–100"):
            FactorScores(**kwargs)


# ---------------------------------------------------------------------------
# compute_composite
# ---------------------------------------------------------------------------

class TestComputeComposite:
    def test_perfect_score(self, perfect_factors: FactorScores) -> None:
        result = compute_composite(perfect_factors)
        assert result == 100.0

    def test_zero_score(self, zero_factors: FactorScores) -> None:
        result = compute_composite(zero_factors)
        assert result == 0.0

    def test_mixed_score_within_bounds(self, mixed_factors: FactorScores) -> None:
        result = compute_composite(mixed_factors)
        assert 0.0 <= result <= 100.0

    def test_mixed_score_deterministic(self, mixed_factors: FactorScores) -> None:
        r1 = compute_composite(mixed_factors)
        r2 = compute_composite(mixed_factors)
        assert r1 == r2

    def test_mixed_score_expected_value(self, mixed_factors: FactorScores) -> None:
        """Manual calculation with default weights:
        80*0.25 + 60*0.20 + 70*0.15 + 40*0.10 + 90*0.15 + 50*0.15
        = 20 + 12 + 10.5 + 4 + 13.5 + 7.5 = 67.5
        """
        result = compute_composite(mixed_factors)
        assert result == 67.5

    def test_custom_weights_applied(self, mixed_factors: FactorScores) -> None:
        heavy_trend = ScoringWeights(
            trend_alignment=0.60,
            structure_quality=0.08,
            momentum=0.08,
            volume_confirmation=0.08,
            multi_timeframe_confluence=0.08,
            key_level_proximity=0.08,
        )
        result = compute_composite(mixed_factors, heavy_trend)
        # 80*0.60 + 60*0.08 + 70*0.08 + 40*0.08 + 90*0.08 + 50*0.08
        # = 48 + 4.8 + 5.6 + 3.2 + 7.2 + 4.0 = 72.8
        assert result == 72.8


# ---------------------------------------------------------------------------
# classify_grade
# ---------------------------------------------------------------------------

class TestClassifyGrade:
    @pytest.mark.parametrize("score_val, expected_grade", [
        (100.0, ScoreGrade.A_PLUS),
        (95.0, ScoreGrade.A_PLUS),
        (90.0, ScoreGrade.A_PLUS),
        (89.9, ScoreGrade.A),
        (80.0, ScoreGrade.A),
        (79.9, ScoreGrade.B),
        (65.0, ScoreGrade.B),
        (64.9, ScoreGrade.C),
        (50.0, ScoreGrade.C),
        (49.9, ScoreGrade.D),
        (35.0, ScoreGrade.D),
        (34.9, ScoreGrade.F),
        (0.0, ScoreGrade.F),
    ])
    def test_grade_boundaries(self, score_val: float, expected_grade: ScoreGrade) -> None:
        assert classify_grade(score_val) == expected_grade


# ---------------------------------------------------------------------------
# score() — full pipeline
# ---------------------------------------------------------------------------

class TestScoreFunction:
    def test_returns_l4_result(self, mixed_factors: FactorScores) -> None:
        result = score("EURUSD", mixed_factors)
        assert isinstance(result, L4Result)

    def test_result_is_immutable(self, mixed_factors: FactorScores) -> None:
        result = score("EURUSD", mixed_factors)
        with pytest.raises(AttributeError):
            result.composite_score = 0.0  # type: ignore[misc]

    def test_symbol_preserved(self, mixed_factors: FactorScores) -> None:
        result = score("GBPJPY", mixed_factors)
        assert result.symbol == "GBPJPY"

    def test_pass_threshold_default(self, mixed_factors: FactorScores) -> None:
        result = score("EURUSD", mixed_factors)
        # 67.5 >= 55.0
        assert result.pass_threshold is True
        assert result.threshold_used == DEFAULT_PASS_THRESHOLD

    def test_fail_threshold(self, zero_factors: FactorScores) -> None:
        result = score("EURUSD", zero_factors)
        assert result.pass_threshold is False

    def test_custom_threshold(self, mixed_factors: FactorScores) -> None:
        result = score("EURUSD", mixed_factors, threshold=70.0)
        # 67.5 < 70.0
        assert result.pass_threshold is False
        assert result.threshold_used == 70.0

    def test_dominant_and_weakness_identified(self, mixed_factors: FactorScores) -> None:
        result = score("EURUSD", mixed_factors)
        assert result.dominant_factor != ""
        assert result.weakness_factor != ""
        assert result.dominant_factor != result.weakness_factor

    def test_metadata_passthrough(self, mixed_factors: FactorScores) -> None:
        meta = {"timeframe": "H4", "session": "london"}
        result = score("EURUSD", mixed_factors, metadata=meta)
        assert result.metadata == meta

    def test_no_side_effects(self, mixed_factors: FactorScores) -> None:
        """L4 is analysis zone: calling score() must not modify inputs."""
        original_trend = mixed_factors.trend_alignment
        _ = score("EURUSD", mixed_factors)
        assert mixed_factors.trend_alignment == original_trend
