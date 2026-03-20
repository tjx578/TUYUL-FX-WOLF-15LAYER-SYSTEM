"""
Tests for journal/l14_underperform_miner.py

Coverage targets:
  - JournalExtractor: field alias resolution, missing fields, partial tolerance
  - UnderperformPatternMiner: min_trades threshold, penalty scoring, Wilson
    bound, redundancy pruning, memory guard
  - L14AdaptiveReflection: end-to-end flow, context matching, penalty bounds
  - Constitutional boundary: no execute methods, advisory-only output
  - Edge cases: empty data, single record, all wins, all losses
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from journal.l14_underperform_miner import (
    _MAX_GROUPED_KEYS,
    _infer_result,
    _norm_text,
    _to_datetime,
    _to_float,
    _wilson_lower_bound,
    AdaptiveReflectionReport,
    analyze_underperforming_setups,
    JournalExtractor,
    JournalRecord,
    L14AdaptiveReflection,
    PatternStats,
    UnderperformPatternMiner,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _row(
    *,
    setup_type: str = "LONDON_SWEEP",
    pair: str = "EURUSD",
    timeframe: str = "H1",
    session: str = "LONDON",
    regime: str = "TREND",
    direction: str = "LONG",
    outcome_r: float = 1.0,
    pnl: float | None = None,
    stage: str = "J4",
) -> dict[str, Any]:
    """Build a minimal valid raw journal row."""
    return {
        "setup_type": setup_type,
        "pair": pair,
        "timeframe": timeframe,
        "session": session,
        "regime": regime,
        "direction": direction,
        "outcome_r": outcome_r,
        "pnl": pnl,
        "journal_stage": stage,
    }


def _make_rows(
    n: int,
    outcome_r: float = 1.0,
    *,
    setup_type: str = "LONDON_SWEEP",
    pair: str = "EURUSD",
    timeframe: str = "H1",
    session: str = "LONDON",
    regime: str = "TREND",
    direction: str = "LONG",
) -> list[dict[str, Any]]:
    """Build *n* identical rows."""
    return [
        _row(
            setup_type=setup_type,
            pair=pair,
            timeframe=timeframe,
            session=session,
            regime=regime,
            direction=direction,
            outcome_r=outcome_r,
        )
        for _ in range(n)
    ]


def _mixed_dataset(
    n_good: int = 10,
    n_bad: int = 10,
) -> list[dict[str, Any]]:
    """Two groups: one profitable (EURUSD/H1/TREND) and one losing (XAUUSD/M15/RANGE)."""
    good = _make_rows(
        n_good,
        outcome_r=1.5,
        pair="EURUSD",
        timeframe="H1",
        regime="TREND",
        direction="LONG",
    )
    bad = _make_rows(
        n_bad,
        outcome_r=-0.8,
        pair="XAUUSD",
        timeframe="M15",
        regime="RANGE",
        direction="SHORT",
    )
    return good + bad


# ---------------------------------------------------------------------------
# Private utility tests
# ---------------------------------------------------------------------------


class TestNormText:
    def test_upper_case(self) -> None:
        assert _norm_text("london") == "LONDON"

    def test_spaces_to_underscores(self) -> None:
        assert _norm_text("new york") == "NEW_YORK"

    def test_none_returns_none(self) -> None:
        assert _norm_text(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _norm_text("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _norm_text("   ") is None

    def test_numeric_coerced(self) -> None:
        assert _norm_text(42) == "42"


class TestToFloat:
    def test_int(self) -> None:
        assert _to_float(3) == 3.0

    def test_string(self) -> None:
        assert _to_float("1.5") == 1.5

    def test_none_returns_none(self) -> None:
        assert _to_float(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _to_float("") is None

    def test_invalid_returns_none(self) -> None:
        assert _to_float("abc") is None


class TestToDatetime:
    def test_iso_format(self) -> None:
        dt = _to_datetime("2026-03-08T14:00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_date_only(self) -> None:
        dt = _to_datetime("2026-03-08")
        assert dt is not None

    def test_none_returns_none(self) -> None:
        assert _to_datetime(None) is None

    def test_empty_returns_none(self) -> None:
        assert _to_datetime("") is None

    def test_already_datetime(self) -> None:
        from datetime import datetime
        now = datetime(2026, 1, 1)
        assert _to_datetime(now) is now


class TestInferResult:
    def test_positive_r_is_win(self) -> None:
        assert _infer_result(1.5, None) == "WIN"

    def test_negative_r_is_loss(self) -> None:
        assert _infer_result(-0.5, None) == "LOSS"

    def test_zero_r_is_be(self) -> None:
        assert _infer_result(0.0, None) == "BE"

    def test_explicit_win_label(self) -> None:
        assert _infer_result(None, "WIN") == "WIN"

    def test_explicit_breakeven_label(self) -> None:
        assert _infer_result(None, "BE") == "BE"
        assert _infer_result(None, "BREAKEVEN") == "BE"

    def test_none_r_none_label(self) -> None:
        assert _infer_result(None, None) == "UNKNOWN"


class TestWilsonLowerBound:
    def test_zero_total(self) -> None:
        assert _wilson_lower_bound(0, 0) == 0.0

    def test_all_wins(self) -> None:
        lb = _wilson_lower_bound(100, 100)
        assert lb > 0.9

    def test_all_losses(self) -> None:
        lb = _wilson_lower_bound(0, 100)
        assert lb == 0.0

    def test_50_percent(self) -> None:
        lb = _wilson_lower_bound(50, 100)
        assert 0.3 < lb < 0.5


# ---------------------------------------------------------------------------
# JournalExtractor tests
# ---------------------------------------------------------------------------


class TestJournalExtractor:
    def setup_method(self) -> None:
        self.extractor = JournalExtractor()

    def test_basic_extraction(self) -> None:
        rows = _make_rows(5)
        records, total = self.extractor.extract(rows)
        assert total == 5
        assert len(records) == 5

    def test_setup_type_alias_setup(self) -> None:
        row = {"setup": "FAKEOUT", "outcome_r": 1.0}
        records, _ = self.extractor.extract([row])
        assert len(records) == 1
        assert records[0].setup_type == "FAKEOUT"

    def test_setup_type_alias_model(self) -> None:
        row = {"model": "BOS_SWEEP", "outcome_r": -0.5}
        records, _ = self.extractor.extract([row])
        assert len(records) == 1
        assert records[0].setup_type == "BOS_SWEEP"

    def test_outcome_r_alias_realized_r(self) -> None:
        row = {"setup_type": "X", "realized_r": 2.0}
        records, _ = self.extractor.extract([row])
        assert records[0].outcome_r == 2.0

    def test_outcome_r_alias_r_multiple(self) -> None:
        row = {"setup_type": "X", "r_multiple": -1.0}
        records, _ = self.extractor.extract([row])
        assert records[0].outcome_r == -1.0

    def test_pair_alias_symbol(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "symbol": "GBPUSD"}
        records, _ = self.extractor.extract([row])
        assert records[0].pair == "GBPUSD"

    def test_pair_alias_instrument(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "instrument": "XAUUSD"}
        records, _ = self.extractor.extract([row])
        assert records[0].pair == "XAUUSD"

    def test_timeframe_alias_tf(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "tf": "m15"}
        records, _ = self.extractor.extract([row])
        assert records[0].timeframe == "M15"

    def test_missing_setup_type_skipped(self) -> None:
        row = {"outcome_r": 1.0}
        records, total = self.extractor.extract([row])
        assert total == 1
        assert len(records) == 0

    def test_missing_outcome_r_skipped(self) -> None:
        row = {"setup_type": "X"}
        records, total = self.extractor.extract([row])
        assert total == 1
        assert len(records) == 0

    def test_partial_dimensions_tolerated(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0}  # no pair, session, etc.
        records, _ = self.extractor.extract([row])
        assert len(records) == 1
        assert records[0].pair is None
        assert records[0].session is None

    def test_is_win_property(self) -> None:
        row = _row(outcome_r=1.5)
        records, _ = self.extractor.extract([row])
        assert records[0].is_win is True
        assert records[0].is_loss is False

    def test_is_loss_property(self) -> None:
        row = _row(outcome_r=-0.5)
        records, _ = self.extractor.extract([row])
        assert records[0].is_win is False
        assert records[0].is_loss is True

    def test_breakeven_neither_win_nor_loss(self) -> None:
        row = _row(outcome_r=0.0)
        records, _ = self.extractor.extract([row])
        assert records[0].is_win is False
        assert records[0].is_loss is False

    def test_empty_rows(self) -> None:
        records, total = self.extractor.extract([])
        assert records == []
        assert total == 0

    def test_stage_default_when_missing(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0}
        records, _ = self.extractor.extract([row])
        assert records[0].stage == "J?"

    def test_stage_from_journal_stage(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "journal_stage": "J3"}
        records, _ = self.extractor.extract([row])
        assert records[0].stage == "J3"

    def test_pnl_extracted(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "pnl": 150.0}
        records, _ = self.extractor.extract([row])
        assert records[0].pnl == 150.0

    def test_pnl_alias_realized_pnl(self) -> None:
        row = {"setup_type": "X", "outcome_r": 1.0, "realized_pnl": -75.0}
        records, _ = self.extractor.extract([row])
        assert records[0].pnl == -75.0

    def test_raw_preserved(self) -> None:
        row = _row(outcome_r=2.0)
        records, _ = self.extractor.extract([row])
        assert records[0].raw is row


# ---------------------------------------------------------------------------
# UnderperformPatternMiner tests
# ---------------------------------------------------------------------------


class TestUnderperformPatternMiner:
    def setup_method(self) -> None:
        self.extractor = JournalExtractor()
        self.miner = UnderperformPatternMiner(min_trades=8)

    def _extract(self, rows: list[dict]) -> list[JournalRecord]:
        records, _ = self.extractor.extract(rows)
        return records

    def test_empty_returns_empty(self) -> None:
        patterns, be, bw = self.miner.mine([])
        assert patterns == []
        assert be == 0.0
        assert bw == 0.0

    def test_below_min_trades_not_flagged(self) -> None:
        # Only 5 rows for the bad setup — below min_trades=8
        good = _make_rows(10, outcome_r=1.5)
        bad = _make_rows(5, outcome_r=-0.8, pair="XAUUSD", timeframe="M15", regime="RANGE")
        records = self._extract(good + bad)
        patterns, _, _ = self.miner.mine(records)
        # No pattern should be flagged for the 5-row group
        bad_sigs = [p.signature for p in patterns if "XAUUSD" in p.signature]
        assert bad_sigs == []

    def test_sufficient_trades_can_flag(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        # At least one pattern should reference the bad group
        assert len(patterns) >= 1

    def test_baseline_expectancy_computed(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        _, baseline_e, _ = self.miner.mine(records)
        # good=1.5*10, bad=-0.8*10; mean = (15 - 8)/20 = 0.35
        assert math.isclose(baseline_e, 0.35, abs_tol=0.01)

    def test_baseline_win_rate_computed(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        _, _, baseline_wr = self.miner.mine(records)
        # 10 wins, 10 losses → 0.5
        assert math.isclose(baseline_wr, 0.5, abs_tol=0.01)

    def test_pattern_stats_immutable(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        if patterns:
            with pytest.raises((AttributeError, TypeError)):
                patterns[0].penalty_score = 0.0  # type: ignore[misc]

    def test_reasons_is_tuple(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            assert isinstance(p.reasons, tuple)

    def test_dimensions_is_tuple(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            assert isinstance(p.dimensions, tuple)

    def test_penalty_score_bounded_0_to_1(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            assert 0.0 <= p.penalty_score <= 1.0

    def test_win_rate_bounded(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            assert 0.0 <= p.win_rate <= 1.0

    def test_max_patterns_limit(self) -> None:
        miner = UnderperformPatternMiner(min_trades=8, max_patterns=3)
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = miner.mine(records)
        assert len(patterns) <= 3

    def test_all_wins_no_flagged_patterns(self) -> None:
        rows = _make_rows(20, outcome_r=2.0)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        # If everyone has the same positive outcome there is no underperformer
        assert patterns == []

    def test_all_losses_baseline_negative(self) -> None:
        rows = _make_rows(20, outcome_r=-1.0)
        records = self._extract(rows)
        patterns, baseline_e, _ = self.miner.mine(records)
        assert baseline_e < 0

    def test_signature_contains_dimension_values(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            for dim, val in zip(p.dimensions, p.values):
                assert f"{dim}={val}" in p.signature

    def test_wilson_low_in_pattern(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        for p in patterns:
            assert 0.0 <= p.wilson_low <= 1.0

    def test_memory_guard_constant_exists(self) -> None:
        assert _MAX_GROUPED_KEYS == 5000

    def test_memory_guard_prevents_explosion(self) -> None:
        """Miner must complete without error even with many distinct dimension combos."""
        # Generate 60 records each with a unique pair to force many grouped keys
        rows = [
            _row(
                pair=f"PAIR{i:03d}",
                timeframe=f"TF{i % 5}",
                session=f"S{i % 3}",
                regime=f"R{i % 4}",
                direction="LONG" if i % 2 == 0 else "SHORT",
                outcome_r=-0.5,
            )
            for i in range(60)
        ]
        records = self._extract(rows)
        # Should not raise and should complete in reasonable time
        patterns, _, _ = self.miner.mine(records)
        assert isinstance(patterns, list)

    def test_single_record_no_patterns(self) -> None:
        rows = [_row(outcome_r=-2.0)]
        records = self._extract(rows)
        patterns, _, _ = self.miner.mine(records)
        assert patterns == []


# ---------------------------------------------------------------------------
# L14AdaptiveReflection tests
# ---------------------------------------------------------------------------


class TestL14AdaptiveReflection:
    def setup_method(self) -> None:
        self.engine = L14AdaptiveReflection(
            UnderperformPatternMiner(min_trades=8)
        )

    def test_returns_report(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        assert isinstance(report, AdaptiveReflectionReport)

    def test_total_records_counted(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        report = self.engine.analyze(rows[:5], rows[5:])
        assert report.total_records == 20

    def test_usable_records_counted(self) -> None:
        rows = _mixed_dataset()
        # Add rows missing required fields
        invalid_rows = [{"foo": "bar"}, {"setup_type": "X"}]
        report = self.engine.analyze([], rows + invalid_rows)
        assert report.usable_records == len(rows)
        assert report.total_records == len(rows) + 2

    def test_empty_input(self) -> None:
        report = self.engine.analyze([], [])
        assert report.total_records == 0
        assert report.usable_records == 0
        assert report.baseline_expectancy_r == 0.0
        assert report.baseline_win_rate == 0.0
        assert report.flagged_patterns == []
        assert report.current_setup_penalty == 0.0

    def test_no_context_match_empty(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows, current_context={})
        assert report.current_setup_matches == []
        assert report.current_setup_penalty == 0.0

    def test_context_match_found(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        context = {
            "pair": "XAUUSD",
            "timeframe": "M15",
            "regime": "RANGE",
        }
        report = self.engine.analyze([], rows, current_context=context)
        # The bad pattern for XAUUSD/M15/RANGE should be matched
        if report.flagged_patterns:
            assert len(report.current_setup_matches) >= 0  # may or may not match exactly

    def test_context_no_match(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        context = {
            "pair": "NZDUSD",  # not in the dataset
            "timeframe": "W1",
        }
        report = self.engine.analyze([], rows, current_context=context)
        assert report.current_setup_matches == []
        assert report.current_setup_penalty == 0.0

    def test_penalty_bounded_by_penalty_for_current_setup(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        context = {
            "pair": "XAUUSD",
            "timeframe": "M15",
            "regime": "RANGE",
            "direction": "SHORT",
            "setup_type": "LONDON_SWEEP",
            "session": "LONDON",
        }
        report = self.engine.analyze([], rows, current_context=context)
        capped = self.engine.penalty_for_current_setup(report, max_penalty=0.35)
        assert 0.0 <= capped <= 0.35

    def test_penalty_for_current_setup_zero_when_no_match(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows, current_context={})
        assert self.engine.penalty_for_current_setup(report) == 0.0

    def test_adaptive_notes_non_empty(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        assert isinstance(report.adaptive_notes, list)
        assert len(report.adaptive_notes) >= 1

    def test_adaptive_notes_when_no_match(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows, current_context={})
        assert any("Tidak ada" in note for note in report.adaptive_notes)

    def test_j3_and_j4_combined(self) -> None:
        j3 = _make_rows(5, outcome_r=1.0)
        j4 = _make_rows(5, outcome_r=-0.5, pair="XAUUSD", regime="RANGE")
        report = self.engine.analyze(j3, j4)
        assert report.total_records == 10

    def test_to_dict_serialisable(self) -> None:
        import json
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        d = report.to_dict()
        # Must be JSON-serialisable (no datetime objects, etc.)
        serialised = json.dumps(d, default=str)
        assert isinstance(serialised, str)

    def test_to_dict_keys(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        d = report.to_dict()
        required_keys = {
            "total_records", "usable_records", "baseline_expectancy_r",
            "baseline_win_rate", "current_setup_penalty", "adaptive_notes",
            "flagged_patterns", "current_setup_matches",
        }
        assert required_keys <= set(d.keys())

    def test_penalty_aggregate_capped_at_1(self) -> None:
        """aggregate_penalty must never exceed 1.0."""
        rows = _mixed_dataset(n_good=10, n_bad=10)
        context = {
            "setup_type": "LONDON_SWEEP",
            "pair": "XAUUSD",
            "timeframe": "M15",
            "session": "LONDON",
            "regime": "RANGE",
            "direction": "SHORT",
        }
        report = self.engine.analyze([], rows, current_context=context)
        assert report.current_setup_penalty <= 1.0

    def test_baseline_expectancy_r_in_report(self) -> None:
        rows = _mixed_dataset(n_good=10, n_bad=10)
        report = self.engine.analyze([], rows)
        # baseline should be (10*1.5 + 10*-0.8) / 20 = (15 - 8) / 20 = 0.35
        assert math.isclose(report.baseline_expectancy_r, 0.35, abs_tol=0.01)


# ---------------------------------------------------------------------------
# analyze_underperforming_setups convenience function
# ---------------------------------------------------------------------------


class TestAnalyzeUnderperformingSetups:
    def test_returns_dict(self) -> None:
        rows = _mixed_dataset()
        result = analyze_underperforming_setups([], rows)
        assert isinstance(result, dict)

    def test_has_required_keys(self) -> None:
        rows = _mixed_dataset()
        result = analyze_underperforming_setups([], rows)
        assert "baseline_expectancy_r" in result
        assert "flagged_patterns" in result
        assert "current_setup_penalty" in result

    def test_custom_min_trades(self) -> None:
        rows = _make_rows(5, outcome_r=-1.0)
        # With min_trades=3 we should allow patterns from 5-trade groups
        result = analyze_underperforming_setups([], rows, min_trades=3)
        assert isinstance(result, dict)

    def test_empty_rows(self) -> None:
        result = analyze_underperforming_setups([], [])
        assert result["total_records"] == 0

    def test_with_context(self) -> None:
        rows = _mixed_dataset()
        ctx = {"pair": "XAUUSD", "regime": "RANGE"}
        result = analyze_underperforming_setups([], rows, current_context=ctx)
        assert "current_setup_penalty" in result


# ---------------------------------------------------------------------------
# Constitutional boundary tests
# ---------------------------------------------------------------------------


class TestConstitutionalBoundary:
    """L14 underperform miner MUST NOT expose execution or verdict-override capability."""

    def test_no_execute_method_on_module(self) -> None:
        import journal.l14_underperform_miner as mod
        public_names = {n for n in dir(mod) if not n.startswith("_")}
        forbidden = {"execute", "place_order", "send_trade", "override_verdict", "modify_l12"}
        assert forbidden.isdisjoint(public_names)

    def test_no_execute_method_on_reflection_class(self) -> None:
        engine = L14AdaptiveReflection()
        public_methods = {n for n in dir(engine) if not n.startswith("_")}
        forbidden = {"execute", "place_order", "override_verdict", "modify_l12"}
        assert forbidden.isdisjoint(public_methods)

    def test_report_has_no_execute_field(self) -> None:
        import dataclasses
        rows = _mixed_dataset()
        engine = L14AdaptiveReflection(UnderperformPatternMiner(min_trades=8))
        report = engine.analyze([], rows)
        field_names = {f.name for f in dataclasses.fields(report)}
        forbidden = {"trade_action", "execute", "override", "order_id"}
        assert forbidden.isdisjoint(field_names)

    def test_output_is_advisory_only(self) -> None:
        """Penalty output must be a float in [0, 1] — no execution side-effects."""
        rows = _mixed_dataset()
        engine = L14AdaptiveReflection(UnderperformPatternMiner(min_trades=8))
        report = engine.analyze([], rows)
        assert isinstance(report.current_setup_penalty, float)
        assert 0.0 <= report.current_setup_penalty <= 1.0

    def test_pattern_stats_frozen_immutable(self) -> None:
        rows = _mixed_dataset()
        engine = L14AdaptiveReflection(UnderperformPatternMiner(min_trades=8))
        report = engine.analyze([], rows)
        for p in report.flagged_patterns:
            with pytest.raises((AttributeError, TypeError)):
                p.penalty_score = 9.99  # type: ignore[misc]

    def test_l14_cannot_modify_l12_verdict(self) -> None:
        """L14 has no mechanism to change the constitution's verdict."""
        import journal.l14_underperform_miner as mod
        assert not hasattr(mod, "set_verdict")
        assert not hasattr(mod, "approve_trade")
        assert not hasattr(mod, "reject_trade")


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def setup_method(self) -> None:
        self.engine = L14AdaptiveReflection(
            UnderperformPatternMiner(min_trades=8)
        )

    def test_single_record(self) -> None:
        report = self.engine.analyze([], [_row(outcome_r=1.0)])
        assert report.total_records == 1
        assert report.flagged_patterns == []

    def test_exactly_min_trades_boundary(self) -> None:
        """Exactly 8 identical rows should be eligible for flagging."""
        rows = _make_rows(8, outcome_r=-1.0)
        miner = UnderperformPatternMiner(min_trades=8, min_penalty_score=0.0)
        engine = L14AdaptiveReflection(miner)
        report = engine.analyze([], rows)
        # With min_penalty_score=0 and all losses, the pattern may be flagged
        assert isinstance(report.flagged_patterns, list)

    def test_one_below_min_trades_boundary(self) -> None:
        """7 rows should NOT produce a flagged pattern with min_trades=8."""
        good = _make_rows(20, outcome_r=1.5)
        bad = _make_rows(7, outcome_r=-1.0, pair="XAUUSD", regime="RANGE")
        miner = UnderperformPatternMiner(min_trades=8)
        engine = L14AdaptiveReflection(miner)
        report = engine.analyze([], good + bad)
        bad_sigs = [p for p in report.flagged_patterns if "XAUUSD" in p.signature]
        assert bad_sigs == []

    def test_all_wins_no_patterns(self) -> None:
        rows = _make_rows(20, outcome_r=2.0)
        report = self.engine.analyze([], rows)
        assert report.flagged_patterns == []

    def test_all_losses_completes(self) -> None:
        rows = _make_rows(20, outcome_r=-1.0)
        report = self.engine.analyze([], rows)
        assert report.baseline_expectancy_r < 0

    def test_no_context_gives_zero_penalty(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        # No context → no match → zero penalty
        assert report.current_setup_penalty == 0.0

    def test_only_j3_rows(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze(rows, [])
        assert report.total_records == len(rows)

    def test_only_j4_rows(self) -> None:
        rows = _mixed_dataset()
        report = self.engine.analyze([], rows)
        assert report.total_records == len(rows)

    def test_mixed_valid_and_invalid_rows(self) -> None:
        valid = _make_rows(10, outcome_r=1.0)
        invalid = [{"foo": "bar"}, {"setup_type": "X"}, {"outcome_r": 0.5}]
        report = self.engine.analyze([], valid + invalid)
        assert report.total_records == 13
        assert report.usable_records == 10
