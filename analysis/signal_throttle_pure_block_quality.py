"""Pure pressure block quality scoring for SignalThrottle Fusion V3.

The scorer is diagnostic-only. It treats time gaps as quality/heat metadata,
not as a split or invalidation rule for the Pure Pressure Ledger.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any


@dataclass(frozen=True)
class PurePressureBlockQuality:
    pure_pressure_score: float
    heat_score: float
    sequence_score: float
    duration_score: float
    event_count_score: float
    density_score: float
    gap_quality_score: float
    source_purity_score: float
    block_quality_score: float
    pressure_class: str
    split_rule: str = "PAIR_ROTATION_ONLY"
    gap_policy: str = "QUALITY_ONLY"
    gap_split_applied: bool = False
    advisory_only: bool = True
    execution_tier: str = "WAIT"
    valid_for_execution: bool = False
    reason: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason"] = list(self.reason)
        return payload


def score_pure_pressure_block(
    block: Any,
    *,
    clean_block_seconds: int = 300,
) -> PurePressureBlockQuality:
    """Score a pure pressure block without granting execution authority."""

    duration_seconds = max(0.0, _number(_get(block, "duration_seconds")) or 0.0)
    events = max(0, int(_number(_get(block, "events") or _get(block, "event_count")) or 0))
    effective_ticks = max(0, int(_number(_get(block, "effective_ticks")) or events))
    density = max(
        0.0,
        _number(_get(block, "effective_density_per_minute"))
        or _number(_get(block, "density_per_minute"))
        or 0.0,
    )
    max_gap_seconds = max(0.0, _number(_get(block, "max_gap_seconds")) or 0.0)

    duration_score = _bounded(duration_seconds / max(float(clean_block_seconds * 3), 1.0) * 100.0)
    event_count_score = _bounded(effective_ticks / 40.0 * 100.0)
    density_score = _bounded(density / 12.0 * 100.0)
    gap_quality_score = _gap_quality_score(max_gap_seconds)
    source_purity_score = _source_purity_score(block)

    sequence_score = _round(
        duration_score * 0.45
        + event_count_score * 0.35
        + source_purity_score * 0.20
    )
    pure_pressure_score = _round(
        duration_score * 0.40
        + event_count_score * 0.40
        + density_score * 0.10
        + source_purity_score * 0.10
    )
    timing_compression_score = _timing_compression_score(duration_seconds, clean_block_seconds)
    heat_score = _round(
        density_score * 0.50
        + gap_quality_score * 0.35
        + timing_compression_score * 0.15
    )
    block_quality_score = _round(
        pure_pressure_score * 0.55
        + heat_score * 0.30
        + gap_quality_score * 0.15
    )
    pressure_class = _pressure_class(
        pure_pressure_score=pure_pressure_score,
        heat_score=heat_score,
        duration_seconds=duration_seconds,
        effective_ticks=effective_ticks,
    )

    return PurePressureBlockQuality(
        pure_pressure_score=pure_pressure_score,
        heat_score=heat_score,
        sequence_score=sequence_score,
        duration_score=_round(duration_score),
        event_count_score=_round(event_count_score),
        density_score=_round(density_score),
        gap_quality_score=_round(gap_quality_score),
        source_purity_score=_round(source_purity_score),
        block_quality_score=block_quality_score,
        pressure_class=pressure_class,
        reason=tuple(
            _reasons(
                duration_seconds=duration_seconds,
                effective_ticks=effective_ticks,
                heat_score=heat_score,
                max_gap_seconds=max_gap_seconds,
                clean_block_seconds=clean_block_seconds,
                pressure_class=pressure_class,
            )
        ),
    )


def _pressure_class(
    *,
    pure_pressure_score: float,
    heat_score: float,
    duration_seconds: float,
    effective_ticks: int,
) -> str:
    if effective_ticks <= 1:
        return "SPARSE_ARCHIVE"
    if pure_pressure_score >= 70.0 and heat_score >= 75.0:
        return "HOT_BURST_PRESSURE"
    if pure_pressure_score >= 70.0 and duration_seconds >= 300.0:
        return "LONG_CONTEXTUAL_RADAR"
    if pure_pressure_score >= 60.0 and heat_score >= 55.0:
        return "ACTIVE_PRESSURE_RADAR"
    if pure_pressure_score >= 40.0:
        return "TACTICAL_RADAR"
    if effective_ticks >= 2:
        return "LOW_ACTIVITY_RADAR"
    return "SPARSE_ARCHIVE"


def _reasons(
    *,
    duration_seconds: float,
    effective_ticks: int,
    heat_score: float,
    max_gap_seconds: float,
    clean_block_seconds: int,
    pressure_class: str,
) -> list[str]:
    reasons = [pressure_class]
    if duration_seconds >= clean_block_seconds:
        reasons.append("PURE_PRESSURE_DURATION_VALID")
    if effective_ticks >= 10:
        reasons.append("PURE_PRESSURE_EVENT_COUNT_VALID")
    if max_gap_seconds > clean_block_seconds:
        reasons.append("GAP_DEGRADES_HEAT_ONLY")
    if heat_score < 55.0:
        reasons.append("HEAT_NOT_FRESH_ENOUGH")
    reasons.append("EXECUTION_TIER_WAIT")
    return reasons


def _gap_quality_score(max_gap_seconds: float) -> float:
    if max_gap_seconds <= 75.0:
        return 100.0
    if max_gap_seconds <= 300.0:
        return 82.0
    if max_gap_seconds <= 900.0:
        return 62.0
    if max_gap_seconds <= 1800.0:
        return 45.0
    return 30.0


def _timing_compression_score(duration_seconds: float, clean_block_seconds: int) -> float:
    if duration_seconds <= 0.0:
        return 0.0
    if duration_seconds <= clean_block_seconds:
        return 100.0
    decay_window = max(float(clean_block_seconds * 6), 1.0)
    return _bounded(100.0 - ((duration_seconds - clean_block_seconds) / decay_window * 80.0), minimum=20.0)


def _source_purity_score(block: Any) -> float:
    eligible = _get(block, "eligible_for_pressure_block")
    if eligible is False:
        return 0.0
    source_stream = str(_get(block, "source_stream") or "").upper()
    if source_stream in {"SIGNAL_JSON", "SIGNAL_WATCH"}:
        return 40.0
    return 100.0


def _get(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _bounded(value: float, *, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return min(maximum, max(minimum, value))


def _round(value: float) -> float:
    return round(_bounded(float(value)), 3)


__all__ = ["PurePressureBlockQuality", "score_pure_pressure_block"]
