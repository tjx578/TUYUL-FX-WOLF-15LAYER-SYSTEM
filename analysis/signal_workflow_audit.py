"""Offline workflow audit for SignalThrottle/Microboost/Watch logs.

The parser joins exported CSV rows across lifecycle channels by ``cluster_id``
and summarizes direction conflicts without treating watch/decision telemetry as
execution intent.
"""

from __future__ import annotations

import argparse
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
    "MicroboostSourceDiagnostic",
    "MicroboostStaleDiagnostic",
    "MicroboostWatchDiagnostic",
    "MicroboostShadowDiagnostic",
    "SignalThrottleFreshnessDiagnostic",
    "SignalThrottleStateSnapshot",
    "SignalThrottlePressureTierSnapshot",
    "SignalPressureStateJSON",
    "SignalWatchPromotionDiagnostic",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize SignalThrottle/Microboost/Watch lifecycle logs from an exported CSV.",
    )
    parser.add_argument("csv_path", help="CSV export containing timestamp/message log rows.")
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Keep duplicate CSV rows instead of deduplicating exact row matches.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of pretty-printed JSON.",
    )
    parser.add_argument(
        "--historical-cross-deployment-audit",
        action="store_true",
        help="Explicitly allow accuracy-oriented analysis across multiple deployments.",
    )
    args = parser.parse_args(argv)

    events = parse_signal_workflow_csv(args.csv_path, dedupe=not args.no_dedupe)
    indent = None if args.compact else 2
    print(
        json.dumps(
            summarize_signal_workflow(
                events,
                historical_cross_deployment_audit=args.historical_cross_deployment_audit,
            ),
            ensure_ascii=False,
            sort_keys=True,
            indent=indent,
        )
    )
    return 0


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
        raw_direction=normalize_direction(
            _optional_text(payload.get("raw_direction") or payload.get("direction")), None
        ),
        candidate_direction=normalize_direction(_optional_text(payload.get("candidate_direction")), None),
        watch_direction=normalize_direction(_optional_text(payload.get("watch_direction")), None),
        final_direction=normalize_direction(_optional_text(payload.get("final_direction")), None),
        valid_for_execution=_optional_bool(payload.get("valid_for_execution")),
    )


def summarize_signal_workflow(
    events: Iterable[SignalWorkflowAuditEvent],
    *,
    historical_cross_deployment_audit: bool = False,
) -> dict[str, Any]:
    ordered = list(events)
    channel_counts = Counter(event.channel for event in ordered)
    deployment_counts = Counter(event.deployment_id or "UNKNOWN" for event in ordered)
    cluster_groups = _cluster_groups(ordered)
    conflict_counts = Counter()
    raw_buy_candidate_sell = Counter()
    watch_tier_contexts = []
    tier3_key_level_exceptions = Counter()
    low_event_high_impact = Counter()
    for event in ordered:
        candidate = event.candidate_direction or event.watch_direction
        tier_context = _pressure_priority_context(event)
        if event.channel == "SignalWatchJSON" and tier_context is not None:
            watch_tier_contexts.append(event)
            if event.symbol and tier_context.get("effective_pressure_tier") == "TIER_3_KEY_LEVEL_RADAR_EXCEPTION":
                tier3_key_level_exceptions[event.symbol] += 1
            if event.symbol and tier_context.get("low_event_high_impact_candidate") is True:
                low_event_high_impact[event.symbol] += 1
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
        "accuracy_scope_gate": _accuracy_scope_gate(
            deployment_counts,
            historical_cross_deployment_audit=historical_cross_deployment_audit,
        ),
        "pressure_state_schema_gate": _pressure_state_schema_gate(ordered),
        "signal_json_final": sum(_is_final_signal(event) for event in ordered),
        "valid_for_execution_true": sum(event.valid_for_execution is True for event in ordered),
        "direction_conflicts_by_symbol": dict(conflict_counts.most_common()),
        "raw_buy_candidate_sell_by_symbol": dict(raw_buy_candidate_sell.most_common()),
        "pressure_tier_snapshot_count": sum(event.channel == "SignalThrottlePressureTierSnapshot" for event in ordered),
        "latest_pressure_tier_snapshot": _latest_pressure_tier_snapshot(ordered),
        "watch_pressure_priority_context_count": len(watch_tier_contexts),
        "watch_pressure_priority_context_by_symbol": dict(
            Counter(event.symbol or "UNKNOWN" for event in watch_tier_contexts).most_common()
        ),
        "tier3_key_level_exception_by_symbol": dict(tier3_key_level_exceptions.most_common()),
        "low_event_high_impact_watch_by_symbol": dict(low_event_high_impact.most_common()),
        "tier_leakage_guard": _tier_leakage_guard(ordered),
        "cluster_summary": _cluster_summary(cluster_groups),
    }


def _pressure_state_schema_gate(events: list[SignalWorkflowAuditEvent]) -> dict[str, Any]:
    versions = Counter(
        str(event.payload.get("schema_version") or "LEGACY_UNVERSIONED")
        for event in events
        if event.channel == "SignalPressureStateJSON"
    )
    noncanonical = sum(count for version, count in versions.items() if version != "2.0-pressure-state")
    total = sum(versions.values())
    return {
        "canonical_schema_version": "2.0-pressure-state",
        "schema_counts": dict(versions.most_common()),
        "total_pressure_states": total,
        "noncanonical_pressure_states": noncanonical,
        "consistent": total == 0 or noncanonical == 0,
        "status": "CANONICAL" if total == 0 or noncanonical == 0 else "REJECTED_MIXED_OR_LEGACY_SCHEMA",
    }


def _accuracy_scope_gate(
    deployment_counts: Counter[str],
    *,
    historical_cross_deployment_audit: bool,
) -> dict[str, Any]:
    known_deployments = [deployment for deployment in deployment_counts if deployment != "UNKNOWN"]
    deployment_count = len(known_deployments)
    mixed = deployment_count > 1
    unknown_present = bool(deployment_counts.get("UNKNOWN"))
    single_known_deployment = deployment_count == 1 and not unknown_present
    allowed = single_known_deployment or historical_cross_deployment_audit
    return {
        "deployment_count": deployment_count,
        "mixed_deployment": mixed,
        "unknown_deployment_present": unknown_present,
        "historical_cross_deployment_audit": historical_cross_deployment_audit,
        "accuracy_computation_allowed": allowed,
        "status": (
            "HISTORICAL_CROSS_DEPLOYMENT_AUDIT"
            if historical_cross_deployment_audit and not single_known_deployment
            else "REJECTED_MIXED_DEPLOYMENT"
            if mixed
            else "REJECTED_UNKNOWN_DEPLOYMENT"
            if unknown_present or deployment_count == 0
            else "SINGLE_DEPLOYMENT_VALID"
        ),
        "reason": (None if allowed else "Accuracy evidence requires one deployment and one runtime configuration."),
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


def _latest_pressure_tier_snapshot(events: list[SignalWorkflowAuditEvent]) -> dict[str, Any] | None:
    snapshots = [event for event in events if event.channel == "SignalThrottlePressureTierSnapshot"]
    if not snapshots:
        return None
    latest = max(snapshots, key=lambda item: item.timestamp or datetime.min.replace(tzinfo=UTC))
    payload = latest.payload
    summary = payload.get("summary")
    visibility_policy = payload.get("visibility_policy")
    execution_guard = payload.get("execution_guard")
    return {
        "generated_at_utc": payload.get("generated_at_utc"),
        "schema_version": payload.get("schema_version"),
        "display_line": payload.get("display_line"),
        "summary": dict(summary) if isinstance(summary, Mapping) else {},
        "tier_1": payload.get("tier_1") if isinstance(payload.get("tier_1"), list) else [],
        "tier_2": payload.get("tier_2") if isinstance(payload.get("tier_2"), list) else [],
        "tier_3_hidden_count": _non_negative_int(payload.get("tier_3_hidden_count")),
        "stale_archive_count": _non_negative_int(payload.get("stale_archive_count")),
        "unsafe_mixed_deployment_count": _non_negative_int(payload.get("unsafe_mixed_deployment_count")),
        "visibility_policy": dict(visibility_policy) if isinstance(visibility_policy, Mapping) else {},
        "execution_guard": dict(execution_guard) if isinstance(execution_guard, Mapping) else {},
        "tier_is_execution_signal": payload.get("tier_is_execution_signal"),
        "tier_execution_impact": payload.get("tier_execution_impact"),
    }


def _tier_leakage_guard(events: list[SignalWorkflowAuditEvent]) -> dict[str, Any]:
    decision_or_final = [event for event in events if event.channel in {"SignalDecisionUpdateJSON", "SignalJSON"}]
    pressure_context = [
        event for event in decision_or_final if isinstance(event.payload.get("pressure_priority_context"), dict)
    ]
    direct_tier = [event for event in decision_or_final if event.payload.get("effective_pressure_tier") is not None]
    reason_mentions = [
        event
        for event in decision_or_final
        if "TIER_" in str(event.payload.get("reason") or "").upper()
        or "PRESSURE_PRIORITY" in str(event.payload.get("reason") or "").upper()
    ]
    return {
        "clean": not pressure_context and not direct_tier and not reason_mentions,
        "decision_or_signal_with_pressure_priority_context": len(pressure_context),
        "decision_or_signal_with_effective_pressure_tier": len(direct_tier),
        "decision_or_signal_reason_mentions_tier": len(reason_mentions),
        "leaking_symbols": sorted(
            {str(event.symbol or "UNKNOWN") for event in [*pressure_context, *direct_tier, *reason_mentions]}
        ),
    }


def _pressure_priority_context(event: SignalWorkflowAuditEvent) -> Mapping[str, Any] | None:
    context = event.payload.get("pressure_priority_context")
    return context if isinstance(context, Mapping) else None


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


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


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
    "main",
    "parse_signal_workflow_csv",
    "parse_signal_workflow_row",
    "parse_signal_workflow_rows",
    "summarize_signal_workflow",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
