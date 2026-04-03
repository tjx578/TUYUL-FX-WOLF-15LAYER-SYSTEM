"""Data contracts for legacy WOLF ARSENAL v4.0 FTA adapter.

These dataclasses carry normalized legacy scores through the pipeline.
All fields are clamped to their canonical ranges by the normalization layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LegacyCurrencyScore:
    """Single-currency fundamental score (0-50 scale)."""

    currency: str
    total_50: float
    cb_10: float
    econ_10: float
    commodity_10: float
    risk_10: float
    techpos_10: float


@dataclass
class LegacyPairFTAResult:
    """Pair-level FTA result with both claimed and calibrated scores.

    ``fundamental_score_claimed_100`` preserves the legacy document's stated
    value (provenance only — NOT for computation).
    ``fundamental_score_calibrated_100`` is the formula-derived value that
    downstream consumers should use.
    """

    pair: str
    base_score_50: float
    quote_score_50: float
    pair_gap_points: float
    pair_gap_norm: float
    technical_score_100: float
    fta_score_100: float
    fta_norm: float
    direction: str
    confidence_hint: float
    trade_band: str
    fundamental_score_claimed_100: float | None = None
    fundamental_score_calibrated_100: float = 0.0
