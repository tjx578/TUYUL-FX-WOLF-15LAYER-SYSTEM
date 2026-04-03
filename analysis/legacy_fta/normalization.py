"""Normalization helpers for legacy WOLF ARSENAL v4.0 scores.

All functions clamp outputs to their canonical range so that downstream
consumers never receive out-of-bound values regardless of input quality.
"""

from __future__ import annotations


def clamp01(x: float) -> float:
    """Clamp *x* to [0.0, 1.0]."""
    return max(0.0, min(1.0, x))


def score10_to_norm(x: float) -> float:
    """Map a 0-10 sub-score to [0, 1]."""
    return clamp01(x / 10.0)


def score50_to_norm(x: float) -> float:
    """Map a 0-50 currency total to [0, 1]."""
    return clamp01(x / 50.0)


def score100_to_norm(x: float) -> float:
    """Map a 0-100 FTA/technical score to [0, 1]."""
    return clamp01(x / 100.0)


def gap_points_to_norm(gap_points: float, max_gap: float = 30.0) -> float:
    """Normalize gap magnitude to [0, 1] with configurable ceiling.

    The default ``max_gap=30`` is a practical compromise: the legacy scoring
    system caps individual currencies at 50, so the theoretical maximum gap
    is 50. A 30-point gap already represents very strong divergence.
    """
    if max_gap <= 0.0:
        return 0.0
    return clamp01(abs(gap_points) / max_gap)


def fta100_to_l4_subscore(fta_score_100: float) -> float:
    """Convert legacy FTA 0-100 to a 0-5 sub-score suitable for L4 blending."""
    return score100_to_norm(fta_score_100) * 5.0


def fta100_to_l10_confidence(fta_score_100: float) -> float:
    """Convert legacy FTA 0-100 to a 0-1 confidence hint for L10 blending."""
    return score100_to_norm(fta_score_100)
