"""Quantum Advisory Engine -- Layer-11 trade advisory synthesis.

Synthesizes outputs from all preceding engines into a final advisory
recommendation for the Layer-12 constitution. Acts as the last analysis
step before the gatekeeper verdict.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

# Backward-compat enum (tests/older callers may use AdvisorySignal)
class AdvisorySignal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"
    ABORT = "ABORT"


@dataclass
class AdvisoryResult:
    """Output of the Quantum Advisory Engine."""

    # Advisory recommendation
    advisory_action: str = "HOLD"  # "EXECUTE" | "HOLD" | "NO_TRADE" | "ABORT"
    direction: str = "NONE"        # "BUY" | "SELL" | "NONE"

    # Composite scores
    wolf_score: float = 0.0  # 0.0-100.0 Wolf composite score
    tii_score: float = 0.0   # Trade Idea Index (0-100)
    frpc_score: float = 0.0  # Full Risk-Performance Composite (0-100)

    # Component contributions
    structure_weight: float = 0.0
    momentum_weight: float = 0.0
    precision_weight: float = 0.0
    field_weight: float = 0.0
    coherence_weight: float = 0.0
    context_weight: float = 0.0
    risk_sim_weight: float = 0.0

    # Trade parameters (advisory, not binding)
    suggested_entry: float = 0.0
    suggested_sl: float = 0.0
    suggested_tp1: float = 0.0
    suggested_rr: float = 0.0

    # Reasoning
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class QuantumAdvisoryEngine:
    """Quantum Advisory Engine -- final analysis synthesis.

    Parameters
    ----------
    min_wolf_score : float
        Minimum Wolf score to recommend EXECUTE.
    min_tii : float
        Minimum TII to recommend EXECUTE.
    weights : dict
        Component weights for Wolf score calculation.
    """

    DEFAULT_WEIGHTS = {
        "structure": 0.20,
        "momentum": 0.15,
        "precision": 0.15,
        "field": 0.15,
        "coherence": 0.15,
        "context": 0.10,
        "risk_simulation": 0.10,
    }

    def __init__(
        self,
        min_wolf_score: float = 65.0,
        min_tii: float = 60.0,
        weights: dict[str, float] | None = None,
        **_extra: Any,
    ) -> None:
        self.min_wolf_score = min_wolf_score
        self.min_tii = min_tii
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()

    def analyze(
        self,
        engine_outputs: dict[str, Any],
        symbol: str = "",
    ) -> AdvisoryResult:
        """Synthesize advisory from all engine outputs.

        Parameters
        ----------
        engine_outputs : dict
            Keys: "structure", "momentum", "precision", "field",
            "coherence", "context", "risk_simulation", "probability".
        """
        if not engine_outputs:
            return AdvisoryResult(metadata={"symbol": symbol, "error": "no_inputs"})

        scores: dict[str, float] = {}
        reasons: list[str] = []
        warnings: list[str] = []

        # Extract scores
        for name in self.weights:
            output = engine_outputs.get(name)
            if output is None:
                scores[name] = 0.0
                warnings.append(f"{name} engine missing")
                continue
            score = self._extract_score(name, output)
            scores[name] = score

        # Wolf score (weighted composite * 100)
        wolf_score = sum(scores.get(n, 0.0) * w for n, w in self.weights.items()) * 100
        wolf_score = max(0.0, min(100.0, wolf_score))

        # Direction consensus
        direction = self._determine_direction(engine_outputs)

        # TII (Trade Idea Index)
        tii = self._compute_tii(engine_outputs, wolf_score)

        # FRPC
        frpc = self._compute_frpc(engine_outputs, wolf_score, tii)

        # Trade parameters from precision engine
        precision = engine_outputs.get("precision")
        entry = getattr(precision, "entry_optimal", 0.0) if precision else 0.0
        sl = getattr(precision, "stop_loss", 0.0) if precision else 0.0
        tp1 = getattr(precision, "tp1", 0.0) if precision else 0.0
        rr = getattr(precision, "risk_reward_1", 0.0) if precision else 0.0

        # Advisory decision
        advisory_action = self._decide_action(wolf_score, tii, direction, engine_outputs, reasons, warnings)

        confidence = min(1.0, len([s for s in scores.values() if s > 0]) / len(self.weights) * 0.6 + wolf_score / 100 * 0.4)

        return AdvisoryResult(
            advisory_action=advisory_action,
            direction=direction,
            wolf_score=round(wolf_score, 2),
            tii_score=round(tii, 2),
            frpc_score=round(frpc, 2),
            structure_weight=round(scores.get("structure", 0.0), 3),
            momentum_weight=round(scores.get("momentum", 0.0), 3),
            precision_weight=round(scores.get("precision", 0.0), 3),
            field_weight=round(scores.get("field", 0.0), 3),
            coherence_weight=round(scores.get("coherence", 0.0), 3),
            context_weight=round(scores.get("context", 0.0), 3),
            risk_sim_weight=round(scores.get("risk_simulation", 0.0), 3),
            suggested_entry=entry,
            suggested_sl=sl,
            suggested_tp1=tp1,
            suggested_rr=rr,
            reasons=reasons,
            warnings=warnings,
            confidence=round(confidence, 3),
            metadata={"symbol": symbol, "component_scores": scores},
        )

    @staticmethod
    def _extract_score(name: str, output: Any) -> float:
        """Extract a 0.0-1.0 score from an engine output."""
        attr_map = {
            "structure": "structure_score",
            "momentum": "momentum_score",
            "precision": "precision_score",
            "field": "energy_score",
            "coherence": "coherence_score",
            "context": "context_score",
            "risk_simulation": "risk_score",
            "probability": "confidence",
        }
        attr = attr_map.get(name, "confidence")
        val = getattr(output, attr, None)
        if val is None:
            val = getattr(output, "confidence", 0.0)
        return max(0.0, min(1.0, float(val)))

    @staticmethod
    def _determine_direction(engine_outputs: dict[str, Any]) -> str:
        """Determine consensus direction."""
        bullish = 0
        bearish = 0

        for output in engine_outputs.values():
            if output is None:
                continue
            for attr in ("direction", "field_polarity", "structure_bias", "momentum_bias"):
                val = getattr(output, attr, None)
                if val in ("BULLISH", "BUY"):
                    bullish += 1
                elif val in ("BEARISH", "SELL"):
                    bearish += 1

        if bullish > bearish and bullish >= 2:
            return "BUY"
        if bearish > bullish and bearish >= 2:
            return "SELL"
        return "NONE"

    @staticmethod
    def _compute_tii(engine_outputs: dict[str, Any], wolf_score: float) -> float:
        """Trade Idea Index: quality of the trade idea."""
        coherence = engine_outputs.get("coherence")
        coherence_val = getattr(coherence, "coherence_score", 0.5) if coherence else 0.5

        context = engine_outputs.get("context")
        context_val = getattr(context, "context_score", 0.5) if context else 0.5

        precision = engine_outputs.get("precision")
        rr = getattr(precision, "risk_reward_1", 1.0) if precision else 1.0

        tii = wolf_score * 0.4 + coherence_val * 100 * 0.25 + context_val * 100 * 0.15 + min(rr / 3.0, 1.0) * 100 * 0.2
        return max(0.0, min(100.0, tii))

    @staticmethod
    def _compute_frpc(engine_outputs: dict[str, Any], wolf_score: float, tii: float) -> float:
        """Full Risk-Performance Composite."""
        risk_sim = engine_outputs.get("risk_simulation")
        win_prob = getattr(risk_sim, "win_probability", 0.5) if risk_sim else 0.5
        risk_score = getattr(risk_sim, "risk_score", 0.5) if risk_sim else 0.5

        frpc = wolf_score * 0.3 + tii * 0.3 + win_prob * 100 * 0.2 + risk_score * 100 * 0.2
        return max(0.0, min(100.0, frpc))

    def _decide_action(
        self,
        wolf_score: float,
        tii: float,
        direction: str,
        engine_outputs: dict[str, Any],
        reasons: list[str],
        warnings: list[str],
    ) -> str:
        """Determine advisory action."""
        # Coherence gate
        coherence = engine_outputs.get("coherence")
        coherence_verdict = getattr(coherence, "coherence_verdict", "HOLD") if coherence else "HOLD"

        if coherence_verdict == "ABORT":
            reasons.append("Coherence engine recommends ABORT")
            return "ABORT"

        # Context gate
        context = engine_outputs.get("context")
        context_verdict = getattr(context, "context_verdict", "NEUTRAL") if context else "NEUTRAL"

        if context_verdict == "AVOID":
            reasons.append("Context engine recommends AVOID")
            return "NO_TRADE"

        # No direction
        if direction == "NONE":
            reasons.append("No directional consensus")
            return "NO_TRADE"

        # Score gates
        if wolf_score >= self.min_wolf_score and tii >= self.min_tii:
            reasons.append(f"Wolf={wolf_score:.1f} TII={tii:.1f} above thresholds")
            return "EXECUTE"

        if wolf_score >= self.min_wolf_score * 0.85:
            reasons.append(f"Wolf={wolf_score:.1f} near threshold, HOLD for confirmation")
            warnings.append("Marginal setup -- close to threshold")
            return "HOLD"

        reasons.append(f"Wolf={wolf_score:.1f} TII={tii:.1f} below thresholds")
        return "NO_TRADE"
