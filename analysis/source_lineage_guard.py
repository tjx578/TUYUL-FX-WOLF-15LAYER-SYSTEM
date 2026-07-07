"""Source-lineage guards for SignalThrottle downstream stages.

Downstream events are observability/execution lifecycle products, not new
sources of truth.  These helpers keep Microboost, Watch, and Decision stages
anchored to fresh SignalThrottle clean-block lineage.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from typing import Any

DEFAULT_SOURCE_FRESHNESS_SECONDS = 300.0
DEFAULT_SIGNAL_THROTTLE_FRESHNESS_PREFIX = "[SignalThrottleFreshnessDiagnostic]"
DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX = "[MicroboostSourceDiagnostic]"
DEFAULT_MICROBOOST_STALE_DIAGNOSTIC_PREFIX = "[MicroboostStaleDiagnostic]"
DEFAULT_SIGNAL_THROTTLE_STATE_SNAPSHOT_PREFIX = "[SignalThrottleStateSnapshot]"
DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER = "signal_throttle_observability"


@dataclass(frozen=True)
class SourceFreshnessState:
    symbol: str
    fresh_signal_throttle_seen: bool
    last_signal_throttle_utc: str | None
    source_age_seconds: float | None
    max_source_age_seconds: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "fresh_signal_throttle_seen": self.fresh_signal_throttle_seen,
            "last_signal_throttle_utc": self.last_signal_throttle_utc,
            "source_age_seconds": self.source_age_seconds,
            "max_source_age_seconds": self.max_source_age_seconds,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class MicroboostSourceGuardResult:
    can_emit_microboost: bool
    diagnostics: list[dict[str, Any]]


def source_freshness_state(
    report: Mapping[str, Any],
    symbol: str,
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_SOURCE_FRESHNESS_SECONDS,
) -> SourceFreshnessState:
    symbol_key = str(symbol or "").upper()
    activity = _symbol_activity(report, symbol_key)
    if not symbol_key:
        return SourceFreshnessState("", False, None, None, max_age_seconds, "SYMBOL_MISSING")
    if not isinstance(activity, Mapping):
        return SourceFreshnessState(symbol_key, False, None, None, max_age_seconds, "NO_SIGNAL_THROTTLE_SOURCE")

    latest = _text(activity.get("latest_event_utc"))
    age = _optional_float(activity.get("idle_seconds"))
    if age is None and latest:
        latest_dt = _parse_time(latest)
        if latest_dt is not None:
            reference = _coerce_now(now)
            age = max(0.0, (reference - latest_dt).total_seconds())
    if age is None:
        return SourceFreshnessState(symbol_key, False, latest, None, max_age_seconds, "SOURCE_AGE_UNKNOWN")
    fresh = age <= max_age_seconds
    return SourceFreshnessState(
        symbol_key,
        fresh,
        latest,
        round(age, 3),
        max_age_seconds,
        "FRESH_SIGNAL_THROTTLE_SOURCE" if fresh else "STALE_SIGNAL_THROTTLE_SOURCE",
    )


def guard_microboost_source(
    report: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_SOURCE_FRESHNESS_SECONDS,
) -> MicroboostSourceGuardResult:
    latest = _latest_microboost(report)
    if latest is None:
        return MicroboostSourceGuardResult(True, [])

    symbol = str(latest.get("symbol") or "").upper()
    source_id = _text(latest.get("source_clean_block_id"))
    freshness = source_freshness_state(report, symbol, now=now, max_age_seconds=max_age_seconds)
    diagnostics: list[dict[str, Any]] = []

    if not freshness.fresh_signal_throttle_seen:
        diagnostics.append(
            _diagnostic(
                "signal_throttle_freshness_diagnostic",
                blocked_stage="MICROBOOST",
                blocked_by=["NO_FRESH_SIGNAL_THROTTLE_SOURCE"],
                reason=freshness.reason,
                **_freshness_context(freshness),
            )
        )
    if not source_id:
        diagnostics.append(
            _diagnostic(
                "microboost_source_diagnostic",
                blocked_stage="MICROBOOST",
                blocked_by=["SOURCE_CLEAN_BLOCK_ID_MISSING"],
                reason="MICROBOOST_REQUIRES_SOURCE_CLEAN_BLOCK_ID",
                **_microboost_context(latest),
                **_freshness_context(freshness),
            )
        )

    stale_age = _cluster_stale_age(latest, now=now)
    if stale_age is not None and stale_age > max_age_seconds:
        diagnostics.append(
            _diagnostic(
                "microboost_stale_diagnostic",
                blocked_stage="MICROBOOST",
                blocked_by=["MICROBOOST_CLUSTER_STALE"],
                reason="MICROBOOST_CLUSTER_END_EXCEEDS_SOURCE_STALE_WINDOW",
                cluster_stale_age_seconds=round(stale_age, 3),
                **_microboost_context(latest),
                **_freshness_context(freshness),
            )
        )

    return MicroboostSourceGuardResult(not diagnostics, diagnostics)


def signal_watch_source_diagnostic(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    status = str(payload.get("status") or "")
    if not status.endswith("_WATCH"):
        return None
    if _text(payload.get("source_clean_block_id")):
        return None
    symbol = str(payload.get("symbol") or "").upper() or None
    return {
        "event": "signal_watch_promotion_diagnostic",
        "symbol": symbol,
        "source_clean_block_id": None,
        "clean_block_valid": False,
        "eligible_for_signal_watch": False,
        "blocked_by": ["SOURCE_CLEAN_BLOCK_ID_MISSING"],
        "next_required_stage": "ATTACH_CLEAN_BLOCK_LINEAGE",
        "status": status,
        "signal_family": payload.get("signal_family"),
        "cluster_id": payload.get("cluster_id"),
        "valid_for_execution": False,
        "is_final_signal": False,
        "final_direction": "WAIT",
        "reason": "signal_watch_requires_source_clean_block_id",
    }


def signal_throttle_state_snapshot_payload(
    report: Mapping[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: float = DEFAULT_SOURCE_FRESHNESS_SECONDS,
) -> dict[str, Any]:
    reference = _coerce_now(now)
    activity = report.get("symbol_activity")
    activity_map = activity if isinstance(activity, Mapping) else {}
    fresh_symbols: list[str] = []
    stale_symbols: list[str] = []
    last_seen: str | None = None
    latest_seen_dt: datetime | None = None

    for symbol in sorted(str(key).upper() for key in activity_map):
        state = source_freshness_state(report, symbol, now=reference, max_age_seconds=max_age_seconds)
        if state.fresh_signal_throttle_seen:
            fresh_symbols.append(symbol)
        else:
            stale_symbols.append(symbol)
        seen_dt = _parse_time(state.last_signal_throttle_utc)
        if seen_dt is not None and (latest_seen_dt is None or seen_dt > latest_seen_dt):
            latest_seen_dt = seen_dt
            last_seen = state.last_signal_throttle_utc

    candidates = report.get("clean_watch_candidates")
    candidates_list = [item for item in candidates if isinstance(item, Mapping)] if isinstance(candidates, list) else []
    latest_clean = max(
        candidates_list,
        key=lambda item: _parse_time(_text(item.get("clean_block_end_utc") or item.get("block_end_utc"))) or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    last_clean_block_id = _text(latest_clean.get("source_clean_block_id")) if isinstance(latest_clean, Mapping) else None
    active_clean_blocks = sum(
        1
        for item in candidates_list
        if _is_fresh_time(_text(item.get("clean_block_end_utc") or item.get("block_end_utc")), reference, max_age_seconds)
    )
    counts = report.get("counts")
    total_events = counts.get("total_events") if isinstance(counts, Mapping) else None
    return {
        "event": "signal_throttle_state_snapshot",
        "deployment_id": os.getenv("RAILWAY_DEPLOYMENT_ID") or os.getenv("DEPLOYMENT_ID") or "unknown",
        "last_signal_throttle_utc": last_seen,
        "last_clean_block_id": last_clean_block_id,
        "active_clean_blocks": active_clean_blocks,
        "fresh_symbols": fresh_symbols,
        "stale_symbols": stale_symbols,
        "record_buffer_size": _optional_int(total_events) or 0,
        "max_source_age_seconds": max_age_seconds,
        "snapshot_time_utc": reference.isoformat(),
        "valid_for_execution": False,
        "is_final_signal": False,
    }


def _observability_logger_name() -> str:
    return os.getenv("SIGNAL_THROTTLE_OBSERVABILITY_LOGGER", DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER)


def emit_source_guard_diagnostic(payload: Mapping[str, Any], *, prefix: str, logger_name: str | None = None) -> bool:
    data = dict(payload)
    data["valid_for_execution"] = False
    data["is_final_signal"] = False
    logging.getLogger(logger_name or _observability_logger_name()).warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def emit_signal_throttle_state_snapshot(
    payload: Mapping[str, Any],
    *,
    prefix: str,
    logger_name: str | None = None,
) -> bool:
    data = dict(payload)
    logging.getLogger(logger_name or _observability_logger_name()).warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def diagnostic_prefix(event: str) -> str:
    return {
        "signal_throttle_freshness_diagnostic": DEFAULT_SIGNAL_THROTTLE_FRESHNESS_PREFIX,
        "microboost_source_diagnostic": DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX,
        "microboost_stale_diagnostic": DEFAULT_MICROBOOST_STALE_DIAGNOSTIC_PREFIX,
    }.get(event, DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX)


def _latest_microboost(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    summary = report.get("microboost_summary")
    if not isinstance(summary, Mapping):
        return None
    latest = summary.get("latest")
    return latest if isinstance(latest, Mapping) else None


def _symbol_activity(report: Mapping[str, Any], symbol: str) -> Mapping[str, Any] | None:
    activity = report.get("symbol_activity")
    if not isinstance(activity, Mapping):
        return None
    direct = activity.get(symbol) or activity.get(symbol.lower())
    return direct if isinstance(direct, Mapping) else None


def _diagnostic(event: str, **payload: Any) -> dict[str, Any]:
    data = dict(payload)
    data["event"] = event
    data["eligible_for_normal_emit"] = False
    data["valid_for_execution"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    return data


def _microboost_context(latest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cluster_id": latest.get("cluster_id"),
        "cluster_stage": latest.get("cluster_stage"),
        "source_clean_block_id": latest.get("source_clean_block_id"),
        "source_pressure_block_id": latest.get("source_pressure_block_id"),
        "source_signal_throttle_event_range": latest.get("source_signal_throttle_event_range"),
        "microboost_end_utc": latest.get("end_utc"),
        "phase_unpriced": latest.get("phase_unpriced"),
        "phase_priced": latest.get("phase_priced"),
    }


def _freshness_context(freshness: SourceFreshnessState) -> dict[str, Any]:
    payload = freshness.to_dict()
    reason = payload.pop("reason", None)
    payload["source_freshness_reason"] = reason
    return payload


def _cluster_stale_age(latest: Mapping[str, Any], *, now: datetime | None = None) -> float | None:
    end = _parse_time(_text(latest.get("end_utc")))
    if end is None:
        return None
    return max(0.0, (_coerce_now(now) - end).total_seconds())


def _is_fresh_time(value: str | None, now: datetime, max_age_seconds: float) -> bool:
    stamp = _parse_time(value)
    if stamp is None:
        return False
    return max(0.0, (now - stamp).total_seconds()) <= max_age_seconds


def _parse_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "DEFAULT_MICROBOOST_SOURCE_DIAGNOSTIC_PREFIX",
    "DEFAULT_MICROBOOST_STALE_DIAGNOSTIC_PREFIX",
    "DEFAULT_SIGNAL_THROTTLE_FRESHNESS_PREFIX",
    "DEFAULT_SIGNAL_THROTTLE_OBSERVABILITY_LOGGER",
    "DEFAULT_SIGNAL_THROTTLE_STATE_SNAPSHOT_PREFIX",
    "DEFAULT_SOURCE_FRESHNESS_SECONDS",
    "MicroboostSourceGuardResult",
    "SourceFreshnessState",
    "diagnostic_prefix",
    "emit_signal_throttle_state_snapshot",
    "emit_source_guard_diagnostic",
    "guard_microboost_source",
    "signal_throttle_state_snapshot_payload",
    "signal_watch_source_diagnostic",
    "source_freshness_state",
]
