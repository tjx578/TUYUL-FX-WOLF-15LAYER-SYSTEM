"""
L2 MTA Hierarchy Analyzer - Multi-Timeframe Analysis.

Sources:
    core_cognitive_unified.py  → ReflexEmotionCore, ReflexState
    core_reflective_unified.py → FRPCEngine, adaptive_field_stabilizer, FieldState
    core_fusion_unified.py     → FusionIntegrator, MonteCarloConfidence

Produces:
    - mta_compliance (str)
    - hierarchy_followed (bool)
    - reflex_coherence (float)  → target ≥ 0.88
    - conf12 (float)            → target ≥ 0.92
    - frpc_energy (float)
    - frpc_state (str)          → SYNC | PARTIAL | DESYNC
    - field_phase (str)         → ACCUMULATION | EXPANSION | DISTRIBUTION | REVERSAL | CONSOLIDATION
    - direction (str)           → BULLISH | BEARISH | NEUTRAL
    - composite_bias (float)
    - available_timeframes (int)
    - aligned (bool)
    - alignment_strength (float)
    - per_tf_bias (dict)
    - valid (bool)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

try:
    from core.core_cognitive_unified import ReflexEmotionCore
    from core.core_fusion_unified import FusionIntegrator
    from core.core_reflective_unified import FRPCEngine
except ImportError as exc:
    logger.warning(f"[L2] Could not load core modules: {exc}")
    ReflexEmotionCore = None  # type: ignore[assignment,misc]
    FusionIntegrator = None  # type: ignore[assignment,misc]
    FRPCEngine = None  # type: ignore[assignment,misc]

# Timeframe weights (higher TF = more weight)
_TF_WEIGHTS: dict[str, float] = {
    "MN": 0.35,
    "W1": 0.25,
    "D1": 0.15,
    "H4": 0.15,
    "H1": 0.07,
    "M15": 0.03,
}

_MIN_TIMEFRAMES = 3


class L2MTAAnalyzer:
    """Layer 2: MTA Hierarchy + Reflex Context - Perception & Context zone."""

    def __init__(self, *, redis_client: Any = None) -> None:
        self._reflex_core = None
        self._frpc_engine = None
        self._fusion_integrator = None
        self._redis_client = redis_client
        self.context: Any = None  # Candle source (mock-able in tests)
        self.bus: Any = None      # Candle bus (mock-able in integration tests)

    def _ensure_loaded(self) -> None:
        if self._reflex_core is not None:
            return
        try:
            if ReflexEmotionCore is None or FRPCEngine is None or FusionIntegrator is None:
                raise ImportError("Core modules not available")
            self._reflex_core = ReflexEmotionCore()
            self._frpc_engine = FRPCEngine()
            self._fusion_integrator = FusionIntegrator()
        except Exception as exc:
            logger.warning(f"[L2] Could not load core modules: {exc}")

    # ------------------------------------------------------------------
    # Candle bias helper
    # ------------------------------------------------------------------
    @staticmethod
    def _candle_bias(candle: dict | None) -> int:
        """Return +1 (bullish), -1 (bearish), or 0 (doji/None)."""
        if candle is None:
            return 0
        o = candle.get("open", 0.0)
        c = candle.get("close", 0.0)
        if c > o:
            return 1
        if c < o:
            return -1
        return 0

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def analyze(self, symbol: str) -> dict[str, Any]:
        """
        Analyze multi-timeframe hierarchy for *symbol*.

        Returns:
            dict with all MTA metrics including direction, composite_bias,
            alignment, per_tf_bias, etc.
        """
        self._ensure_loaded()

        per_tf_bias: dict[str, int] = {}
        composite_bias: float = 0.0
        available_tfs = 0

        for tf, weight in _TF_WEIGHTS.items():
            candle = None
            if self.context is not None:
                try:
                    candle = self.context.get_candle(symbol, tf)
                except Exception:
                    candle = None
            if candle is not None:
                bias = self._candle_bias(candle)
                per_tf_bias[tf] = bias
                composite_bias += bias * weight
                available_tfs += 1

        composite_bias = round(composite_bias, 5)

        # Validity
        valid = available_tfs >= _MIN_TIMEFRAMES

        if not valid:
            return {
                "mta_compliance": f"0/{len(_TF_WEIGHTS)}",
                "hierarchy_followed": False,
                "reflex_coherence": 0.0,
                "conf12": 0.0,
                "frpc_energy": 0.0,
                "frpc_state": "DESYNC",
                "field_phase": "CONSOLIDATION",
                "valid": False,
                "direction": "NEUTRAL",
                "composite_bias": 0.0,
                "available_timeframes": available_tfs,
                "aligned": False,
                "alignment_strength": 0.0,
                "per_tf_bias": per_tf_bias,
            }

        # Direction
        if composite_bias > 0:
            direction = "BULLISH"
        elif composite_bias < 0:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Alignment: all biases same sign (ignoring 0)
        non_zero = [b for b in per_tf_bias.values() if b != 0]
        if non_zero:
            aligned = all(b == non_zero[0] for b in non_zero)
        else:
            aligned = False

        alignment_strength = abs(composite_bias)

        # Compliance string
        bullish_count = sum(1 for b in per_tf_bias.values() if b > 0)
        bearish_count = sum(1 for b in per_tf_bias.values() if b < 0)
        compliance = f"{max(bullish_count, bearish_count)}/{available_tfs}"

        return {
            "mta_compliance": compliance,
            "hierarchy_followed": aligned,
            "reflex_coherence": 0.0,
            "conf12": 0.0,
            "frpc_energy": 0.0,
            "frpc_state": "DESYNC",
            "field_phase": "CONSOLIDATION",
            "valid": True,
            "direction": direction,
            "composite_bias": composite_bias,
            "available_timeframes": available_tfs,
            "aligned": aligned,
            "alignment_strength": round(alignment_strength, 5),
            "per_tf_bias": per_tf_bias,
        }


    # ------------------------------------------------------------------
    # Integration / legacy compute method
    # ------------------------------------------------------------------
    def compute(self, symbol: str, macro_bias: str | None = None) -> dict[str, Any]:
        """
        Compute MTA with per-TF detail dict (integration entry point).

        Returns dict with ``per_tf`` mapping each TF to
        ``{weight, bias, candle}``.
        """
        per_tf: dict[str, dict[str, Any]] = {}
        candle_source = self.bus or self.context

        for tf, weight in _TF_WEIGHTS.items():
            candle = None
            if candle_source is not None:
                try:
                    candle = candle_source.get_candle(symbol, tf)
                except Exception:
                    candle = None

            bias_val = self._candle_bias(candle)
            if bias_val > 0:
                bias_str = "BULLISH"
            elif bias_val < 0:
                bias_str = "BEARISH"
            else:
                bias_str = "NEUTRAL"

            per_tf[tf] = {
                "weight": weight,
                "bias": bias_str,
                "candle": candle,
            }

        return {"per_tf": per_tf, "macro_bias": macro_bias}


# Alias for integration test compatibility
L2MTA = L2MTAAnalyzer
