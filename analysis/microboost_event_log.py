"""Standalone MicroboostIntel log events.

Microboost pressure is derived from SignalThrottle, but it is a different
operational event.  This module emits and parses a dedicated log line so
service logs can show microboost state without forcing dashboards to infer it
from raw throttle rows.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_FIELD_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>\"[^\"]*\"|[^ ]+)")


@dataclass(frozen=True)
class MicroboostIntelEvent:
    cluster_id: str | None
    cluster_stage: str | None
    cluster_age_seconds: float
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
    source_clean_block_id: str | None
    source_pressure_block_id: str | None
    source_signal_throttle_start_utc: str | None
    source_signal_throttle_end_utc: str | None
    source_age_seconds: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dedupe_key(self) -> tuple[Any, ...]:
        return (
            self.cluster_id,
            self.symbol,
            self.phase_unpriced,
            self.phase_priced,
            self.action,
            self.final_direction,
            self.cluster_stage,
            self.requires_market_context,
            self.price_position,
            self.source_clean_block_id,
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


@dataclass(frozen=True)
class MicroboostTableEvent:
    cluster_id: str | None
    cluster_stage: str | None
    cluster_age_seconds: float
    symbol: str
    raw_direction: str | None
    window_local: str
    local_timezone: str
    start_utc: str | None
    end_utc: str | None
    effective_tick_count: int
    suppressed_tick_count: int
    duration_minutes: float
    effective_density_per_minute: float
    phase: str
    phase_unpriced: str
    phase_priced: str | None
    action: str
    requires_market_context: bool
    market_context_applied: bool
    score: int
    rank: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def dedupe_key(self) -> tuple[Any, ...]:
        return (
            self.cluster_id,
            self.symbol,
            self.phase,
            self.action,
            self.cluster_stage,
            self.requires_market_context,
        )


@dataclass(frozen=True)
class MicroboostTableLogRecord:
    timestamp: datetime
    severity: str
    message: str
    event: MicroboostTableEvent

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
    event_context_applied = _block_market_context_applied(latest)
    source_range = latest.get("source_signal_throttle_event_range")
    source_range = source_range if isinstance(source_range, dict) else {}

    return MicroboostIntelEvent(
        cluster_id=_optional_str(latest.get("cluster_id")),
        cluster_stage=_optional_str(latest.get("cluster_stage")),
        cluster_age_seconds=round(_coerce_float(latest.get("cluster_age_seconds"), 0.0), 3),
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
        market_context_applied=event_context_applied,
        price_position=_optional_str(latest.get("price_position") or snapshot.get("price_position")),
        m15_phase=_optional_str(snapshot.get("m15_phase")),
        h1_phase=_optional_str(snapshot.get("h1_phase")),
        price_at_signal_start=_optional_float(snapshot.get("price_at_signal_start")),
        price_at_5m_confirm=_optional_float(snapshot.get("price_at_5m_confirm")),
        price_at_signal_end=_optional_float(snapshot.get("price_at_signal_end")),
        end_utc=_optional_str(latest.get("end_utc")),
        source_clean_block_id=_optional_str(latest.get("source_clean_block_id")),
        source_pressure_block_id=_optional_str(latest.get("source_pressure_block_id")),
        source_signal_throttle_start_utc=_optional_str(source_range.get("start_utc")),
        source_signal_throttle_end_utc=_optional_str(source_range.get("end_utc")),
        source_age_seconds=_optional_float(latest.get("source_age_seconds")),
        reason=str(latest.get("reason") or summary.get("reason") or "microboost_detected"),
    )


def build_microboost_table_events(
    report: dict[str, Any],
    *,
    timezone_name: str = "Asia/Makassar",
    max_rows: int | None = None,
) -> list[MicroboostTableEvent]:
    summary = report.get("microboost_summary")
    if not isinstance(summary, dict):
        return []
    blocks = summary.get("blocks")
    if not isinstance(blocks, list):
        return []
    timezone_info, resolved_timezone_name = _local_timezone(timezone_name)
    rows: list[MicroboostTableEvent] = []

    ordered_blocks = sorted(
        (block for block in blocks if isinstance(block, dict)),
        key=lambda item: (
            str(item.get("symbol") or ""),
            _datetime_sort_key(item.get("start_utc")),
            _datetime_sort_key(item.get("end_utc")),
        ),
    )
    if max_rows is not None:
        ordered_blocks = ordered_blocks[: max(0, int(max_rows))]

    for rank, block in enumerate(ordered_blocks, start=1):
        symbol = str(block.get("symbol") or "").upper()
        if not symbol:
            continue
        phase_unpriced = str(block.get("phase_unpriced") or "UNKNOWN")
        phase_priced = _optional_str(block.get("phase_priced"))
        rows.append(
            MicroboostTableEvent(
                cluster_id=_optional_str(block.get("cluster_id")),
                cluster_stage=_optional_str(block.get("cluster_stage")),
                cluster_age_seconds=round(_coerce_float(block.get("cluster_age_seconds"), 0.0), 3),
                symbol=symbol,
                raw_direction=_optional_str(block.get("direction")),
                window_local=_window_local_text(
                    block.get("start_utc"),
                    block.get("end_utc"),
                    timezone_info=timezone_info,
                ),
                local_timezone=resolved_timezone_name,
                start_utc=_optional_str(block.get("start_utc")),
                end_utc=_optional_str(block.get("end_utc")),
                effective_tick_count=_coerce_int(block.get("effective_tick_count"), 0),
                suppressed_tick_count=_coerce_int(block.get("suppressed_tick_count"), 0),
                duration_minutes=round(_coerce_float(block.get("duration_minutes"), 0.0), 2),
                effective_density_per_minute=round(
                    _coerce_float(block.get("effective_density_per_minute"), 0.0),
                    2,
                ),
                phase=_phase_label(phase_unpriced, phase_priced, str(block.get("action") or "")),
                phase_unpriced=phase_unpriced,
                phase_priced=phase_priced,
                action=str(block.get("action") or "WAIT"),
                requires_market_context=bool(block.get("requires_market_context", True)),
                market_context_applied=_block_market_context_applied(block),
                score=_coerce_int(block.get("score"), 0),
                rank=rank,
                reason=str(block.get("reason") or "microboost_detected"),
            )
        )
    return rows


def _microboost_intel_full_payload_enabled() -> bool:
    """Heavy market-context fields are debug-only; the production line is lean."""
    return os.getenv("MICROBOOST_INTEL_FULL_PAYLOAD_ENABLED", "false").strip().lower() == "true"


def emit_microboost_intel(event: MicroboostIntelEvent | None) -> None:
    if event is None:
        return
    parts = [
        "[MicroboostIntel]",
        f"cluster_id={event.cluster_id or 'NONE'}",
        f"cluster_stage={event.cluster_stage or 'UNKNOWN'}",
        f"cluster_age={event.cluster_age_seconds:.3f}s",
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
        f"source_clean_block_id={event.source_clean_block_id or 'NONE'}",
        f"source_pressure_block_id={event.source_pressure_block_id or 'NONE'}",
        f"source_age={_number_text(event.source_age_seconds)}",
    ]
    # M15/H1 phase + price path belong to SignalWatch/SignalDecision, not the
    # Microboost timing line. Lean by default; full payload only under the debug
    # flag MICROBOOST_INTEL_FULL_PAYLOAD_ENABLED=true.
    if _microboost_intel_full_payload_enabled():
        parts.extend(
            [
                f"m15_phase={event.m15_phase or 'NONE'}",
                f"h1_phase={event.h1_phase or 'NONE'}",
                f"price_start={_number_text(event.price_at_signal_start)}",
                f"price_5m={_number_text(event.price_at_5m_confirm)}",
                f"price_end={_number_text(event.price_at_signal_end)}",
            ]
        )
    parts.extend(
        [
            f"end_utc={event.end_utc or 'NONE'}",
            f"source_start_utc={event.source_signal_throttle_start_utc or 'NONE'}",
            f"source_end_utc={event.source_signal_throttle_end_utc or 'NONE'}",
            # Pure-stage contract markers: Microboost is timing evidence only.
            "direction=UNRESOLVED",
            "valid_for_execution=false",
            "next_stage=SIGNAL_WATCH",
            f"reason={event.reason}",
        ]
    )
    sys.stdout.write(" ".join(parts) + "\n")
    sys.stdout.flush()


def emit_microboost_table_event(event: MicroboostTableEvent | None) -> None:
    if event is None:
        return
    parts = [
        "[MicroboostTable]",
        f"rank={event.rank}",
        f"cluster_id={event.cluster_id or 'NONE'}",
        f"cluster_stage={event.cluster_stage or 'UNKNOWN'}",
        f"cluster_age={event.cluster_age_seconds:.3f}s",
        f"symbol={event.symbol}",
        f"raw_direction={event.raw_direction or 'NONE'}",
        f"window_{_timezone_suffix(event.local_timezone)}={event.window_local}",
        f"timezone={event.local_timezone}",
        f"effective_ticks={event.effective_tick_count}",
        f"suppressed={event.suppressed_tick_count}",
        f"duration_minutes={event.duration_minutes:.2f}",
        f"effective_density={event.effective_density_per_minute:.2f}",
        f"phase={event.phase}",
        f"phase_unpriced={event.phase_unpriced}",
        f"phase_priced={event.phase_priced or 'NONE'}",
        f"action={event.action}",
        f"requires_market_context={_bool_text(event.requires_market_context)}",
        f"market_context_applied={_bool_text(event.market_context_applied)}",
        f"score={event.score}",
        f"start_utc={event.start_utc or 'NONE'}",
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
        cluster_id=_none_text(fields.get("cluster_id")),
        cluster_stage=_none_text(fields.get("cluster_stage")),
        cluster_age_seconds=_duration_seconds(fields.get("cluster_age")),
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
        source_clean_block_id=_none_text(fields.get("source_clean_block_id")),
        source_pressure_block_id=_none_text(fields.get("source_pressure_block_id")),
        source_signal_throttle_start_utc=_none_text(fields.get("source_start_utc")),
        source_signal_throttle_end_utc=_none_text(fields.get("source_end_utc")),
        source_age_seconds=_optional_float(fields.get("source_age")),
        reason=str(fields.get("reason") or "microboost_detected"),
    )
    return MicroboostLogRecord(
        timestamp=timestamp,
        severity=_extract_field(row, "severity", "level", default="info").lower(),
        message=message,
        event=event,
    )


def parse_microboost_table_row(row: dict[str, Any]) -> MicroboostTableLogRecord | None:
    message = _extract_message(row)
    if "[MicroboostTable]" not in message:
        return None
    timestamp = _parse_timestamp(_extract_field(row, "timestamp", "time", "@timestamp", "datetime"))
    if timestamp is None:
        return None
    fields = _parse_fields(message)
    symbol = str(fields.get("symbol") or "").upper()
    if not symbol:
        return None
    timezone_name = str(fields.get("timezone") or "Asia/Makassar")
    event = MicroboostTableEvent(
        cluster_id=_none_text(fields.get("cluster_id")),
        cluster_stage=_none_text(fields.get("cluster_stage")),
        cluster_age_seconds=_duration_seconds(fields.get("cluster_age")),
        symbol=symbol,
        raw_direction=_none_text(fields.get("raw_direction")),
        window_local=_extract_window_local(fields),
        local_timezone=timezone_name,
        start_utc=_none_text(fields.get("start_utc")),
        end_utc=_none_text(fields.get("end_utc")),
        effective_tick_count=_coerce_int(fields.get("effective_ticks"), 0),
        suppressed_tick_count=_coerce_int(fields.get("suppressed"), 0),
        duration_minutes=_coerce_float(fields.get("duration_minutes"), 0.0),
        effective_density_per_minute=_coerce_float(fields.get("effective_density"), 0.0),
        phase=str(fields.get("phase") or "unknown"),
        phase_unpriced=str(fields.get("phase_unpriced") or "UNKNOWN"),
        phase_priced=_none_text(fields.get("phase_priced")),
        action=str(fields.get("action") or "WAIT"),
        requires_market_context=_coerce_bool(fields.get("requires_market_context"), True),
        market_context_applied=_coerce_bool(fields.get("market_context_applied"), False),
        score=_coerce_int(fields.get("score"), 0),
        rank=_coerce_int(fields.get("rank"), 0),
        reason=str(fields.get("reason") or "microboost_detected"),
    )
    return MicroboostTableLogRecord(
        timestamp=timestamp,
        severity=_extract_field(row, "severity", "level", default="info").lower(),
        message=message,
        event=event,
    )


def parse_microboost_intel_rows(rows: list[dict[str, Any]]) -> list[MicroboostLogRecord]:
    records = [record for row in rows if (record := parse_microboost_intel_row(row)) is not None]
    return sorted(records, key=lambda item: item.timestamp)


def parse_microboost_table_rows(rows: list[dict[str, Any]]) -> list[MicroboostTableLogRecord]:
    records = [record for row in rows if (record := parse_microboost_table_row(row)) is not None]
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


def _parse_optional_timestamp(value: Any) -> datetime | None:
    return _parse_timestamp(str(value or ""))


def _datetime_sort_key(value: Any) -> str:
    parsed = _parse_optional_timestamp(value)
    return parsed.isoformat() if parsed else ""


def _parse_fields(message: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _FIELD_RE.finditer(message):
        value = match.group("value")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        fields[match.group("key")] = value
    return fields


def _local_timezone(timezone_name: str) -> tuple[ZoneInfo, str]:
    try:
        return ZoneInfo(timezone_name), timezone_name
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC"), "UTC"


def _window_local_text(start_utc: Any, end_utc: Any, *, timezone_info: ZoneInfo) -> str:
    start = _parse_optional_timestamp(start_utc)
    end = _parse_optional_timestamp(end_utc)
    if start is None or end is None:
        return "UNKNOWN"
    return f"{start.astimezone(timezone_info):%H:%M:%S}-{end.astimezone(timezone_info):%H:%M:%S}"


def _extract_window_local(fields: dict[str, str]) -> str:
    for key in fields:
        if key.startswith("window_"):
            return fields[key]
    return "UNKNOWN"


def _phase_label(phase_unpriced: str, phase_priced: str | None, action: str) -> str:
    priced = (phase_priced or "").upper()
    unpriced = phase_unpriced.upper()
    action = action.upper()
    if priced in {"TREND_CONTINUATION_MICROBOOST", "CONTINUATION_MICROBOOST"}:
        return "continuation"
    if priced == "CONFIRMATION_MICROBOOST":
        return "confirmation"
    if priced == "LATE_DENSE_PRESSURE" or action == "PROTECT_PROFIT":
        return "late_dense"
    if priced in {"BULLISH_PULLBACK_MICROBOOST", "BEARISH_PULLBACK_MICROBOOST"}:
        return "pullback_validation"
    if priced in {"EXHAUSTION_AT_RESISTANCE", "EXHAUSTION_AT_SUPPORT"}:
        return "exhaustion_warning"
    if priced in {"RESISTANCE_PRESSURE_WARNING", "SUPPORT_PRESSURE_WARNING"}:
        return "pressure_warning"
    if priced == "SUPPORT_BOUNCE_MICROBOOST":
        return "support_bounce"
    if priced == "RESISTANCE_REJECTION_MICROBOOST":
        return "resistance_rejection"
    if priced == "MINOR_PULLBACK_MICROBOOST":
        return "pullback"
    if priced == "COUNTER_BIAS_MICROBOOST":
        return "counter_bias"
    if priced == "ABSORPTION_WARNING":
        return "absorption_warning"
    if priced == "REVERSAL_WARNING":
        return "reversal_warning"
    if unpriced == "NEAR_TIMING_GATE_MICROBOOST":
        return "near_timing_gate"
    if unpriced == "REPEATED_MICROBOOST":
        return "repeated"
    if unpriced == "DENSE_MICROBOOST":
        return "dense"
    if unpriced == "IGNITION_MICROBOOST":
        return "ignition"
    return "microboost"


def _block_market_context_applied(block: dict[str, Any]) -> bool:
    snapshot = block.get("market_context_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    price_position = block.get("price_position") or snapshot.get("price_position")
    return (
        _optional_float(snapshot.get("price_at_signal_start")) is not None
        and _optional_float(snapshot.get("price_at_5m_confirm")) is not None
        and _optional_float(snapshot.get("price_at_signal_end")) is not None
        and _none_text(price_position) is not None
    )


def _timezone_suffix(timezone_name: str) -> str:
    if timezone_name == "Asia/Makassar":
        return "wita"
    return re.sub(r"[^a-z0-9]+", "_", timezone_name.lower()).strip("_") or "local"


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
