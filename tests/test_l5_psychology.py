"""
Tests for Layer 5 — Market Psychology & Trader Sentiment Analysis.
Zone: Analysis. No execution side-effects.
"""

import pytest  # pyright: ignore[reportMissingImports]

from analysis.l5_psychology import (  # pyright: ignore[reportMissingImports]
    BAD_DAY_PNL_PCT,
    EXTREME_SENTIMENT_THRESHOLD,
    LOSS_STREAK_CAUTION,
    LOSS_STREAK_TILT,
    MAX_TRADES_PER_DAY,
    L5Result,
    PsychologyInputs,
    PsychState,
    SentimentBias,
    analyze,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def optimal_inputs() -> PsychologyInputs:
    """Healthy trader state — no flags expected."""
    return PsychologyInputs(
        retail_long_ratio=0.50,
        recent_consecutive_losses=0,
        hours_since_last_trade=4.0,
        trades_today=1,
        daily_pnl_pct=0.5,
        in_session_window=True,
        fear_greed_index=50.0,
    )


@pytest.fixture
def tilted_inputs() -> PsychologyInputs:
    """Worst-case: loss streak + revenge + overtrading + bad day + out of session."""
    return PsychologyInputs(
        retail_long_ratio=0.50,
        recent_consecutive_losses=5,
        hours_since_last_trade=0.1,
        trades_today=8,
        daily_pnl_pct=-4.0,
        in_session_window=False,
        fear_greed_index=10.0,
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestPsychologyInputsValidation:
    def test_valid_inputs(self, optimal_inputs: PsychologyInputs) -> None:
        assert optimal_inputs.retail_long_ratio == 0.50

    def test_long_ratio_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="retail_long_ratio"):
            PsychologyInputs(retail_long_ratio=-0.1)

    def test_long_ratio_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="retail_long_ratio"):
            PsychologyInputs(retail_long_ratio=1.1)

    def test_fear_greed_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="fear_greed_index"):
            PsychologyInputs(retail_long_ratio=0.5, fear_greed_index=-1.0)

    def test_fear_greed_above_100_raises(self) -> None:
        with pytest.raises(ValueError, match="fear_greed_index"):
            PsychologyInputs(retail_long_ratio=0.5, fear_greed_index=101.0)

    def test_boundary_values_accepted(self) -> None:
        PsychologyInputs(retail_long_ratio=0.0, fear_greed_index=0.0)
        PsychologyInputs(retail_long_ratio=1.0, fear_greed_index=100.0)


# ---------------------------------------------------------------------------
# Sentiment classification
# ---------------------------------------------------------------------------

class TestSentimentBias:
    @pytest.mark.parametrize("ratio, expected", [
        (0.95, SentimentBias.EXTREME_LONG),
        (EXTREME_SENTIMENT_THRESHOLD, SentimentBias.EXTREME_LONG),
        (0.70, SentimentBias.LONG),
        (0.50, SentimentBias.NEUTRAL),
        (0.30, SentimentBias.SHORT),
        (0.10, SentimentBias.EXTREME_SHORT),
        (1.0 - EXTREME_SENTIMENT_THRESHOLD, SentimentBias.EXTREME_SHORT),
    ])
    def test_sentiment_classification(self, ratio: float, expected: SentimentBias) -> None:
        inputs = PsychologyInputs(retail_long_ratio=ratio)
        result = analyze("EURUSD", inputs)
        assert result.sentiment_bias == expected


# ---------------------------------------------------------------------------
# Contrarian signal
# ---------------------------------------------------------------------------

class TestContrarianSignal:
    def test_extreme_long_triggers_contrarian(self) -> None:
        inputs = PsychologyInputs(retail_long_ratio=0.90)
        result = analyze("EURUSD", inputs)
        assert result.contrarian_signal is True

    def test_extreme_short_triggers_contrarian(self) -> None:
        inputs = PsychologyInputs(retail_long_ratio=0.10)
        result = analyze("EURUSD", inputs)
        assert result.contrarian_signal is True

    def test_neutral_no_contrarian(self) -> None:
        inputs = PsychologyInputs(retail_long_ratio=0.50)
        result = analyze("EURUSD", inputs)
        assert result.contrarian_signal is False


# ---------------------------------------------------------------------------
# Optimal state
# ---------------------------------------------------------------------------

class TestOptimalState:
    def test_optimal_inputs_produce_optimal_state(
        self, optimal_inputs: PsychologyInputs
    ) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert result.state == PsychState.OPTIMAL

    def test_optimal_psych_score_high(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert result.psych_score >= 80.0

    def test_optimal_no_tilt(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert result.tilt_detected is False

    def test_optimal_no_overtrade(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert result.overtrade_warning is False

    def test_optimal_no_flags(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert len(result.flags) == 0


# ---------------------------------------------------------------------------
# Loss streak detection
# ---------------------------------------------------------------------------

class TestLossStreak:
    def test_caution_at_threshold(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=LOSS_STREAK_CAUTION,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "LOSS_STREAK_CAUTION" in flag_codes
        assert result.state in (PsychState.CAUTION, PsychState.IMPAIRED)

    def test_tilt_at_threshold(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=LOSS_STREAK_TILT,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "LOSS_STREAK_TILT" in flag_codes

    def test_no_flag_below_caution(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=LOSS_STREAK_CAUTION - 1,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "LOSS_STREAK_CAUTION" not in flag_codes
        assert "LOSS_STREAK_TILT" not in flag_codes


# ---------------------------------------------------------------------------
# Revenge trade detection
# ---------------------------------------------------------------------------

class TestRevengeTrade:
    def test_revenge_trade_detected(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=1,
            hours_since_last_trade=0.2,  # 12 min after a loss
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "REVENGE_TRADE_RISK" in flag_codes

    def test_no_revenge_if_no_losses(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=0,
            hours_since_last_trade=0.1,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "REVENGE_TRADE_RISK" not in flag_codes

    def test_no_revenge_if_enough_time(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            recent_consecutive_losses=2,
            hours_since_last_trade=2.0,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "REVENGE_TRADE_RISK" not in flag_codes


# ---------------------------------------------------------------------------
# Overtrading
# ---------------------------------------------------------------------------

class TestOvertrading:
    def test_overtrade_at_max(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            trades_today=MAX_TRADES_PER_DAY,
        )
        result = analyze("EURUSD", inputs)
        assert result.overtrade_warning is True
        flag_codes = [f.code for f in result.flags]
        assert "OVERTRADE" in flag_codes

    def test_no_overtrade_below_max(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            trades_today=MAX_TRADES_PER_DAY - 1,
        )
        result = analyze("EURUSD", inputs)
        assert result.overtrade_warning is False


# ---------------------------------------------------------------------------
# Bad day / session
# ---------------------------------------------------------------------------

class TestBadDayAndSession:
    def test_bad_day_flag(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            daily_pnl_pct=BAD_DAY_PNL_PCT - 0.5,  # worse than threshold
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "BAD_DAY" in flag_codes

    def test_out_of_session_flag(self) -> None:
        inputs = PsychologyInputs(
            retail_long_ratio=0.50,
            in_session_window=False,
        )
        result = analyze("EURUSD", inputs)
        flag_codes = [f.code for f in result.flags]
        assert "OUT_OF_SESSION" in flag_codes


# ---------------------------------------------------------------------------
# Tilt detection — full compound scenario
# ---------------------------------------------------------------------------

class TestTiltDetection:
    def test_tilted_state(self, tilted_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", tilted_inputs)
        assert result.state == PsychState.TILT
        assert result.tilt_detected is True
        assert result.psych_score < 25.0

    def test_tilted_multiple_critical_flags(self, tilted_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", tilted_inputs)
        critical_flags = [f for f in result.flags if f.severity == "CRITICAL"]
        assert len(critical_flags) >= 2


# ---------------------------------------------------------------------------
# Psych score bounds & determinism
# ---------------------------------------------------------------------------

class TestPsychScore:
    def test_score_within_bounds(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert 0.0 <= result.psych_score <= 100.0

    def test_score_deterministic(self, optimal_inputs: PsychologyInputs) -> None:
        r1 = analyze("EURUSD", optimal_inputs)
        r2 = analyze("EURUSD", optimal_inputs)
        assert r1.psych_score == r2.psych_score

    def test_tilted_score_low(self, tilted_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", tilted_inputs)
        assert result.psych_score < 30.0


# ---------------------------------------------------------------------------
# Result immutability & no side-effects
# ---------------------------------------------------------------------------

class TestResultIntegrity:
    def test_result_is_l5result(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert isinstance(result, L5Result)

    def test_result_is_frozen(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        with pytest.raises(AttributeError):
            result.state = PsychState.TILT  # type: ignore[misc]

    def test_flags_are_tuple(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("EURUSD", optimal_inputs)
        assert isinstance(result.flags, tuple)

    def test_symbol_preserved(self, optimal_inputs: PsychologyInputs) -> None:
        result = analyze("GBPJPY", optimal_inputs)
        assert result.symbol == "GBPJPY"

    def test_no_side_effects_on_inputs(self, optimal_inputs: PsychologyInputs) -> None:
        original_ratio = optimal_inputs.retail_long_ratio
        _ = analyze("EURUSD", optimal_inputs)
        assert optimal_inputs.retail_long_ratio == original_ratio

    def test_metadata_passthrough(self, optimal_inputs: PsychologyInputs) -> None:
        meta = {"session": "london", "day_of_week": "monday"}
        result = analyze("EURUSD", optimal_inputs, metadata=meta)
        assert result.metadata == meta
