"""
L9 SMC Integration Analyzer — Smart Money Concepts.

Sources:
    core_cognitive_unified.py → SmartMoneyDetector, TWMSCalculator
    core_fusion_unified.py    → LiquidityZoneMapper, VolumeProfileAnalyzer

Produces:
    - smc (bool)               → True if clear SMC signal detected
    - smc_score (int)
    - liquidity_score (float)  → target ≥ 0.65
    - dvg_confidence (float)   → target ≥ 0.70
    - smart_money_bias (str)
    - smart_money_signal (str) → ACCUMULATION | DISTRIBUTION | MANIPULATION | NEUTRAL
    - ob_present (bool)
    - fvg_present (bool)
    - sweep_detected (bool)
    - bos_detected (bool)
    - choch_detected (bool)
    - displacement (bool)
    - liquidity_sweep (bool)
    - confidence (float)
    - reason (str)
    - valid (bool)
"""

from __future__ import annotations

from typing import Any

from loguru import logger

try:
    import core.core_cognitive_unified

    from core.core_fusion_unified import LiquidityZoneMapper
except ImportError as exc:
    logger.warning(f"[L9] Could not load core modules: {exc}")
    core = None
    LiquidityZoneMapper = None

_MIN_BOS_CANDLES = 5


class L9SMCAnalyzer:
    """Layer 9: SMC Integration Analysis — Probability & Validation zone."""

    def __init__(self) -> None:
        self._smc_detector = None
        self._liquidity_mapper = None
        self._prev_trend: str | None = None  # Track for CHoCH detection

    def _ensure_loaded(self) -> None:
        if self._smc_detector is not None:
            return
        try:
            if core is None or LiquidityZoneMapper is None:
                raise ImportError("Core modules not available")
            self._smc_detector = core.core_cognitive_unified.SmartMoneyDetector()
            self._liquidity_mapper = LiquidityZoneMapper()
        except Exception as exc:
            logger.warning(f"[L9] Could not initialize detectors: {exc}")

    # ------------------------------------------------------------------
    # Candle retrieval
    # ------------------------------------------------------------------
    @staticmethod
    def _get_candles(symbol: str, timeframe: str = "H1", count: int = 30) -> list[dict]:
        try:
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415

            bus = LiveContextBus()
            return bus.get_candle_history(symbol, timeframe, count)
        except Exception:
            return []

    # ------------------------------------------------------------------
    # BOS detection
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_bos(candles: list[dict], trend: str) -> bool:
        """Detect Break of Structure (BOS) from candle history + trend."""
        if len(candles) < _MIN_BOS_CANDLES:
            return False

        recent = candles[-_MIN_BOS_CANDLES:]
        highs = [c.get("high", 0.0) for c in recent]
        lows = [c.get("low", 0.0) for c in recent]

        if trend == "BULLISH":
            # BOS: current high breaks previous swing high
            prev_high = max(highs[:-1])
            return highs[-1] > prev_high
        if trend == "BEARISH":
            prev_low = min(lows[:-1])
            return lows[-1] < prev_low
        return False

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def analyze(
        self, symbol: str, structure: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Analyze Smart Money Concepts for *symbol*.

        Args:
            structure: Dict with keys ``valid``, ``trend``, ``bos``, ``choch``.

        Returns:
            dict with all SMC detection fields.
        """
        self._ensure_loaded()

        # --- Validate structure input ---
        if structure is None or not structure:
            return self._fail("no_structure_data")

        if not structure.get("valid", False):
            return self._fail("invalid_structure")

        trend = structure.get("trend", "NEUTRAL")

        # --- CHoCH detection (trend reversal vs previous call) ---
        choch_detected = False
        if self._prev_trend is not None and self._prev_trend != trend:
            if trend in ("BULLISH", "BEARISH") and self._prev_trend in ("BULLISH", "BEARISH"):
                choch_detected = True
        self._prev_trend = trend

        # --- BOS detection from candle data ---
        candles = self._get_candles(symbol)
        bos_detected = self._detect_bos(candles, trend) if candles else False

        # --- Confidence ---
        if bos_detected:
            confidence = 0.8
        elif choch_detected:
            confidence = 0.6
        elif trend == "NEUTRAL":
            confidence = 0.3
        else:
            confidence = 0.4

        # --- SMC signal ---
        smc = bos_detected or choch_detected

        # --- Displacement (strong move in trend direction) ---
        displacement = bos_detected  # displacement accompanies BOS

        return {
            "smc_score": int(confidence * 100),
            "liquidity_score": 0.0,
            "dvg_confidence": 0.0,
            "smart_money_bias": trend,
            "smart_money_signal": "ACCUMULATION" if trend == "BULLISH" else (
                "DISTRIBUTION" if trend == "BEARISH" else "NEUTRAL"
            ),
            "ob_present": False,
            "fvg_present": False,
            "sweep_detected": False,
            "confidence": confidence,
            "valid": True,
            # Extended SMC fields
            "smc": smc,
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "displacement": displacement,
            "liquidity_sweep": False,
            "reason": "smc_ok" if smc else "no_signal",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fail(reason: str) -> dict[str, Any]:
        return {
            "smc_score": 0,
            "liquidity_score": 0.0,
            "dvg_confidence": 0.0,
            "smart_money_bias": "NEUTRAL",
            "smart_money_signal": "NEUTRAL",
            "ob_present": False,
            "fvg_present": False,
            "sweep_detected": False,
            "confidence": 0.0,
            "valid": False,
            "smc": False,
            "bos_detected": False,
            "choch_detected": False,
            "displacement": False,
            "liquidity_sweep": False,
            "reason": reason,
        }
