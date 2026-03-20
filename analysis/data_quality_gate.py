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

import os
import time
from dataclasses import dataclass
from typing import Any

from state.data_freshness import FeedFreshnessState, classify_feed_freshness, stale_threshold_seconds
from utils.market_hours import weekend_gap_seconds


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
    freshness_state: FeedFreshnessState
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
            "freshness_state": self.freshness_state,
            "reasons": list(self.reasons),
        }


@dataclass
class DataQualityConfig:
    """Thresholds for data quality assessment."""

    max_gap_ratio: float = 0.10  # >10% gap candles = degraded
    min_tick_count: int = 3  # candles with <3 ticks are suspect
    max_low_tick_ratio: float = 0.15  # >15% low-tick candles = degraded
    stale_threshold_seconds: float = 300.0  # loaded from stale_threshold_seconds() by default loader
    stale_candle_multiplier: float = 2.0  # allow up to N candle periods before stale
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
        self._config = config or self._load_config_from_env()

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value.strip())
        except (ValueError, AttributeError):
            return default

    @classmethod
    def _load_config_from_env(cls) -> DataQualityConfig:
        """Load tunable data-quality thresholds from environment variables."""
        return DataQualityConfig(
            stale_threshold_seconds=cls._env_float(
                "WOLF_DQ_STALE_THRESHOLD_SECONDS",
                stale_threshold_seconds(),
            ),
            stale_candle_multiplier=cls._env_float(
                "WOLF_DQ_STALE_CANDLE_MULTIPLIER",
                3.0,
            ),
            stale_penalty=cls._env_float(
                "WOLF_DQ_STALE_PENALTY",
                DataQualityConfig.stale_penalty,
            ),
        )

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> float | None:
        tf = timeframe.strip().upper()
        if not tf:
            return None
        if tf == "MN":
            return 30.0 * 24.0 * 3600.0

        unit = tf[0]
        value = tf[1:]
        if not value.isdigit():
            return None
        n = max(1, int(value))
        if unit == "M":
            return n * 60.0
        if unit == "H":
            return n * 3600.0
        if unit == "D":
            return n * 86400.0
        if unit == "W":
            return n * 604800.0
        return None

    def _stale_threshold_for_timeframe(self, timeframe: str) -> float:
        cfg = self._config
        base = max(0.0, float(cfg.stale_threshold_seconds))
        tf_seconds = self._timeframe_to_seconds(timeframe)
        if tf_seconds is None:
            return base
        return max(base, tf_seconds * max(0.0, float(cfg.stale_candle_multiplier)))

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
                freshness_state="no_producer",
                reasons=("no_candles",),
            )

        # Count gap candles
        gap_candles = sum(1 for c in window if c.get("has_gap", False))
        gap_ratio = gap_candles / total

        # Count low-tick candles
        low_tick = sum(1 for c in window if (c.get("tick_count", cfg.min_tick_count) < cfg.min_tick_count))
        low_tick_ratio = low_tick / total

        # Staleness — subtract weekend closure time so data from
        # Friday evening doesn't falsely flag as stale on Saturday.
        now = time.time()
        if last_update_ts:
            raw_staleness = now - last_update_ts
            weekend_gap = weekend_gap_seconds(last_update_ts, now)
            staleness = max(0.0, raw_staleness - weekend_gap)
        else:
            staleness = float("inf")

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

        stale_threshold = self._stale_threshold_for_timeframe(timeframe)
        freshness = classify_feed_freshness(
            transport_ok=True,
            has_producer_signal=last_update_ts is not None,
            staleness_seconds=staleness,
            threshold_seconds=stale_threshold,
        )
        if freshness.state == "stale_preserved":
            penalty += cfg.stale_penalty
            reasons.append(f"stale_data:{staleness:.0f}s>thr:{stale_threshold:.0f}s")
        elif freshness.state in {"no_producer", "no_transport"}:
            penalty += cfg.stale_penalty
            reasons.append(f"stale_data:{freshness.state}")

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
            freshness_state=freshness.state,
            reasons=tuple(reasons),
        )
