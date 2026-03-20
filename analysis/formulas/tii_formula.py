"""TII (Trade Integrity Index) formula — redirect to canonical implementation.

Zone: analysis/formulas/ — pure calculation, no side-effects.

**Canonical TII lives in ``analysis.l8_tii._compute_tii``** (5-component
weighted model: VWAP alignment, energy coherence, bias confirmation,
reflective stability, meta integrity).  This module provides a thin
adapter so existing callers (``constitution/layer12_pipeline.py``,
``core/tii_engine.py``) keep working without change.
"""

from __future__ import annotations

from analysis.l8_tii import _compute_tii

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
    """Compute TII via canonical 5-component model (``analysis.l8_tii``).

    Parameters are mapped to the canonical interface:
        trq         → trq_energy  (field energy)
        intensity   → reflective_intensity  (L1 confidence proxy)
        integrity   → meta_integrity  (data-completeness)
        price, vwap → passed through
        atr         → validation guard only (not used in computation)
        bias_strength → passed through

    Returns the TII score (0.0–1.0) or ``None`` if inputs are invalid.
    """
    if vwap == 0 or atr <= 0 or price <= 0:
        return None
    result = _compute_tii(
        price=price,
        vwap=vwap,
        trq_energy=trq,
        bias_strength=bias_strength,
        reflective_intensity=max(0.0, min(1.0, intensity)),
        meta_integrity=max(0.0, min(1.0, integrity)),
    )
    return result["tii"]
