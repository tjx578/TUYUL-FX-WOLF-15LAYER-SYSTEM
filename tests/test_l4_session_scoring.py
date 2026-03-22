"""
Tests for L4 Session & Timing + Wolf 30-Point + Bayesian Expectancy.
====================================================================

Coverage targets:
  §1-§4  Session logic (preserved from v2)
  §5     Wolf 30-Point scoring (preserved from v2)
  §3B    BayesianConfig validation + stability constraints (§XV)
  §5B    Bayesian engine:
         - Bayesian win probability (§IV-§V)
         - Expectancy model (§VIII)
         - Risk-adjusted edge (§IX)
         - Posterior entropy + confidence index (§XI)
         - Coherence dampener (§VI)
         - Volatility dampener (§VII)
         - Bayesian grade classification (§XIV)
  §6     Full pipeline integration
  §7     Backward-compatible interfaces

Test strategy:
  - Unit tests: pure functions, isolated math verification
  - Integration tests: full pipeline L1→L2→L3→L4 flow
  - Parametrized tests: edge cases, boundary conditions, all regimes
  - Regression tests: backward compatibility byte-identical output
  - Math verification: hand-calculated expected values

Run: pytest tests/test_l4_session_scoring.py -v --tb=short
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from analysis.layers.L4_session_scoring import (
    BayesianConfig,
    L4ScoringEngine,
    L4SessionScoring,
    _bayesian_win_probability,
    _classify_bayesian_grade,
    _classify_grade,
    _compute_bayesian_enrichment,
    _compute_confidence_index,
    _compute_exec_score,
    _compute_expectancy,
    _compute_f_score,
    _compute_fta_score,
    _compute_posterior_entropy,
    _compute_risk_adjusted_edge,
    _compute_session_context,
    _compute_t_score,
    _extract_currencies,
    _get_regime_prior,
    _get_regime_strengths,
    _identify_session,
    _is_near_event,
    _normalize_bias,
    _safe,
    _safe_raw,
    analyze_session,
    analyze_session_scoring,
)

# ═══════════════════════════════════════════════════════════════════════
# TEST FIXTURES
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def bullish_l1() -> dict[str, Any]:
    """Strong bullish L1 output with all v3 fields."""
    return {
        "bias": "BULLISH",
        "confidence": 0.82,
        "strength": 0.75,
        "regime": "TREND_UP",
        "context_coherence": 0.91,
        "volatility_level": "NORMAL",
    }


@pytest.fixture
def bullish_l2() -> dict[str, Any]:
    """Strong bullish L2 output with reflex coherence."""
    return {
        "trend_strength": 0.80,
        "momentum": 0.70,
        "rsi": 62,
        "structure_score": 0.65,
        "volume_score": 0.55,
        "trend_bias": "BULLISH",
        "reflex_coherence": 0.88,
    }


@pytest.fixture
def strong_l3() -> dict[str, Any]:
    """Good L3 market structure output."""
    return {
        "confidence": 0.78,
        "rr_ratio": 1.8,
    }


@pytest.fixture
def weak_l1() -> dict[str, Any]:
    """Weak/neutral L1 — transition regime, low confidence."""
    return {
        "bias": "NEUTRAL",
        "confidence": 0.35,
        "strength": 0.2,
        "regime": "TRANSITION",
        "context_coherence": 0.40,
        "volatility_level": "HIGH",
    }


@pytest.fixture
def weak_l2() -> dict[str, Any]:
    """Weak L2 — low signals, poor coherence."""
    return {
        "trend_strength": 0.25,
        "momentum": 0.20,
        "rsi": 48,
        "structure_score": 0.30,
        "volume_score": 0.20,
        "trend_bias": "NEUTRAL",
        "reflex_coherence": 0.45,
    }


@pytest.fixture
def weak_l3() -> dict[str, Any]:
    """Weak L3 — low confidence, no RR."""
    return {
        "confidence": 0.30,
    }


@pytest.fixture
def london_ny_time() -> datetime:
    """Wednesday 14:30 UTC — London-NY overlap."""
    return datetime(2026, 2, 11, 14, 30, 0, tzinfo=UTC)


@pytest.fixture
def weekend_time() -> datetime:
    """Saturday 10:00 UTC — market closed."""
    return datetime(2026, 2, 14, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def default_config() -> BayesianConfig:
    """Default production BayesianConfig."""
    return BayesianConfig()


# ═══════════════════════════════════════════════════════════════════════
# §1-§4: SESSION TESTS (preserved behavior from v2)
# ═══════════════════════════════════════════════════════════════════════


class TestSessionIdentification:
    """Test _identify_session for all UTC hours."""

    @pytest.mark.parametrize(
        "hour, expected_session",
        [
            (14, "LONDON_NEWYORK"),
            (8, "TOKYO_LONDON"),
            (10, "LONDON"),
            (18, "NEWYORK"),
            (3, "TOKYO"),
            (0, "SYDNEY"),
            (23, "SYDNEY"),
        ],
    )
    def test_session_mapping(self, hour: int, expected_session: str) -> None:
        session, quality = _identify_session(hour)
        assert session == expected_session
        assert 0.0 <= quality <= 1.0

    def test_london_ny_highest_quality(self) -> None:
        _, quality = _identify_session(14)
        assert quality == 1.0

    def test_sydney_lowest_quality(self) -> None:
        _, quality = _identify_session(23)
        assert quality == 0.40


class TestCurrencyExtraction:
    """Test _extract_currencies for various pair formats."""

    @pytest.mark.parametrize(
        "pair, expected",
        [
            ("GBPUSD", ["USD", "GBP"]),
            ("EUR/JPY", ["EUR", "JPY"]),
            ("AUD_NZD", ["AUD", "NZD"]),
            ("XAUUSD", ["USD"]),
            ("BTCUSD", ["USD"]),
        ],
    )
    def test_extraction(
        self,
        pair: str,
        expected: list[str],
    ) -> None:
        result = _extract_currencies(pair)
        assert set(result) == set(expected)


class TestEventDetection:
    """Test _is_near_event for high-impact news."""

    def test_nfp_within_buffer(self) -> None:
        # First Friday of month, 13:35 UTC (5 min after NFP)
        now = datetime(2026, 2, 6, 13, 35, 0, tzinfo=UTC)
        near, name = _is_near_event(now, ["USD"])
        assert near is True
        assert name == "NFP"

    def test_nfp_outside_buffer(self) -> None:
        # First Friday of month, 15:00 UTC (90 min after NFP)
        now = datetime(2026, 2, 6, 15, 0, 0, tzinfo=UTC)
        near, name = _is_near_event(now, ["USD"])
        assert near is False
        assert name is None

    def test_nfp_second_friday_ignored(self) -> None:
        # Second Friday (day=13), should NOT match NFP
        now = datetime(2026, 2, 13, 13, 30, 0, tzinfo=UTC)
        near, _ = _is_near_event(now, ["USD"])
        assert near is False

    def test_unrelated_currency_not_triggered(self) -> None:
        # NFP time but checking JPY pair
        now = datetime(2026, 2, 6, 13, 30, 0, tzinfo=UTC)
        near, _ = _is_near_event(now, ["JPY"])
        assert near is False

    def test_fomc_within_buffer(self) -> None:
        # Wednesday 19:00 UTC
        now = datetime(2026, 2, 11, 19, 0, 0, tzinfo=UTC)
        near, name = _is_near_event(now, ["USD"])
        assert near is True
        assert name == "FOMC"


class TestSessionContext:
    """Test _compute_session_context for full session logic."""

    def test_weekend_not_tradeable(self, weekend_time: datetime) -> None:
        ctx = _compute_session_context("GBPUSD", weekend_time)
        assert ctx["tradeable"] is False
        assert ctx["quality"] == 0.0
        assert "WEEKEND" in ctx["gate_reasons"]

    def test_london_ny_overlap_quality(
        self,
        london_ny_time: datetime,
    ) -> None:
        ctx = _compute_session_context("GBPUSD", london_ny_time)
        assert ctx["session"] == "LONDON_NEWYORK"
        assert ctx["quality"] == 1.0
        assert ctx["tradeable"] is True
        assert ctx["gate_reasons"] == ["OK"]

    def test_friday_close_penalty(self) -> None:
        # Friday 21:30 UTC
        now = datetime(2026, 2, 13, 21, 30, 0, tzinfo=UTC)
        ctx = _compute_session_context("GBPUSD", now)
        assert "FRIDAY_CLOSE" in ctx["gate_reasons"]
        assert ctx["quality"] < 0.5

    def test_sunday_open_penalty(self) -> None:
        # Sunday (weekday=6) -> WEEKEND, not SUNDAY_OPEN
        # Monday 00:30 UTC (weekday=0, h < 1) -> SUNDAY_OPEN
        now = datetime(2026, 2, 16, 0, 30, 0, tzinfo=UTC)
        ctx = _compute_session_context("GBPUSD", now)
        assert "SUNDAY_OPEN" in ctx["gate_reasons"]

    def test_event_buffer_reduces_quality(self) -> None:
        # FOMC: Wednesday 19:00 UTC
        now = datetime(2026, 2, 11, 19, 0, 0, tzinfo=UTC)
        ctx = _compute_session_context("GBPUSD", now)
        assert ctx["near_event"] is True
        assert ctx["event_name"] == "FOMC"
        assert "EVENT_BUFFER_FOMC" in ctx["gate_reasons"]
        # Quality should be dampened
        assert ctx["quality"] < 0.85 * 0.30 + 0.01


# ═══════════════════════════════════════════════════════════════════════
# §5: WOLF 30-POINT SCORING TESTS (preserved behavior)
# ═══════════════════════════════════════════════════════════════════════


class TestSafeExtraction:
    """Test _safe and _safe_raw helper functions."""

    def test_safe_clamps_to_01(self) -> None:
        assert _safe({"x": 1.5}, "x") == 1.0
        assert _safe({"x": -0.5}, "x") == 0.0
        assert _safe({"x": 0.5}, "x") == 0.5

    def test_safe_default_on_missing(self) -> None:
        assert _safe({}, "x", 0.3) == 0.3

    def test_safe_handles_nan(self) -> None:
        assert _safe({"x": float("nan")}, "x", 0.1) == 0.1

    def test_safe_handles_inf(self) -> None:
        assert _safe({"x": float("inf")}, "x", 0.2) == 0.2

    def test_safe_handles_string(self) -> None:
        assert _safe({"x": "not_a_number"}, "x", 0.5) == 0.5

    def test_safe_raw_no_clamp(self) -> None:
        assert _safe_raw({"x": 1.5}, "x") == 1.5
        assert _safe_raw({"x": -0.5}, "x") == -0.5

    def test_safe_raw_handles_nan(self) -> None:
        assert _safe_raw({"x": float("nan")}, "x", 0.1) == 0.1


class TestNormalizeBias:
    """Test _normalize_bias for all input formats."""

    def test_string_bullish(self) -> None:
        d, s = _normalize_bias("BULLISH")
        assert d == "BULLISH"
        assert s == 0.7

    def test_string_bearish(self) -> None:
        d, s = _normalize_bias("bearish")
        assert d == "BEARISH"
        assert s == 0.7

    def test_string_neutral(self) -> None:
        d, s = _normalize_bias("NEUTRAL")
        assert d == "NEUTRAL"
        assert s == 0.0

    def test_float_positive(self) -> None:
        d, s = _normalize_bias(0.8)
        assert d == "BULLISH"
        assert s == 0.8

    def test_float_negative(self) -> None:
        d, s = _normalize_bias(-0.6)
        assert d == "BEARISH"
        assert s == 0.6

    def test_float_near_zero(self) -> None:
        d, s = _normalize_bias(0.02)
        assert d == "NEUTRAL"
        assert s == 0.0

    def test_dict_format(self) -> None:
        d, s = _normalize_bias({"direction": "BULLISH", "strength": 0.9})
        assert d == "BULLISH"
        assert s == 0.9


class TestFScore:
    """Test _compute_f_score fundamental scoring."""

    def test_max_score_no_event(self) -> None:
        l1 = {"bias": "BULLISH", "strength": 1.0, "confidence": 1.0}
        score, detail = _compute_f_score(l1, near_event=False)
        assert score == 8.0
        assert detail["event_clear"] == 1.0

    def test_event_penalty(self) -> None:
        l1 = {"bias": "BULLISH", "strength": 1.0, "confidence": 1.0}
        score, detail = _compute_f_score(l1, near_event=True)
        assert detail["event_clear"] == 0.0
        assert score <= 6.0  # lost 2 points from event

    def test_neutral_bias_low_score(self) -> None:
        l1 = {"bias": "NEUTRAL", "confidence": 0.3}
        score, _ = _compute_f_score(l1, near_event=False)
        assert score < 3.0

    def test_zero_inputs(self) -> None:
        score, _ = _compute_f_score({}, near_event=False)
        assert score >= 0.0


class TestTScore:
    """Test _compute_t_score technical scoring."""

    def test_max_score(self) -> None:
        l2 = {
            "trend_strength": 1.0,
            "momentum": 1.0,
            "rsi_score": 1.0,
            "structure_score": 1.0,
            "volume_score": 1.0,
        }
        score, _ = _compute_t_score(l2)
        assert score == 12.0

    def test_rsi_raw_conversion(self) -> None:
        """RSI at 80 → high signal → rsi_score ≈ 1.0."""
        l2 = {"rsi": 80.0}
        _, detail = _compute_t_score(l2)
        assert detail["rsi_score"] == 1.0

    def test_rsi_at_50_zero_signal(self) -> None:
        """RSI at 50 → no signal → rsi_score = 0."""
        l2 = {"rsi": 50.0}
        _, detail = _compute_t_score(l2)
        assert detail["rsi_score"] == 0.0

    def test_fallback_keys(self) -> None:
        """Uses 'trend' if 'trend_strength' missing."""
        l2 = {"trend": 0.6}
        _, detail = _compute_t_score(l2)
        assert detail["trend"] == 0.6

    def test_empty_input(self) -> None:
        score, _ = _compute_t_score({})
        assert score == 0.0


class TestFTAScore:
    """Test _compute_fta_score alignment scoring."""

    def test_perfect_alignment(self) -> None:
        l1 = {"bias": "BULLISH", "strength": 0.7}
        l2 = {"trend_bias": "BULLISH", "trend_strength": 0.7}
        score, detail = _compute_fta_score(l1, l2)
        assert detail["direction_match"] == 1.0
        assert score == 5.0

    def test_opposite_directions(self) -> None:
        l1 = {"bias": "BULLISH"}
        l2 = {"trend_bias": "BEARISH", "trend_strength": 0.7}
        _score, detail = _compute_fta_score(l1, l2)
        assert detail["direction_match"] == 0.0

    def test_one_neutral(self) -> None:
        l1 = {"bias": "NEUTRAL"}
        l2 = {"trend_bias": "BULLISH", "trend_strength": 0.8}
        _, detail = _compute_fta_score(l1, l2)
        assert detail["direction_match"] == 0.5


class TestExecScore:
    """Test _compute_exec_score execution scoring."""

    def test_max_score(self) -> None:
        l3 = {"confidence": 1.0}
        score, _ = _compute_exec_score(l3, session_quality=1.0)
        assert score == 5.0

    def test_zero_session(self) -> None:
        l3 = {"confidence": 0.8}
        _score, detail = _compute_exec_score(l3, session_quality=0.0)
        assert detail["pts_session"] == 0.0

    def test_fallback_keys(self) -> None:
        l3 = {"structure_score": 0.6}
        _, detail = _compute_exec_score(l3, session_quality=0.5)
        assert detail["structure_quality"] == 0.6


class TestGradeClassification:
    """Test _classify_grade threshold system."""

    @pytest.mark.parametrize(
        "total, expected",
        [
            (30.0, "PERFECT"),
            (27.0, "PERFECT"),
            (26.9, "EXCELLENT"),
            (23.0, "EXCELLENT"),
            (22.5, "GOOD"),
            (18.0, "GOOD"),
            (13.0, "MARGINAL"),
            (12.5, "FAIL"),
            (0.0, "FAIL"),
        ],
    )
    def test_grade_thresholds(self, total: float, expected: str) -> None:
        assert _classify_grade(total) == expected


# ═══════════════════════════════════════════════════════════════════════
# §3B: BAYESIAN CONFIG TESTS (stability constraints §XV)
# ═══════════════════════════════════════════════════════════════════════


class TestBayesianConfig:
    """Test BayesianConfig validation and stability constraints."""

    def test_default_config_valid(self) -> None:
        """Default production config passes all constraints."""
        cfg = BayesianConfig()
        assert cfg.prior_trend_up == 0.58
        assert cfg.likelihood_min < cfg.likelihood_max

    def test_strength_sum_constraint(self) -> None:
        """Verify default Σαᵢ for each regime is within [2.8, 5.2]."""
        cfg = BayesianConfig()
        regimes = [
            (cfg.strength_trend_up_f, cfg.strength_trend_up_t, cfg.strength_trend_up_fta, cfg.strength_trend_up_exec),
            (cfg.strength_range_f, cfg.strength_range_t, cfg.strength_range_fta, cfg.strength_range_exec),
            (
                cfg.strength_transition_f,
                cfg.strength_transition_t,
                cfg.strength_transition_fta,
                cfg.strength_transition_exec,
            ),
        ]
        for strengths in regimes:
            s_sum = sum(strengths)
            assert 2.8 <= s_sum <= 5.2, f"Σα={s_sum}"

    def test_individual_strength_bounds(self) -> None:
        """Each αᵢ must be in [0.5, 2.0]."""
        cfg = BayesianConfig()
        all_strengths = [
            cfg.strength_trend_up_f,
            cfg.strength_trend_up_t,
            cfg.strength_trend_up_fta,
            cfg.strength_trend_up_exec,
            cfg.strength_range_f,
            cfg.strength_range_t,
            cfg.strength_range_fta,
            cfg.strength_range_exec,
            cfg.strength_transition_f,
            cfg.strength_transition_t,
            cfg.strength_transition_fta,
            cfg.strength_transition_exec,
        ]
        for s in all_strengths:
            assert 0.5 <= s <= 2.0, f"α={s}"  # noqa: RUF001

    def test_invalid_strength_sum_raises(self) -> None:
        """Σαᵢ outside [2.8, 5.2] must raise ValueError."""
        with pytest.raises(ValueError, match="Σαᵢ"):
            BayesianConfig(
                strength_trend_up_f=2.0,
                strength_trend_up_t=2.0,
                strength_trend_up_fta=2.0,
                strength_trend_up_exec=2.0,
            )

    def test_invalid_individual_strength_raises(self) -> None:
        """Individual α outside [0.5, 2.0] must raise ValueError."""
        with pytest.raises(ValueError, match="α\\["):  # noqa: RUF001
            BayesianConfig(strength_range_f=0.3)

    def test_invalid_prior_raises(self) -> None:
        """Prior = 0 or 1 must raise ValueError."""
        with pytest.raises(ValueError, match="must be in"):
            BayesianConfig(prior_trend_up=0.0)
        with pytest.raises(ValueError, match="must be in"):
            BayesianConfig(prior_range=1.0)

    def test_invalid_likelihood_bounds_raises(self) -> None:
        """likelihood_min >= likelihood_max must raise ValueError."""
        with pytest.raises(ValueError, match="likelihood bounds"):
            BayesianConfig(likelihood_min=0.95, likelihood_max=0.05)

    def test_custom_config_within_bounds(self) -> None:
        """Custom config that satisfies all constraints."""
        cfg = BayesianConfig(
            prior_trend_up=0.62,
            strength_trend_up_f=1.0,
            strength_trend_up_t=1.2,
            strength_trend_up_fta=1.0,
            strength_trend_up_exec=0.8,
        )
        assert cfg.prior_trend_up == 0.62


class TestRegimePriorLookup:
    """Test _get_regime_prior for all regime types."""

    def test_trend_up(self, default_config: BayesianConfig) -> None:
        assert _get_regime_prior("TREND_UP", default_config) == 0.58

    def test_trend_down(self, default_config: BayesianConfig) -> None:
        assert _get_regime_prior("TREND_DOWN", default_config) == 0.58

    def test_range(self, default_config: BayesianConfig) -> None:
        assert _get_regime_prior("RANGE", default_config) == 0.47

    def test_transition(self, default_config: BayesianConfig) -> None:
        assert _get_regime_prior("TRANSITION", default_config) == 0.42

    def test_unknown_fallback(self, default_config: BayesianConfig) -> None:
        assert _get_regime_prior("UNKNOWN", default_config) == 0.45
        assert _get_regime_prior("GARBAGE", default_config) == 0.45


class TestRegimeStrengthsLookup:
    """Test _get_regime_strengths for regime-conditioned matrix."""

    def test_trend_up_strengths(
        self,
        default_config: BayesianConfig,
    ) -> None:
        f, t, fta, exc = _get_regime_strengths(
            "TREND_UP",
            default_config,
        )
        assert t > f  # Technical most reliable in trend
        assert fta > exc  # Alignment more important than exec

    def test_range_strengths(
        self,
        default_config: BayesianConfig,
    ) -> None:
        _f, t, _fta, exc = _get_regime_strengths(
            "RANGE",
            default_config,
        )
        assert exc > t  # Execution most critical in range

    def test_transition_strengths(
        self,
        default_config: BayesianConfig,
    ) -> None:
        f, t, fta, exc = _get_regime_strengths(
            "TRANSITION",
            default_config,
        )
        assert fta > f  # Alignment most critical in transition
        assert exc > t  # Execution more important than tech

    def test_unknown_fallback(
        self,
        default_config: BayesianConfig,
    ) -> None:
        strengths = _get_regime_strengths("GARBAGE", default_config)
        assert all(s == 0.8 for s in strengths)


# ═══════════════════════════════════════════════════════════════════════
# §5B: BAYESIAN ENGINE TESTS (§IV-§XV mathematical verification)
# ═══════════════════════════════════════════════════════════════════════


class TestBayesianWinProbability:
    """Test _bayesian_win_probability (§IV-§V)."""

    def test_neutral_evidence_returns_near_prior(self) -> None:
        """With all L=0.5, posterior ≈ prior (BF=1 for each)."""
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.58,
            likelihoods=[0.5, 0.5, 0.5, 0.5],
            strengths=[1.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert abs(posterior - 0.58) < 0.01

    def test_strong_evidence_increases_posterior(self) -> None:
        """High likelihoods should increase posterior above prior."""
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.50,
            likelihoods=[0.9, 0.85, 0.8, 0.75],
            strengths=[1.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert posterior > 0.50

    def test_weak_evidence_decreases_posterior(self) -> None:
        """Low likelihoods should decrease posterior below prior."""
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.50,
            likelihoods=[0.1, 0.15, 0.2, 0.1],
            strengths=[1.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert posterior < 0.50

    def test_clamping_prevents_degenerate_bf(self) -> None:
        """L=0.0 should be clamped to likelihood_min, not cause div/0."""
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.5,
            likelihoods=[0.0, 0.0, 0.0, 0.0],
            strengths=[1.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert 0.0 <= posterior <= 1.0

    def test_clamping_prevents_runaway(self) -> None:
        """L=1.0 should be clamped to likelihood_max."""
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.5,
            likelihoods=[1.0, 1.0, 1.0, 1.0],
            strengths=[1.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert 0.0 <= posterior <= 1.0

    def test_strength_amplifies_evidence(self) -> None:
        """Higher strength exponent should amplify the Bayes factor."""
        cfg = BayesianConfig()
        p_low_s = _bayesian_win_probability(
            prior=0.5,
            likelihoods=[0.8, 0.5, 0.5, 0.5],
            strengths=[0.5, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        p_high_s = _bayesian_win_probability(
            prior=0.5,
            likelihoods=[0.8, 0.5, 0.5, 0.5],
            strengths=[2.0, 1.0, 1.0, 1.0],
            cfg=cfg,
        )
        assert p_high_s > p_low_s

    def test_output_always_bounded_01(self) -> None:
        """Posterior must always be in [0, 1]."""
        cfg = BayesianConfig()
        for prior in [0.01, 0.5, 0.99]:
            for l_val in [0.01, 0.5, 0.99]:
                p = _bayesian_win_probability(
                    prior=prior,
                    likelihoods=[l_val] * 4,
                    strengths=[1.5] * 4,
                    cfg=cfg,
                )
                assert 0.0 <= p <= 1.0

    def test_hand_calculated_posterior(self) -> None:
        """Verify against manual Bayes factor calculation.

        prior = 0.58, L=[0.8], α=[1.0], one evidence component
        O₀ = 0.58/0.42 = 1.38095
        BF = (0.8/0.2)^1.0 = 4.0
        O_post = 1.38095 × 4.0 = 5.52381
        P(W|E) = 5.52381 / 6.52381 = 0.8467
        """
        cfg = BayesianConfig()
        posterior = _bayesian_win_probability(
            prior=0.58,
            likelihoods=[0.8],
            strengths=[1.0],
            cfg=cfg,
        )
        expected = 5.52381 / 6.52381
        assert abs(posterior - expected) < 0.005


class TestExpectancy:
    """Test _compute_expectancy (§VIII)."""

    def test_positive_edge(self) -> None:
        """P=0.64, RR=1.8 → E = 0.64×1.8 - 0.36 = 0.792."""
        e = _compute_expectancy(0.64, 1.8)
        assert abs(e - 0.792) < 0.001

    def test_breakeven(self) -> None:
        """P=0.5, RR=1.0 → E = 0.5×1.0 - 0.5 = 0."""
        e = _compute_expectancy(0.5, 1.0)
        assert abs(e) < 0.001

    def test_negative_edge(self) -> None:
        """P=0.3, RR=1.0 → E = 0.3×1.0 - 0.7 = -0.4."""
        e = _compute_expectancy(0.3, 1.0)
        assert abs(e - (-0.4)) < 0.001

    def test_high_rr_compensates_low_wr(self) -> None:
        """P=0.4, RR=3.0 → E = 0.4×3.0 - 0.6 = 0.6 (positive)."""
        e = _compute_expectancy(0.4, 3.0)
        assert e > 0

    def test_equivalent_formula(self) -> None:
        """E = P(R+1) - 1 ≡ P×R - (1-P)."""
        p, rr = 0.65, 2.0
        e1 = _compute_expectancy(p, rr)
        e2 = p * (rr + 1) - 1
        assert abs(e1 - e2) < 0.0001


class TestRiskAdjustedEdge:
    """Test _compute_risk_adjusted_edge (§IX)."""

    def test_positive_edge(self) -> None:
        """RAE = E × ln(1+P) for positive expectancy."""
        rae = _compute_risk_adjusted_edge(0.5, 0.7)
        expected = 0.5 * math.log(1.0 + 0.7)
        assert abs(rae - expected) < 0.001

    def test_negative_expectancy_passthrough(self) -> None:
        """Negative expectancy returned as-is (rounded)."""
        rae = _compute_risk_adjusted_edge(-0.3, 0.7)
        assert abs(rae - (-0.3)) < 0.001

    def test_zero_expectancy(self) -> None:
        rae = _compute_risk_adjusted_edge(0.0, 0.7)
        assert rae <= 0.0

    def test_higher_posterior_higher_rae(self) -> None:
        """Higher confidence should yield higher RAE."""
        rae_low = _compute_risk_adjusted_edge(0.5, 0.55)
        rae_high = _compute_risk_adjusted_edge(0.5, 0.85)
        assert rae_high > rae_low


class TestPosteriorEntropy:
    """Test _compute_posterior_entropy (§XI)."""

    def test_max_entropy_at_05(self) -> None:
        """H(0.5) = ln(2) ≈ 0.6931."""
        h = _compute_posterior_entropy(0.5)
        assert abs(h - math.log(2.0)) < 0.001

    def test_low_entropy_at_extreme(self) -> None:
        """H(0.99) ≈ 0 (near certainty)."""
        h = _compute_posterior_entropy(0.99)
        assert h < 0.1

    def test_symmetric(self) -> None:
        """H(p) = H(1-p)."""
        h1 = _compute_posterior_entropy(0.3)
        h2 = _compute_posterior_entropy(0.7)
        assert abs(h1 - h2) < 0.0001

    def test_handles_edge_values(self) -> None:
        """P=0 and P=1 should not cause math errors."""
        h0 = _compute_posterior_entropy(0.0)
        h1 = _compute_posterior_entropy(1.0)
        assert math.isfinite(h0)
        assert math.isfinite(h1)


class TestConfidenceIndex:
    """Test _compute_confidence_index (§XI)."""

    def test_max_confidence_at_extreme(self) -> None:
        """CI → 1.0 when P is near 0 or 1."""
        ci = _compute_confidence_index(0.99)
        assert ci > 0.9

    def test_zero_confidence_at_05(self) -> None:
        """CI = 0.0 when P = 0.5 (max uncertainty)."""
        ci = _compute_confidence_index(0.5)
        assert abs(ci) < 0.001

    def test_output_bounded_01(self) -> None:
        for p in [0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99]:
            ci = _compute_confidence_index(p)
            assert 0.0 <= ci <= 1.0


class TestBayesianGradeClassification:
    """Test _classify_bayesian_grade (§XIV)."""

    @pytest.mark.parametrize(
        "posterior, expectancy, expected_grade",
        [
            (0.80, 0.60, "INSTITUTIONAL_A"),
            (0.75, 0.51, "INSTITUTIONAL_A"),
            (0.70, 0.40, "INSTITUTIONAL_B"),
            (0.65, 0.31, "INSTITUTIONAL_B"),
            (0.60, 0.20, "SPECULATIVE"),
            (0.55, 0.01, "SPECULATIVE"),
            (0.54, 0.50, "NO_EDGE"),
            (0.70, -0.10, "NO_EDGE"),
            (0.50, 0.00, "NO_EDGE"),
            (0.40, -0.50, "NO_EDGE"),
        ],
    )
    def test_grade_mapping(
        self,
        posterior: float,
        expectancy: float,
        expected_grade: str,
    ) -> None:
        assert _classify_bayesian_grade(posterior, expectancy) == expected_grade


class TestCoherenceDampener:
    """Test coherence dampening in _compute_bayesian_enrichment (§VI)."""

    def test_high_coherence_no_dampening(self) -> None:
        """reflex_coherence ≥ threshold → no dampening applied."""
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=BayesianConfig(),
        )
        assert result["dampeners"]["coherence_applied"] is False

    def test_low_coherence_dampens_posterior(self) -> None:
        """reflex_coherence < threshold → posterior dampened."""
        cfg = BayesianConfig()
        high_coh = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        low_coh = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.40},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        assert low_coh["dampeners"]["coherence_applied"] is True
        assert low_coh["posterior_win_probability"] < high_coh["posterior_win_probability"]

    def test_l1_coherence_fallback(self) -> None:
        """Uses L1.context_coherence when L2.reflex_coherence missing."""
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={
                "regime": "TREND_UP",
                "volatility_level": "NORMAL",
                "context_coherence": 0.50,
            },
            l2={},  # no reflex_coherence
            l3={"rr_ratio": 1.5},
            cfg=BayesianConfig(),
        )
        assert result["dampeners"]["coherence_value"] == 0.50
        assert result["dampeners"]["coherence_applied"] is True


class TestVolatilityDampener:
    """Test volatility dampening in _compute_bayesian_enrichment (§VII)."""

    def test_extreme_vol_dampens(self) -> None:
        cfg = BayesianConfig()
        normal = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        extreme = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "EXTREME"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        assert extreme["posterior_win_probability"] < normal["posterior_win_probability"]
        assert extreme["dampeners"]["volatility_mult"] == 0.85

    def test_high_vol_dampens(self) -> None:
        cfg = BayesianConfig()
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "HIGH"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        assert result["dampeners"]["volatility_mult"] == 0.93

    def test_normal_vol_no_dampening(self) -> None:
        cfg = BayesianConfig()
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        assert result["dampeners"]["volatility_mult"] == 1.0


class TestBayesianEnrichmentIntegration:
    """Test full _compute_bayesian_enrichment pipeline."""

    def test_output_structure(self) -> None:
        """Verify all required keys are present."""
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=BayesianConfig(),
        )
        required_keys = {
            "posterior_win_probability",
            "expected_value",
            "risk_adjusted_edge",
            "posterior_entropy",
            "confidence_index",
            "regime_prior",
            "regime_used",
            "rr_ratio",
            "bayesian_grade",
            "bayesian_tradeable",
            "confidence_lineage",
            "regime_strengths",
            "dampeners",
        }
        assert required_keys.issubset(result.keys())

    def test_confidence_lineage_values(self) -> None:
        """Verify confidence_lineage = score / max for each component."""
        result = _compute_bayesian_enrichment(
            f_score=4.0,
            t_score=6.0,
            fta_score=2.5,
            exec_score=2.5,
            l1={"regime": "RANGE"},
            l2={},
            l3={},
            cfg=BayesianConfig(),
        )
        lin = result["confidence_lineage"]
        assert abs(lin["F"] - 4.0 / 8) < 0.001
        assert abs(lin["T"] - 6.0 / 12) < 0.001
        assert abs(lin["FTA"] - 2.5 / 5) < 0.001
        assert abs(lin["EXEC"] - 2.5 / 5) < 0.001

    def test_default_rr_fallback(self) -> None:
        """Uses default RR when L3 doesn't provide."""
        cfg = BayesianConfig(default_rr=2.0)
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP"},
            l2={},
            l3={},
            cfg=cfg,
        )
        assert result["rr_ratio"] == 2.0

    def test_negative_rr_uses_default(self) -> None:
        """Negative RR from L3 should fall back to default."""
        cfg = BayesianConfig(default_rr=1.5)
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP"},
            l2={},
            l3={"rr_ratio": -1.0},
            cfg=cfg,
        )
        assert result["rr_ratio"] == 1.5

    def test_regime_strength_applied(self) -> None:
        """Different regimes should produce different posteriors."""
        cfg = BayesianConfig()
        trend = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        rng = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "RANGE", "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.90},
            l3={"rr_ratio": 1.5},
            cfg=cfg,
        )
        # Different priors + strengths → different posteriors
        assert trend["posterior_win_probability"] != rng["posterior_win_probability"]

    def test_posterior_entropy_present_and_valid(self) -> None:
        result = _compute_bayesian_enrichment(
            f_score=6.0,
            t_score=9.0,
            fta_score=4.0,
            exec_score=4.0,
            l1={"regime": "TREND_UP"},
            l2={},
            l3={},
            cfg=BayesianConfig(),
        )
        assert 0.0 <= result["posterior_entropy"] <= math.log(2.0) + 0.01
        assert 0.0 <= result["confidence_index"] <= 1.0


class TestRegimeConditioning:
    """Test that regime properly conditions the Bayesian output."""

    @pytest.mark.parametrize(
        "regime",
        ["TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION", "UNKNOWN"],
    )
    def test_all_regimes_produce_valid_output(
        self,
        regime: str,
    ) -> None:
        result = _compute_bayesian_enrichment(
            f_score=5.0,
            t_score=7.0,
            fta_score=3.0,
            exec_score=3.0,
            l1={"regime": regime, "volatility_level": "NORMAL"},
            l2={"reflex_coherence": 0.80},
            l3={"rr_ratio": 1.5},
            cfg=BayesianConfig(),
        )
        assert 0.0 <= result["posterior_win_probability"] <= 1.0
        assert result["regime_used"] == regime
        assert result["bayesian_grade"] in {
            "INSTITUTIONAL_A",
            "INSTITUTIONAL_B",
            "SPECULATIVE",
            "NO_EDGE",
        }


# ═══════════════════════════════════════════════════════════════════════
# §6: FULL PIPELINE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestL4SessionScoringAnalyze:
    """Test L4SessionScoring.analyze() full pipeline."""

    def test_full_pipeline_output_structure(
        self,
        bullish_l1: dict[str, Any],
        bullish_l2: dict[str, Any],
        strong_l3: dict[str, Any],
        london_ny_time: datetime,
    ) -> None:
        analyzer = L4SessionScoring()
        result = analyzer.analyze(
            l1=bullish_l1,
            l2=bullish_l2,
            l3=strong_l3,
            pair="GBPUSD",
            now=london_ny_time,
        )

        # Session keys
        assert "session" in result
        assert "quality" in result
        assert "tradeable" in result
        assert "gate_reasons" in result

        # Wolf 30-Point keys (preserved)
        wp = result["wolf_30_point"]
        assert "total" in wp
        assert "f_score" in wp
        assert "t_score" in wp
        assert "fta_score" in wp
        assert "exec_score" in wp
        assert "max_possible" in wp
        assert wp["max_possible"] == 30

        # Bayesian keys (NEW)
        bay = result["bayesian"]
        assert "posterior_win_probability" in bay
        assert "expected_value" in bay
        assert "risk_adjusted_edge" in bay
        assert "posterior_entropy" in bay
        assert "confidence_index" in bay
        assert "bayesian_grade" in bay
        assert "bayesian_tradeable" in bay
        assert "confidence_lineage" in bay
        assert "regime_strengths" in bay
        assert "dampeners" in bay

        # Classification keys
        assert "grade" in result
        assert "technical_score" in result
        assert "valid" in result
        assert "pair" in result
        assert "timestamp" in result

    def test_strong_bullish_produces_good_grade(
        self,
        bullish_l1: dict[str, Any],
        bullish_l2: dict[str, Any],
        strong_l3: dict[str, Any],
        london_ny_time: datetime,
    ) -> None:
        analyzer = L4SessionScoring()
        result = analyzer.analyze(
            l1=bullish_l1,
            l2=bullish_l2,
            l3=strong_l3,
            pair="GBPUSD",
            now=london_ny_time,
        )
        assert result["grade"] in ("PERFECT", "EXCELLENT", "GOOD")
        assert result["tradeable"] is True
        assert result["bayesian"]["posterior_win_probability"] > 0.5
        assert result["bayesian"]["expected_value"] > 0.0

    def test_weak_signals_produce_poor_grade(
        self,
        weak_l1: dict[str, Any],
        weak_l2: dict[str, Any],
        weak_l3: dict[str, Any],
        london_ny_time: datetime,
    ) -> None:
        analyzer = L4SessionScoring()
        result = analyzer.analyze(
            l1=weak_l1,
            l2=weak_l2,
            l3=weak_l3,
            pair="GBPUSD",
            now=london_ny_time,
        )
        assert result["wolf_30_point"]["total"] < 18
        assert result["bayesian"]["posterior_win_probability"] < 0.65

    def test_weekend_blocks_tradeable(
        self,
        bullish_l1: dict[str, Any],
        bullish_l2: dict[str, Any],
        strong_l3: dict[str, Any],
        weekend_time: datetime,
    ) -> None:
        analyzer = L4SessionScoring()
        result = analyzer.analyze(
            l1=bullish_l1,
            l2=bullish_l2,
            l3=strong_l3,
            pair="GBPUSD",
            now=weekend_time,
        )
        assert result["tradeable"] is False
        assert "WEEKEND" in result["gate_reasons"]

    def test_wolf_total_capped_at_30(self) -> None:
        """Even with perfect scores, total ≤ 30."""
        l1 = {"bias": "BULLISH", "strength": 1.0, "confidence": 1.0, "regime": "TREND_UP"}
        l2 = {
            "trend_strength": 1.0,
            "momentum": 1.0,
            "rsi_score": 1.0,
            "structure_score": 1.0,
            "volume_score": 1.0,
            "trend_bias": "BULLISH",
        }
        l3 = {"confidence": 1.0}
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)

        result = L4SessionScoring().analyze(
            l1=l1,
            l2=l2,
            l3=l3,
            now=now,
        )
        assert result["wolf_30_point"]["total"] <= 30

    def test_technical_score_0_100_scale(
        self,
        bullish_l1: dict[str, Any],
        bullish_l2: dict[str, Any],
        strong_l3: dict[str, Any],
        london_ny_time: datetime,
    ) -> None:
        result = L4SessionScoring().analyze(
            l1=bullish_l1,
            l2=bullish_l2,
            l3=strong_l3,
            now=london_ny_time,
        )
        assert 0 <= result["technical_score"] <= 100

    def test_custom_bayesian_config(self) -> None:
        """Analyzer accepts custom BayesianConfig."""
        cfg = BayesianConfig(prior_trend_up=0.62)
        analyzer = L4SessionScoring(bayesian_config=cfg)
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)

        result = analyzer.analyze(
            l1={"bias": "BULLISH", "confidence": 0.8, "regime": "TREND_UP"},
            l2={"trend_strength": 0.7, "momentum": 0.6},
            l3={"confidence": 0.7},
            now=now,
        )
        assert result["bayesian"]["regime_prior"] == 0.62

    def test_empty_inputs_valid_false(self) -> None:
        """Minimal inputs should still produce valid output."""
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)
        result = L4SessionScoring().analyze(
            l1={},
            l2={},
            l3={},
            now=now,
        )
        assert result["valid"] is True  # L4 is always valid
        assert result["wolf_30_point"]["total"] >= 0

    def test_call_count_increments(self) -> None:
        analyzer = L4SessionScoring()
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)
        analyzer.analyze(l1={}, l2={}, l3={}, now=now)
        analyzer.analyze(l1={}, l2={}, l3={}, now=now)
        assert analyzer._call_count == 2


# ═══════════════════════════════════════════════════════════════════════
# §7: BACKWARD COMPATIBILITY TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestL4ScoringEngine:
    """Test L4ScoringEngine backward-compatible wrapper."""

    def test_score_returns_wolf_30_keys(self) -> None:
        engine = L4ScoringEngine()
        result = engine.score(
            l1={"bias": "BULLISH", "confidence": 0.7},
            l2={"trend_strength": 0.6, "momentum": 0.5},
            l3={"confidence": 0.6},
        )
        wp = result["wolf_30_point"]
        assert "total" in wp
        assert "f_score" in wp
        assert "t_score" in wp
        assert "fta_score" in wp
        assert "exec_score" in wp
        assert "grade" in result
        assert "technical_score" in result
        assert "valid" in result

    def test_score_includes_bayesian(self) -> None:
        """New 'bayesian' key is additive — present but non-breaking."""
        engine = L4ScoringEngine()
        result = engine.score(
            l1={"bias": "BULLISH", "confidence": 0.7, "regime": "TREND_UP"},
            l2={"trend_strength": 0.6},
            l3={"confidence": 0.6},
        )
        assert "bayesian" in result
        assert "posterior_win_probability" in result["bayesian"]

    def test_no_arg_instantiation(self) -> None:
        """L4ScoringEngine() must work with no arguments."""
        engine = L4ScoringEngine()
        assert engine is not None


class TestAnalyzeSession:
    """Test analyze_session backward-compatible function."""

    def test_signature_unchanged(self) -> None:
        """analyze_session(market_data, pair, now) signature works."""
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)
        result = analyze_session({}, pair="GBPUSD", now=now)

        assert "session" in result
        assert "quality" in result
        assert "tradeable" in result
        assert "gate_reasons" in result
        assert "near_event" in result
        assert "event_name" in result
        assert "pair" in result
        assert "valid" in result
        assert "timestamp" in result

    def test_no_bayesian_in_session_only(self) -> None:
        """Session-only analysis does NOT include bayesian output."""
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)
        result = analyze_session({}, pair="GBPUSD", now=now)
        assert "bayesian" not in result


class TestAnalyzeSessionScoring:
    """Test analyze_session_scoring convenience function."""

    def test_returns_full_output(self) -> None:
        now = datetime(2026, 2, 11, 14, 0, 0, tzinfo=UTC)
        result = analyze_session_scoring(
            l1={"bias": "BULLISH", "confidence": 0.7, "regime": "TREND_UP"},
            l2={"trend_strength": 0.6},
            l3={"confidence": 0.6},
            now=now,
        )
        assert "wolf_30_point" in result
        assert "bayesian" in result
        assert "grade" in result
