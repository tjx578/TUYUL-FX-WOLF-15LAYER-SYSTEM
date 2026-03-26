"""
L9 SMC Integration Analyzer - Smart Money Concepts.

Sources:
    core_cognitive_unified.py -> SmartMoneyDetector, TWMSCalculator
    core_fusion_unified.py    -> LiquidityZoneMapper, VolumeProfileAnalyzer

Produces:
    - smc (bool)               -> True if clear SMC signal detected
    - smc_score (int)
    - liquidity_score (float)  -> target ≥ 0.65
    - dvg_confidence (float)   -> target ≥ 0.70
    - smart_money_bias (str)
    - smart_money_signal (str) -> ACCUMULATION | DISTRIBUTION | MANIPULATION | NEUTRAL
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
"""  # noqa: N999

from __future__ import annotations

from typing import Any

import numpy as np
from loguru import logger

try:
    import core.core_cognitive_unified
    from core.core_fusion import (
        LiquidityZoneMapper,
    )
except ImportError as exc:
    logger.warning(f"[L9] Could not load core modules: {exc}")
    core = None
    LiquidityZoneMapper = None

try:
    from engines.v11.liquidity_sweep_scorer import LiquiditySweepScorer
except ImportError:
    LiquiditySweepScorer = None

try:
    from analysis.exhaustion_dvg_fusion_engine import ExhaustionDivergenceFusionEngine
except ImportError:
    ExhaustionDivergenceFusionEngine = None

_MIN_BOS_CANDLES = 5
_RSI_PERIOD = 14
_DVG_TIMEFRAMES = ["M5", "M15", "H1", "H4"]


class L9SMCAnalyzer:
    """Layer 9: SMC Integration Analysis - Probability & Validation zone."""

    def __init__(self) -> None:
        self._smc_detector = None
        self._liquidity_mapper = None
        self._liq_scorer = None
        self._dvg_engine: object | None = None
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
        # LiquiditySweepScorer — best-effort
        if self._liq_scorer is None and LiquiditySweepScorer is not None:
            try:
                self._liq_scorer = LiquiditySweepScorer()
            except Exception as exc:
                logger.warning(f"[L9] Could not init LiquiditySweepScorer: {exc}")
        # ExhaustionDivergenceFusionEngine — best-effort
        if self._dvg_engine is None and ExhaustionDivergenceFusionEngine is not None:
            try:
                self._dvg_engine = ExhaustionDivergenceFusionEngine()
            except Exception as exc:
                logger.warning(f"[L9] Could not init DivergenceEngine: {exc}")

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
    # FVG detection (3-candle imbalance)
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_fvg(candles: list[dict]) -> bool:
        """Detect Fair Value Gap from candle dicts."""
        if len(candles) < 10:
            return False

        highs = [c.get("high", 0.0) for c in candles]
        lows = [c.get("low", 0.0) for c in candles]

        for i in range(len(candles) - 6, len(candles) - 2):
            h0, l0 = highs[i], lows[i]
            h1, l1 = highs[i + 1], lows[i + 1]
            h2, l2 = highs[i + 2], lows[i + 2]

            # Bullish FVG: gap up
            if h0 < l2:
                filled = (l1 <= h0) and (h1 >= l2)
                if not filled:
                    return True
            # Bearish FVG: gap down
            if l0 > h2:
                filled = (l1 <= h2) and (h1 >= l0)
                if not filled:
                    return True

        return False

    # ------------------------------------------------------------------
    # Order Block detection (impulse + retest)
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_orderblock(candles: list[dict]) -> bool:
        """Detect order block from candle dicts."""
        if len(candles) < 30:
            return False

        highs = [c.get("high", 0.0) for c in candles]
        lows = [c.get("low", 0.0) for c in candles]
        closes = [c.get("close", 0.0) for c in candles]

        ranges = np.array(highs[-30:], dtype=np.float64) - np.array(
            lows[-30:],
            dtype=np.float64,
        )
        avg_r = float(np.mean(ranges[:-1]))
        if avg_r <= 0:
            return False

        impulse_range = float(ranges[-1])
        if impulse_range < 1.5 * avg_r:
            return False

        impulse_bull = closes[-1] > closes[-2]

        ob_idx = None
        for i in range(-6, -1):
            if impulse_bull and closes[i] < closes[i - 1]:
                ob_idx = i
                break
            if (not impulse_bull) and closes[i] > closes[i - 1]:
                ob_idx = i
                break

        if ob_idx is None:
            return False

        # ATR-based proximity
        tr_vals = [max(highs[j] - lows[j], 0.0) for j in range(-14, 0)]
        atr = float(np.mean(tr_vals)) if tr_vals else 0.0

        ob_mid = (highs[ob_idx] + lows[ob_idx]) / 2.0
        price = closes[-1]
        band = atr * 0.5 if atr > 0 else price * 0.004
        return abs(price - ob_mid) < band

    # ------------------------------------------------------------------
    # Liquidity sweep scoring
    # ------------------------------------------------------------------
    def _detect_sweep(self, candles: list[dict], trend: str) -> tuple[bool, float]:
        """Detect liquidity sweep using LiquiditySweepScorer.

        Returns (sweep_detected, sweep_quality).
        """
        if not candles or self._liq_scorer is None:
            return False, 0.0

        try:
            direction = "bullish" if trend == "BULLISH" else "bearish"
            result = self._liq_scorer.score(candles, direction=direction)
            return (
                bool(getattr(result, "sweep_detected", False)),
                float(getattr(result, "sweep_quality", 0.0)),
            )
        except Exception:
            return False, 0.0

    # ------------------------------------------------------------------
    # RSI computation for divergence
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_rsi(closes: list[float], period: int = _RSI_PERIOD) -> list[float]:
        """Compute RSI from close prices.  Returns list aligned to *closes*."""
        if len(closes) < period + 1:
            return []
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(d, 0.0) for d in deltas]
        losses = [abs(min(d, 0.0)) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi_values: list[float] = []
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
            rsi_values.append(100.0 - 100.0 / (1.0 + rs))
        return rsi_values

    # ------------------------------------------------------------------
    # Divergence detection (multi-TF)
    # ------------------------------------------------------------------
    def _compute_divergence(self, symbol: str, trend: str) -> float:
        """Compute dvg_confidence using ExhaustionDivergenceFusionEngine.

        Fetches candle data across M5/M15/H1/H4, derives RSI, and runs
        the multi-TF divergence detector.

        Returns:
            Divergence confidence in [0.0, 1.0].  0.0 on any failure.
        """
        if self._dvg_engine is None:
            return 0.0

        mode = "bullish" if trend == "BEARISH" else "bearish"

        osc_data: dict[str, list[float]] = {}
        price_data: dict[str, list[float]] = {}

        for tf in _DVG_TIMEFRAMES:
            candles = self._get_candles(symbol, timeframe=tf, count=30)
            if len(candles) < _RSI_PERIOD + 2:
                continue
            closes = [float(c.get("close", 0.0)) for c in candles]
            rsi = self._compute_rsi(closes)
            if len(rsi) >= 2:
                osc_data[tf] = rsi[-2:]
                price_data[tf] = closes[-2:]

        if not osc_data:
            return 0.0

        try:
            result = self._dvg_engine.analyze(osc=osc_data, price=price_data, mode=mode)  # type: ignore[union-attr]
            return float(result.get("confidence", 0.0))
        except Exception as exc:
            logger.warning("[L9] Divergence analysis failed: {}", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def analyze(self, symbol: str, structure: dict[str, Any] | None = None) -> dict[str, Any]:
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
        if self._prev_trend is not None and self._prev_trend != trend:  # noqa: SIM102
            if trend in ("BULLISH", "BEARISH") and self._prev_trend in ("BULLISH", "BEARISH"):
                choch_detected = True
        self._prev_trend = trend

        # --- BOS detection from candle data ---
        candles = self._get_candles(symbol)
        bos_detected = self._detect_bos(candles, trend) if candles else False

        # --- FVG and OB detection from candle data ---
        fvg_present = self._detect_fvg(candles) if candles else False
        ob_present = self._detect_orderblock(candles) if candles else False

        # --- Liquidity sweep detection ---
        sweep_detected, sweep_quality = self._detect_sweep(candles, trend)

        # --- Divergence detection ---
        dvg_confidence = self._compute_divergence(symbol, trend)

        # --- Confidence ---
        base_confidence = 0.3
        if bos_detected:
            base_confidence = 0.8
        elif choch_detected:
            base_confidence = 0.6
        elif trend != "NEUTRAL":
            base_confidence = 0.4

        # Boost confidence for additional SMC confirmations
        smc_boost = sum(
            [
                0.05 if fvg_present else 0.0,
                0.05 if ob_present else 0.0,
                0.05 if sweep_detected else 0.0,
            ]
        )
        confidence = min(1.0, base_confidence + smc_boost)

        # --- SMC signal ---
        smc = bos_detected or choch_detected

        # --- Displacement (strong move in trend direction) ---
        displacement = bos_detected  # displacement accompanies BOS

        # --- Liquidity score from sweep quality ---
        liquidity_score = sweep_quality if sweep_detected else 0.0

        return {
            "smc_score": int(confidence * 100),
            "liquidity_score": liquidity_score,
            "dvg_confidence": dvg_confidence,
            "smart_money_bias": trend,
            "smart_money_signal": "ACCUMULATION"
            if trend == "BULLISH"
            else ("DISTRIBUTION" if trend == "BEARISH" else "NEUTRAL"),
            "ob_present": ob_present,
            "fvg_present": fvg_present,
            "sweep_detected": sweep_detected,
            "confidence": confidence,
            "valid": True,
            # Extended SMC fields
            "smc": smc,
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "displacement": displacement,
            "liquidity_sweep": sweep_detected,
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
