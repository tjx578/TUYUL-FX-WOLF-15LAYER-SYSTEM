"""
Tests for Layer 14 — Adaptive Learning / Pattern Memory.
Zone: Journal boundary. Advisory-only. No L12 override. No execution.
"""

import pytest

from journal.l13_reflection import (
    L13ReflectionRecord,
    LayerContribution,
    OriginalDecision,
    OutcomeType,
    ReflectionVerdict,
    TradeOutcome,
)
from journal.l14_adaptive import (
    InsightType,
    L14AdaptiveResult,
    _compute_overall_win_rate,
    _extract_top_lesson_tags,
    analyze_patterns,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reflection(
    signal_id: str,
    symbol: str,
    verdict: ReflectionVerdict,
    wolf_score: float = 70.0,
    tii_score: float = 70.0,
    psych_state: str = "OPTIMAL",
    lesson_tags: tuple[str, ...] = (),
    layer_contribs: tuple[LayerContribution, ...] = (),
) -> L13ReflectionRecord:
    """Helper to create reflection records for testing."""
    outcome_type = (
        OutcomeType.WIN
        if verdict == ReflectionVerdict.CORRECT_EXECUTE
        else OutcomeType.LOSS
        if verdict == ReflectionVerdict.INCORRECT_EXECUTE
        else OutcomeType.REJECTED_NO_TRADE
    )
    return L13ReflectionRecord(
        signal_id=signal_id,
        symbol=symbol,
        reflection_verdict=verdict,
        original_decision=OriginalDecision(
            signal_id=signal_id,
            symbol=symbol,
            verdict="EXECUTE" if "EXECUTE" in verdict.value else "REJECT",
            confidence=0.75,
            wolf_score=wolf_score,
            tii_score=tii_score,
            psych_state=psych_state,
        ),
        trade_outcome=TradeOutcome(
            symbol=symbol,
            outcome_type=outcome_type,
            pnl_pips=20.0 if outcome_type == OutcomeType.WIN else -15.0,
        ),
        layer_contributions=layer_contribs,
        timing_quality=70.0,
        exit_quality=75.0,
        lesson_tags=lesson_tags,
        reflection_notes="",
        timestamp="2026-02-17T12:00:00Z",
    )


@pytest.fixture
def mixed_history() -> list[L13ReflectionRecord]:
    """10 reflection records with mixed results."""
    positive_l4 = LayerContribution(layer="L4_scoring", accuracy_contribution="POSITIVE")
    negative_l4 = LayerContribution(layer="L4_scoring", accuracy_contribution="NEGATIVE")
    neutral_l8 = LayerContribution(layer="L8_tii", accuracy_contribution="NEUTRAL")
    positive_l8 = LayerContribution(layer="L8_tii", accuracy_contribution="POSITIVE")

    return [
        _make_reflection(
            "S01",
            "EURUSD",
            ReflectionVerdict.CORRECT_EXECUTE,
            lesson_tags=("clean_exit",),
            layer_contribs=(positive_l4, positive_l8),
        ),
        _make_reflection(
            "S02",
            "EURUSD",
            ReflectionVerdict.CORRECT_EXECUTE,
            lesson_tags=("clean_exit",),
            layer_contribs=(positive_l4, neutral_l8),
        ),
        _make_reflection(
            "S03",
            "EURUSD",
            ReflectionVerdict.INCORRECT_EXECUTE,
            lesson_tags=("poor_entry_timing",),
            layer_contribs=(negative_l4, neutral_l8),
        ),
        _make_reflection(
            "S04",
            "GBPJPY",
            ReflectionVerdict.CORRECT_EXECUTE,
            lesson_tags=("clean_exit",),
            layer_contribs=(positive_l4,),
        ),
        _make_reflection(
            "S05",
            "GBPJPY",
            ReflectionVerdict.INCORRECT_EXECUTE,
            lesson_tags=("loss_taken",),
            layer_contribs=(negative_l4,),
        ),
        _make_reflection(
            "S06",
            "GBPJPY",
            ReflectionVerdict.INCORRECT_EXECUTE,
            lesson_tags=("loss_taken", "poor_entry_timing"),
            layer_contribs=(negative_l4,),
        ),
        _make_reflection(
            "S07",
            "XAUUSD",
            ReflectionVerdict.CORRECT_REJECT,
            lesson_tags=("good_rejection",),
            layer_contribs=(positive_l4,),
        ),
        _make_reflection(
            "S08",
            "XAUUSD",
            ReflectionVerdict.CORRECT_REJECT,
            lesson_tags=("good_rejection",),
            layer_contribs=(positive_l4,),
        ),
        _make_reflection(
            "S09",
            "XAUUSD",
            ReflectionVerdict.INCORRECT_REJECT,
            lesson_tags=("missed_opportunity",),
            layer_contribs=(negative_l4,),
        ),
        _make_reflection(
            "S10",
            "EURUSD",
            ReflectionVerdict.CORRECT_EXECUTE,
            lesson_tags=("excellent_entry_timing",),
            layer_contribs=(positive_l4,),
        ),
    ]


@pytest.fixture
def empty_history() -> list[L13ReflectionRecord]:
    return []


# ---------------------------------------------------------------------------
# Overall win rate
# ---------------------------------------------------------------------------


class TestOverallWinRate:
    def test_mixed_win_rate(self, mixed_history: list[L13ReflectionRecord]) -> None:
        wr = _compute_overall_win_rate(mixed_history)
        # 7 correct (S01,S02,S04,S07,S08,S10 + S07,S08 are CORRECT_REJECT) out of 10
        # CORRECT_EXECUTE: S01,S02,S04,S10 = 4
        # CORRECT_REJECT: S07,S08 = 2 → total 6/10 = 0.6
        # Wait: S03=INCORRECT_EXECUTE, S05=INCORRECT_EXECUTE, S06=INCORRECT_EXECUTE, S09=INCORRECT_REJECT
        # Correct: S01,S02,S04,S07,S08,S10 = 6 → 6/10 = 0.6
        assert wr == 0.6

    def test_empty_returns_zero(self, empty_history: list[L13ReflectionRecord]) -> None:
        assert _compute_overall_win_rate(empty_history) == 0.0

    def test_all_wins(self) -> None:
        records = [_make_reflection(f"S{i}", "EURUSD", ReflectionVerdict.CORRECT_EXECUTE) for i in range(5)]
        assert _compute_overall_win_rate(records) == 1.0


# ---------------------------------------------------------------------------
# Top lesson tags
# ---------------------------------------------------------------------------


class TestTopLessonTags:
    def test_most_frequent_tags(self, mixed_history: list[L13ReflectionRecord]) -> None:
        tags = _extract_top_lesson_tags(mixed_history, top_n=3)
        assert len(tags) <= 3
        assert len(tags) > 0
        # "clean_exit" appears 3 times, should be in top
        assert "clean_exit" in tags

    def test_empty_returns_empty(self, empty_history: list[L13ReflectionRecord]) -> None:
        tags = _extract_top_lesson_tags(empty_history)
        assert tags == []


# ---------------------------------------------------------------------------
# Full analyze_patterns pipeline
# ---------------------------------------------------------------------------


class TestAnalyzePatterns:
    def test_returns_l14_result(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert isinstance(result, L14AdaptiveResult)

    def test_result_is_frozen(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        with pytest.raises(AttributeError):
            result.overall_win_rate = 0.0  # type: ignore[misc]

    def test_analysis_id_preserved(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert result.analysis_id == "A001"

    def test_period_label_preserved(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert result.period_label == "2026-W07"

    def test_total_reflections_counted(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert result.total_reflections_analysed == 10

    def test_insights_generated(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert len(result.insights) > 0

    def test_pair_patterns_present(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        pair_insights = [i for i in result.insights if i.insight_type == InsightType.PAIR_PATTERN]
        assert len(pair_insights) > 0

    def test_layer_accuracy_present(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        layer_insights = [i for i in result.insights if i.insight_type == InsightType.LAYER_ACCURACY]
        assert len(layer_insights) > 0

    def test_weight_suggestions_are_advisory(self, mixed_history: list[L13ReflectionRecord]) -> None:
        """L14 weight suggestions MUST be advisory-only, never auto-applied."""
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        for suggestion in result.weight_suggestions:
            assert suggestion.direction in ("increase", "decrease", "maintain")
            assert 0.0 <= suggestion.confidence <= 1.0

    def test_empty_history(self, empty_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(empty_history, "A002", "2026-W07")
        assert result.total_reflections_analysed == 0
        assert result.overall_win_rate == 0.0
        assert len(result.insights) == 0
        assert len(result.weight_suggestions) == 0

    def test_metadata_passthrough(self, mixed_history: list[L13ReflectionRecord]) -> None:
        meta = {"analyst": "auto", "version": "1.0"}
        result = analyze_patterns(mixed_history, "A001", "2026-W07", metadata=meta)
        assert result.metadata == meta

    def test_no_side_effects_on_input(self, mixed_history: list[L13ReflectionRecord]) -> None:
        original_len = len(mixed_history)
        original_first_id = mixed_history[0].signal_id
        _ = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert len(mixed_history) == original_len
        assert mixed_history[0].signal_id == original_first_id

    def test_timestamp_populated(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert "2026" in result.timestamp

    def test_top_lesson_tags_populated(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        assert len(result.top_lesson_tags) > 0


# ---------------------------------------------------------------------------
# Constitutional boundary enforcement
# ---------------------------------------------------------------------------


class TestConstitutionalBoundary:
    """L14 MUST NOT have any method that modifies L12 verdicts or triggers execution."""

    def test_no_execute_method(self) -> None:
        """L14 module must not expose any execute/trade function."""
        import journal.l14_adaptive as mod

        public_names = [n for n in dir(mod) if not n.startswith("_")]
        forbidden = {"execute", "place_order", "send_trade", "override_verdict", "modify_l12"}
        assert forbidden.isdisjoint(set(public_names))

    def test_result_has_no_execute_field(self, mixed_history: list[L13ReflectionRecord]) -> None:
        result = analyze_patterns(mixed_history, "A001", "2026-W07")
        field_names = set(result.__dataclass_fields__.keys())
        forbidden_fields = {"trade_action", "execute", "override", "order_id"}
        assert forbidden_fields.isdisjoint(field_names)
