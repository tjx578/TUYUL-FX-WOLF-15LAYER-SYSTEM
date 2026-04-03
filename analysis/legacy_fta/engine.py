"""Legacy FTA computation engine — WOLF ARSENAL v4.0.

Computes pair-level FTA from legacy currency scores and technical inputs.
Always stores **both** ``claimed`` and ``calibrated`` fundamental scores.

Authority: **advisory only** — this engine produces hints, not verdicts.
"""

from __future__ import annotations

import logging
from typing import Any

from analysis.legacy_fta.contracts import LegacyCurrencyScore, LegacyPairFTAResult
from analysis.legacy_fta.normalization import clamp01, gap_points_to_norm

logger = logging.getLogger(__name__)

# Trade-band thresholds (on fta_norm 0-1 scale)
_BAND_HIGH = 0.80
_BAND_MODERATE = 0.60
_BAND_LOW = 0.40


def _classify_trade_band(fta_norm: float) -> str:
    if fta_norm >= _BAND_HIGH:
        return "HIGH"
    if fta_norm >= _BAND_MODERATE:
        return "MODERATE"
    if fta_norm >= _BAND_LOW:
        return "LOW"
    return "NONE"


def compute_pair_fta(
    pair: str,
    base: LegacyCurrencyScore,
    quote: LegacyCurrencyScore,
    technical_score_100: float,
    fta_score_100: float,
    fundamental_score_claimed_100: float | None = None,
    max_gap: float = 30.0,
) -> LegacyPairFTAResult:
    """Compute a fully normalized legacy pair FTA result.

    Parameters
    ----------
    pair : str
        Symbol name, e.g. ``"AUDCAD"``.
    base, quote : LegacyCurrencyScore
        Legacy 0-50 currency scores.
    technical_score_100 : float
        Legacy technical confluence score (0-100).
    fta_score_100 : float
        Legacy FTA composite score (0-100).
    fundamental_score_claimed_100 : float | None
        The score stated in the legacy document (provenance only).
    max_gap : float
        Denominator for gap normalization.  Default 30.

    Returns
    -------
    LegacyPairFTAResult
        Fully normalized result with ``confidence_hint`` ready for blending.
    """
    pair_gap_points = base.total_50 - quote.total_50
    pair_gap_norm = gap_points_to_norm(pair_gap_points, max_gap)

    clamp01(technical_score_100 / 100.0)
    fta_norm = clamp01(fta_score_100 / 100.0)

    # Confidence hint: 70% FTA quality + 30% directional gap strength
    confidence_hint = clamp01(0.70 * fta_norm + 0.30 * pair_gap_norm)

    direction = "BUY" if pair_gap_points > 0 else ("SELL" if pair_gap_points < 0 else "HOLD")

    trade_band = _classify_trade_band(fta_norm)

    # Calibrated fundamental = gap_norm * 100 (formula-consistent)
    fundamental_score_calibrated_100 = round(pair_gap_norm * 100.0, 2)

    return LegacyPairFTAResult(
        pair=pair,
        base_score_50=base.total_50,
        quote_score_50=quote.total_50,
        pair_gap_points=pair_gap_points,
        pair_gap_norm=round(pair_gap_norm, 4),
        technical_score_100=technical_score_100,
        fta_score_100=fta_score_100,
        fta_norm=round(fta_norm, 4),
        direction=direction,
        confidence_hint=round(confidence_hint, 4),
        trade_band=trade_band,
        fundamental_score_claimed_100=fundamental_score_claimed_100,
        fundamental_score_calibrated_100=fundamental_score_calibrated_100,
    )


def compute_pair_fta_from_dict(data: dict[str, Any]) -> LegacyPairFTAResult:
    """Convenience: build a ``LegacyPairFTAResult`` from a flat dict.

    Expected keys: ``pair``, ``base_total_50``, ``quote_total_50``,
    ``base_currency``, ``quote_currency``, ``technical_score_100``,
    ``fta_score_100``, plus optional sub-scores and ``claimed_100``.
    """
    base = LegacyCurrencyScore(
        currency=str(data.get("base_currency", "BASE")),
        total_50=float(data.get("base_total_50", 0.0)),
        cb_10=float(data.get("base_cb_10", 0.0)),
        econ_10=float(data.get("base_econ_10", 0.0)),
        commodity_10=float(data.get("base_commodity_10", 0.0)),
        risk_10=float(data.get("base_risk_10", 0.0)),
        techpos_10=float(data.get("base_techpos_10", 0.0)),
    )
    quote = LegacyCurrencyScore(
        currency=str(data.get("quote_currency", "QUOTE")),
        total_50=float(data.get("quote_total_50", 0.0)),
        cb_10=float(data.get("quote_cb_10", 0.0)),
        econ_10=float(data.get("quote_econ_10", 0.0)),
        commodity_10=float(data.get("quote_commodity_10", 0.0)),
        risk_10=float(data.get("quote_risk_10", 0.0)),
        techpos_10=float(data.get("quote_techpos_10", 0.0)),
    )
    return compute_pair_fta(
        pair=str(data.get("pair", "UNKNOWN")),
        base=base,
        quote=quote,
        technical_score_100=float(data.get("technical_score_100", 0.0)),
        fta_score_100=float(data.get("fta_score_100", 0.0)),
        fundamental_score_claimed_100=data.get("claimed_100"),
        max_gap=float(data.get("max_gap", 30.0)),
    )
