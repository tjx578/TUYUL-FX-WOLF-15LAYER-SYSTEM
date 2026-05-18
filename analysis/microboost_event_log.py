"""Standalone MicroboostIntel log events.

Microboost pressure is derived from SignalThrottle, but it is a different
operational event.  This module emits and parses a dedicated log line so
service logs can show microboost state without forcing dashboards to infer it
from raw throttle rows.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any

_FIELD_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\"[^\"]*\"|[^ ]+)")


@dataclass(frozen=True)
class MicroboostIntelEvent:
    symbol: str
    raw_direction: str | None
    final_direction: str
    phase_unpriced: str
    phase_priced: str | None
    action: str
    event_count: int
    effective_tick_count: int
    suppressed_tick_count: int
    effective_density_per_minute: float
    duration_seconds: float
    requires_market_context: bool
    market_context_applied: bool
    price_position: str | None
    m15_phase: str | None
    h1_phase: str | None
    price_at_signal_start: float | None
    price_at_5m_confirm: float | None
    price_at_signal_end: float | None
    end_utc: str | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dedupe_key(self) -> tuple[Any, ...]:
        return (
            self.symbol,
            self.end_utc,
            self.phase_unpriced,
            self.phase_priced,
            self.action,
            self.effective_tick_count,
            self.requires_market_context,
        )


@dataclass(frozen=True)
class MicroboostLogRecord:
    timestamp: datetime
    severity: str
    message: str
    event: MicroboostIntelEvent

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        return payload


def build_microboost_intel_event(report: dict[str, Any]) -> MicroboostIntelEvent | None:
    summary = report.get("microboost_summary")
    if not isinstance(summary, dict):
        return None
    latest = summary.get("latest")
    if not isinstance(latest, dict):
        return None
    if _coerce_int(summary.get("count_total"), 0) <= 0:
        return None

    validation = latest.get("market_context_validation")
    validation = validation if isinstance(validation, dict) else {}
    snapshot = latest.get("market_context_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    return MicroboostIntelEvent(
        symbol=str(latest.get("symbol") or "").upper(),
        raw_direction=_optional_str(latest.get("direction")),
        final_direction=str(validation.get("final_direction") or "WAIT"),
        phase_unpriced=str(latest.get("phase_unpriced") or "UNKNOWN"),
        phase_priced=_optional_str(latest.get("phase_priced")),
        action=str(latest.get("action") or summary.get("action") or "WAIT"),
        event_count=_coerce_int(latest.get("event_count"), 0),
        effective_tick_count=_coerce_int(latest.get("effective_tick_count"), 0),
        suppressed_tick_count=_coerce_int(latest.get("suppressed_tick_count"), 0),
        effective_density_per_minute=round(_coerce_float(latest.get("effective_density_per_minute"), 0.0), 2),
        duration_seconds=round(_coerce_float(latest.get("duration_seconds"), 0.0), 3),
        requires_market_context=bool(latest.get("requires_market_context", True)),
        market_context_applied=bool(summary.get("market_context_applied", False)),
        price_position=_optional_str(latest.get("price_position") or snapshot.get("price_position")),
        m15_phase=_optional_str(snapshot.get("m15_phase")),
        h1_phase=_optional_str(snapshot.get("h1_phase")),
        price_at_signal_start=_optional_float(snapshot.get("price_at_signal_start")),
        price_at_5m_confirm=_optional_float(snapshot.get("price_at_5m_confirm")),
        price_at_signal_end=_optional_float(snapshot.get("price_at_signal_end")),
        end_utc=_optional_str(latest.get("end_utc")),
        reason=str(latest.get("reason") or summary.get("reason") or "microboost_detected"),
    )


def emit_microboost_intel(event: MicroboostIntelEvent | None) -> None:
    if event is None:
        return
    parts = [
        "[MicroboostIntel]",
        f"symbol={event.symbol}",
        f"raw_direction={event.raw_direction or 'NONE'}",
        f"final_direction={event.final_direction}",
        f"phase_unpriced={event.phase_unpriced}",
        f"phase_priced={event.phase_priced or 'NONE'}",
        f"action={event.action}",
        f"events={event.event_count}",
        f"effective_ticks={event.effective_tick_count}",
        f"suppressed={event.suppressed_tick_count}",
        f"effective_density={event.effective_density_per_minute:.2f}",
        f"duration={event.duration_seconds:.3f}s",
        f"requires_market_context={_bool_text(event.requires_market_context)}",
        f"market_context_applied={_bool_text(event.market_context_applied)}",
        f"price_position={event.price_position or 'NONE'}",
        f"m15_phase={event.m15_phase or 'NONE'}",
        f"h1_phase={event.h1_phase or 'NONE'}",
        f"price_start={_number_text(event.price_at_signal_start)}",
        f"price_5m={_number_text(event.price_at_5m_confirm)}",
        f"price_end={_number_text(event.price_at_signal_end)}",
        f"end_utc={event.end_utc or 'NONE'}",
        f"reason={event.reason}",
    ]
    sys.stdout.write(" ".join(parts) + "\n")
    sys.stdout.flush()


def parse_microboost_intel_row(row: dict[str, Any]) -> MicroboostLogRecord | None:
    message = _extract_message(row)
    if "[MicroboostIntel]" not in message:
        return None
    timestamp = _parse_timestamp(_extract_field(row, "timestamp", "time", "@timestamp", "datetime"))
    if timestamp is None:
        return None
    fields = _parse_fields(message)
    symbol = str(fields.get("symbol") or "").upper()
    if not symbol:
        return None

    event = MicroboostIntelEvent(
        symbol=symbol,
        raw_direction=_none_text(fields.get("raw_direction")),
        final_direction=str(fields.get("final_direction") or "WAIT"),
        phase_unpriced=str(fields.get("phase_unpriced") or "UNKNOWN"),
        phase_priced=_none_text(fields.get("phase_priced")),
        action=str(fields.get("action") or "WAIT"),
        event_count=_coerce_int(fields.get("events"), 0),
        effective_tick_count=_coerce_int(fields.get("effective_ticks"), 0),
        suppressed_tick_count=_coerce_int(fields.get("suppressed"), 0),
        effective_density_per_minute=_coerce_float(fields.get("effective_density"), 0.0),
        duration_seconds=_duration_seconds(fields.get("duration")),
        requires_market_context=_coerce_bool(fields.get("requires_market_context"), True),
        market_context_applied=_coerce_bool(fields.get("market_context_applied"), False),
        price_position=_none_text(fields.get("price_position")),
        m15_phase=_none_text(fields.get("m15_phase")),
        h1_phase=_none_text(fields.get("h1_phase")),
        price_at_signal_start=_optional_float(fields.get("price_start")),
        price_at_5m_confirm=_optional_float(fields.get("price_5m")),
        price_at_signal_end=_optional_float(fields.get("price_end")),
        end_utc=_none_text(fields.get("end_utc")),
        reason=str(fields.get("reason") or "microboost_detected"),
    )
    return MicroboostLogRecord(
        timestamp=timestamp,
        severity=_extract_field(row, "severity", "level", default="info").lower(),
        message=message,
        event=event,
    )


def parse_microboost_intel_rows(rows: list[dict[str, Any]]) -> list[MicroboostLogRecord]:
    records = [record for row in rows if (record := parse_microboost_intel_row(row)) is not None]
    return sorted(records, key=lambda item: item.timestamp)


def _extract_message(row: dict[str, Any]) -> str:
    return _extract_field(row, "message", "body", "log", "text")


def _extract_field(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        return _extract_json_message(text) if key == "message" else text
    return default


def _extract_json_message(text: str) -> str:
    if not text.startswith("{"):
        return text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    nested = payload.get("message")
    return str(nested) if nested is not None else text


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_fields(message: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(message):
        value = match.group("value")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[match.group("key")] = value
    return fields


def _coerce_int(value: Any, default: int) -> int:
    if isinstance(value, Real) and not isinstance(value, bool):
        return max(0, int(float(value)))
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float) -> float:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip().removesuffix("s")
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.upper() in {"", "NONE", "NULL", "?"}:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _none_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"NONE", "NULL", "?"}:
        return None
    return text


def _duration_seconds(value: Any) -> float:
    return _coerce_float(value, 0.0)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _number_text(value: float | None) -> str:
    if value is None:
        return "NONE"
    return f"{value:.8f}".rstrip("0").rstrip(".")
