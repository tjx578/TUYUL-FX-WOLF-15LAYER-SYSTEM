"""
Tests for Layer 8 — Trade Integrity Index (TII).
Zone: Analysis. No execution side-effects.

TII measures how "clean" a setup is — alignment across multiple
quality dimensions. It is NOT a trade decision; that's L12's job.
"""

import pytest

from analysis.l8_tii import (
    TIIGrade,
    TIIInputs,
    TIIResult,
    classify_tii_grade,
    compute_tii,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_setup() -> TIIInputs:
    """A textbook-clean setup — high TII expected."""
    return TIIInputs(
        setup_clarity=95.0,
        rule_compliance=100.0,
        risk_reward_quality=90.0,
        confluence_depth=85.0,
        timing_alignment=88.0,
    )


@pytest.fixture
def dirty_setup() -> TIIInputs:
    """A messy, forced setup — low TII expected."""
    return TIIInputs(
        setup_clarity=20.0,
        rule_compliance=30.0,
        risk_reward_quality=25.0,
        confluence_depth=15.0,
        timing_alignment=10.0,
    )


@pytest.fixture
def borderline_setup() -> TIIInputs:
    """Right at the edge of pass/fail."""
    return TIIInputs(
        setup_clarity=55.0,
        rule_compliance=55.0,
        risk_reward_quality=55.0,
        confluence_depth=55.0,
        timing_alignment=55.0,
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestTIIInputsValidation:
    def test_valid_inputs(self, clean_setup: TIIInputs) -> None:
        assert clean_setup.setup_clarity == 95.0

    @pytest.mark.parametrize(
        "field_name",
        [
            "setup_clarity",
            "rule_compliance",
            "risk_reward_quality",
            "confluence_depth",
            "timing_alignment",
        ],
    )
    def test_below_zero_raises(self, field_name: str) -> None:
        kwargs = {
            "setup_clarity": 50.0,
            "rule_compliance": 50.0,
            "risk_reward_quality": 50.0,
            "confluence_depth": 50.0,
            "timing_alignment": 50.0,
        }
        kwargs[field_name] = -1.0
        with pytest.raises(ValueError, match="must be 0–100"):
            TIIInputs(**kwargs)

    @pytest.mark.parametrize(
        "field_name",
        [
            "setup_clarity",
            "rule_compliance",
            "risk_reward_quality",
            "confluence_depth",
            "timing_alignment",
        ],
    )
    def test_above_100_raises(self, field_name: str) -> None:
        kwargs = {
            "setup_clarity": 50.0,
            "rule_compliance": 50.0,
            "risk_reward_quality": 50.0,
            "confluence_depth": 50.0,
            "timing_alignment": 50.0,
        }
        kwargs[field_name] = 100.1
        with pytest.raises(ValueError, match="must be 0–100"):
            TIIInputs(**kwargs)

    def test_boundary_zero_accepted(self) -> None:
        TIIInputs(
            setup_clarity=0.0,
            rule_compliance=0.0,
            risk_reward_quality=0.0,
            confluence_depth=0.0,
            timing_alignment=0.0,
        )

    def test_boundary_100_accepted(self) -> None:
        TIIInputs(
            setup_clarity=100.0,
            rule_compliance=100.0,
            risk_reward_quality=100.0,
            confluence_depth=100.0,
            timing_alignment=100.0,
        )


# ---------------------------------------------------------------------------
# TII computation
# ---------------------------------------------------------------------------


class TestComputeTII:
    def test_clean_setup_high_score(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        assert result.tii_score >= 80.0

    def test_dirty_setup_low_score(self, dirty_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", dirty_setup)
        assert result.tii_score < 30.0

    def test_score_within_bounds(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        assert 0.0 <= result.tii_score <= 100.0

    def test_score_within_bounds_dirty(self, dirty_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", dirty_setup)
        assert 0.0 <= result.tii_score <= 100.0

    def test_perfect_score(self) -> None:
        perfect = TIIInputs(
            setup_clarity=100.0,
            rule_compliance=100.0,
            risk_reward_quality=100.0,
            confluence_depth=100.0,
            timing_alignment=100.0,
        )
        result = compute_tii("EURUSD", perfect)
        assert result.tii_score == 100.0

    def test_zero_score(self) -> None:
        zero = TIIInputs(
            setup_clarity=0.0,
            rule_compliance=0.0,
            risk_reward_quality=0.0,
            confluence_depth=0.0,
            timing_alignment=0.0,
        )
        result = compute_tii("EURUSD", zero)
        assert result.tii_score == 0.0

    def test_deterministic(self, clean_setup: TIIInputs) -> None:
        r1 = compute_tii("EURUSD", clean_setup)
        r2 = compute_tii("EURUSD", clean_setup)
        assert r1.tii_score == r2.tii_score


# ---------------------------------------------------------------------------
# TII grade classification
# ---------------------------------------------------------------------------


class TestTIIGrade:
    @pytest.mark.parametrize(
        "score_val, expected_grade",
        [
            (100.0, TIIGrade.PRISTINE),
            (90.0, TIIGrade.PRISTINE),
            (89.9, TIIGrade.CLEAN),
            (75.0, TIIGrade.CLEAN),
            (74.9, TIIGrade.ACCEPTABLE),
            (55.0, TIIGrade.ACCEPTABLE),
            (54.9, TIIGrade.QUESTIONABLE),
            (35.0, TIIGrade.QUESTIONABLE),
            (34.9, TIIGrade.COMPROMISED),
            (0.0, TIIGrade.COMPROMISED),
        ],
    )
    def test_grade_boundaries(self, score_val: float, expected_grade: TIIGrade) -> None:
        assert classify_tii_grade(score_val) == expected_grade

    def test_clean_setup_grade(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        assert result.grade in (TIIGrade.PRISTINE, TIIGrade.CLEAN)

    def test_dirty_setup_grade(self, dirty_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", dirty_setup)
        assert result.grade in (TIIGrade.QUESTIONABLE, TIIGrade.COMPROMISED)


# ---------------------------------------------------------------------------
# Pass threshold
# ---------------------------------------------------------------------------


class TestPassThreshold:
    def test_clean_setup_passes(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        assert result.pass_threshold is True

    def test_dirty_setup_fails(self, dirty_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", dirty_setup)
        assert result.pass_threshold is False

    def test_custom_threshold(self, borderline_setup: TIIInputs) -> None:
        strict = compute_tii("EURUSD", borderline_setup, threshold=60.0)
        lenient = compute_tii("EURUSD", borderline_setup, threshold=50.0)
        assert strict.pass_threshold is False
        assert lenient.pass_threshold is True

    def test_threshold_recorded(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup, threshold=70.0)
        assert result.threshold_used == 70.0


# ---------------------------------------------------------------------------
# Weakest dimension identification
# ---------------------------------------------------------------------------


class TestWeakestDimension:
    def test_weakest_identified(self) -> None:
        inputs = TIIInputs(
            setup_clarity=90.0,
            rule_compliance=90.0,
            risk_reward_quality=90.0,
            confluence_depth=30.0,  # clearly weakest
            timing_alignment=90.0,
        )
        result = compute_tii("EURUSD", inputs)
        assert result.weakest_dimension == "confluence_depth"

    def test_strongest_identified(self) -> None:
        inputs = TIIInputs(
            setup_clarity=50.0,
            rule_compliance=99.0,  # clearly strongest
            risk_reward_quality=50.0,
            confluence_depth=50.0,
            timing_alignment=50.0,
        )
        result = compute_tii("EURUSD", inputs)
        assert result.strongest_dimension == "rule_compliance"


# ---------------------------------------------------------------------------
# Result immutability & integrity
# ---------------------------------------------------------------------------


class TestResultIntegrity:
    def test_returns_tii_result(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        assert isinstance(result, TIIResult)

    def test_result_is_frozen(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("EURUSD", clean_setup)
        with pytest.raises(AttributeError):
            result.tii_score = 0.0  # type: ignore[misc]

    def test_symbol_preserved(self, clean_setup: TIIInputs) -> None:
        result = compute_tii("XAUUSD", clean_setup)
        assert result.symbol == "XAUUSD"

    def test_metadata_passthrough(self, clean_setup: TIIInputs) -> None:
        meta = {"timeframe": "H1", "session": "newyork"}
        result = compute_tii("EURUSD", clean_setup, metadata=meta)
        assert result.metadata == meta

    def test_no_side_effects(self, clean_setup: TIIInputs) -> None:
        original = clean_setup.setup_clarity
        _ = compute_tii("EURUSD", clean_setup)
        assert clean_setup.setup_clarity == original


# ---------------------------------------------------------------------------
# Rule compliance penalty (TII special rule)
# ---------------------------------------------------------------------------


class TestRuleCompliancePenalty:
    """
    If rule_compliance < 50, TII should be capped or penalised
    regardless of other dimensions. A setup that violates trading
    rules is never "clean".
    """

    def test_low_compliance_caps_grade(self) -> None:
        inputs = TIIInputs(
            setup_clarity=95.0,
            rule_compliance=30.0,  # rule violation
            risk_reward_quality=95.0,
            confluence_depth=95.0,
            timing_alignment=95.0,
        )
        result = compute_tii("EURUSD", inputs)
        # Even with all other scores at 95, low compliance must drag grade down
        assert result.grade not in (TIIGrade.PRISTINE,)
        assert result.tii_score < 90.0
