"""Tests for _coerce_confidence_to_score and the Phase 5 overlay conversion fix.

Regression guard against the production bug that produced ~74
``could not convert string to float: 'LOW'`` non-fatal errors per minute
in the engine log, stemming from naked ``float(l12_verdict["confidence"])``
when ``confidence`` is a band string (LOW/MEDIUM/HIGH/VERY_HIGH).
"""

from __future__ import annotations

import pytest


def _coerce():
    from pipeline.wolf_constitutional_pipeline import _coerce_confidence_to_score

    return _coerce_confidence_to_score


class TestCoerceConfidenceToScore:
    @pytest.mark.parametrize(
        "band,expected",
        [
            ("LOW", 0.25),
            ("MEDIUM", 0.50),
            ("HIGH", 0.75),
            ("VERY_HIGH", 0.95),
            ("low", 0.25),
            ("  High  ", 0.75),
        ],
    )
    def test_band_strings_map_to_numeric(self, band: str, expected: float):
        coerce = _coerce()
        score, warning = coerce(band)
        assert score == expected
        assert warning is None

    @pytest.mark.parametrize("value,expected", [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.73, 0.73)])
    def test_numeric_passes_through(self, value: float, expected: float):
        coerce = _coerce()
        score, warning = coerce(value)
        assert score == pytest.approx(expected)
        assert warning is None

    def test_numeric_out_of_range_is_clamped(self):
        coerce = _coerce()
        assert coerce(1.5) == (1.0, None)
        assert coerce(-0.3) == (0.0, None)

    def test_int_accepted(self):
        coerce = _coerce()
        score, warning = coerce(1)
        assert score == 1.0
        assert warning is None

    def test_numeric_string_accepted(self):
        coerce = _coerce()
        score, warning = coerce("0.42")
        assert score == pytest.approx(0.42)
        assert warning is None

    @pytest.mark.parametrize("bad", [None, "UNKNOWN_BAND", "", [], {}, object()])
    def test_unmappable_returns_warning_not_raises(self, bad):
        """The original bug — must never raise ValueError here."""
        coerce = _coerce()
        score, warning = coerce(bad)
        assert score == 0.0
        assert warning == "PHASE5_NON_NUMERIC_CONFIDENCE"

    def test_bool_is_rejected_as_non_numeric(self):
        """Booleans are Python ints — explicitly reject to avoid
        True/False being silently treated as 1.0/0.0 scores."""
        coerce = _coerce()
        for val in (True, False):
            score, warning = coerce(val)
            assert score == 0.0
            assert warning == "PHASE5_NON_NUMERIC_CONFIDENCE"

    def test_regression_float_low_no_longer_raises(self):
        """Direct regression: the exact input from the production log."""
        coerce = _coerce()
        # Must not raise; must map to 0.25 (LOW band).
        score, warning = coerce("LOW")
        assert score == 0.25
        assert warning is None
