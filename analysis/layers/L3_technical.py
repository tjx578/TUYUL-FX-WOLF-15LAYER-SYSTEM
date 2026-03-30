"""
L3 — Technical Deep Dive + Smart Money Enrichment (PRODUCTION v6)
==================================================================
Multi-asset safe: FX, XAU, XAG, BTC, Indices.

v6 upgrade: Logistic edge probability as ADDITIVE enrichment.
ALL v5 methods, scoring, and output contract preserved byte-identical.

Mathematical model (v6 enrichment):
    X = [trend_str, struct_score, conf/4, liq, trq3d, adx_n, atr_exp]
    z = W^T · X + bias
    P_edge = σ(z)
    drift_state = classify(drift)     # FRESH / EXTENDING / OVEREXTENDED
    drift_factor = lookup(drift_state) # 1.0 / 0.85 / 0.65
    P_adj = P_edge × drift_factor

Pipeline interface:
    L3TechnicalAnalyzer().analyze(symbol) -> dict[str, Any]

Output contract (consumed by L4, L12 synthesis, L13, L15):
    === v5 contract (IDENTICAL, preserved) ===
    technical_score    int   0-100   ScoresContract + L4 legacy
    structure_validity str   STRONG/MODERATE/WEAK
    confluence_points  int   0-4     smart-money confluence count
    trq3d_energy       float 0-1     L15 Zona 1 (target >= 0.65)
    drift              float 0+      L13 alpha-beta-gamma (target <= 0.004)
    trend              str   BULLISH/BEARISH/NEUTRAL  direction source
    confidence         float 0-1     L4 exec_score PRIMARY key
    structure_score    float 0-1     L4 exec_score FALLBACK key
    valid              bool          pipeline gate check

    === v6 enrichment (ADDITIVE, new keys) ===
    edge_probability        float 0-1   calibrated P(structural edge)
    edge_detail             dict        full breakdown (features, z, p_raw, etc.)
    drift_state             str         FRESH / EXTENDING / OVEREXTENDED
    trend_strength          float 0-1   ADX-derived (direction-agnostic)
    adx                     float 0-100 raw Wilder ADX
    atr                     float       raw ATR value
    atr_expansion           float       vol_factor ratio [0.7, 2.0]
    liquidity_score         float 0-1   sweep quality from engine

    === v7 SMC event markers (ADDITIVE) ===
    fvg_detected            bool        Fair Value Gap detected (3-candle imbalance)
    ob_detected             bool        Order Block detected (impulse + retest)
    fib_retracement_hit     bool        Price near key Fibonacci level
    volume_profile_poc      float       POC price level (highest-volume bin mid)
    volume_profile_poc_hit  bool        Price near POC
    vpc_zones               list[dict]  High-volume cluster zones [{price_low,price_high,volume,strength}]

Version: v6 (Logistic Edge Enrichment + Drift Context)
Preserves all v5-final infrastructure:
    - ATR-based vol_factor, confluence band, TRQ3D normalization
    - True EMA via IndicatorEngine, True ADX (Wilder RMA)
    - BOS + range filter structure, Volume Profile, Order Block, FVG
    - LiquiditySweepScorer integration, per-call TRQ3D
    - Balanced scoring: 25+25+20+20+10 = 100 max (UNCHANGED)
"""  # noqa: N999

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
# §0  EDGE MODEL CONSTANTS (v6 enrichment)
# ═══════════════════════════════════════════════════════════════════════

# Expert-calibrated weight vector W for P_edge = σ(W^T · X + bias)
# Order: [trend_str, struct_score, conf_norm, liq_score,
#         trq3d_energy, adx_norm, atr_expansion]
#
# NOTE: All weights are DIRECTION-AGNOSTIC.  trend_strength=0.8 for
# BULLISH and BEARISH produces IDENTICAL P_edge.  This is correct:
# ADX measures strength-of-trend, not direction.  Direction is
# captured by the `trend` label output, not the edge score.
_EDGE_WEIGHTS: list[float] = [1.8, 1.5, 1.2, 1.0, 0.8, 0.6, 0.4]
_EDGE_BIAS: float = -3.5

# Drift context thresholds — same for BULLISH and BEARISH
# Drift = |price - VWAP| / price (distance from equilibrium)
_DRIFT_FRESH: float = 0.003  # entry phase: full edge
_DRIFT_EXTENDING: float = 0.008  # continuation: moderate edge
# Above EXTENDING = OVEREXTENDED: late entry

# Drift context multipliers (NOT penalty — context factor)
_DRIFT_FACTORS: dict[str, float] = {
    "FRESH": 1.00,  # early entry → full conviction
    "EXTENDING": 0.85,  # trend continuation → slightly reduced
    "OVEREXTENDED": 0.65,  # late entry → reduced (not killed)
}


# ═══════════════════════════════════════════════════════════════════════
# §0.1  PURE MATH
# ═══════════════════════════════════════════════════════════════════════


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid σ(x) → (0, 1)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def _classify_drift(drift: float) -> str:
    """Classify drift into context state.

    Symmetric for BULLISH and BEARISH:
        FRESH:        drift < 0.003  → price near equilibrium
        EXTENDING:    0.003 ≤ drift < 0.008  → trend underway
        OVEREXTENDED: drift ≥ 0.008 → extended from equilibrium

    This is NOT a directional judgment — a BEARISH move with drift=0.002
    is equally FRESH as a BULLISH move with drift=0.002.
    """
    if drift < _DRIFT_FRESH:
        return "FRESH"
    if drift < _DRIFT_EXTENDING:
        return "EXTENDING"
    return "OVEREXTENDED"


def _compute_edge_probability(
    *,
    trend_strength: float,
    structure_score: float,
    confluence_count: int,
    liquidity_score: float,
    trq3d_energy: float,
    adx_norm: float,
    atr_expansion: float,
    drift: float,
) -> tuple[float, dict[str, Any]]:
    """Compute calibrated edge probability P_edge_adj.

    Mathematical model:
        X = [trend, struct, conf/4, liq, trq3d, adx_n, atr_exp]
        z = W^T · X + bias
        P_edge = σ(z)
        drift_state = classify(drift)
        drift_factor = lookup(drift_state)
        P_adj = P_edge × drift_factor

    Direction-agnostic:
        BULLISH trend_strength=0.8 and BEARISH trend_strength=0.8
        produce IDENTICAL P_edge.  This is by design — edge measures
        the QUALITY of the setup, not its direction.

    Args:
        All features in [0, 1] range (confluence_count → conf/4).
        drift: VWAP deviation (0+), higher = more extended.

    Returns:
        (p_adj, detail_dict) for logging / downstream enrichment.
    """
    x = [
        float(np.clip(trend_strength, 0.0, 1.0)),
        float(np.clip(structure_score, 0.0, 1.0)),
        float(np.clip(confluence_count / 4.0, 0.0, 1.0)),
        float(np.clip(liquidity_score, 0.0, 1.0)),
        float(np.clip(trq3d_energy, 0.0, 1.0)),
        float(np.clip(adx_norm, 0.0, 1.0)),
        float(np.clip(atr_expansion, 0.0, 1.0)),
    ]

    z = sum(w * xi for w, xi in zip(_EDGE_WEIGHTS, x, strict=False)) + _EDGE_BIAS
    p_edge = _sigmoid(z)

    drift_state = _classify_drift(drift)
    drift_factor = _DRIFT_FACTORS[drift_state]
    p_adj = p_edge * drift_factor

    detail = {
        "features": {
            "trend_strength": x[0],
            "structure_score": x[1],
            "confluence_norm": x[2],
            "liquidity_score": x[3],
            "trq3d_energy": x[4],
            "adx_norm": x[5],
            "atr_expansion": x[6],
        },
        "logit_z": round(z, 4),
        "p_edge_raw": round(p_edge, 4),
        "drift": round(drift, 6),
        "drift_state": drift_state,
        "drift_factor": drift_factor,
        "p_edge_adj": round(p_adj, 4),
    }

    return p_adj, detail


# ═══════════════════════════════════════════════════════════════════════
# §1  MAIN ANALYZER
# ═══════════════════════════════════════════════════════════════════════


class L3TechnicalAnalyzer:
    """Layer 3: Technical Deep Dive + TRQ-3D (Smart Money aware).

    Pull-based architecture: sources data from LiveContextBus.
    Stateless per-call for TRQ3D (fresh engine avoids cross-symbol bleed).

    v6: Adds edge probability enrichment on top of v5 scoring.
    v5 `_compute_tech_score()` is preserved UNCHANGED as the primary
    `technical_score` output consumed by L4/L12/L15.
    """

    def __init__(self) -> None:
        self._bus = LiveContextBus()
        self._liq = LiquiditySweepScorer()

    # ── public API ─────────────────────────────────────────────────

    def analyze(self, symbol: str) -> dict[str, Any]:
        """Deep technical analysis for *symbol*.

        Returns:
            dict with v5 contract keys (unchanged) + v6 enrichment keys.
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
            symbol,
            candles_h1,
            candles_h4,
            candles_d1,
        )

        # Liquidity sweep scorer expects candle dicts + direction string.
        # When trend is NEUTRAL, check both directions and use the better
        # quality to avoid always defaulting to one side.
        if trend == "BULLISH":
            liq_result = self._liq.score(candles_h1, direction="bullish")
        elif trend == "BEARISH":
            liq_result = self._liq.score(candles_h1, direction="bearish")
        else:
            liq_bull = self._liq.score(candles_h1, direction="bullish")
            liq_bear = self._liq.score(candles_h1, direction="bearish")
            liq_result = liq_bull if liq_bull.sweep_quality >= liq_bear.sweep_quality else liq_bear
        liq_score = float(getattr(liq_result, "sweep_quality", 0.0))

        # ── v5 scoring (UNCHANGED) ────────────────────────────────
        technical_score = self._compute_tech_score(
            trend_strength=trend_strength,
            structure_score=float(structure["score"]),
            confluence_count=int(confluence["count"]),
            liquidity_score=liq_score,
            trq3d_energy=float(trq3d["energy"]),
        )

        # ── v6 edge enrichment (ADDITIVE) ─────────────────────────
        adx_raw = self._adx_wilder(highs, lows, closes, period=14)
        atr_expansion = self._vol_factor(highs, lows, closes)
        atr_exp_norm = float(np.clip((atr_expansion - 0.7) / 1.3, 0.0, 1.0))

        edge_prob, edge_detail = _compute_edge_probability(
            trend_strength=trend_strength,
            structure_score=float(structure["score"]),
            confluence_count=int(confluence["count"]),
            liquidity_score=liq_score,
            trq3d_energy=float(trq3d["energy"]),
            adx_norm=adx_raw / 100.0,
            atr_expansion=atr_exp_norm,
            drift=float(trq3d["drift"]),
        )

        logger.info(
            "[L3] %s trend=%s tech=%d P_edge=%.4f drift_state=%s "
            "struct=%s conf=%d liq=%.2f trq=%.3f drift=%.5f atr=%.6f",
            symbol,
            trend,
            technical_score,
            edge_prob,
            edge_detail["drift_state"],
            structure["validity"],
            confluence["count"],
            liq_score,
            trq3d["energy"],
            trq3d["drift"],
            atr,
        )

        return {
            # ── v5 contract (PRESERVED IDENTICAL) ─────────────────
            "technical_score": technical_score,
            "structure_validity": structure["validity"],
            "confluence_points": confluence["count"],
            "trq3d_energy": trq3d["energy"],
            "drift": trq3d["drift"],
            "trend": trend,
            "confidence": structure["confidence"],
            "structure_score": structure["score"],
            "valid": True,
            # ── v6 enrichment (ADDITIVE) ──────────────────────────
            "edge_probability": round(edge_prob, 4),
            "edge_detail": edge_detail,
            "drift_state": edge_detail["drift_state"],
            "trend_strength": trend_strength,
            "adx": adx_raw,
            "atr": atr,
            "atr_expansion": atr_expansion,
            "liquidity_score": liq_score,
            # ── v7 SMC event markers (ADDITIVE) ───────────────────
            "fvg_detected": confluence.get("fvg_detected", False),
            "ob_detected": confluence.get("ob_detected", False),
            "fib_retracement_hit": confluence.get("fib_retracement_hit", False),
            "volume_profile_poc": confluence.get("volume_profile_poc", 0.0),
            "volume_profile_poc_hit": confluence.get("volume_profile_poc_hit", False),
            "vpc_zones": confluence.get("vpc_zones", []),
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
            tr_vals.append(  # noqa: PERF401
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

        SYMMETRY: BULLISH and BEARISH use IDENTICAL strength formula:
            strength = min(1.0, (adx - 20.0) / 25.0)
        ADX measures trend intensity, not direction.
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
            tr_short.append(  # noqa: PERF401
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        atr_short = float(np.mean(tr_short)) if tr_short else 0.0

        tr_long: list[float] = []
        for i in range(max(1, len(closes) - 20), len(closes)):
            tr_long.append(  # noqa: PERF401
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
        l = np.array(lows, dtype=np.float64)  # noqa: E741
        c = np.array(closes, dtype=np.float64)

        up_move = h[1:] - h[:-1]
        down_move = l[:-1] - l[1:]

        plus_dm = np.where(
            (up_move > down_move) & (up_move > 0),
            up_move,
            0.0,
        )
        minus_dm = np.where(
            (down_move > up_move) & (down_move > 0),
            down_move,
            0.0,
        )

        tr = np.maximum.reduce(
            [
                h[1:] - l[1:],
                np.abs(h[1:] - c[:-1]),
                np.abs(l[1:] - c[:-1]),
            ]
        )

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

    # ═══════════════════════════════════════════════════════════════
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

        SYMMETRY: BOS upward and BOS downward return IDENTICAL
        score (0.85) and confidence (0.85).  Structure break is
        structure break — direction doesn't affect quality.
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
    ) -> dict[str, Any]:
        """Count smart-money confluence zones (max 4) + individual markers."""
        count = 0

        fib_hit = self._fib_retracement_hit(highs, lows, closes, atr)
        if fib_hit:
            count += 1

        poc_hit = self._volume_profile_poc_hit(closes, volumes, bins=20, atr=atr)
        if poc_hit:
            count += 1

        ob_detected = self._detect_orderblock(highs, lows, closes, atr)
        if ob_detected:
            count += 1

        fvg_detected = self._detect_fvg(highs, lows, closes)
        if fvg_detected:
            count += 1

        # v7: Volume Profile POC price level (float)
        poc_price = self._compute_poc_price(closes, volumes, bins=20)

        # v7: Volume Profile Cluster zones
        vpc_zones = self._compute_vpc_zones(closes, volumes, bins=20, atr=atr)

        return {
            "count": int(min(count, 4)),
            # v7 individual event markers
            "fvg_detected": fvg_detected,
            "ob_detected": ob_detected,
            "fib_retracement_hit": fib_hit,
            "volume_profile_poc_hit": poc_hit,
            "volume_profile_poc": poc_price,
            "vpc_zones": vpc_zones,
        }

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
            np.digitize(window_prices, edges) - 1,
            0,
            bins - 1,
        )
        for idx, v in zip(idxs, window_vols, strict=False):
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

    # ── Volume Profile POC price level (v7) ──────────────────────

    @staticmethod
    def _compute_poc_price(
        closes: list[float],
        volumes: list[float],
        bins: int = 20,
    ) -> float:
        """Return the Point of Control price level (highest-volume bin mid).

        Returns 0.0 on insufficient data.
        """
        if len(closes) < 30:
            return 0.0

        window_prices = np.array(closes[-30:], dtype=np.float64)
        window_vols = np.array(volumes[-30:], dtype=np.float64)

        p_min = float(np.min(window_prices))
        p_max = float(np.max(window_prices))
        if p_max <= p_min:
            return 0.0

        edges = np.linspace(p_min, p_max, bins + 1)
        vol_by_bin = np.zeros(bins, dtype=np.float64)

        idxs = np.clip(
            np.digitize(window_prices, edges) - 1,
            0,
            bins - 1,
        )
        for idx, v in zip(idxs, window_vols, strict=False):
            vol_by_bin[int(idx)] += float(v)

        poc_bin = int(np.argmax(vol_by_bin))
        return float((edges[poc_bin] + edges[poc_bin + 1]) / 2.0)

    # ── Volume Profile Cluster zones (v7) ────────────────────────

    @staticmethod
    def _compute_vpc_zones(
        closes: list[float],
        volumes: list[float],
        bins: int = 20,
        atr: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Compute Volume Profile Cluster (VPC) zones.

        Returns a list of high-volume price zones where volume
        exceeds 1.5× the average bin volume (HVN clusters).
        Each zone: {"price_low", "price_high", "volume", "strength"}.
        """
        if len(closes) < 30:
            return []

        window_prices = np.array(closes[-30:], dtype=np.float64)
        window_vols = np.array(volumes[-30:], dtype=np.float64)

        p_min = float(np.min(window_prices))
        p_max = float(np.max(window_prices))
        if p_max <= p_min:
            return []

        edges = np.linspace(p_min, p_max, bins + 1)
        vol_by_bin = np.zeros(bins, dtype=np.float64)

        idxs = np.clip(
            np.digitize(window_prices, edges) - 1,
            0,
            bins - 1,
        )
        for idx, v in zip(idxs, window_vols, strict=False):
            vol_by_bin[int(idx)] += float(v)

        avg_vol = float(np.mean(vol_by_bin))
        if avg_vol <= 0:
            return []

        hvn_threshold = 1.5
        zones: list[dict[str, Any]] = []
        for i in range(bins):
            if vol_by_bin[i] > avg_vol * hvn_threshold:
                zones.append(
                    {
                        "price_low": round(float(edges[i]), 6),
                        "price_high": round(float(edges[i + 1]), 6),
                        "volume": round(float(vol_by_bin[i]), 2),
                        "strength": round(float(vol_by_bin[i] / avg_vol), 4),
                    }
                )

        return zones

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

        normalized_energy = raw_energy / max(atr * 1000.0, 1e-09) if atr > 0 else raw_energy / max(price, 1e-09)

        energy = float(min(1.0, max(0.0, normalized_energy)))

        vwap = float(trq.get_vwap(symbol))
        drift = float(abs(price - vwap) / max(price, 1e-9))

        return {"energy": energy, "drift": drift}

    # ═══════════════════════════════════════════════════════════════
    # §7  SCORING (balanced, capped at 100) — v5 UNCHANGED
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
        """Balanced technical score — v5 IDENTICAL.

        SYMMETRY: trend_strength from BULLISH and BEARISH uses
        the same formula.  A strong bear scores the same as a
        strong bull — direction is captured separately in `trend`.

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

        return int(
            min(
                100,
                round(
                    trend_pts + struct_pts + conf_pts + liq_pts + trq_pts,
                ),
            )
        )

    # ═══════════════════════════════════════════════════════════════
    # §8  FALLBACK (insufficient data)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _insufficient_data(symbol: str) -> dict[str, Any]:
        """Safe fallback — valid=False triggers pipeline early-exit."""
        logger.warning("[L3] %s insufficient data for analysis", symbol)
        return {
            # v5 contract
            "technical_score": 0,
            "structure_validity": "WEAK",
            "confluence_points": 0,
            "trq3d_energy": 0.0,
            "drift": 0.0,
            "trend": "NEUTRAL",
            "confidence": 0.0,
            "structure_score": 0.0,
            "valid": False,
            # v6 enrichment
            "edge_probability": 0.0,
            "edge_detail": {},
            "drift_state": "FRESH",
            "trend_strength": 0.0,
            "adx": 0.0,
            "atr": 0.0,
            "atr_expansion": 1.0,
            "liquidity_score": 0.0,
            # v7 SMC event markers
            "fvg_detected": False,
            "ob_detected": False,
            "fib_retracement_hit": False,
            "volume_profile_poc": 0.0,
            "volume_profile_poc_hit": False,
            "vpc_zones": [],
        }
