"""
Tests for Layer 13 — Post-Trade Reflection Engine.
Zone: Journal (J4). Append-only. No decision authority.
"""

import pytest

from journal.l13_reflection import (
    L13ReflectionRecord,
    OriginalDecision,
    OutcomeType,
    ReflectionVerdict,
    TradeOutcome,
    _classify_reflection_verdict,
    _evaluate_exit_quality,
    _evaluate_timing_quality,
    _extract_lesson_tags,
    reflect,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def winning_execute() -> tuple[OriginalDecision, TradeOutcome]:
    decision = OriginalDecision(
        signal_id="SIG-001",
        symbol="EURUSD",
        verdict="EXECUTE",
        confidence=0.85,
        wolf_score=78.0,
        tii_score=82.0,
        psych_state="OPTIMAL",
        timestamp="2026-02-17T10:00:00Z",
    )
    outcome = TradeOutcome(
        symbol="EURUSD",
        outcome_type=OutcomeType.WIN,
        pnl_pips=35.0,
        pnl_percent=1.2,
        actual_rr=2.5,
        planned_rr=2.0,
        hold_duration_minutes=180.0,
        exit_reason="TP hit",
    )
    return decision, outcome


@pytest.fixture
def losing_execute() -> tuple[OriginalDecision, TradeOutcome]:
    decision = OriginalDecision(
        signal_id="SIG-002",
        symbol="GBPJPY",
        verdict="EXECUTE",
        confidence=0.65,
        wolf_score=55.0,
        tii_score=48.0,
        psych_state="CAUTION",
    )
    outcome = TradeOutcome(
        symbol="GBPJPY",
        outcome_type=OutcomeType.LOSS,
        pnl_pips=-25.0,
        pnl_percent=-0.8,
        actual_rr=-1.0,
        planned_rr=2.0,
        hold_duration_minutes=45.0,
        exit_reason="SL hit",
    )
    return decision, outcome


@pytest.fixture
def correct_rejection() -> tuple[OriginalDecision, TradeOutcome]:
    decision = OriginalDecision(
        signal_id="SIG-003",
        symbol="XAUUSD",
        verdict="REJECT",
        confidence=0.40,
        wolf_score=35.0,
        tii_score=30.0,
        psych_state="IMPAIRED",
    )
    outcome = TradeOutcome(
        symbol="XAUUSD",
        outcome_type=OutcomeType.REJECTED_NO_TRADE,
        pnl_pips=-40.0,  # hypothetical: price moved against would-be direction
    )
    return decision, outcome


@pytest.fixture
def missed_opportunity() -> tuple[OriginalDecision, TradeOutcome]:
    decision = OriginalDecision(
        signal_id="SIG-004",
        symbol="USDJPY",
        verdict="REJECT",
        confidence=0.50,
        wolf_score=60.0,
        tii_score=55.0,
        psych_state="CAUTION",
    )
    outcome = TradeOutcome(
        symbol="USDJPY",
        outcome_type=OutcomeType.REJECTED_NO_TRADE,
        pnl_pips=50.0,  # hypothetical: would have been profitable
    )
    return decision, outcome


# ---------------------------------------------------------------------------
# Reflection verdict classification
# ---------------------------------------------------------------------------

class TestReflectionVerdict:
    def test_correct_execute(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        verdict = _classify_reflection_verdict(decision.verdict, outcome)
        assert verdict == ReflectionVerdict.CORRECT_EXECUTE

    def test_incorrect_execute(
        self, losing_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = losing_execute
        verdict = _classify_reflection_verdict(decision.verdict, outcome)
        assert verdict == ReflectionVerdict.INCORRECT_EXECUTE

    def test_correct_reject(
        self, correct_rejection: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = correct_rejection
        verdict = _classify_reflection_verdict(decision.verdict, outcome)
        assert verdict == ReflectionVerdict.CORRECT_REJECT

    def test_incorrect_reject(
        self, missed_opportunity: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = missed_opportunity
        verdict = _classify_reflection_verdict(decision.verdict, outcome)
        assert verdict == ReflectionVerdict.INCORRECT_REJECT

    def test_breakeven_is_inconclusive(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD",
            outcome_type=OutcomeType.BREAKEVEN,
            pnl_pips=0.5,
        )
        verdict = _classify_reflection_verdict("EXECUTE", outcome)
        assert verdict == ReflectionVerdict.INCONCLUSIVE

    def test_rejection_with_negligible_move_is_inconclusive(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD",
            outcome_type=OutcomeType.REJECTED_NO_TRADE,
            pnl_pips=1.0,  # within BREAKEVEN_THRESHOLD_PIPS
        )
        verdict = _classify_reflection_verdict("REJECT", outcome)
        assert verdict == ReflectionVerdict.INCONCLUSIVE


# ---------------------------------------------------------------------------
# Timing quality
# ---------------------------------------------------------------------------

class TestTimingQuality:
    def test_better_than_planned(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD",
            outcome_type=OutcomeType.WIN,
            actual_rr=3.0,
            planned_rr=2.0,
        )
        quality = _evaluate_timing_quality(outcome)
        assert quality > 70.0

    def test_worse_than_planned(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD",
            outcome_type=OutcomeType.LOSS,
            actual_rr=0.5,
            planned_rr=2.0,
        )
        quality = _evaluate_timing_quality(outcome)
        assert quality < 40.0

    def test_no_rr_data_returns_neutral(self) -> None:
        outcome = TradeOutcome(symbol="EURUSD", outcome_type=OutcomeType.WIN)
        quality = _evaluate_timing_quality(outcome)
        assert quality == 50.0

    def test_within_bounds(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD",
            outcome_type=OutcomeType.WIN,
            actual_rr=10.0,
            planned_rr=1.0,
        )
        quality = _evaluate_timing_quality(outcome)
        assert 0.0 <= quality <= 100.0


# ---------------------------------------------------------------------------
# Exit quality
# ---------------------------------------------------------------------------

class TestExitQuality:
    def test_tp_hit_is_high(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD", outcome_type=OutcomeType.WIN, exit_reason="TP hit"
        )
        assert _evaluate_exit_quality(outcome) >= 80.0

    def test_sl_hit_loss_is_low(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD", outcome_type=OutcomeType.LOSS,
            pnl_pips=-20.0, exit_reason="SL hit",
        )
        assert _evaluate_exit_quality(outcome) <= 40.0

    def test_sl_hit_in_profit_is_moderate(self) -> None:
        outcome = TradeOutcome(
            symbol="EURUSD", outcome_type=OutcomeType.WIN,
            pnl_pips=5.0, exit_reason="SL hit (trailed)",
        )
        assert 50.0 <= _evaluate_exit_quality(outcome) <= 70.0


# ---------------------------------------------------------------------------
# Lesson tag extraction
# ---------------------------------------------------------------------------

class TestLessonTags:
    def test_loss_tagged(self) -> None:
        tags = _extract_lesson_tags(
            ReflectionVerdict.INCORRECT_EXECUTE,
            TradeOutcome(symbol="X", outcome_type=OutcomeType.LOSS),
            50.0, 50.0,
        )
        assert "loss_taken" in tags

    def test_missed_opportunity_tagged(self) -> None:
        tags = _extract_lesson_tags(
            ReflectionVerdict.INCORRECT_REJECT,
            TradeOutcome(symbol="X", outcome_type=OutcomeType.REJECTED_NO_TRADE, pnl_pips=50.0),
            50.0, 50.0,
        )
        assert "missed_opportunity" in tags

    def test_poor_entry_tagged(self) -> None:
        tags = _extract_lesson_tags(
            ReflectionVerdict.INCORRECT_EXECUTE,
            TradeOutcome(symbol="X", outcome_type=OutcomeType.LOSS),
            20.0, 50.0,     # timing_quality=20
        )
        assert "poor_entry_timing" in tags

    def test_very_short_hold_tagged(self) -> None:
        tags = _extract_lesson_tags(
            ReflectionVerdict.CORRECT_EXECUTE,
            TradeOutcome(
                symbol="X", outcome_type=OutcomeType.WIN,
                hold_duration_minutes=3.0,
            ),
            50.0, 50.0,
        )
        assert "very_short_hold" in tags

    def test_cut_winner_short_tagged(self) -> None:
        tags = _extract_lesson_tags(
            ReflectionVerdict.CORRECT_EXECUTE,
            TradeOutcome(
                symbol="X", outcome_type=OutcomeType.WIN,
                actual_rr=0.8, planned_rr=2.0,
            ),
            50.0, 50.0,
        )
        assert "cut_winner_short" in tags


# ---------------------------------------------------------------------------
# Full reflect() pipeline
# ---------------------------------------------------------------------------

class TestReflectFunction:
    def test_returns_reflection_record(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert isinstance(result, L13ReflectionRecord)

    def test_result_is_frozen(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        with pytest.raises(AttributeError):
            result.reflection_verdict = ReflectionVerdict.TILT  # type: ignore[misc]

    def test_signal_id_preserved(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert result.signal_id == "SIG-001"

    def test_symbol_preserved(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert result.symbol == "EURUSD"

    def test_winning_execute_verdict(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert result.reflection_verdict == ReflectionVerdict.CORRECT_EXECUTE

    def test_losing_execute_verdict(
        self, losing_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = losing_execute
        result = reflect(decision, outcome)
        assert result.reflection_verdict == ReflectionVerdict.INCORRECT_EXECUTE

    def test_timestamp_populated(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert result.timestamp != ""
        assert "2026" in result.timestamp

    def test_metadata_passthrough(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        meta = {"session": "london", "strategy": "wolf-classic"}
        result = reflect(decision, outcome, metadata=meta)
        assert result.metadata == meta

    def test_no_side_effects_on_inputs(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        original_signal = decision.signal_id
        _ = reflect(decision, outcome)
        assert decision.signal_id == original_signal

    def test_layer_contributions_populated(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        """Winning execute with high wolf/tii scores should show positive contributions."""
        decision, outcome = winning_execute
        result = reflect(decision, outcome)
        assert len(result.layer_contributions) > 0
        layer_names = [lc.layer for lc in result.layer_contributions]
        assert "L4_scoring" in layer_names

    def test_reflection_notes_preserved(
        self, winning_execute: tuple[OriginalDecision, TradeOutcome]
    ) -> None:
        decision, outcome = winning_execute
        result = reflect(decision, outcome, reflection_notes="Clean setup, textbook entry")
        assert result.reflection_notes == "Clean setup, textbook entry"
