"""Offline audit helpers for SignalDecisionUpdateJSON exports.

This module is intentionally read-only. It parses exported log rows that already
contain lifecycle/decision JSON and summarizes pressure without treating it as
execution intent.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemas.direction import normalize_direction

DECISION_UPDATE_PREFIX = "[SignalDecisionUpdateJSON]"


@dataclass(frozen=True)
class DecisionUpdateAuditEvent:
    timestamp: datetime
    severity: str
    message: str
    payload: dict[str, Any]
    symbol: str
    signal_family: str | None
    status: str | None
    direction: str | None
    valid_for_execution: bool | None
    signal_valid_time_utc: str | None
    signal_valid_price: float | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


def parse_signal_decision_update_csv(path: str | Path) -> list[DecisionUpdateAuditEvent]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return parse_signal_decision_update_rows(csv.DictReader(handle))


def parse_signal_decision_update_rows(rows: Iterable[dict[str, Any]]) -> list[DecisionUpdateAuditEvent]:
    events: list[DecisionUpdateAuditEvent] = []
    for row in rows:
        event = parse_signal_decision_update_row(row)
        if event is not None:
            events.append(event)
    return sorted(events, key=lambda item: item.timestamp)


def parse_signal_decision_update_row(row: dict[str, Any]) -> DecisionUpdateAuditEvent | None:
    message = _extract_field(row, "message", "body", "log", "text")
    payload = _extract_payload(message)
    if payload is None:
        return None

    timestamp = _parse_timestamp(
        _extract_field(row, "timestamp", "time", "@timestamp", "datetime")
        or payload.get("signal_valid_time_utc")
        or payload.get("signal_valid_time")
    )
    if timestamp is None:
        return None

    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        return None

    return DecisionUpdateAuditEvent(
        timestamp=timestamp,
        severity=_extract_field(row, "severity", "level", default="info").lower(),
        message=message,
        payload=payload,
        symbol=symbol,
        signal_family=_optional_str(payload.get("signal_family") or payload.get("resolved_family")),
        status=_optional_str(payload.get("status")),
        direction=_payload_direction(payload),
        valid_for_execution=_optional_bool(payload.get("valid_for_execution")),
        signal_valid_time_utc=_optional_str(payload.get("signal_valid_time_utc") or payload.get("signal_valid_time")),
        signal_valid_price=_optional_float(payload.get("signal_valid_price") or payload.get("entry_reference_price")),
    )


def summarize_decision_updates(events: Iterable[DecisionUpdateAuditEvent]) -> dict[str, Any]:
    ordered = list(events)
    family_counts = Counter(event.signal_family or "UNKNOWN" for event in ordered)
    status_counts = Counter(event.status or "UNKNOWN" for event in ordered)
    symbol_direction_counts = Counter(
        (event.symbol, event.direction or "NONE")
        for event in ordered
    )
    valid_for_execution_true = sum(event.valid_for_execution is True for event in ordered)
    return {
        "total_events": len(ordered),
        "signal_json_final": 0,
        "valid_for_execution_true": valid_for_execution_true,
        "family_counts": dict(family_counts.most_common()),
        "status_counts": dict(status_counts.most_common()),
        "symbol_direction_counts": {
            f"{symbol}:{direction}": count
            for (symbol, direction), count in symbol_direction_counts.most_common()
        },
        "event_flood": detect_event_flood(ordered),
    }


def rank_symbol_direction_pressure(events: Iterable[DecisionUpdateAuditEvent]) -> list[dict[str, Any]]:
    counts = Counter((event.symbol, event.direction or "NONE") for event in events)
    return [
        {"symbol": symbol, "direction": direction, "count": int(count)}
        for (symbol, direction), count in counts.most_common()
    ]


def extract_status_family_distribution(events: Iterable[DecisionUpdateAuditEvent]) -> dict[str, dict[str, int]]:
    ordered = list(events)
    return {
        "family_counts": dict(Counter(event.signal_family or "UNKNOWN" for event in ordered).most_common()),
        "status_counts": dict(Counter(event.status or "UNKNOWN" for event in ordered).most_common()),
    }


def detect_event_flood(
    events: Iterable[DecisionUpdateAuditEvent],
    *,
    min_count: int = 100,
    min_share: float = 0.50,
    limit: int = 10,
) -> list[dict[str, Any]]:
    ordered = list(events)
    total = max(1, len(ordered))
    counts = Counter((event.symbol, event.direction or "NONE") for event in ordered)
    floods: list[dict[str, Any]] = []
    for (symbol, direction), count in counts.most_common(limit):
        share = count / total
        if count >= min_count or share >= min_share:
            floods.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "count": int(count),
                    "share": round(share, 4),
                }
            )
    return floods


def _extract_payload(message: str) -> dict[str, Any] | None:
    if DECISION_UPDATE_PREFIX not in message:
        return None
    start = message.find("{", message.find(DECISION_UPDATE_PREFIX))
    if start < 0:
        return None
    try:
        payload = json.loads(message[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("event") or "").lower() not in {"", "signal_decision_update_json"}:
        return None
    return payload


def _payload_direction(payload: dict[str, Any]) -> str | None:
    for key in ("raw_direction", "candidate_direction", "watch_direction", "validated_direction", "final_direction"):
        direction = normalize_direction(_optional_str(payload.get(key)), None)
        if direction in {"BUY", "SELL"}:
            return direction
    source_verdict = _optional_str(payload.get("source_verdict") or payload.get("verdict"))
    return normalize_direction(None, source_verdict)


def _extract_field(row: dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return default


def _parse_timestamp(value: Any) -> datetime | None:
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


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DecisionUpdateAuditEvent",
    "detect_event_flood",
    "extract_status_family_distribution",
    "parse_signal_decision_update_csv",
    "parse_signal_decision_update_row",
    "parse_signal_decision_update_rows",
    "rank_symbol_direction_pressure",
    "summarize_decision_updates",
]
