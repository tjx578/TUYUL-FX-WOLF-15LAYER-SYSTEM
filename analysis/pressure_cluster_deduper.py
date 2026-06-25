"""Pressure cluster deduplication for audit and promotion scoring.

This layer collapses repeated telemetry into market-pressure clusters. It does
not suppress logs, emit orders, or change SignalJSON execution gates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from schemas.direction import normalize_direction

ClusterKey = tuple[str, str, str, str, str, str]


@dataclass(frozen=True)
class PressureCluster:
    key: ClusterKey
    symbol: str
    direction: str
    signal_family: str
    status: str
    m15_bucket: str
    price_bucket: str
    raw_event_count: int
    first_timestamp_utc: str | None
    last_timestamp_utc: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def price_bucket(price: float, pip_size: float, bucket_pips: int = 5) -> int:
    if pip_size <= 0:
        raise ValueError("pip_size must be positive")
    if bucket_pips <= 0:
        raise ValueError("bucket_pips must be positive")
    return int(round(float(price) / (float(pip_size) * int(bucket_pips))))


def infer_pip_size(symbol: str, explicit: float | None = None) -> float:
    if explicit is not None and explicit > 0:
        return float(explicit)
    normalized = str(symbol or "").upper()
    if normalized.endswith("JPY"):
        return 0.01
    if normalized.startswith(("XAU", "XAG")):
        return 0.1
    return 0.0001


def m15_bucket(value: Any) -> str:
    timestamp = _coerce_datetime(value)
    if timestamp is None:
        return "UNKNOWN_M15"
    bucket_minute = (timestamp.minute // 15) * 15
    bucket = timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
    return bucket.isoformat()


def cluster_key(event: Any, *, bucket_pips: int = 5) -> ClusterKey:
    symbol = str(_get(event, "symbol") or "").upper() or "UNKNOWN"
    direction = _event_direction(event) or "NONE"
    family = str(_get(event, "signal_family") or _get(event, "resolved_family") or "UNKNOWN").upper()
    status = str(_get(event, "status") or _get(event, "event_type") or "UNKNOWN").upper()
    time_value = _get(event, "signal_valid_time_utc") or _get(event, "timestamp")
    price = _optional_float(_get(event, "signal_valid_price") or _get(event, "entry_reference_price"))
    pip = infer_pip_size(symbol, _optional_float(_get(event, "pip_size") or _get(event, "pip_value")))
    price_part = "UNKNOWN_PRICE" if price is None else str(price_bucket(price, pip, bucket_pips=bucket_pips))
    return (symbol, direction, family, status, m15_bucket(time_value), price_part)


def dedupe_pressure_clusters(
    events: Iterable[Any],
    *,
    bucket_pips: int = 5,
) -> list[PressureCluster]:
    grouped: dict[ClusterKey, list[Any]] = defaultdict(list)
    for event in events:
        grouped[cluster_key(event, bucket_pips=bucket_pips)].append(event)

    clusters: list[PressureCluster] = []
    for key, members in grouped.items():
        timestamps = [_coerce_datetime(_get(member, "timestamp") or _get(member, "signal_valid_time_utc")) for member in members]
        timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
        first = min(timestamps).isoformat() if timestamps else None
        last = max(timestamps).isoformat() if timestamps else None
        symbol, direction, family, status, bucket, bucket_price = key
        clusters.append(
            PressureCluster(
                key=key,
                symbol=symbol,
                direction=direction,
                signal_family=family,
                status=status,
                m15_bucket=bucket,
                price_bucket=bucket_price,
                raw_event_count=len(members),
                first_timestamp_utc=first,
                last_timestamp_utc=last,
            )
        )
    return sorted(clusters, key=lambda item: (item.raw_event_count, item.symbol, item.direction), reverse=True)


def summarize_pressure_clusters(
    events: Iterable[Any],
    *,
    bucket_pips: int = 5,
) -> dict[str, Any]:
    ordered = list(events)
    clusters = dedupe_pressure_clusters(ordered, bucket_pips=bucket_pips)
    raw_count = len(ordered)
    deduped_count = len(clusters)
    duplicate_penalty = 0.0 if raw_count <= 0 else max(0.0, 1.0 - (deduped_count / raw_count))
    by_symbol_direction: dict[str, dict[str, int]] = {}
    for cluster in clusters:
        key = f"{cluster.symbol}:{cluster.direction}"
        stats = by_symbol_direction.setdefault(key, {"raw_event_count": 0, "deduped_cluster_count": 0})
        stats["raw_event_count"] += cluster.raw_event_count
        stats["deduped_cluster_count"] += 1
    for stats in by_symbol_direction.values():
        raw = max(1, stats["raw_event_count"])
        deduped = stats["deduped_cluster_count"]
        stats["duplicate_penalty"] = round(max(0.0, 1.0 - (deduped / raw)), 4)
        stats["cluster_pressure_score"] = min(100, int(round(deduped * 3 + min(raw, 50) * 0.5)))
    return {
        "raw_event_count": raw_count,
        "deduped_cluster_count": deduped_count,
        "duplicate_penalty": round(duplicate_penalty, 4),
        "bucket_pips": int(bucket_pips),
        "by_symbol_direction": dict(sorted(by_symbol_direction.items())),
        "top_clusters": [cluster.to_dict() for cluster in clusters[:10]],
    }


def _event_direction(event: Any) -> str | None:
    for key in ("direction", "raw_direction", "candidate_direction", "watch_direction", "validated_direction"):
        direction = normalize_direction(_optional_str(_get(event, key)), None)
        if direction in {"BUY", "SELL"}:
            return direction
    return normalize_direction(None, _optional_str(_get(event, "verdict") or _get(event, "source_verdict")))


def _get(event: Any, key: str) -> Any:
    if isinstance(event, Mapping):
        return event.get(key)
    return getattr(event, key, None)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "ClusterKey",
    "PressureCluster",
    "cluster_key",
    "dedupe_pressure_clusters",
    "infer_pip_size",
    "m15_bucket",
    "price_bucket",
    "summarize_pressure_clusters",
]
