"""TII (Trade Integrity Index) formula.

Zone: analysis/formulas/ — pure calculation, no side-effects.

Computes a tanh-normalised integrity score from pre-scored components.
Consumed by constitution/layer12_pipeline.py for the L12 verdict.
"""

from numpy import tanh

__all__ = ["calculate_tii"]


def calculate_tii(
    trq: float,
    intensity: float,
    bias_strength: float,
    integrity: float,
    price: float,
    vwap: float,
    atr: float,
) -> float | None:
    """Compute Trade Integrity Index from pre-scored components.

    Returns tanh-normalised score in [0, 0.999], or None if inputs invalid.
    """
    if vwap == 0 or atr <= 0 or price <= 0:
        return None  # Invalid data
    deviation = abs(price - vwap) / atr
    raw_tii = (trq * intensity * bias_strength * integrity) / (1 + deviation)
    tii_index = tanh(raw_tii)
    return min(max(tii_index, 0.0), 0.999)
