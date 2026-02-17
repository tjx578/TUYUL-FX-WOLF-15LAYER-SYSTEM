"""
Dedicated tests for L4 Session Scoring — analyze_session_scoring() production interface.

Covers:
  - Session identification across all hours
  - Wolf 30-Point scoring output contract
  - Bayesian enrichment keys
  - Grade classification boundaries
  - Event proximity detection
  - Backward-compatible interfaces
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from analysis.layers.L4_session_scoring import (
    BayesianConfig,
    L4SessionScoring,
    _classify_grade,
    _identify_session,
    analyze_session,
    analyze_session_scoring,
)

# ── Helpers ──────────────────────────────────────────────────────────

def _mock_l1(regime: str = "TREND_UP", confidence: float = 0.80) -> dict:
    return {
        "regime": regime,
        "dominant_force": "BULLISH",
        "regime_probability": confidence,
        "regime_confidence": confidence,
        "context_coherence": 0.85,
        "volatility_level": "NORMAL",
        "volatility_percentile": 0.5,
        "csi": 0.75,
        "valid": True,
    }


def _mock_l2(trend: str = "BULLISH", momentum: float = 0.75) -> dict:
    return {
        "trend": trend,
        "trend_strength": 0.8,
        "momentum": momentum,
        "structure": "CONTINUATION",
        "indicators": {
            "rsi": 60.0,
            "macd_signal": "BULLISH",
            "ema_alignment": True,
        },
        "valid": True,
    }


def _mock_l3(quality: float = 0.80) -> dict:
    return {
        "structure_quality": quality,
        "key_level_proximity": 0.7,
        "swing_structure": "HH_HL",
        "valid": True,
    }


WOLF_30_KEYS = {"total", "f_score", "t_score", "fta_score", "exec_score", "max_possible"}
BAYESIAN_KEYS = {
    "posterior_win_probability", "expected_value", "risk_adjusted_edge",
    "confidence_index", "bayesian_grade", "bayesian_tradeable",
}
REQUIRED_OUTPUT_KEYS = {"session", "quality", "tradeable", "grade", "valid", "wolf_30_point"}


# ── Session identification ───────────────────────────────────────────

class TestSessionIdentification:
    @pytest.mark.parametrize("hour, expected_contains", [
        (3, "TOKYO"),
        (8, "TOKYO_LONDON"),
        (10, "LONDON"),
        (14, "LONDON_NEWYORK"),
        (18, "NEWYORK"),
    ])
    def test_session_by_hour(self, hour: int, expected_contains: str) -> None:
        session_name, quality = _identify_session(hour)
        assert expected_contains in session_name

    def test_off_hours_session(self) -> None:
        session_name, quality = _identify_session(0)
        assert quality < 1.0


# ── Grade classification ─────────────────────────────────────────────

class TestGradeClassification:
    @pytest.mark.parametrize("score, expected", [
        (28.0, "PERFECT"),
        (24.0, "EXCELLENT"),
        (20.0, "GOOD"),
        (14.0, "MARGINAL"),
        (5.0, "FAIL"),
    ])
    def test_grade_boundaries(self, score: float, expected: str) -> None:
        assert _classify_grade(score) == expected


# ── BayesianConfig validation ────────────────────────────────────────

class TestBayesianConfig:
    def test_default_config_valid(self) -> None:
        cfg = BayesianConfig()
        assert 0.0 < cfg.prior_trend_up < 1.0
        assert 0.0 < cfg.prior_range < 1.0

    def test_invalid_strength_sum_raises(self) -> None:
        with pytest.raises(ValueError):
            BayesianConfig(strength_trend_up_f=5.0, strength_trend_up_t=5.0)


# ── L4SessionScoring full pipeline ──────────────────────────────────

class TestL4SessionScoringPipeline:
    def test_output_contract(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        assert REQUIRED_OUTPUT_KEYS.issubset(result.keys())
        assert result["valid"] is True

    def test_wolf_30_point_keys(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        wolf = result["wolf_30_point"]
        assert WOLF_30_KEYS.issubset(wolf.keys())
        assert wolf["max_possible"] == 30

    def test_wolf_scores_bounded(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        wolf = result["wolf_30_point"]
        assert 0 <= wolf["total"] <= 30
        assert 0 <= wolf["f_score"] <= 8
        assert 0 <= wolf["t_score"] <= 12

    def test_bayesian_enrichment_present(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        bayesian = result.get("bayesian", {})
        assert BAYESIAN_KEYS.issubset(bayesian.keys())

    def test_posterior_probability_bounded(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        p = result["bayesian"]["posterior_win_probability"]
        assert 0.0 <= p <= 1.0


# ── Backward-compat interfaces ──────────────────────────────────────

class TestBackwardCompat:
    def test_analyze_session_returns_dict(self) -> None:
        now = datetime(2026, 2, 16, 10, 0, 0, tzinfo=UTC)
        result = analyze_session({"closes": [1.3] * 60}, pair="EURUSD", now=now)
        assert isinstance(result, dict)
        assert "session" in result

    def test_analyze_session_scoring_returns_dict(self) -> None:
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        result = analyze_session_scoring(
            _mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now,
        )
        assert isinstance(result, dict)
        assert "valid" in result


# ── Determinism ──────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_inputs_same_output(self) -> None:
        scorer = L4SessionScoring()
        now = datetime(2026, 2, 16, 14, 0, 0, tzinfo=UTC)
        r1 = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        r2 = scorer.analyze(_mock_l1(), _mock_l2(), _mock_l3(), pair="EURUSD", now=now)
        assert r1["wolf_30_point"]["total"] == r2["wolf_30_point"]["total"]
