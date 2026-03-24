"""
V11 Data Adapter - Pipeline Bridge (L1-L11 → Gate)

Reads existing pipeline synthesis dict and maps layer outputs to ExtremeGateInput.
Runs v11-only engines (ExhaustionDetector, ExhaustionDVGFusion, LiquiditySweepScorer)
using LiveContextBus candle data.

REUSES existing CorrelationRiskEngine (import, not duplicate).
Provides graceful fallback if any engine fails.

Authority: ANALYSIS-ONLY. No execution side-effects.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from context.live_context_bus import LiveContextBus
from engines.correlation_risk_engine import CorrelationRiskEngine
from engines.v11.exhaustion_detector import ExhaustionDetector
from engines.v11.exhaustion_dvg_fusion import ExhaustionDVGFusion
from engines.v11.extreme_selectivity_gate import ExtremeGateInput
from engines.v11.liquidity_sweep_scorer import LiquiditySweepScorer


class V11DataAdapter:
    """
    Data adapter for bridging pipeline synthesis to v11 gate.

    Responsibilities:
    1. Extract relevant metrics from pipeline synthesis
    2. Run v11-specific engines (exhaustion, dvg, sweep)
    3. Reuse existing engines (correlation risk)
    4. Assemble ExtremeGateInput for gate evaluation
    """

    def __init__(self) -> None:
        # Initialize v11 engines
        self._exhaustion_detector = ExhaustionDetector()
        self._dvg_fusion = ExhaustionDVGFusion()
        self._sweep_scorer = LiquiditySweepScorer()

        # Reuse existing correlation risk engine
        self._correlation_engine = CorrelationRiskEngine(
            max_corr_threshold=0.85,
            high_corr_flag=0.70,
        )

        # Context bus for candle data
        self._context_bus = LiveContextBus()

    def collect(
        self,
        synthesis: dict[str, Any],
        symbol: str,
        timeframe: str = "H1",
    ) -> ExtremeGateInput | None:
        """
        Collect and transform pipeline data into ExtremeGateInput.

        Args:
            synthesis: Pipeline synthesis dictionary (L1-L11 outputs)
            symbol: Trading symbol
            timeframe: Timeframe for candle data

        Returns:
            ExtremeGateInput if successful, None if critical data missing
        """
        try:
            # Get candle history from context bus
            candles = self._get_candle_history(symbol, timeframe)

            if not candles:
                logger.warning("V11DataAdapter: No candles available")
                return None

            # Extract regime data
            regime_data = self._extract_regime_data(synthesis)

            # Extract volatility data
            vol_data = self._extract_volatility_data(synthesis)

            # Extract emotion/discipline data
            emotion_data = self._extract_emotion_data(synthesis)

            # Extract quality scores
            quality_data = self._extract_quality_scores(synthesis)

            # Run v11-specific engines
            exhaustion_result = self._exhaustion_detector.detect(candles)

            # Get divergence data from L4 (FusionMomentumEngine)
            divergence_data = synthesis.get("l4", {}).get("divergence", {})
            dvg_result = self._dvg_fusion.evaluate(exhaustion_result, divergence_data)

            # Detect direction from L12 verdict
            direction = self._infer_direction(synthesis)
            sweep_result = self._sweep_scorer.score(candles, direction)

            # Compute correlation risk
            cluster_exposure, corr_max = self._compute_correlation_risk(synthesis, symbol)

            # Assemble ExtremeGateInput
            gate_input = ExtremeGateInput(
                # Regime
                regime_label=regime_data["label"],
                regime_confidence=regime_data["confidence"],
                regime_transition_risk=regime_data["transition_risk"],
                # Volatility
                vol_state=vol_data["state"],
                vol_expansion=vol_data["expansion"],
                # Portfolio/Correlation
                cluster_exposure=cluster_exposure,
                rolling_correlation_max=corr_max,
                # Emotion/Discipline
                emotion_delta=emotion_data["delta"],
                discipline_score=emotion_data["discipline"],
                eaf_score=emotion_data["eaf"],
                # Quality scores
                liquidity_sweep_quality=sweep_result.sweep_quality,
                exhaustion_confidence=dvg_result.exhaustion_confidence,
                divergence_confidence=dvg_result.divergence_confidence,
                # Monte Carlo
                monte_carlo_win=quality_data["mc_win"],
                monte_carlo_pf=quality_data["mc_pf"],
                # Bayesian
                posterior=quality_data["posterior"],
            )

            return gate_input

        except Exception as e:
            logger.error(f"V11DataAdapter: Failed to collect data: {e}")
            return None

    def _get_candle_history(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Get candle history from context bus."""
        try:
            history = self._context_bus.get_candle_history(symbol, timeframe)
            if not history:
                return []

            # Convert deque to list
            return list(history)
        except Exception as e:
            logger.warning(f"V11DataAdapter: Failed to get candles: {e}")
            return []

    def _extract_regime_data(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        """Extract regime classification data."""
        # Try to get from L3 (regime classifier)
        l3 = synthesis.get("l3", {})
        regime = l3.get("regime", {})

        return {
            "label": regime.get("state", "UNKNOWN"),
            "confidence": regime.get("confidence", 0.5),
            "transition_risk": regime.get("transition_risk", 0.0),
        }

    def _extract_volatility_data(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        """Extract volatility state data."""
        # Try to get from L3 or L2
        l3 = synthesis.get("l3", {})
        vol = l3.get("volatility", {})

        return {
            "state": vol.get("state", "NORMAL"),
            "expansion": vol.get("expansion_ratio", 1.0),
        }

    def _extract_emotion_data(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        """Extract emotion/discipline/EAF data."""
        # From L11 (wolf discipline + EAF)
        l11 = synthesis.get("l11", {})

        return {
            "delta": l11.get("emotion_delta", 0.0),
            "discipline": l11.get("discipline_score", 1.0),
            "eaf": l11.get("eaf_score", 1.0),
        }

    def _extract_quality_scores(self, synthesis: dict[str, Any]) -> dict[str, Any]:
        """Extract Monte Carlo and Bayesian scores."""
        # Monte Carlo from L7
        l7 = synthesis.get("l7", {})
        mc = l7.get("monte_carlo", {})

        # Bayesian from L7
        bayesian = l7.get("bayesian", {})

        # Check if win_probability is already in 0-1 range or percentage
        mc_win_raw = mc.get("win_probability", 50.0)
        # If value > 1.0, assume it's percentage and convert
        mc_win = mc_win_raw / 100.0 if mc_win_raw > 1.0 else mc_win_raw

        return {
            "mc_win": mc_win,
            "mc_pf": mc.get("profit_factor", 1.0),
            "posterior": bayesian.get("posterior", 0.5),
        }

    def _infer_direction(self, synthesis: dict[str, Any]) -> str:
        """Infer trade direction from L12 verdict."""
        l12 = synthesis.get("l12", {})
        direction = str(l12.get("direction") or "").upper()
        verdict = str(l12.get("verdict") or "").upper()

        if direction in ("BUY", "LONG") or "EXECUTE_BUY" in verdict or "EXECUTE_REDUCED_RISK_BUY" in verdict:
            return "bullish"
        if direction in ("SELL", "SHORT") or "EXECUTE_SELL" in verdict or "EXECUTE_REDUCED_RISK_SELL" in verdict:
            return "bearish"
        return "neutral"

    def _compute_correlation_risk(self, synthesis: dict[str, Any], symbol: str) -> tuple[float, float]:
        """
        Compute correlation risk metrics.

        Returns:
            (cluster_exposure, rolling_correlation_max)
        """
        try:
            # Try to get from L6 if already computed
            l6 = synthesis.get("l6", {})
            corr_risk = l6.get("correlation_risk", {})

            if corr_risk:
                return (
                    corr_risk.get("concentration_risk", 0.0),
                    corr_risk.get("max_correlation", 0.0),
                )

            # If not available, return safe defaults
            return 0.0, 0.0

        except Exception:
            return 0.0, 0.0
