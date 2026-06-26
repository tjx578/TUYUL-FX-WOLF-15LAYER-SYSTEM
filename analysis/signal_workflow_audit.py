"""Offline workflow audit for SignalThrottle/Microboost/Watch logs.

The parser joins exported CSV rows across lifecycle channels by ``cluster_id``
and summarizes direction conflicts without treating watch/decision telemetry as
execution intent.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from schemas.direction import normalize_direction

CHANNELS = (
    "SignalIntelligenceFlagSnapshot",
    "SignalThrottle",
    "SignalThrottleIntel",
    "MicroboostIntel",
    "MicroboostTable",
    "MicroboostWatchDiagnostic",
    "MicroboostShadowDiagnostic",
    "SignalPressureStateJSON",
    "SignalWatchJSON",
    "SignalDecisionUpdateJSON",
    "SignalExecutionGateJSON",
    "SignalJSON",
)
_CHANNEL_RE = re.compile(r"\[(?P<channel>" + "|".join(CHANNELS) + r")\]")


@dataclass(frozen=True)
class SignalWorkflowAuditEvent:
    timestamp: datetime | None
    channel: str
    message: str
    payload: dict[str, Any]
    deployment_id: str | None
    symbol: str | None
    cluster_id: str | None
    pending_decision_id: str | None
    signal_family: str | None
    status: str | None
    raw_direction: str | None
    candidate_direction: str | None
    watch_direction: str | None
    final_direction: str | None
    valid_for_execution: bool | None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat() if self.timestamp else None
        return data


def parse_signal_workflow_csv(path: str | Path, *, dedupe: bool = True) -> list[SignalWorkflowAuditEvent]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return parse_signal_workflow_rows(rows, dedupe=dedupe)


def parse_signal_workflow_rows(
    rows: Iterable[dict[str, Any]],
    *,
    dedupe: bool = True,
) -> list[SignalWorkflowAuditEvent]:
    events: list[SignalWorkflowAuditEvent] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for row in rows:
        if dedupe:
            key = tuple(sorted((str(name), str(value)) for name, value in row.items()))
            if key in seen:
                continue
            seen.add(key)
        event = parse_signal_workflow_row(row)
        if event is not None:
            events.append(event)
    return sorted(events, key=lambda item: item.timestamp or datetime.min.replace(tzinfo=UTC))


def parse_signal_workflow_row(row: Mapping[str, Any]) -> SignalWorkflowAuditEvent | None:
    message = _extract_field(row, "message", "body", "log", "text")
    match = _CHANNEL_RE.search(message)
    if match is None:
        return None
    channel = match.group("channel")
    payload = _extract_payload(message, channel)
    tags = _json_dict(_extract_field(row, "tags"))
    timestamp = _parse_timestamp(
        _extract_field(row, "timestamp", "time", "@timestamp", "datetime")
        or payload.get("signal_valid_time_utc")
        or payload.get("signal_valid_time")
    )
    return SignalWorkflowAuditEvent(
        timestamp=timestamp,
        channel=channel,
        message=message,
        payload=payload,
        deployment_id=_optional_text(tags.get("deployment") or payload.get("deployment_id")),
        symbol=_optional_text(payload.get("symbol") or _extract_symbol(message)),
        cluster_id=_optional_text(payload.get("cluster_id")),
        pending_decision_id=_optional_text(payload.get("pending_decision_id")),
        signal_family=_optional_text(payload.get("signal_family") or payload.get("resolved_family")),
        status=_optional_text(payload.get("status") or payload.get("phase") or payload.get("phase_priced")),
        raw_direction=normalize_direction(_optional_text(payload.get("raw_direction") or payload.get("direction")), None),
        candidate_direction=normalize_direction(_optional_text(payload.get("candidate_direction")), None),
        watch_direction=normalize_direction(_optional_text(payload.get("watch_direction")), None),
        final_direction=normalize_direction(_optional_text(payload.get("final_direction")), None),
        valid_for_execution=_optional_bool(payload.get("valid_for_execution")),
    )


def summarize_signal_workflow(events: Iterable[SignalWorkflowAuditEvent]) -> dict[str, Any]:
    ordered = list(events)
    channel_counts = Counter(event.channel for event in ordered)
    deployment_counts = Counter(event.deployment_id or "UNKNOWN" for event in ordered)
    cluster_groups = _cluster_groups(ordered)
    conflict_counts = Counter()
    raw_buy_candidate_sell = Counter()
    for event in ordered:
        candidate = event.candidate_direction or event.watch_direction
        if event.channel not in {"SignalWatchJSON", "SignalDecisionUpdateJSON"}:
            continue
        if event.raw_direction in {"BUY", "SELL"} and candidate in {"BUY", "SELL"}:
            if event.raw_direction != candidate and event.symbol:
                conflict_counts[event.symbol] += 1
            if event.raw_direction == "BUY" and candidate == "SELL" and event.symbol:
                raw_buy_candidate_sell[event.symbol] += 1

    return {
        "total_events": len(ordered),
        "channel_counts": dict(channel_counts.most_common()),
        "deployment_counts": dict(deployment_counts.most_common()),
        "signal_json_final": sum(_is_final_signal(event) for event in ordered),
        "valid_for_execution_true": sum(event.valid_for_execution is True for event in ordered),
        "direction_conflicts_by_symbol": dict(conflict_counts.most_common()),
        "raw_buy_candidate_sell_by_symbol": dict(raw_buy_candidate_sell.most_common()),
        "cluster_summary": _cluster_summary(cluster_groups),
    }


def _cluster_groups(events: list[SignalWorkflowAuditEvent]) -> dict[str, list[SignalWorkflowAuditEvent]]:
    groups: dict[str, list[SignalWorkflowAuditEvent]] = defaultdict(list)
    for event in events:
        key = event.cluster_id or event.pending_decision_id
        if key:
            groups[str(key)].append(event)
    return groups


def _cluster_summary(groups: dict[str, list[SignalWorkflowAuditEvent]]) -> dict[str, Any]:
    watch_clusters = 0
    watch_without_microboost = 0
    decision_with_watch = 0
    decision_without_watch = 0
    for members in groups.values():
        channels = {event.channel for event in members}
        has_watch = "SignalWatchJSON" in channels
        has_decision = "SignalDecisionUpdateJSON" in channels
        has_microboost = "MicroboostIntel" in channels or "MicroboostTable" in channels
        if has_watch:
            watch_clusters += 1
            if not has_microboost:
                watch_without_microboost += 1
        if has_decision:
            if has_watch:
                decision_with_watch += 1
            else:
                decision_without_watch += 1
    return {
        "cluster_count": len(groups),
        "watch_clusters": watch_clusters,
        "watch_clusters_without_microboost": watch_without_microboost,
        "decision_clusters_with_watch": decision_with_watch,
        "decision_clusters_without_watch": decision_without_watch,
    }


def _extract_payload(message: str, channel: str) -> dict[str, Any]:
    start = message.find("{", message.find(f"[{channel}]"))
    if start < 0:
        return _kv_payload(message)
    try:
        payload = json.loads(message[start:])
    except json.JSONDecodeError:
        return _kv_payload(message)
    return payload if isinstance(payload, dict) else {}


def _kv_payload(message: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)=([^\s,]+)", message):
        payload[key] = value.strip().strip("\"'")
    return payload


def _extract_symbol(message: str) -> str | None:
    match = re.search(r"\b([A-Z]{6}|XAUUSD|XAGUSD)\b", message)
    return match.group(1) if match else None


def _extract_field(row: Mapping[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        value = row.get(name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return default


def _json_dict(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


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


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _is_final_signal(event: SignalWorkflowAuditEvent) -> bool:
    if event.channel != "SignalJSON":
        return False
    if event.payload.get("is_final_signal") is True:
        return True
    status = str(event.status or "").upper()
    return bool(status and "WATCH" not in status and "DECISION" not in status)


__all__ = [
    "CHANNELS",
    "SignalWorkflowAuditEvent",
    "parse_signal_workflow_csv",
    "parse_signal_workflow_row",
    "parse_signal_workflow_rows",
    "summarize_signal_workflow",
]
