"""Lorentzian Field Stabilizer — pure mathematical engine.

All outputs are bounded. No pipeline dependency, no IO, no state.
"""

from __future__ import annotations

from math import sqrt


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_e_norm(alpha: float, beta: float, gamma: float) -> float:
    """Normalized field energy E_norm ∈ [0, 1]."""
    return _clamp(sqrt(alpha**2 + beta**2 + gamma**2) / sqrt(3.0))


def compute_gradient_signed(d_alpha: float, d_beta: float, d_gamma: float) -> float:
    """Mean signed gradient — positive=expansion, negative=contraction."""
    return (d_alpha + d_beta + d_gamma) / 3.0


def compute_gradient_abs(alpha: float, beta: float, gamma: float) -> float:
    """Mean pairwise distance — measures inter-axis divergence."""
    return (abs(alpha - beta) + abs(beta - gamma) + abs(alpha - gamma)) / 3.0


def compute_lrce(
    e_norm: float,
    meta_integrity: float,
    integrity_index: float,
    drift: float,
) -> float:
    """Lorentzian Reflective Coherence Estimate ∈ [0, 1]."""
    denom = 1.0 + abs(drift)
    return _clamp((e_norm * meta_integrity * integrity_index) / denom)


def classify_phase(gradient_signed: float) -> str:
    """Classify field phase based on signed gradient."""
    if gradient_signed > 0.005:
        return "EXPANSION"
    if gradient_signed < -0.005:
        return "CONTRACTION"
    return "STABILIZATION"


# ── Confidence adjustment thresholds (conservative defaults) ──────

LFS_RESCUE_LRCE_MIN = 0.970
LFS_RESCUE_DRIFT_MAX = 0.0045
LFS_RESCUE_GRADIENT_MAX = 0.005
LFS_MAX_BONUS = 0.03
LFS_MAX_PENALTY = -0.04


def compute_confidence_adj(lrce: float, drift: float, gradient_signed: float) -> float:
    """Bounded confidence adjustment ∈ [LFS_MAX_PENALTY, LFS_MAX_BONUS]."""
    if lrce >= LFS_RESCUE_LRCE_MIN and drift <= 0.004 and abs(gradient_signed) <= LFS_RESCUE_GRADIENT_MAX:
        return LFS_MAX_BONUS
    if lrce >= 0.955 and drift <= 0.006:
        return 0.01
    if lrce < 0.930 or drift > 0.008:
        return LFS_MAX_PENALTY
    return 0.0
