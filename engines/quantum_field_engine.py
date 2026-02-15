"""Quantum Field Engine — Layer-3 field-state analysis.

Analyses multi-timeframe candle data to detect market energy fields,
momentum flux, and volatility regimes. Produces a FieldResult that
feeds into the Layer-12 constitution verdict pipeline.

This is an ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np  # pyright: ignore[reportMissingImports]

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FieldResult:
    """Output of the Quantum Field Engine."""

    # Core scores (0.0 – 1.0)
    energy_score: float = 0.0
    momentum_flux: float = 0.0
    volatility_regime: str = "NORMAL"  # LOW | NORMAL | HIGH | EXTREME
    field_polarity: str = "NEUTRAL"    # BULLISH | BEARISH | NEUTRAL

    # Component details
    atr_normalized: float = 0.0
    volume_energy: float = 0.0
    price_velocity: float = 0.0
    price_acceleration: float = 0.0
    field_gradient: float = 0.0

    # Multi-timeframe alignment
    mtf_alignment: float = 0.0
    timeframe_scores: dict[str, float] = field(default_factory=dict)

    # Metadata
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# Helper pure functions
# ---------------------------------------------------------------------------

def _safe_array(data: Sequence[float], min_len: int = 2) -> np.ndarray | None:
    """Convert to numpy array; return None if too short."""
    arr = np.asarray(data, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    return arr if len(arr) >= min_len else None


def _normalize(value: float, lo: float, hi: float) -> float:
    """Clamp-normalize *value* into [0, 1]."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _compute_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                 period: int = 14) -> float:
    """Average True Range (Wilder smoothing)."""
    if len(highs) < period + 1:
        return 0.0
    tr_list: list[float] = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    if len(tr_list) < period:
        return float(np.mean(tr_list)) if tr_list else 0.0
    atr = float(np.mean(tr_list[:period]))
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _compute_velocity(closes: np.ndarray, period: int = 5) -> float:
    """Price velocity = average of per-bar returns over *period*."""
    if len(closes) < period + 1:
        return 0.0
    returns = np.diff(closes[-period - 1:]) / closes[-period - 1:-1]
    returns = returns[np.isfinite(returns)]
    return float(np.mean(returns)) if len(returns) > 0 else 0.0


def _compute_acceleration(closes: np.ndarray, period: int = 5) -> float:
    """Price acceleration = velocity delta."""
    if len(closes) < period * 2 + 1:
        return 0.0
    mid = len(closes) - period
    v_recent = _compute_velocity(closes[mid:], min(period, len(closes) - mid - 1))
    v_prior = _compute_velocity(closes[:mid + 1], min(period, mid))
    return v_recent - v_prior


def _volume_energy(volumes: np.ndarray, period: int = 14) -> float:
    """Relative volume energy: current volume vs moving average."""
    if len(volumes) < period + 1:
        return 0.5
    ma = float(np.mean(volumes[-period - 1:-1]))
    if ma <= 0:
        return 0.5
    ratio = float(volumes[-1]) / ma
    return _normalize(ratio, 0.3, 3.0)


def _classify_volatility(atr_norm: float) -> str:
    if atr_norm < 0.2:
        return "LOW"
    if atr_norm < 0.5:
        return "NORMAL"
    if atr_norm < 0.8:
        return "HIGH"
    return "EXTREME"


def _classify_polarity(velocity: float, threshold: float = 0.0002) -> str:
    if velocity > threshold:
        return "BULLISH"
    if velocity < -threshold:
        return "BEARISH"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class QuantumFieldEngine:
    """Quantum Field Engine — analysis only, no side-effects.

    Parameters
    ----------
    atr_period : int
        ATR lookback.
    velocity_period : int
        Price velocity lookback.
    energy_weights : dict
        Weights for sub-components when computing composite energy.
    """

    def __init__(
        self,
        atr_period: int = 14,
        velocity_period: int = 5,
        energy_weights: dict[str, float] | None = None,
        **_extra: Any,
    ) -> None:
        self.atr_period = atr_period
        self.velocity_period = velocity_period
        self.energy_weights: dict[str, float] = energy_weights or {
            "atr": 0.30,
            "volume": 0.25,
            "velocity": 0.25,
            "acceleration": 0.20,
        }

    # ---- public API -------------------------------------------------------

    def analyze(
        self,
        candles: dict[str, list[dict[str, Any]]],
        symbol: str = "",
    ) -> FieldResult:
        """Run field analysis across multiple timeframes.

        Parameters
        ----------
        candles:
            ``{"M15": [...], "H1": [...], ...}`` where each candle dict has
            keys ``open, high, low, close, volume, timestamp``.
        symbol:
            Optional symbol name (for metadata only).

        Returns
        -------
        FieldResult
        """
        if not candles:
            logger.warning("QuantumFieldEngine.analyze: empty candles input")
            return FieldResult(metadata={"symbol": symbol, "error": "no_candles"})

        tf_results: dict[str, dict[str, float]] = {}
        primary_tf = self._select_primary_tf(candles)

        for tf_name, tf_candles in candles.items():
            try:
                tf_results[tf_name] = self._analyze_single_tf(tf_candles)
            except Exception as exc:
                logger.warning("Field engine TF %s error: %s", tf_name, exc)
                tf_results[tf_name] = {"energy": 0.0, "confidence": 0.0}

        # Primary TF drives the main result
        primary = tf_results.get(primary_tf, {})

        # MTF alignment
        mtf_alignment = self._compute_mtf_alignment(tf_results)

        # Build result from primary + MTF
        atr_norm = primary.get("atr_norm", 0.0)
        velocity = primary.get("velocity", 0.0)
        acceleration = primary.get("acceleration", 0.0)
        vol_energy = primary.get("vol_energy", 0.5)
        energy = primary.get("energy", 0.0)
        gradient = primary.get("gradient", 0.0)

        confidence = self._compute_confidence(primary, mtf_alignment, len(candles))

        return FieldResult(
            energy_score=energy,
            momentum_flux=abs(velocity) * (1.0 + abs(acceleration)),
            volatility_regime=_classify_volatility(atr_norm),
            field_polarity=_classify_polarity(velocity),
            atr_normalized=atr_norm,
            volume_energy=vol_energy,
            price_velocity=velocity,
            price_acceleration=acceleration,
            field_gradient=gradient,
            mtf_alignment=mtf_alignment,
            timeframe_scores={tf: r.get("energy", 0.0) for tf, r in tf_results.items()},
            confidence=confidence,
            metadata={"symbol": symbol, "primary_tf": primary_tf},
        )

    # ---- internals --------------------------------------------------------

    @staticmethod
    def _select_primary_tf(candles: dict[str, list[dict[str, Any]]]) -> str:
        priority = ["M15", "H1", "H4", "D1", "W1", "MN"]
        for tf in priority:
            if tf in candles and len(candles[tf]) >= 20:
                return tf
        # Fallback: longest available
        return max(candles, key=lambda k: len(candles[k]))

    def _analyze_single_tf(self, tf_candles: list[dict[str, Any]]) -> dict[str, float]:
        """Analyse a single timeframe's candle list."""
        if len(tf_candles) < 5:
            return {"energy": 0.0, "confidence": 0.0}

        closes_raw = [c.get("close", 0.0) for c in tf_candles]
        highs_raw = [c.get("high", 0.0) for c in tf_candles]
        lows_raw = [c.get("low", 0.0) for c in tf_candles]
        vols_raw = [c.get("volume", 0.0) for c in tf_candles]

        closes = _safe_array(closes_raw)
        highs = _safe_array(highs_raw)
        lows = _safe_array(lows_raw)
        vols = _safe_array(vols_raw)

        if closes is None or highs is None or lows is None:
            return {"energy": 0.0, "confidence": 0.0}

        atr = _compute_atr(highs, lows, closes, self.atr_period)
        price_level = float(closes[-1]) if closes[-1] != 0 else 1.0
        atr_norm = _normalize(atr / abs(price_level), 0.0, 0.03)

        velocity = _compute_velocity(closes, self.velocity_period)
        acceleration = _compute_acceleration(closes, self.velocity_period)
        vol_energy = _volume_energy(vols, self.atr_period) if vols is not None else 0.5

        # Composite energy
        w = self.energy_weights
        energy = (
            w.get("atr", 0.25) * atr_norm
            + w.get("volume", 0.25) * vol_energy
            + w.get("velocity", 0.25) * _normalize(abs(velocity), 0.0, 0.005)
            + w.get("acceleration", 0.25) * _normalize(abs(acceleration), 0.0, 0.003)
        )
        energy = max(0.0, min(1.0, energy))

        # Field gradient (slope of recent energy proxy)
        gradient = velocity  # simplified

        confidence = min(1.0, len(closes) / 50.0) * 0.6 + 0.4 * (1.0 if atr > 0 else 0.0)

        return {
            "energy": energy,
            "atr_norm": atr_norm,
            "velocity": velocity,
            "acceleration": acceleration,
            "vol_energy": vol_energy,
            "gradient": gradient,
            "confidence": confidence,
        }

    @staticmethod
    def _compute_mtf_alignment(tf_results: dict[str, dict[str, float]]) -> float:
        """Compute multi-timeframe directional alignment [0,1]."""
        velocities = [r.get("velocity", 0.0) for r in tf_results.values() if r.get("confidence", 0) > 0]
        if len(velocities) < 2:
            return 0.5
        signs = [1 if v > 0 else (-1 if v < 0 else 0) for v in velocities]
        if not signs:
            return 0.5
        agreement = abs(sum(signs)) / len(signs)
        return agreement

    @staticmethod
    def _compute_confidence(
        primary: dict[str, float],
        mtf_alignment: float,
        num_timeframes: int,
    ) -> float:
        base = primary.get("confidence", 0.0)
        tf_bonus = min(0.2, num_timeframes * 0.05)
        mtf_bonus = mtf_alignment * 0.2
        return max(0.0, min(1.0, base * 0.6 + tf_bonus + mtf_bonus))
