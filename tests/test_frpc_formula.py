"""Canonical FRPC formula tests."""

from __future__ import annotations

from analysis.formulas.frpc_formula import calculate_frpc


def test_frpc_is_bounded() -> None:
    val = calculate_frpc(
        fusion=1.2,
        trq=0.8,
        intensity=0.7,
        alpha=0.6,
        beta=0.55,
        gamma=0.52,
        integrity=0.95,
    )
    assert 0.0 <= float(val) <= 0.999


def test_frpc_zero_integrity_forces_zero_output() -> None:
    val = calculate_frpc(
        fusion=10.0,
        trq=10.0,
        intensity=10.0,
        alpha=1.0,
        beta=1.0,
        gamma=1.0,
        integrity=0.0,
    )
    assert float(val) == 0.0


def test_frpc_negative_inputs_clipped_and_non_negative() -> None:
    val = calculate_frpc(
        fusion=-2.0,
        trq=-1.0,
        intensity=-1.0,
        alpha=-0.2,
        beta=-0.4,
        gamma=-0.6,
        integrity=-1.0,
    )
    assert 0.0 <= float(val) <= 0.999
