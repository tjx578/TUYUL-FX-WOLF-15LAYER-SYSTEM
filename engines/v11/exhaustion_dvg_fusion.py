"""
Exhaustion + Divergence Fusion Engine

Combines ExhaustionDetector output with multi-timeframe divergence detection.
Computes weighted confidence score:
- exhaustion_weight: 0.45
- divergence_weight: 0.55 (split across H1=0.25, H4=0.45, D1=0.30)

Uses existing FusionMomentumEngine divergence data from L4 output (does NOT recompute indicators).
Returns frozen ExhaustionDVGResult with to_dict().

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engines.v11.config import get_v11
from engines.v11.exhaustion_detector import ExhaustionResult


@dataclass(frozen=True)
class ExhaustionDVGResult:
    """Immutable result of exhaustion + divergence fusion."""
    
    exhaustion_confidence: float
    divergence_confidence: float
    composite_confidence: float
    exhaustion_state: str
    divergence_detected: bool
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON consumption."""
        return {
            "exhaustion_confidence": self.exhaustion_confidence,
            "divergence_confidence": self.divergence_confidence,
            "composite_confidence": self.composite_confidence,
            "exhaustion_state": self.exhaustion_state,
            "divergence_detected": self.divergence_detected,
        }


class ExhaustionDVGFusion:
    """
    Exhaustion + Divergence confidence fusion engine.
    
    Combines structural exhaustion signals with multi-timeframe divergence
    to produce a weighted composite confidence score.
    
    Parameters
    ----------
    exhaustion_weight : float
        Weight for exhaustion component (default from config)
    divergence_weight : float
        Weight for divergence component (default from config)
    divergence_tf_weights : dict
        Timeframe weights for divergence (H1, H4, D1)
    """
    
    def __init__(
        self,
        exhaustion_weight: float | None = None,
        divergence_weight: float | None = None,
        divergence_tf_weights: dict[str, float] | None = None,
    ) -> None:
        self._exhaustion_weight = exhaustion_weight or get_v11(
            "exhaustion_dvg_fusion.exhaustion_weight", 0.45
        )
        self._divergence_weight = divergence_weight or get_v11(
            "exhaustion_dvg_fusion.divergence_weight", 0.55
        )
        
        if divergence_tf_weights is None:
            self._tf_weights = get_v11(
                "exhaustion_dvg_fusion.divergence_tf_weights",
                {"H1": 0.25, "H4": 0.45, "D1": 0.30}
            )
        else:
            self._tf_weights = divergence_tf_weights
    
    def evaluate(
        self,
        exhaustion_result: ExhaustionResult,
        divergence_data: dict[str, Any],
    ) -> ExhaustionDVGResult:
        """
        Compute exhaustion + divergence fusion confidence.
        
        Args:
            exhaustion_result: Result from ExhaustionDetector
            divergence_data: Divergence data from L4 FusionMomentumEngine output.
                Expected structure:
                {
                    "divergence_detected": bool,
                    "divergence_confidence": float,
                    "timeframe_signals": {
                        "H1": {"detected": bool, "confidence": float},
                        "H4": {"detected": bool, "confidence": float},
                        "D1": {"detected": bool, "confidence": float},
                    }
                }
        
        Returns:
            ExhaustionDVGResult with composite confidence
        """
        # Extract exhaustion confidence
        exhaustion_conf = exhaustion_result.confidence
        
        # Compute divergence confidence from timeframe signals
        divergence_conf = self._compute_divergence_confidence(divergence_data)
        
        # Check if divergence detected
        divergence_detected = divergence_data.get("divergence_detected", False)
        
        # Weighted composite
        composite = (
            self._exhaustion_weight * exhaustion_conf +
            self._divergence_weight * divergence_conf
        )
        
        return ExhaustionDVGResult(
            exhaustion_confidence=exhaustion_conf,
            divergence_confidence=divergence_conf,
            composite_confidence=composite,
            exhaustion_state=exhaustion_result.state.value,
            divergence_detected=divergence_detected,
        )
    
    def _compute_divergence_confidence(self, divergence_data: dict[str, Any]) -> float:
        """
        Compute weighted divergence confidence from multi-timeframe signals.
        
        Weighted average of H1, H4, D1 confidences using configured weights.
        Falls back to overall divergence_confidence if timeframe data unavailable.
        """
        # Try to get timeframe-specific signals
        tf_signals = divergence_data.get("timeframe_signals", {})
        
        if not tf_signals:
            # Fallback to overall confidence if no timeframe breakdown
            return float(divergence_data.get("divergence_confidence", 0.0))
        
        # Weighted sum across timeframes
        weighted_conf = 0.0
        total_weight = 0.0
        
        for tf, weight in self._tf_weights.items():
            signal = tf_signals.get(tf, {})
            conf = signal.get("confidence", 0.0)
            weighted_conf += weight * conf
            total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        return weighted_conf / total_weight
