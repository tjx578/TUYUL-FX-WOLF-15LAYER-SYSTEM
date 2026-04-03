"""Legacy FTA Enricher — pipeline adapter for WOLF ARSENAL v4.0 scores.

Runs **before L10** in the pipeline (not inside Phase 2.5 enrichment).
Produces an advisory dict that the pipeline uses for confidence blending.

Authority: **advisory only** — never overrides L12 verdict.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from analysis.legacy_fta.contracts import LegacyCurrencyScore, LegacyPairFTAResult
from analysis.legacy_fta.engine import compute_pair_fta
from analysis.legacy_fta.normalization import clamp01

logger = logging.getLogger(__name__)

# Default neutral output when legacy data is unavailable
_NEUTRAL: dict[str, Any] = {
    "base_score_50": 0.0,
    "quote_score_50": 0.0,
    "pair_gap_points": 0.0,
    "pair_gap_norm": 0.0,
    "technical_score_100": 0.0,
    "fta_score_100": 0.0,
    "fta_norm": 0.0,
    "confidence_hint": 0.0,
    "trade_band": "NONE",
    "direction": "HOLD",
    "fundamental_score_claimed_100": None,
    "fundamental_score_calibrated_100": 0.0,
    "legacy_fta_present": False,
}


class LegacyFTAEnricher:
    """Pipeline adapter that converts cached legacy scores into advisory hints.

    The enricher holds per-symbol legacy currency data that can be fed
    externally (e.g. from a JSON file, dashboard push, or manual input).
    When data is available for both base and quote currencies, it computes
    and returns a hint dict. Otherwise it returns the neutral default.
    """

    def __init__(self) -> None:
        # symbol/currency -> LegacyCurrencyScore
        self._scores: dict[str, LegacyCurrencyScore] = {}

    # ── Data loading ──────────────────────────────────────────────

    def set_currency_score(self, score: LegacyCurrencyScore) -> None:
        """Register or update a legacy currency score."""
        self._scores[score.currency.upper()] = score

    def set_currency_scores(self, scores: list[LegacyCurrencyScore]) -> None:
        """Batch-register legacy currency scores."""
        for s in scores:
            self._scores[s.currency.upper()] = s

    def clear(self) -> None:
        """Remove all cached legacy scores."""
        self._scores.clear()

    # ── Main entry point ─────────────────────────────────────────

    def run(
        self,
        symbol: str,
        *,
        technical_score_100: float = 0.0,
        fta_score_100: float = 0.0,
        fundamental_score_claimed_100: float | None = None,
    ) -> dict[str, Any]:
        """Compute legacy FTA advisory hint for *symbol*.

        Parameters
        ----------
        symbol : str
            Forex pair, e.g. ``"AUDCAD"``.
        technical_score_100 : float
            Legacy technical confluence (0-100). Pass 0 if unavailable.
        fta_score_100 : float
            Legacy FTA composite (0-100). Pass 0 if unavailable.
        fundamental_score_claimed_100 : float | None
            The raw "claimed" score from legacy docs (provenance only).

        Returns
        -------
        dict
            Advisory hint dict. Always safe to inject into pipeline; returns
            neutral values when legacy data is missing.
        """
        sym = symbol.upper().replace("/", "").replace("_", "")
        base_ccy, quote_ccy = self._split_pair(sym)

        base = self._scores.get(base_ccy)
        quote = self._scores.get(quote_ccy)

        if base is None or quote is None:
            logger.debug(
                "[LegacyFTA] No legacy data for %s (base=%s quote=%s) → neutral",
                sym,
                base_ccy,
                quote_ccy,
            )
            return dict(_NEUTRAL)

        try:
            result: LegacyPairFTAResult = compute_pair_fta(
                pair=sym,
                base=base,
                quote=quote,
                technical_score_100=technical_score_100,
                fta_score_100=fta_score_100,
                fundamental_score_claimed_100=fundamental_score_claimed_100,
            )
            out = asdict(result)
            out["legacy_fta_present"] = True
            return out
        except Exception:
            logger.warning("[LegacyFTA] Computation failed for %s → neutral", sym, exc_info=True)
            return dict(_NEUTRAL)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _split_pair(sym: str) -> tuple[str, str]:
        """Split a 6-char forex pair into base/quote currency codes."""
        if len(sym) >= 6:
            return sym[:3], sym[3:6]
        return sym, ""


def blend_confidence(
    repo_confidence: float,
    legacy_confidence_hint: float,
    weight_repo: float = 0.85,
    weight_legacy: float = 0.15,
) -> float:
    """Blend repo SMC confidence with legacy FTA hint.

    Returns a clamped [0, 1] value. The default 85/15 split ensures legacy
    data can nudge borderline setups without dominating.
    """
    return clamp01(weight_repo * repo_confidence + weight_legacy * legacy_confidence_hint)
