"""
Extreme Selectivity Gate v11 - 3-Layer Sniper Filter

Implements the Extreme Selectivity Gate v11 with 3 layers:

Layer 1 - VETO (9 binary conditions, any TRUE = BLOCK):
1. regime_label == "SHOCK"
2. regime_confidence < 0.65
3. regime_transition_risk > 0.40
4. vol_state not in allowed set
5. cluster_exposure >= 0.75
6. rolling_correlation_max >= 0.90
7. emotion_delta > 0.25
8. discipline_score < 0.90
9. eaf_score < 0.75

Layer 2 - SCORING (weighted composite):
score = 0.20×regime_conf + 0.15×liquidity + 0.15×exhaustion
      + 0.10×dvg + 0.15×mc_win + 0.15×posterior + 0.10×(1-cluster_exposure)

Layer 3 - EXECUTION (5 simultaneous thresholds):
- score >= 0.78 AND mc_win >= 0.70 AND posterior >= 0.72 AND mc_pf >= 1.8 AND vol_expansion >= 1.4

All thresholds configurable via constructor params (walk-forward ready).
Returns frozen ExtremeGateResult with verdict, score, veto_triggered, veto_reasons, confidence_band.

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

from engines.v11.config import get_v11


class GateVerdict(str, Enum):
    """Gate verdict enum."""
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class ConfidenceBand(str, Enum):
    """Confidence band enum."""
    ULTRA_HIGH = "ULTRA_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class ExtremeGateInput:
    """Input data for the Extreme Selectivity Gate."""

    # Regime data
    regime_label: str
    regime_confidence: float
    regime_transition_risk: float

    # Volatility state
    vol_state: str
    vol_expansion: float

    # Portfolio/Correlation risk
    cluster_exposure: float
    rolling_correlation_max: float

    # Emotion/Discipline
    emotion_delta: float
    discipline_score: float
    eaf_score: float

    # Quality scores
    liquidity_sweep_quality: float
    exhaustion_confidence: float
    divergence_confidence: float

    # Monte Carlo
    monte_carlo_win: float
    monte_carlo_pf: float

    # Bayesian posterior
    posterior: float


@dataclass(frozen=True)
class ExtremeGateResult:
    """Immutable result of extreme selectivity gate evaluation."""

    verdict: GateVerdict
    score: float
    veto_triggered: bool
    veto_reasons: tuple[str, ...]
    confidence_band: ConfidenceBand
    layer_breakdown: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON consumption."""
        return {
            "verdict": self.verdict.value,
            "score": self.score,
            "veto_triggered": self.veto_triggered,
            "veto_reasons": list(self.veto_reasons),
            "confidence_band": self.confidence_band.value,
            "layer_breakdown": self.layer_breakdown,
        }


class ExtremeSelectivityGateV11:
    """
    3-Layer extreme selectivity gate for sniper-grade trade filtering.

    Layer 1: VETO - Binary conditions that instantly block
    Layer 2: SCORING - Weighted composite quality score
    Layer 3: EXECUTION - Multiple simultaneous thresholds

    Parameters
    ----------
    All thresholds can be overridden via constructor for walk-forward optimization.
    Defaults are loaded from config/v11.yaml.
    """

    def __init__(
        self,
        # Veto thresholds
        regime_confidence_floor: float | None = None,
        regime_transition_risk_ceiling: float | None = None,
        discipline_min: float | None = None,
        eaf_min: float | None = None,
        cluster_exposure_max: float | None = None,
        correlation_max: float | None = None,
        emotion_delta_max: float | None = None,
        allowed_vol_states: list[str] | None = None,
        # Scoring weights
        scoring_weights: dict[str, float] | None = None,
        # Execution thresholds
        score_min: float | None = None,
        monte_carlo_win_min: float | None = None,
        posterior_min: float | None = None,
        mc_pf_min: float | None = None,
        vol_expansion_min: float | None = None,
    ) -> None:
        # Veto thresholds
        self._regime_conf_floor = regime_confidence_floor or get_v11(
            "veto.regime_confidence_floor", 0.65
        )
        self._regime_transition_ceiling = regime_transition_risk_ceiling or get_v11(
            "veto.regime_transition_risk_ceiling", 0.40
        )
        self._discipline_min = discipline_min or get_v11("veto.discipline_min", 0.90)
        self._eaf_min = eaf_min or get_v11("veto.eaf_min", 0.75)
        self._cluster_max = cluster_exposure_max or get_v11("veto.cluster_exposure_max", 0.75)
        self._corr_max = correlation_max or get_v11("veto.correlation_max", 0.90)
        self._emotion_max = emotion_delta_max or get_v11("veto.emotion_delta_max", 0.25)

        if allowed_vol_states is None:
            self._allowed_vol_states = set(get_v11(
                "veto.allowed_vol_states", ["NORMAL", "EXPANSION", "TRENDING"]
            ))
        else:
            self._allowed_vol_states = set(allowed_vol_states)

        # Scoring weights
        if scoring_weights is None:
            self._weights = {
                "regime_confidence": get_v11("scoring.regime_confidence", 0.20),
                "liquidity_sweep": get_v11("scoring.liquidity_sweep", 0.15),
                "exhaustion_confidence": get_v11("scoring.exhaustion_confidence", 0.15),
                "divergence_confidence": get_v11("scoring.divergence_confidence", 0.10),
                "monte_carlo_win": get_v11("scoring.monte_carlo_win", 0.15),
                "posterior": get_v11("scoring.posterior", 0.15),
                "cluster_exposure_inverse": get_v11("scoring.cluster_exposure_inverse", 0.10),
            }
        else:
            self._weights = scoring_weights

        # Execution thresholds
        self._score_min = score_min or get_v11("selectivity.score_min", 0.78)
        self._mc_win_min = monte_carlo_win_min or get_v11("selectivity.monte_carlo_win_min", 0.70)
        self._posterior_min = posterior_min or get_v11("selectivity.posterior_min", 0.72)
        self._mc_pf_min = mc_pf_min or get_v11("selectivity.mc_pf_min", 1.8)
        self._vol_exp_min = vol_expansion_min or get_v11("selectivity.vol_expansion_min", 1.4)

    def evaluate(self, gate_input: ExtremeGateInput) -> ExtremeGateResult:
        """
        Evaluate trade through 3-layer gate.

        Args:
            gate_input: All required metrics for gate evaluation

        Returns:
            ExtremeGateResult with verdict and detailed breakdown
        """
        # Layer 1: VETO
        veto_triggered, veto_reasons = self._layer1_veto(gate_input)

        if veto_triggered:
            return self._blocked_result(
                score=0.0,
                veto_reasons=veto_reasons,
                gate_input=gate_input,
            )

        # Layer 2: SCORING
        score = self._layer2_scoring(gate_input)

        # Layer 3: EXECUTION
        execution_pass = self._layer3_execution(gate_input, score)

        if execution_pass:
            verdict = GateVerdict.ALLOW
        else:
            verdict = GateVerdict.BLOCK

        # Compute confidence band
        confidence_band = self._compute_confidence_band(score, gate_input)

        # Build layer breakdown
        layer_breakdown = {
            "layer1_veto": {
                "triggered": False,
                "reasons": [],
            },
            "layer2_score": {
                "score": score,
                "components": self._score_components(gate_input),
            },
            "layer3_execution": {
                "passed": execution_pass,
                "thresholds": self._execution_thresholds(gate_input, score),
            },
        }

        return ExtremeGateResult(
            verdict=verdict,
            score=score,
            veto_triggered=False,
            veto_reasons=(),
            confidence_band=confidence_band,
            layer_breakdown=layer_breakdown,
        )

    def _layer1_veto(self, inp: ExtremeGateInput) -> tuple[bool, tuple[str, ...]]:
        """
        Layer 1: Binary veto conditions.

        Returns:
            (veto_triggered: bool, reasons: tuple[str, ...])
        """
        reasons = []

        # 1. Regime == SHOCK
        if inp.regime_label == "SHOCK":
            reasons.append("regime_shock")

        # 2. Regime confidence too low
        if inp.regime_confidence < self._regime_conf_floor:
            reasons.append(f"regime_confidence_low:{inp.regime_confidence:.3f}<{self._regime_conf_floor}")

        # 3. Regime transition risk too high
        if inp.regime_transition_risk > self._regime_transition_ceiling:
            reasons.append(f"regime_transition_high:{inp.regime_transition_risk:.3f}>{self._regime_transition_ceiling}")

        # 4. Vol state not allowed
        if inp.vol_state not in self._allowed_vol_states:
            reasons.append(f"vol_state_blocked:{inp.vol_state}")

        # 5. Cluster exposure too high
        if inp.cluster_exposure >= self._cluster_max:
            reasons.append(f"cluster_exposure_high:{inp.cluster_exposure:.3f}>={self._cluster_max}")

        # 6. Rolling correlation too high
        if inp.rolling_correlation_max >= self._corr_max:
            reasons.append(f"correlation_high:{inp.rolling_correlation_max:.3f}>={self._corr_max}")

        # 7. Emotion delta too high
        if inp.emotion_delta > self._emotion_max:
            reasons.append(f"emotion_delta_high:{inp.emotion_delta:.3f}>{self._emotion_max}")

        # 8. Discipline too low
        if inp.discipline_score < self._discipline_min:
            reasons.append(f"discipline_low:{inp.discipline_score:.3f}<{self._discipline_min}")

        # 9. EAF too low
        if inp.eaf_score < self._eaf_min:
            reasons.append(f"eaf_low:{inp.eaf_score:.3f}<{self._eaf_min}")

        return len(reasons) > 0, tuple(reasons)

    def _layer2_scoring(self, inp: ExtremeGateInput) -> float:
        """
        Layer 2: Weighted composite scoring.

        Returns:
            Composite score [0, 1]
        """
        score = 0.0

        score += self._weights["regime_confidence"] * inp.regime_confidence
        score += self._weights["liquidity_sweep"] * inp.liquidity_sweep_quality
        score += self._weights["exhaustion_confidence"] * inp.exhaustion_confidence
        score += self._weights["divergence_confidence"] * inp.divergence_confidence
        score += self._weights["monte_carlo_win"] * inp.monte_carlo_win
        score += self._weights["posterior"] * inp.posterior
        score += self._weights["cluster_exposure_inverse"] * (1.0 - inp.cluster_exposure)

        return float(np.clip(score, 0.0, 1.0))

    def _layer3_execution(self, inp: ExtremeGateInput, score: float) -> bool:
        """
        Layer 3: Multiple simultaneous execution thresholds.

        Returns:
            True if all thresholds passed
        """
        return (
            score >= self._score_min and
            inp.monte_carlo_win >= self._mc_win_min and
            inp.posterior >= self._posterior_min and
            inp.monte_carlo_pf >= self._mc_pf_min and
            inp.vol_expansion >= self._vol_exp_min
        )

    def _compute_confidence_band(self, score: float, inp: ExtremeGateInput) -> ConfidenceBand:
        """
        Compute confidence band based on score and key metrics.
        """
        if score >= 0.85 and inp.monte_carlo_win >= 0.75 and inp.posterior >= 0.80:
            return ConfidenceBand.ULTRA_HIGH
        elif score >= 0.80:
            return ConfidenceBand.HIGH
        elif score >= 0.70:
            return ConfidenceBand.MEDIUM
        else:
            return ConfidenceBand.LOW

    def _score_components(self, inp: ExtremeGateInput) -> dict[str, float]:
        """Return individual scoring components."""
        return {
            "regime_confidence": inp.regime_confidence * self._weights["regime_confidence"],
            "liquidity_sweep": inp.liquidity_sweep_quality * self._weights["liquidity_sweep"],
            "exhaustion_confidence": inp.exhaustion_confidence * self._weights["exhaustion_confidence"],
            "divergence_confidence": inp.divergence_confidence * self._weights["divergence_confidence"],
            "monte_carlo_win": inp.monte_carlo_win * self._weights["monte_carlo_win"],
            "posterior": inp.posterior * self._weights["posterior"],
            "cluster_exposure_inverse": (1.0 - inp.cluster_exposure) * self._weights["cluster_exposure_inverse"],
        }

    def _execution_thresholds(self, inp: ExtremeGateInput, score: float) -> dict[str, Any]:
        """Return execution threshold check results."""
        return {
            "score": {"value": score, "threshold": self._score_min, "passed": score >= self._score_min},
            "mc_win": {"value": inp.monte_carlo_win, "threshold": self._mc_win_min, "passed": inp.monte_carlo_win >= self._mc_win_min},
            "posterior": {"value": inp.posterior, "threshold": self._posterior_min, "passed": inp.posterior >= self._posterior_min},
            "mc_pf": {"value": inp.monte_carlo_pf, "threshold": self._mc_pf_min, "passed": inp.monte_carlo_pf >= self._mc_pf_min},
            "vol_expansion": {"value": inp.vol_expansion, "threshold": self._vol_exp_min, "passed": inp.vol_expansion >= self._vol_exp_min},
        }

    def _blocked_result(
        self, score: float, veto_reasons: tuple[str, ...], gate_input: ExtremeGateInput
    ) -> ExtremeGateResult:
        """Return result for blocked trade."""
        layer_breakdown = {
            "layer1_veto": {
                "triggered": True,
                "reasons": list(veto_reasons),
            },
            "layer2_score": {
                "score": score,
                "components": {},
            },
            "layer3_execution": {
                "passed": False,
                "thresholds": {},
            },
        }

        return ExtremeGateResult(
            verdict=GateVerdict.BLOCK,
            score=score,
            veto_triggered=True,
            veto_reasons=veto_reasons,
            confidence_band=ConfidenceBand.LOW,
            layer_breakdown=layer_breakdown,
        )
