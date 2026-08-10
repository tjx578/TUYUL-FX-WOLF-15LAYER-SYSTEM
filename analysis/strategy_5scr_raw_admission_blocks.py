"""Canonical raw-only block population for Strategy 5S-CR PairAdmission.

This module deliberately does not reuse advisory pressure blocks.  CANARY and
derived pressure state rows may remain useful to observability, but they cannot
change an admission block's interval, count, gap, or lineage.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_RAW_AUTHORITY_STREAMS = frozenset({"RAW_THROTTLED", "ALLOWED", "DOWNGRADED"})
_RAW_AUTHORITY_EVENT_TYPES = frozenset({"THROTTLED", "ALLOWED", "DOWNGRADED_TO_HOLD"})


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, str) and value.strip():
        try:
            resolved = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        return None
    return resolved.astimezone(UTC)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def raw_signal_throttle_event_id(event: Any) -> str:
    """Return the stable identity used for raw-ledger replay deduplication."""

    identity = {
        "timestamp": _utc(_value(event, "timestamp")),
        "symbol": str(_value(event, "symbol") or "").upper(),
        "event_type": _value(event, "event_type"),
        "source_stream": _value(event, "source_stream"),
        "pressure_source": _value(event, "pressure_source"),
        "verdict": _value(event, "verdict"),
        "direction": _value(event, "direction"),
        "suppressed": _value(event, "suppressed", 0),
        "scanner_cycle_id": _value(event, "scanner_cycle_id"),
        "deployment_id": _value(event, "deployment_id"),
    }
    return "sha256:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()


def is_raw_signal_throttle_authority(event: Any) -> bool:
    """Return whether one event may participate in canonical PairAdmission."""

    return (
        _value(event, "eligible_for_pressure_block") is not False
        and str(_value(event, "pressure_source") or "").strip() == "SignalThrottle"
        and str(_value(event, "source_stream") or "").strip().upper() in _RAW_AUTHORITY_STREAMS
        and str(_value(event, "event_type") or "").strip().upper() in _RAW_AUTHORITY_EVENT_TYPES
        and _utc(_value(event, "timestamp")) is not None
    )


def _direction(event: Any) -> str | None:
    direct = str(_value(event, "direction") or "").strip().upper()
    if direct in {"BUY", "SELL"}:
        return direct
    verdict = str(_value(event, "verdict") or "").strip().upper()
    if verdict.endswith("_BUY"):
        return "BUY"
    if verdict.endswith("_SELL"):
        return "SELL"
    return None


def _effective_ticks(event: Any) -> int:
    try:
        suppressed = int(_value(event, "suppressed", 0) or 0)
    except (TypeError, ValueError):
        suppressed = 0
    return 1 + max(0, suppressed)


@dataclass(frozen=True)
class RawAdmissionBlock:
    """One deterministic, consecutive raw-authority block."""

    raw_block_id: str
    symbol: str
    start: datetime
    end: datetime
    events: int
    duration_seconds: float
    density_per_minute: float
    max_gap_seconds: float
    direction: str | None
    effective_ticks: int
    deployment_ids: tuple[str, ...]
    scanner_cycle_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    cross_symbol_interruption_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_block_id": self.raw_block_id,
            "symbol": self.symbol,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "events": self.events,
            "duration_seconds": self.duration_seconds,
            "density_per_minute": self.density_per_minute,
            "max_gap_seconds": self.max_gap_seconds,
            "direction": self.direction,
            "effective_ticks": self.effective_ticks,
            "deployment_ids": list(self.deployment_ids),
            "scanner_cycle_ids": list(self.scanner_cycle_ids),
            "source_event_ids": list(self.source_event_ids),
            "cross_symbol_interruption_count": self.cross_symbol_interruption_count,
            "ledger_scope": "GLOBAL_SIGNAL_THROTTLE_RAW_LEDGER",
            "authority_population": "RAW_SIGNAL_THROTTLE_ONLY",
            "execution_authority": False,
        }


@dataclass(frozen=True)
class RawAdmissionPopulation:
    """Raw events and blocks selected before any advisory block is built."""

    events: tuple[Any, ...]
    blocks: tuple[RawAdmissionBlock, ...]
    input_event_count: int
    skipped_non_authority_count: int
    duplicate_event_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "input_event_count": self.input_event_count,
            "raw_authority_event_count": len(self.events),
            "skipped_non_authority_event_count": self.skipped_non_authority_count,
            "duplicate_raw_event_count": self.duplicate_event_count,
            "raw_block_count": len(self.blocks),
            "population_status": (
                "RAW_AUTHORITY_CANDIDATES_AVAILABLE" if self.blocks else "NO_RAW_AUTHORITY_CANDIDATE"
            ),
            "authority_population": "RAW_SIGNAL_THROTTLE_ONLY",
            "cross_symbol_policy": "CROSS_SYMBOL_EVENT_FINALIZES_BLOCK",
            "gap_boundary_policy": "GAP_GT_MAX_FINALIZES_BLOCK",
            "duplicate_event_policy": "IGNORE_DUPLICATE_STABLE_RAW_ID",
            "execution_authority": False,
        }


def _make_block(events: list[Any], *, interrupted: bool) -> RawAdmissionBlock:
    ordered = sorted(events, key=lambda event: (_utc(_value(event, "timestamp")), raw_signal_throttle_event_id(event)))
    timestamps = tuple(_utc(_value(event, "timestamp")) for event in ordered)
    assert all(timestamp is not None for timestamp in timestamps)
    concrete_times = tuple(timestamp for timestamp in timestamps if timestamp is not None)
    start = concrete_times[0]
    end = concrete_times[-1]
    event_ids = tuple(raw_signal_throttle_event_id(event) for event in ordered)
    gaps = tuple(
        (concrete_times[index] - concrete_times[index - 1]).total_seconds() for index in range(1, len(concrete_times))
    )
    directions = {_direction(event) for event in ordered if _direction(event) is not None}
    deployments = tuple(
        sorted(
            {
                str(_value(event, "deployment_id") or "").strip()
                for event in ordered
                if str(_value(event, "deployment_id") or "").strip()
            }
        )
    )
    cycles = tuple(
        dict.fromkeys(
            str(_value(event, "scanner_cycle_id") or "").strip()
            for event in ordered
            if str(_value(event, "scanner_cycle_id") or "").strip()
        )
    )
    identity = {
        "deployment_id": deployments[0] if len(deployments) == 1 else list(deployments),
        "symbol": str(_value(ordered[0], "symbol") or "").upper(),
        "direction": next(iter(directions)) if len(directions) == 1 else "UNRESOLVED",
        "first_source_event_id": event_ids[0],
        "started_at_utc": start,
    }
    raw_block_id = "5scr-raw-block:" + hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:32]
    duration = (end - start).total_seconds()
    effective_ticks = sum(_effective_ticks(event) for event in ordered)
    return RawAdmissionBlock(
        raw_block_id=raw_block_id,
        symbol=str(_value(ordered[0], "symbol") or "").upper(),
        start=start,
        end=end,
        events=len(ordered),
        duration_seconds=duration,
        density_per_minute=round(effective_ticks / max(duration / 60.0, 1.0), 6),
        max_gap_seconds=max(gaps, default=0.0),
        direction=next(iter(directions)) if len(directions) == 1 else None,
        effective_ticks=effective_ticks,
        deployment_ids=deployments,
        scanner_cycle_ids=cycles,
        source_event_ids=event_ids,
        cross_symbol_interruption_count=1 if interrupted else 0,
    )


def build_raw_admission_population(
    events: Iterable[Any],
    *,
    max_gap_seconds: float = 300.0,
) -> RawAdmissionPopulation:
    """Build raw blocks before advisory/CANARY aggregation can affect them.

    The ledger is globally ordered.  A symbol or resolved-direction change
    finalizes the active block.  A gap exactly equal to the maximum remains in
    the block; only a strictly larger gap finalizes it.
    """

    source = tuple(events)
    candidates = sorted(
        (event for event in source if is_raw_signal_throttle_authority(event)),
        key=lambda event: (_utc(_value(event, "timestamp")), raw_signal_throttle_event_id(event)),
    )
    unique: list[Any] = []
    seen: set[str] = set()
    duplicates = 0
    for event in candidates:
        event_id = raw_signal_throttle_event_id(event)
        if event_id in seen:
            duplicates += 1
            continue
        seen.add(event_id)
        unique.append(event)

    blocks: list[RawAdmissionBlock] = []
    current: list[Any] = []
    for event in unique:
        if not current:
            current = [event]
            continue
        previous = current[-1]
        previous_time = _utc(_value(previous, "timestamp"))
        current_time = _utc(_value(event, "timestamp"))
        assert previous_time is not None and current_time is not None
        symbol_changed = str(_value(previous, "symbol") or "").upper() != str(_value(event, "symbol") or "").upper()
        prior_direction = _direction(previous)
        next_direction = _direction(event)
        direction_changed = (
            prior_direction is not None and next_direction is not None and prior_direction != next_direction
        )
        gap_exceeded = (current_time - previous_time).total_seconds() > max_gap_seconds
        deployment_changed = str(_value(previous, "deployment_id") or "") != str(_value(event, "deployment_id") or "")
        if symbol_changed or direction_changed or gap_exceeded or deployment_changed:
            blocks.append(_make_block(current, interrupted=symbol_changed))
            current = [event]
        else:
            current.append(event)
    if current:
        blocks.append(_make_block(current, interrupted=False))

    return RawAdmissionPopulation(
        events=tuple(unique),
        blocks=tuple(blocks),
        input_event_count=len(source),
        skipped_non_authority_count=len(source) - len(candidates),
        duplicate_event_count=duplicates,
    )


__all__ = [
    "RawAdmissionBlock",
    "RawAdmissionPopulation",
    "build_raw_admission_population",
    "is_raw_signal_throttle_authority",
    "raw_signal_throttle_event_id",
]
