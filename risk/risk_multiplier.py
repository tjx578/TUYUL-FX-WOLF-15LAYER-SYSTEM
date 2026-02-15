"""Risk Multiplier — Aggregates risk scaling factors from multiple sources.

Combines macro, session, regime, and volatility-clustering multipliers
into a single composite risk multiplier for position sizing.

Authority: RISK ZONE. Computes scaling factors only.
           Does NOT decide market direction.
           Does NOT override Layer-12 verdict.
           Output feeds → DynamicPositionSizingEngine → L10 → L12.

Enhancement (Tier 2):
    ✅ Now accepts vol_clustering.risk_multiplier as input source
    ✅ Backward-compatible: all new parameters are optional with safe defaults
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DEFAULT_MACRO_MULT = 1.0
_DEFAULT_SESSION_MULT = 1.0
_DEFAULT_REGIME_MULT = 1.0
_DEFAULT_VOL_CLUSTER_MULT = 1.0  # No clustering = no adjustment
_DEFAULT_CORRELATION_MULT = 1.0


@dataclass(frozen=True)
class RiskMultiplierResult:
    """Immutable composite risk multiplier with per-source breakdown.

    All individual multipliers are ≥ 0.
    composite ≥ 0 (product of all sources, clamped to [floor, cap]).
    """

    macro_multiplier: float
    session_multiplier: float
    regime_multiplier: float
    vol_clustering_multiplier: float
    correlation_multiplier: float
    composite: float
    clamped: bool  # True if composite was clamped to floor or cap

    def to_dict(self) -> dict[str, Any]:
        return {
            "macro_multiplier": self.macro_multiplier,
            "session_multiplier": self.session_multiplier,
            "regime_multiplier": self.regime_multiplier,
            "vol_clustering_multiplier": self.vol_clustering_multiplier,
            "correlation_multiplier": self.correlation_multiplier,
            "composite": self.composite,
            "clamped": self.clamped,
        }


class RiskMultiplierAggregator:
    """Aggregates risk multipliers from multiple engine sources.

    The composite multiplier is the product of all individual sources,
    clamped to [floor, cap] to prevent extreme sizing.

    Parameters
    ----------
    floor : float
        Minimum composite multiplier. Default 0.1 (10% of base size).
        Prevents position from being reduced to near-zero by compounding
        multiple small multipliers.
    cap : float
        Maximum composite multiplier. Default 3.0 (300% of base size).
        Prevents position amplification beyond safe limits.
    """

    def __init__(
        self,
        floor: float = 0.1,
        cap: float = 3.0,
    ) -> None:
        if floor < 0:
            raise ValueError(f"floor must be ≥ 0, got {floor}")
        if cap < floor:
            raise ValueError(f"cap ({cap}) must be ≥ floor ({floor})")
        self._floor = floor
        self._cap = cap

    def compute(
        self,
        macro_multiplier: float = _DEFAULT_MACRO_MULT,
        session_multiplier: float = _DEFAULT_SESSION_MULT,
        regime_multiplier: float = _DEFAULT_REGIME_MULT,
        vol_clustering_multiplier: float = _DEFAULT_VOL_CLUSTER_MULT,
        correlation_multiplier: float = _DEFAULT_CORRELATION_MULT,
    ) -> RiskMultiplierResult:
        """Compute composite risk multiplier from all sources.

        Args:
            macro_multiplier: From macro_volatility_engine (VIX regime).
                > 1.0 = elevated macro risk → larger position reduction.
            session_multiplier: From session/time-of-day analysis.
                > 1.0 = unfavorable session → larger position reduction.
            regime_multiplier: From regime_classifier_ml or L1 regime.
                > 1.0 = uncertain regime → larger position reduction.
            vol_clustering_multiplier: From VolatilityClusteringModel.risk_multiplier.
                > 1.0 = volatility persistence detected → larger position reduction.
                Default 1.0 (no clustering = neutral).
            correlation_multiplier: From CorrelationRiskEngine.
                > 1.0 = correlated exposure → larger position reduction.

        Returns:
            RiskMultiplierResult with composite and per-source breakdown.

        Note:
            All multipliers represent RISK SCALING, not position scaling.
            - multiplier > 1.0 → higher risk → DynamicPSE divides by this
            - multiplier = 1.0 → neutral
            - multiplier < 1.0 → lower risk (rare; most sources only increase)
        """
        # Validate non-negative
        sources = {
            "macro_multiplier": macro_multiplier,
            "session_multiplier": session_multiplier,
            "regime_multiplier": regime_multiplier,
            "vol_clustering_multiplier": vol_clustering_multiplier,
            "correlation_multiplier": correlation_multiplier,
        }
        for name, value in sources.items():
            if value < 0:
                raise ValueError(f"{name} must be ≥ 0, got {value}")

        # Composite = product of all sources
        raw_composite = (
            macro_multiplier
            * session_multiplier
            * regime_multiplier
            * vol_clustering_multiplier
            * correlation_multiplier
        )

        # Clamp to [floor, cap]
        clamped = raw_composite < self._floor or raw_composite > self._cap
        composite = max(self._floor, min(raw_composite, self._cap))

        return RiskMultiplierResult(
            macro_multiplier=round(macro_multiplier, 4),
            session_multiplier=round(session_multiplier, 4),
            regime_multiplier=round(regime_multiplier, 4),
            vol_clustering_multiplier=round(vol_clustering_multiplier, 4),
            correlation_multiplier=round(correlation_multiplier, 4),
            composite=round(composite, 4),
            clamped=clamped,
        )
