"""
VIX Analysis Engine - FINAL PRODUCTION

Analyzes VIX levels for regime classification.
Outputs: regime (0/1/2), fear/greed score, term structure.

Integrated into MacroVolatilityEngine for Wolf-15.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class VIXState:
    """Immutable VIX analysis output."""

    vix_level: float
    vix_regime: str
    term_structure: str
    fear_greed_score: float
    regime_score: float


class VIXAnalysisEngine:
    """
    Regime-aware VIX analyzer.

    Thresholds:
      VIX < 14: LOW (Tranquil)
      14-20: ELEVATED (Stressed)
      20+: HIGH (Crisis)
    """

    def __init__(self, history_length: int = 60):
        self._vix_history: list[float] = []
        self._max_history = history_length

    def analyze(self, vix_level: float) -> VIXState:
        """Comprehensive VIX analysis."""

        # Input validation
        vix_level = max(0, min(vix_level, 100))
        self._vix_history.append(vix_level)
        if len(self._vix_history) > self._max_history:
            self._vix_history.pop(0)

        # Regime classification
        vix_regime = self._classify_regime(vix_level)

        # Fear/Greed score
        fear_greed = self._fear_greed(vix_level)

        # Regime score (0-1 for hybrid RSD)
        regime_score = self._regime_score(vix_level)

        # Term structure
        term_structure = self._term_structure()

        return VIXState(
            vix_level=round(vix_level, 2),
            vix_regime=vix_regime,
            term_structure=term_structure,
            fear_greed_score=round(fear_greed, 3),
            regime_score=round(regime_score, 3),
        )

    def _classify_regime(self, vix: float) -> str:
        if vix < 14:
            return "LOW"
        if vix < 20:
            return "ELEVATED"
        return "HIGH"

    @staticmethod
    def _fear_greed(vix: float) -> float:
        """Fear/Greed 0-1 scale."""
        if vix <= 10:
            return 0.0
        if vix >= 50:
            return 1.0
        return (vix - 10) / 40

    @staticmethod
    def _regime_score(vix: float) -> float:
        """Normalized regime danger (0-1)."""
        if vix <= 12:
            return 0.1
        if vix >= 40:
            return 1.0
        return (vix - 12) / 28

    def _term_structure(self) -> str:
        """Estimate term structure from history."""
        if len(self._vix_history) < 3:
            return "UNKNOWN"

        recent = np.mean(self._vix_history[-5:])
        older = np.mean(self._vix_history[-10:-5])

        if abs(recent - older) < 1:
            return "FLAT"
        if recent < older:
            return "CONTANGO"
        return "BACKWARDATION"
