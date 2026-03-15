"""
Data Quality Gate — validates candle data before it enters the analysis pipeline.

Zone: analysis/ — pure read-only validation, no execution side-effects.

Checks:
- Gap candle ratio: if too many candles in a window have `has_gap=True`,
  emits a degradation signal that downstream layers can use to reduce
  confidence.
- Staleness: flags candle series that haven't updated recently.
- Minimum tick count: candles with suspiciously few ticks are flagged.

The gate does NOT block candles — it annotates them with quality metadata
so that downstream layers (especially L12 gatekeeper) can degrade
gracefully rather than trading on bad data.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DataQualityReport:
    """Quality assessment for a symbol's candle window."""

    symbol: str
    timeframe: str
    total_candles: int
    gap_candles: int
    gap_ratio: float
    low_tick_candles: int
    degraded: bool
    confidence_penalty: float
    staleness_seconds: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "total_candles": self.total_candles,
            "gap_candles": self.gap_candles,
            "gap_ratio": round(self.gap_ratio, 4),
            "low_tick_candles": self.low_tick_candles,
            "degraded": self.degraded,
            "confidence_penalty": round(self.confidence_penalty, 4),
            "staleness_seconds": round(self.staleness_seconds, 2),
            "reasons": list(self.reasons),
        }


@dataclass
class DataQualityConfig:
    """Thresholds for data quality assessment."""

    max_gap_ratio: float = 0.10  # >10% gap candles = degraded
    min_tick_count: int = 3  # candles with <3 ticks are suspect
    max_low_tick_ratio: float = 0.15  # >15% low-tick candles = degraded
    stale_threshold_seconds: float = 300.0  # >5 min = stale
    gap_penalty_per_pct: float = 0.5  # penalty per 1% gap ratio (max 0.3)
    low_tick_penalty_per_pct: float = 0.3
    stale_penalty: float = 0.15
    max_penalty: float = 0.50  # total penalty cap (50% max)
    lookback_candles: int = 50  # how many recent candles to evaluate


class DataQualityGate:
    """Assess candle data quality and compute confidence degradation.

    Zone: analysis/ — pure read-only analysis, no execution side-effects.
    """

    def __init__(self, config: DataQualityConfig | None = None) -> None:
        self._config = config or DataQualityConfig()

    def assess(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict[str, Any]],
        last_update_ts: float | None = None,
    ) -> DataQualityReport:
        """Assess quality of candle data for a symbol/timeframe.

        Args:
            symbol: Trading pair symbol.
            timeframe: Candle timeframe (e.g. "M15", "H1").
            candles: List of candle dicts. Must contain at least
                     'has_gap' (bool) and optionally 'tick_count' (int).
            last_update_ts: Epoch timestamp of when candles were last updated.

        Returns:
            DataQualityReport with degradation signal and confidence penalty.
        """
        cfg = self._config
        window = candles[-cfg.lookback_candles :] if candles else []
        total = len(window)

        if total == 0:
            return DataQualityReport(
                symbol=symbol,
                timeframe=timeframe,
                total_candles=0,
                gap_candles=0,
                gap_ratio=0.0,
                low_tick_candles=0,
                degraded=True,
                confidence_penalty=cfg.max_penalty,
                staleness_seconds=float("inf"),
                reasons=("no_candles",),
            )

        # Count gap candles
        gap_candles = sum(1 for c in window if c.get("has_gap", False))
        gap_ratio = gap_candles / total

        # Count low-tick candles
        low_tick = sum(1 for c in window if (c.get("tick_count", cfg.min_tick_count) < cfg.min_tick_count))
        low_tick_ratio = low_tick / total

        # Staleness
        now = time.time()
        staleness = (now - last_update_ts) if last_update_ts else float("inf")

        # Compute penalty
        reasons: list[str] = []
        penalty = 0.0

        if gap_ratio > cfg.max_gap_ratio:
            gap_pct = gap_ratio * 100
            gap_penalty = min(0.3, gap_pct * cfg.gap_penalty_per_pct / 100)
            penalty += gap_penalty
            reasons.append(f"high_gap_ratio:{gap_ratio:.2%}")

        if low_tick_ratio > cfg.max_low_tick_ratio:
            lt_pct = low_tick_ratio * 100
            lt_penalty = min(0.2, lt_pct * cfg.low_tick_penalty_per_pct / 100)
            penalty += lt_penalty
            reasons.append(f"low_tick_candles:{low_tick_ratio:.2%}")

        if staleness > cfg.stale_threshold_seconds:
            penalty += cfg.stale_penalty
            reasons.append(f"stale_data:{staleness:.0f}s")

        penalty = min(penalty, cfg.max_penalty)
        degraded = len(reasons) > 0

        return DataQualityReport(
            symbol=symbol,
            timeframe=timeframe,
            total_candles=total,
            gap_candles=gap_candles,
            gap_ratio=gap_ratio,
            low_tick_candles=low_tick,
            degraded=degraded,
            confidence_penalty=penalty,
            staleness_seconds=staleness,
            reasons=tuple(reasons),
        )
