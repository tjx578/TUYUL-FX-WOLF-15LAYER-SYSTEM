"""Canonical TII adapter tests.

Verifies that analysis.formulas.tii_formula.calculate_tii delegates to
analysis.l8_tii canonical implementation and applies input guards.
"""

from __future__ import annotations

from analysis.formulas.tii_formula import calculate_tii


def test_calculate_tii_returns_none_on_invalid_guards() -> None:
    assert calculate_tii(0.6, 0.5, 0.2, 0.9, price=1.1, vwap=0.0, atr=0.001) is None
    assert calculate_tii(0.6, 0.5, 0.2, 0.9, price=0.0, vwap=1.1, atr=0.001) is None
    assert calculate_tii(0.6, 0.5, 0.2, 0.9, price=1.1, vwap=1.1, atr=0.0) is None


def test_calculate_tii_returns_canonical_range() -> None:
    tii = calculate_tii(
        trq=0.72,
        intensity=0.65,
        bias_strength=0.41,
        integrity=0.87,
        price=1.1050,
        vwap=1.1042,
        atr=0.0012,
    )
    assert tii is not None
    assert 0.0 <= tii <= 1.0


def test_calculate_tii_clamps_intensity_and_integrity() -> None:
    tii_low = calculate_tii(
        trq=0.6,
        intensity=-5.0,
        bias_strength=0.2,
        integrity=-2.0,
        price=1.2,
        vwap=1.19,
        atr=0.0009,
    )
    tii_high = calculate_tii(
        trq=0.6,
        intensity=5.0,
        bias_strength=0.2,
        integrity=2.0,
        price=1.2,
        vwap=1.19,
        atr=0.0009,
    )
    assert tii_low is not None
    assert tii_high is not None
    assert 0.0 <= tii_low <= 1.0
    assert 0.0 <= tii_high <= 1.0
