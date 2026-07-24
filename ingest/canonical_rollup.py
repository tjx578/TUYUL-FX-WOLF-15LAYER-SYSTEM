"""Fail-closed canonical candle rollups for Strategy 5S-CR.

Only explicitly complete, authoritative, contiguous source windows may create
an H1 or H4 candle. Missing, duplicated, mixed-duration, or ambiguous source
windows are dropped instead of being promoted as closed evidence.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from contracts.canonical_candle import TIMEFRAME_DELTAS
from ingest.candle_builder import Candle, _align_to_period

_SUPPORTED_ROLLUPS = {
    ("M15", "H1"),
    ("H1", "H4"),
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _rollup_feed(
    *,
    source_timeframe: str,
    target_timeframe: str,
    component_feeds: set[str],
) -> str:
    material = "+".join(sorted(component_feeds)) or "unknown"
    prefix = f"canonical_rollup:{source_timeframe}-{target_timeframe}:"
    value = prefix + material
    if len(value) <= 100:
        return value
    digest = hashlib.sha256(material.encode()).hexdigest()[:16]
    return f"{prefix}feeds-{digest}"


def aggregate_contiguous_candles(
    candles: Iterable[Candle],
    *,
    source_timeframe: str,
    target_timeframe: str,
) -> list[Candle]:
    """Aggregate only full contiguous source windows into a higher timeframe."""

    source = source_timeframe.upper()
    target = target_timeframe.upper()
    if (source, target) not in _SUPPORTED_ROLLUPS:
        raise ValueError(f"unsupported canonical rollup: {source}->{target}")
    source_delta = TIMEFRAME_DELTAS[source]
    target_delta = TIMEFRAME_DELTAS[target]
    expected_count = int(target_delta / source_delta)

    grouped: dict[tuple[str, datetime], list[Candle]] = defaultdict(list)
    for candle in candles:
        if (
            candle.timeframe.upper() != source
            or not candle.complete
            or candle.provider_timestamp_semantics == "UNSPECIFIED"
        ):
            continue
        open_time = _utc(candle.open_time)
        close_time = _utc(candle.close_time)
        if close_time - open_time != source_delta:
            continue
        group_start = _align_to_period(open_time, int(target_delta.total_seconds() // 60))
        if open_time < group_start or close_time > group_start + target_delta:
            continue
        grouped[(candle.symbol.upper(), group_start)].append(candle)

    rolled: list[Candle] = []
    for (symbol, group_start), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: _utc(item.open_time))
        expected_opens = [group_start + index * source_delta for index in range(expected_count)]
        actual_opens = [_utc(item.open_time) for item in ordered]
        if len(ordered) != expected_count or actual_opens != expected_opens:
            continue
        if any(
            _utc(item.close_time) != expected + source_delta
            for item, expected in zip(ordered, expected_opens, strict=True)
        ):
            continue

        providers = {item.provider for item in ordered}
        provider = next(iter(providers)) if len(providers) == 1 else "wolf15_mixed_rollup"
        provider_feed = _rollup_feed(
            source_timeframe=source,
            target_timeframe=target,
            component_feeds={item.provider_feed for item in ordered},
        )
        rolled.append(
            Candle(
                symbol=symbol,
                timeframe=target,
                open_time=group_start,
                close_time=group_start + target_delta,
                open=ordered[0].open,
                high=max(item.high for item in ordered),
                low=min(item.low for item in ordered),
                close=ordered[-1].close,
                volume=sum(item.volume for item in ordered),
                tick_count=sum(item.tick_count for item in ordered),
                complete=True,
                provider=provider,
                provider_timestamp_semantics="CANONICAL_WINDOW",
                provider_timestamp=group_start,
                provider_feed=provider_feed,
            )
        )
    return rolled


__all__ = ["aggregate_contiguous_candles"]
