"""
L3 — Technical Deep Dive + Smart Money Enrichment (PRODUCTION)
===============================================================
Multi-asset safe: FX, XAU, XAG, BTC, Indices.

Pipeline interface:
    L3TechnicalAnalyzer().analyze(symbol) -> dict[str, Any]

Output contract (consumed by L4, L12 synthesis, L13, L15):
    technical_score    int   0-100   ScoresContract + L4 legacy
    structure_validity str   STRONG/MODERATE/WEAK
    confluence_points  int   0-4     smart-money confluence count
    trq3d_energy       float 0-1     L15 Zona 1 (target >= 0.65)
    drift              float 0+      L13 alpha-beta-gamma (target <= 0.004)
    trend              str   BULLISH/BEARISH/NEUTRAL  direction source
    confidence         float 0-1     L4 exec_score PRIMARY key
    structure_score    float 0-1     L4 exec_score FALLBACK key
    valid              bool          pipeline gate check

Version: v5-final (ATR-normalized, multi-asset)
Fixes applied:
    - ATR-based vol_factor (asset-agnostic, replaces hardcoded x1000)
    - ATR-based confluence band (replaces fixed 0.3% threshold)
    - ATR-normalized TRQ3D energy (replaces raw min(1.0, ...) clamp)
    - Correct LiquiditySweepScorer integration (engines/v11/)
    - True EMA via IndicatorEngine (analysis/market/indicators.py)
    - True ADX with Wilder RMA smoothing
    - Structure 3-state: STRONG / MODERATE / WEAK (BOS + range filter)
    - Volume Profile: equal-width bins, meaningful POC
    - Order Block: impulse + last opposite candle + retest proximity
    - FVG: bullish + bearish + middle-candle non-fill check
    - TRQ3D: per-call instance (no cross-symbol state bleed), 60-bar feed
    - Balanced scoring: 25+25+20+20+10 = 100 max
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from analysis.market.indicators import IndicatorEngine
from context.live_context_bus import LiveContextBus
from core.core_quantum_unified import TRQ3DEngine
from engines.v11.liquidity_sweep_scorer import LiquiditySweepScorer

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# §1  MAIN ANALYZER
# ═══════════════════════════════════════════════════════════════════════


class L3TechnicalAnalyzer:
    """Layer 3: Technical Deep Dive + TRQ-3D (Smart Money aware).

    Pull-based architecture: sources data from LiveContextBus.
    Stateless per-call for TRQ3D (fresh engine avoids cross-symbol bleed).
    """

    def __init__(self) -> None:
        self._bus = LiveContextBus()
        self._liq = LiquiditySweepScorer()

    # ── public API ─────────────────────────────────────────────────

    def analyze(self, symbol: str) -> dict[str, Any]:
        """Deep technical analysis for *symbol*.

        Returns:
            dict matching the L3 output contract (see module docstring).
        """
        candles_h1 = self._bus.get_candle_history(symbol, "H1", count=80)
        candles_h4 = self._bus.get_candle_history(symbol, "H4", count=30)
        candles_d1 = self._bus.get_candle_history(symbol, "D1", count=15)

        if not candles_h1 or len(candles_h1) < 30:
            return self._insufficient_data(symbol)

        closes = [float(c["close"]) for c in candles_h1]
        highs = [float(c["high"]) for c in candles_h1]
        lows = [float(c["low"]) for c in candles_h1]
        volumes = [float(c.get("volume", 1.0)) for c in candles_h1]

        # ATR for asset-agnostic normalization (shared across sub-methods)
        atr = self._compute_atr(highs, lows, closes, period=14)

        trend, trend_strength = self._detect_trend(highs, lows, closes, atr)

        structure = self._analyze_structure(highs, lows, closes, atr)

        confluence = self._find_confluence(highs, lows, closes, volumes, atr)

        trq3d = self._compute_trq3d(
            symbol, candles_h1, candles_h4, candles_d1,
        )

        # Liquidity sweep scorer expects candle dicts + direction string
        direction = "bullish" if trend == "BULLISH" else "bearish"
        liq_result = self._liq.score(candles_h1, direction=direction)
        liq_score = float(getattr(liq_result, "sweep_quality", 0.0))

        technical_score = self._compute_tech_score(
            trend_strength=trend_strength,
            structure_score=float(structure["score"]),
            confluence_count=int(confluence["count"]),
            liquidity_score=liq_score,
            trq3d_energy=float(trq3d["energy"]),
        )

        logger.info(
            "[L3] %s trend=%s tech=%d struct=%s conf=%d "
            "liq=%.2f trq=%.3f drift=%.5f atr=%.6f",
            symbol,
            trend,
            technical_score,
            structure["validity"],
            confluence["count"],
            liq_score,
            trq3d["energy"],
            trq3d["drift"],
            atr,
        )

        return {
            "technical_score": technical_score,
            "structure_validity": structure["validity"],
            "confluence_points": confluence["count"],
            "trq3d_energy": trq3d["energy"],
            "drift": trq3d["drift"],
            "trend": trend,
            "confidence": structure["confidence"],
            "structure_score": structure["score"],
            "valid": True,
        }

    # ═══════════════════════════════════════════════════════════════
    # §2  ATR (shared foundation for asset-agnostic normalization)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_atr(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:
        """Average True Range — simple mean of last *period* TRs.

        Returns 0.0 when insufficient data.
        """
        if len(closes) < period + 1:
            return 0.0

        tr_vals: list[float] = []
        for i in range(1, len(closes)):
            tr_vals.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )

        return float(np.mean(tr_vals[-period:]))

    # ═══════════════════════════════════════════════════════════════
    # §3  TREND: EMA(20/50) + True ADX + ATR-adaptive sensitivity
    # ═══════════════════════════════════════════════════════════════

    def _detect_trend(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        atr: float,
    ) -> tuple[str, float]:
        """Detect trend direction and strength.

        Uses IndicatorEngine.ema for EMA crossover and true Wilder ADX
        for trend strength.  Gap threshold is ATR-adaptive so the same
        logic works for EURUSD (ATR ~0.0008) and XAUUSD (ATR ~20).
        """
        ema20 = IndicatorEngine.ema(closes, 20)
        ema50 = IndicatorEngine.ema(closes, 50)

        if ema20 is None or ema50 is None:
            return "NEUTRAL", 0.0

        adx = self._adx_wilder(highs, lows, closes, period=14)

        vol_factor = self._vol_factor(highs, lows, closes)
        price = max(closes[-1], 1e-9)
        ema_gap = abs(ema20 - ema50) / price
        gap_threshold = (atr / price) * 0.3 * vol_factor

        if ema20 > ema50 and ema_gap >= gap_threshold and adx >= 20.0:
            return "BULLISH", float(min(1.0, (adx - 20.0) / 25.0))

        if ema20 < ema50 and ema_gap >= gap_threshold and adx >= 20.0:
            return "BEARISH", float(min(1.0, (adx - 20.0) / 25.0))

        if adx < 15.0:
            return "NEUTRAL", 0.1

        return "NEUTRAL", 0.2

    def _vol_factor(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> float:
        """ATR-based volatility factor — asset-agnostic.

        Compares recent ATR(7) to longer ATR(20) to detect
        expansion / contraction.  Returns [0.7, 2.0].
        """
        if len(closes) < 30:
            return 1.0

        tr_short: list[float] = []
        for i in range(max(1, len(closes) - 7), len(closes)):
            tr_short.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        atr_short = float(np.mean(tr_short)) if tr_short else 0.0

        tr_long: list[float] = []
        for i in range(max(1, len(closes) - 20), len(closes)):
            tr_long.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        atr_long = float(np.mean(tr_long)) if tr_long else 0.0

        if atr_long <= 0:
            return 1.0

        ratio = atr_short / atr_long
        return float(min(2.0, max(0.7, ratio)))

    # ── True ADX (Wilder RMA smoothing) ──────────────────────────

    def _adx_wilder(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float:
        """Compute true ADX with Wilder RMA smoothing.

        Requires at least ``period * 2 + 2`` bars.
        Returns 0.0 on insufficient data or computation error.
        """
        if len(closes) < period * 2 + 2:
            return 0.0

        h = np.array(highs, dtype=np.float64)
        l = np.array(lows, dtype=np.float64)
        c = np.array(closes, dtype=np.float64)

        up_move = h[1:] - h[:-1]
        down_move = l[:-1] - l[1:]

        plus_dm = np.where(
            (up_move > down_move) & (up_move > 0), up_move, 0.0,
        )
        minus_dm = np.where(
            (down_move > up_move) & (down_move > 0), down_move, 0.0,
        )

        tr = np.maximum.reduce([
            h[1:] - l[1:],
            np.abs(h[1:] - c[:-1]),
            np.abs(l[1:] - c[:-1]),
        ])

        def _rma(x: np.ndarray, n: int) -> np.ndarray:
            """Wilder smoothing (Running Moving Average)."""
            out = np.zeros_like(x)
            out[n - 1] = np.mean(x[:n])
            alpha = 1.0 / n
            for i in range(n, len(x)):
                out[i] = out[i - 1] + alpha * (x[i] - out[i - 1])
            return out

        tr_rma = _rma(tr, period)
        plus_rma = _rma(plus_dm, period)
        minus_rma = _rma(minus_dm, period)

        tr_safe = np.where(tr_rma == 0, 1e-9, tr_rma)
        plus_di = 100.0 * (plus_rma / tr_safe)
        minus_di = 100.0 * (minus_rma / tr_safe)

        di_sum = plus_di + minus_di
        dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(di_sum, 1e-9)

        adx = _rma(dx, period)

        val = float(adx[-1])
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return float(max(0.0, min(100.0, val)))

    # ═══════════════════════════════════════��═══════════════════════
    # §4  STRUCTURE: BOS + range filter → STRONG / MODERATE / WEAK
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _analyze_structure(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        atr: float,
    ) -> dict[str, Any]:
        """Market structure analysis with ATR-based range filter.

        Uses ATR to determine whether the range is meaningful for
        the instrument (works for EURUSD, XAUUSD, XAGUSD alike).
        """
        if len(highs) < 20:
            return {"validity": "WEAK", "confidence": 0.0, "score": 0.0}

        prev_high = max(highs[-20:-5])
        prev_low = min(lows[-20:-5])
        last_high = highs[-1]
        last_low = lows[-1]

        bos_up = last_high > prev_high
        bos_down = last_low < prev_low

        recent_range = max(highs[-20:]) - min(lows[-20:])
        range_threshold = atr * 3.0 if atr > 0 else 0.0

        if not (bos_up or bos_down) and recent_range < range_threshold:
            return {"validity": "WEAK", "confidence": 0.15, "score": 0.15}

        if bos_up or bos_down:
            return {"validity": "STRONG", "confidence": 0.85, "score": 0.85}

        return {"validity": "MODERATE", "confidence": 0.55, "score": 0.55}

    # ═══════════════════════════════════════════════════════════════
    # §5  CONFLUENCE: Fib + Volume Profile + Order Block + FVG
    # ═══════════════════════════════════════════════════════════════

    def _find_confluence(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
        atr: float,
    ) -> dict[str, int]:
        """Count smart-money confluence zones (max 4)."""
        count = 0

        if self._fib_retracement_hit(highs, lows, closes, atr):
            count += 1
        if self._volume_profile_poc_hit(closes, volumes, bins=20, atr=atr):
            count += 1
        if self._detect_orderblock(highs, lows, closes, atr):
            count += 1
        if self._detect_fvg(highs, lows, closes):
            count += 1

        return {"count": int(min(count, 4))}

    # ── Fibonacci ────────────────────────────────────────────────

    @staticmethod
    def _fib_retracement_hit(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        atr: float,
    ) -> bool:
        """Check if price is near a key Fibonacci retracement level.

        Uses ATR-based band instead of fixed 0.3%.
        """
        if len(closes) < 40:
            return False

        swing_high = max(highs[-40:])
        swing_low = min(lows[-40:])
        diff = swing_high - swing_low
        if diff <= 0:
            return False

        price = closes[-1]
        band = atr * 0.5 if atr > 0 else price * 0.003

        levels = [
            swing_high - diff * 0.382,
            swing_high - diff * 0.500,
            swing_high - diff * 0.618,
            swing_high - diff * 0.786,
        ]
        return any(abs(price - lv) < band for lv in levels)

    # ── Volume Profile POC ───────────────────────────────────────

    @staticmethod
    def _volume_profile_poc_hit(
        closes: list[float],
        volumes: list[float],
        bins: int = 20,
        atr: float = 0.0,
    ) -> bool:
        """Check if price is near the Point of Control (highest-volume bin).

        Uses ATR-based proximity band — asset agnostic.
        """
        if len(closes) < 30:
            return False

        window_prices = np.array(closes[-30:], dtype=np.float64)
        window_vols = np.array(volumes[-30:], dtype=np.float64)

        p_min = float(np.min(window_prices))
        p_max = float(np.max(window_prices))
        if p_max <= p_min:
            return False

        edges = np.linspace(p_min, p_max, bins + 1)
        vol_by_bin = np.zeros(bins, dtype=np.float64)

        idxs = np.clip(
            np.digitize(window_prices, edges) - 1, 0, bins - 1,
        )
        for idx, v in zip(idxs, window_vols):
            vol_by_bin[int(idx)] += float(v)

        poc_bin = int(np.argmax(vol_by_bin))
        poc_mid = (edges[poc_bin] + edges[poc_bin + 1]) / 2.0

        price = float(closes[-1])
        band = atr * 0.5 if atr > 0 else price * 0.003
        return abs(price - poc_mid) < band

    # ── Order Block ──────────────────────────────────────────────

    @staticmethod
    def _detect_orderblock(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        atr: float,
    ) -> bool:
        """Detect practical order block with ATR-based proximity.

        Requires:
        1. Strong impulse candle (range > 1.5x average range)
        2. Last opposite candle before impulse (within lookback)
        3. Price retesting near OB zone (within 0.5 ATR)
        """
        if len(closes) < 30:
            return False

        ranges = np.array(highs[-30:], dtype=np.float64) - np.array(
            lows[-30:], dtype=np.float64,
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

        ob_mid = (highs[ob_idx] + lows[ob_idx]) / 2.0
        price = closes[-1]
        band = atr * 0.5 if atr > 0 else price * 0.004
        return abs(price - ob_mid) < band

    # ── Fair Value Gap ───────────────────────────────────────────

    @staticmethod
    def _detect_fvg(
        highs: list[float],
        lows: list[float],
        closes: list[float],
    ) -> bool:
        """Detect Fair Value Gap (3-candle imbalance).

        Bullish FVG:  high[i] < low[i+2]  (gap up)
        Bearish FVG:  low[i]  > high[i+2]  (gap down)
        Middle candle must NOT fully fill the gap.
        """
        if len(closes) < 10:
            return False

        for i in range(len(closes) - 6, len(closes) - 2):
            h0, l0 = highs[i], lows[i]
            h1, l1 = highs[i + 1], lows[i + 1]
            h2, l2 = highs[i + 2], lows[i + 2]

            if h0 < l2:
                filled = (l1 <= h0) and (h1 >= l2)
                if not filled:
                    return True

            if l0 > h2:
                filled = (l1 <= h2) and (h1 >= l0)
                if not filled:
                    return True

        return False

    # ═══════════════════════════════════════════════════════════════
    # §6  TRQ-3D (per-call instance, ATR-normalized energy)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_trq3d(
        symbol: str,
        candles_h1: list[dict[str, Any]],
        candles_h4: list[dict[str, Any]],
        candles_d1: list[dict[str, Any]],
    ) -> dict[str, float]:
        """Compute TRQ-3D energy and drift.

        Creates a fresh TRQ3DEngine per call to avoid cross-symbol
        state pollution.  Feeds up to 60 H1 candles.

        Energy normalization (ATR-based):
            TRQ3DEngine.get_energy() = mean(|delta_price|) * 1000
            normalized = raw_energy / (ATR * 1000)
                       ~ mean(|delta_price|) / ATR
            This yields momentum-relative-to-expected-volatility [0, ~1].

        Falls back to price normalization when ATR is unavailable.
        """
        if not candles_h4 or not candles_d1:
            return {"energy": 0.0, "drift": 0.0}

        trq = TRQ3DEngine()

        feed = candles_h1[-60:] if len(candles_h1) >= 60 else candles_h1
        for c in feed:
            trq.update(symbol, float(c["close"]))

        raw_energy = float(trq.get_energy(symbol))

        price = float(candles_h1[-1]["close"])
        highs = [float(c["high"]) for c in candles_h1]
        lows = [float(c["low"]) for c in candles_h1]
        closes = [float(c["close"]) for c in candles_h1]

        # ATR normalization (preferred over price-only)
        atr = L3TechnicalAnalyzer._compute_atr(highs, lows, closes, period=14)

        if atr > 0:
            normalized_energy = raw_energy / max(atr * 1000.0, 1e-9)
        else:
            normalized_energy = raw_energy / max(price, 1e-9)

        energy = float(min(1.0, max(0.0, normalized_energy)))

        vwap = float(trq.get_vwap(symbol))
        drift = float(abs(price - vwap) / max(price, 1e-9))

        return {"energy": energy, "drift": drift}

    # ═══════════════════════════════════════════════════════════════
    # §7  SCORING (balanced, capped at 100)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_tech_score(
        *,
        trend_strength: float,
        structure_score: float,
        confluence_count: int,
        liquidity_score: float,
        trq3d_energy: float,
    ) -> int:
        """Balanced technical score.

        Components:
            Trend strength:     0-25
            Structure score:    0-25
            Confluence (0-4):   0-20  (5 pts each)
            Liquidity sweep:    0-20
            TRQ3D energy:       0-10  (bonus confidence)
            ─────────────────────────
            Max:               100
        """
        trend_pts = float(np.clip(trend_strength, 0.0, 1.0)) * 25.0
        struct_pts = float(np.clip(structure_score, 0.0, 1.0)) * 25.0
        conf_pts = int(max(0, min(confluence_count, 4))) * 5.0
        liq_pts = float(np.clip(liquidity_score, 0.0, 1.0)) * 20.0
        trq_pts = float(np.clip(trq3d_energy, 0.0, 1.0)) * 10.0

        return int(min(100, round(
            trend_pts + struct_pts + conf_pts + liq_pts + trq_pts,
        )))

    # ═══════════════════════════════════════════════════════════════
    # §8  FALLBACK (insufficient data)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _insufficient_data(symbol: str) -> dict[str, Any]:
        """Safe fallback — valid=False triggers pipeline early-exit."""
        logger.warning("[L3] %s insufficient data for analysis", symbol)
        return {
            "technical_score": 0,
            "structure_validity": "WEAK",
            "confluence_points": 0,
            "trq3d_energy": 0.0,
            "drift": 0.0,
            "trend": "NEUTRAL",
            "confidence": 0.0,
            "structure_score": 0.0,
            "valid": False,
        }