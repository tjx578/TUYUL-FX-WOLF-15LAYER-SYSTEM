"""SignalThrottle live and historical log intelligence.

Runtime code feeds structured engine events directly through
``SignalThrottleLiveAnalyzer``.  CSV parsing is kept only for offline audits of
exported platform logs.  This module is intentionally pure: no broker calls,
no order execution, and no dependency on pandas.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import threading
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime, timedelta
from numbers import Real
from pathlib import Path
from typing import Any

try:
    from ..schemas.direction import normalize_direction
except ImportError:  # pragma: no cover - supports top-level ``analysis`` imports in tests/tools.
    from schemas.direction import normalize_direction

from .clean_block_watch_router import clean_block_lineage_fields, route_clean_blocks_to_watch
from .direction_conflict_resolver import resolve_direction_conflict
from .market_context_validator import (
    MarketContext,
    missing_market_context_result,
    validate_execution_context,
    validate_radar_context,
)
from .microboost_continuation_entry import MicroboostContinuationEngine
from .microboost_core_event import to_microboost_core_event
from .microboost_counter_entry import MicroboostCounterEntryEngine
from .microboost_detector import build_microboost_summary
from .microboost_followthrough_role import microboost_role_fields_from
from .outcome_memory import summarize_outcome_memory
from .pressure_cluster_deduper import summarize_pressure_clusters
from .regime_invalidation import validate_regime_state
from .signal_promotion_score import score_signal_promotion
from .signal_throttle_followthrough_score import build_signal_throttle_followthrough_scores
from .signal_throttle_fusion_router import build_signal_throttle_fusion_v3_diagnostic
from .signal_throttle_pattern_detector import classify_pressure_block
from .signal_throttle_pressure_tier import build_pressure_tier_snapshot
from .signal_throttle_pure_block_quality import score_pure_pressure_block

_SYMBOL_RE = r"(?P<symbol>[A-Z]{3,6}[A-Z0-9]*)"
_THROTTLED_RE = re.compile(rf"\[SignalThrottle\]\s+{_SYMBOL_RE}\s+THROTTLED", re.IGNORECASE)
_ALLOWED_RE = re.compile(
    rf"\[SignalThrottle\]\s+{_SYMBOL_RE}\s+allowed\s+(?:—|-)\s+verdict\s+(?P<verdict>[A-Z_]+)",
    re.IGNORECASE,
)
_VERDICT_RE = re.compile(r"\bverdict\s+(?P<verdict>EXECUTE(?:_REDUCED_RISK)?_(?:BUY|SELL))\b", re.IGNORECASE)
_DOWNGRADED_RE = re.compile(
    rf"\[SignalThrottle\]\s+{_SYMBOL_RE}.*?verdict\s+(?P<verdict>[A-Z_]+).*?downgraded\s+to\s+HOLD",
    re.IGNORECASE,
)
_INTEL_RE = re.compile(r"\[SignalThrottleIntel\]\s+symbol=(?P<symbol>[A-Z]{3,6}[A-Z0-9]*)", re.IGNORECASE)
_SIGNAL_THROTTLE_CHECK_RE = re.compile(r"\bevent=signal_throttle_check\b", re.IGNORECASE)
_SUPPRESSED_RE = re.compile(r"\bsuppressed=(?P<suppressed>\d+)\b", re.IGNORECASE)
_COUNT_KV_RE = re.compile(r"\bcount=(?P<count>\d+)\b", re.IGNORECASE)
_COUNT_SIGNAL_RE = re.compile(r"\b(?P<count>\d+)\s+signals?\s+in\s+last\b", re.IGNORECASE)
_REMAINING_RE = re.compile(r"\bremaining=(?P<remaining>\d+)\b", re.IGNORECASE)
_STREAK_RE = re.compile(r"\bstreak=(?P<streak>\d+)\b", re.IGNORECASE)
_MAX_KV_RE = re.compile(r"\bmax=(?P<max>\d+)\b", re.IGNORECASE)
_MAX_PAREN_RE = re.compile(r"\(max\s+(?P<max>\d+)\)", re.IGNORECASE)
_WINDOW_KV_RE = re.compile(r"\bwindow=(?P<window>\d+(?:\.\d+)?)s\b", re.IGNORECASE)
_WINDOW_SIGNAL_RE = re.compile(r"\blast\s+(?P<window>\d+(?:\.\d+)?)s\b", re.IGNORECASE)

_CURRENCIES = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD")
_METAL_BASES = ("XAG", "XAU")
_DEFAULT_CANDIDATE_LIFECYCLE_WINDOW_SECONDS = 4 * 60 * 60
DEFAULT_SIGNAL_THROTTLE_RAW_LOGGER = "signal_throttle_raw"
DEFAULT_SIGNAL_THROTTLE_RAW_PREFIX = "[SignalThrottle]"
DEFAULT_SIGNAL_THROTTLE_RAW_LEVEL = "WARNING"
PURE_PRESSURE_LEDGER_SOURCE = "SIGNAL_THROTTLE_PURE_PRESSURE_LEDGER"
PURE_PRESSURE_LEDGER_TYPE = "PURE_PRESSURE_LEDGER"
V1_CLEAN_BLOCK_LEDGER_TYPE = "V1_SCANNER_CLEAN_BLOCK_LEDGER"
V1_CLEAN_BLOCK_LEDGER_SOURCE = "SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER"
V1_CLEAN_BLOCK_RULE = "SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE_DURATION_GE_THRESHOLD"
V1_CLEAN_BLOCK_LEGACY_RULE = "PAIR_ROTATION_ONLY_GAP_AGNOSTIC_DURATION_GE_THRESHOLD"


@dataclass(frozen=True)
class SignalThrottleLogEvent:
    timestamp: datetime
    severity: str
    message: str
    symbol: str
    event_type: str
    verdict: str | None = None
    direction: str | None = None
    raw_verdict: str | None = None
    effective_action: str = "UNKNOWN"
    is_downgraded: bool = False
    suppressed: int = 0
    count: int | None = None
    remaining: int | None = None
    allowed_streak: int | None = None
    max_signals: int | None = None
    window_seconds: float | None = None
    pressure_strength: str | None = None
    pressure_source: str | None = None
    source_stream: str | None = None
    deployment_id: str | None = None
    scanner_cycle_id: str | None = None
    scanner_epoch: str | None = None
    observed_cycle_index: int | None = None
    eligible_for_pressure_block: bool | None = None
    eligible_for_execution: bool | None = None
    execution_block_reason: str | None = None
    direction_source: str | None = None
    direction_confidence: str | None = None
    direction_inherited: bool = False
    inherited_direction: str | None = None
    inherited_direction_age_seconds: float | None = None
    base_ccy: str | None = None
    quote_ccy: str | None = None
    symbol_orientation: str | None = None
    verdict_source: str | None = None
    verdict_features_hash: str | None = None
    window_count_before: int | None = None
    window_count_after: int | None = None
    window_remaining_before: int | None = None
    window_remaining_after: int | None = None
    allowed_streak_before: int | None = None
    allowed_streak_after: int | None = None
    throttled_inferred_direction: str | None = None

    @property
    def effective_ticks(self) -> int:
        return 1 + max(0, int(self.suppressed))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["timestamp"] = self.timestamp.isoformat()
        payload["effective_ticks"] = self.effective_ticks
        return payload


@dataclass(frozen=True)
class PressureBlock:
    symbol: str
    start: datetime
    end: datetime
    events: int
    duration_seconds: float
    density_per_minute: float
    max_gap_seconds: float
    avg_gap_seconds: float = 0.0
    direction: str | None = None
    effective_ticks: int = 0
    suppressed_ticks: int = 0
    allowed_events: int = 0
    throttled_events: int = 0
    downgraded_events: int = 0
    effective_density_per_minute: float = 0.0
    direction_source: str | None = None
    direction_confidence: str | None = None
    direction_inherited: bool = False
    inherited_direction: str | None = None
    inherited_direction_age_seconds: float | None = None
    deployment_ids: tuple[str, ...] = ()
    scanner_cycle_ids: tuple[str, ...] = ()
    scanner_epoch_start_utc: str | None = None
    scanner_epoch_end_utc: str | None = None
    observed_cycle_index_min: int | None = None
    observed_cycle_index_max: int | None = None
    source_stream_profile: tuple[tuple[str, int], ...] = ()
    raw_signal_throttle_severity_profile: tuple[tuple[str, int], ...] = ()
    raw_signal_throttle_error_count: int = 0
    raw_signal_throttle_primary_severity: str | None = None
    raw_pressure_origin: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        payload.update(_pressure_profile_payload(self))
        payload.update(_source_profile_payload(self))
        return payload


def parse_signal_throttle_csv(path: str | Path) -> list[SignalThrottleLogEvent]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(parse_signal_throttle_rows(reader))


def parse_signal_throttle_rows(rows: Iterable[dict[str, Any]]) -> list[SignalThrottleLogEvent]:
    events: list[SignalThrottleLogEvent] = []
    for row in rows:
        event = parse_signal_throttle_row(row)
        if event is not None:
            events.append(event)
    return sorted(events, key=lambda item: item.timestamp)


def parse_engine_log_event(event: dict[str, Any]) -> SignalThrottleLogEvent | None:
    """Parse one structured log event from the engine/log service.

    The input shape matches Railway-style exported rows, but this function is
    deliberately generic so runtime code can pass log-event dictionaries
    directly without writing or reading CSV files.
    """
    return parse_signal_throttle_row(event)


def parse_signal_throttle_row(row: dict[str, Any]) -> SignalThrottleLogEvent | None:
    message = _extract_field(row, "message", "body", "log", "text")
    is_signal_throttle_check = _SIGNAL_THROTTLE_CHECK_RE.search(message) is not None
    intel = _INTEL_RE.search(message)
    if "[SignalThrottle]" not in message and not is_signal_throttle_check and intel is None:
        return None

    timestamp = _parse_timestamp(_extract_field(row, "timestamp", "time", "@timestamp", "datetime"))
    if timestamp is None:
        return None

    severity = _extract_field(row, "severity", "level", default="info").lower()
    symbol = ""
    event_type = "UNKNOWN"
    verdict: str | None = None
    direction: str | None = None
    pressure_strength: str | None = None
    pressure_source: str | None = "SignalThrottle"
    source_stream: str | None = None
    eligible_for_pressure_block: bool | None = True
    eligible_for_execution: bool | None = None
    execution_block_reason: str | None = None
    direction_source: str | None = None
    direction_confidence: str | None = None
    direction_inherited = False
    inherited_direction: str | None = None
    inherited_direction_age_seconds: float | None = None
    deployment_id = (
        _extract_kv_text(message, "deployment_id")
        or _extract_json_text(message, "deployment_id")
        or _extract_field(row, "deployment_id", "deployment", default="")
    )
    scanner_cycle_id = (
        _extract_kv_text(message, "scanner_cycle_id")
        or _extract_json_text(message, "scanner_cycle_id")
        or _extract_field(row, "scanner_cycle_id", default="")
    )
    scanner_epoch = (
        _extract_kv_text(message, "scanner_epoch")
        or _extract_json_text(message, "scanner_epoch")
        or _extract_field(row, "scanner_epoch", default="")
    )
    observed_cycle_index = (
        _extract_kv_optional_int(message, "observed_cycle_index")
        or _coerce_non_negative_int(_extract_json_text(message, "observed_cycle_index"))
        or _coerce_non_negative_int(_extract_field(row, "observed_cycle_index", default=""))
    )

    throttled = _THROTTLED_RE.search(message)
    allowed = _ALLOWED_RE.search(message)
    downgraded = _DOWNGRADED_RE.search(message)

    if is_signal_throttle_check:
        symbol = _extract_kv_text(message, "symbol").upper()
        if not symbol:
            return None
        verdict = (_extract_kv_text(message, "source_verdict") or _extract_kv_text(message, "verdict")).upper()
        event_type = "PRESSURE_CANARY"
        effective_action = "OBSERVE"
        is_downgraded = False
        direction = normalize_direction(_extract_kv_text(message, "direction"), None)
        pressure_strength = "CANARY"
        pressure_source = "signal_throttle_check"
        source_stream = "CANARY"
        eligible_for_execution = False
        execution_block_reason = _extract_kv_text(message, "reason") or "non_execute_verdict"
        direction_source = _extract_kv_text(message, "direction_source") or None
        direction_confidence = _extract_kv_text(message, "direction_confidence") or None
        direction_inherited = _extract_kv_text(message, "direction_inherited").lower() == "true"
        inherited_direction = normalize_direction(_extract_kv_text(message, "inherited_direction"), None)
        inherited_direction_age_seconds = _extract_kv_float(message, "inherited_direction_age_seconds")
    elif intel:
        symbol = intel.group("symbol").upper()
        verdict_text = _extract_kv_text(message, "verdict").upper()
        verdict = verdict_text or None
        event_type = "INTEL"
        effective_action = (_extract_kv_text(message, "action") or "OBSERVE").upper()
        is_downgraded = False
        direction = normalize_direction(
            _extract_kv_text(message, "raw_direction") or _extract_kv_text(message, "direction"),
            verdict,
        )
        pressure_strength = (_extract_kv_text(message, "phase") or "INTEL").upper()
        pressure_source = "SignalThrottleIntel"
        source_stream = "INTEL"
        eligible_for_execution = False
        execution_block_reason = _extract_kv_text(message, "reason") or "signal_throttle_intel"
        direction_source = "SIGNAL_THROTTLE_INTEL_LOG"
        direction_confidence = "HIGH" if direction in {"BUY", "SELL"} else None
    elif downgraded:
        symbol = downgraded.group("symbol").upper()
        verdict = downgraded.group("verdict").upper()
        event_type = "DOWNGRADED_TO_HOLD"
        effective_action = "HOLD"
        is_downgraded = True
        source_stream = "DOWNGRADED"
        eligible_for_execution = False
        execution_block_reason = "downgraded_to_hold"
    elif allowed:
        symbol = allowed.group("symbol").upper()
        verdict = allowed.group("verdict").upper()
        event_type = "ALLOWED"
        effective_action = "ALLOWED"
        is_downgraded = False
        source_stream = "ALLOWED"
        eligible_for_execution = bool(verdict and verdict.startswith("EXECUTE"))
    elif throttled:
        symbol = throttled.group("symbol").upper()
        event_type = "THROTTLED"
        effective_action = "HOLD"
        is_downgraded = False
        source_stream = "RAW_THROTTLED"
        eligible_for_execution = False
        execution_block_reason = "signal_throttled"
    else:
        return None

    if verdict is None:
        verdict_match = _VERDICT_RE.search(message)
        verdict = verdict_match.group("verdict").upper() if verdict_match else None
    state_fields = _extract_state_fields(message)

    return SignalThrottleLogEvent(
        timestamp=timestamp,
        severity=severity,
        message=message,
        symbol=symbol,
        event_type=event_type,
        verdict=verdict,
        direction=direction if (is_signal_throttle_check or intel) else normalize_direction(None, verdict),
        raw_verdict=verdict,
        effective_action=effective_action,
        is_downgraded=is_downgraded,
        suppressed=_extract_suppressed(message),
        count=state_fields.get("count"),
        remaining=state_fields.get("remaining"),
        allowed_streak=state_fields.get("allowed_streak"),
        max_signals=state_fields.get("max_signals"),
        window_seconds=state_fields.get("window_seconds"),
        pressure_strength=pressure_strength,
        pressure_source=pressure_source,
        source_stream=source_stream,
        deployment_id=deployment_id or None,
        scanner_cycle_id=scanner_cycle_id or None,
        scanner_epoch=scanner_epoch or None,
        observed_cycle_index=observed_cycle_index,
        eligible_for_pressure_block=eligible_for_pressure_block,
        eligible_for_execution=eligible_for_execution,
        execution_block_reason=execution_block_reason,
        direction_source=direction_source,
        direction_confidence=direction_confidence,
        direction_inherited=direction_inherited,
        inherited_direction=inherited_direction,
        inherited_direction_age_seconds=inherited_direction_age_seconds,
        base_ccy=state_fields.get("base_ccy"),
        quote_ccy=state_fields.get("quote_ccy"),
        symbol_orientation=state_fields.get("symbol_orientation"),
        verdict_source=state_fields.get("verdict_source"),
        verdict_features_hash=state_fields.get("verdict_features_hash"),
        window_count_before=state_fields.get("window_count_before"),
        window_count_after=state_fields.get("window_count_after"),
        window_remaining_before=state_fields.get("window_remaining_before"),
        window_remaining_after=state_fields.get("window_remaining_after"),
        allowed_streak_before=state_fields.get("allowed_streak_before"),
        allowed_streak_after=state_fields.get("allowed_streak_after"),
        throttled_inferred_direction=state_fields.get("throttled_inferred_direction"),
    )


def analyze_signal_throttle_events(
    events: Iterable[SignalThrottleLogEvent],
    *,
    latest_window_minutes: int | None = None,
    latest_window_seconds: int | None = 3600,
    clean_gap_seconds: int = 75,
    min_clean_block_minutes: float | None = None,
    clean_block_seconds: int | None = 300,
    fragmented_min_unique_pairs: int = 5,
    fragmented_max_clean_block_minutes: float = 1.0,
    microboost_window_minutes: int = 15,
    candidate_lifecycle_window_seconds: int = _DEFAULT_CANDIDATE_LIFECYCLE_WINDOW_SECONDS,
    source: str = "live_process",
    source_found: bool = True,
    row_count: int | None = None,
    unparsed_count: int = 0,
    timezone_assumption: str = "UTC",
    market_contexts: dict[str, Any] | None = None,
    state_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if latest_window_minutes is not None:
        latest_window_seconds = int(latest_window_minutes * 60)
    latest_window_seconds = int(latest_window_seconds or 3600)
    if min_clean_block_minutes is not None:
        clean_block_seconds = int(min_clean_block_minutes * 60)
    clean_block_seconds = int(clean_block_seconds or 300)
    fragmented_max_clean_block_seconds = fragmented_max_clean_block_minutes * 60.0
    scanner_cycle_gap_seconds = _env_float("SIGNAL_THROTTLE_SCANNER_CYCLE_MAX_GAP_SECONDS", 300.0)

    ordered = sorted(events, key=lambda item: item.timestamp)
    state_metadata = state_metadata or _state_metadata_from_events(ordered)
    if not ordered:
        pressure_tier_snapshot = _build_pressure_tier_snapshot(
            events=[],
            blocks=[],
            symbol_activity={},
            clean_watch_candidates=[],
            candidate_lifecycle=_empty_candidate_lifecycle(candidate_lifecycle_window_seconds),
            theme_scores=[],
            clean_block_seconds=clean_block_seconds,
            state_metadata=state_metadata,
        )
        empty_market_context_validation = missing_market_context_result("UNKNOWN").to_dict()
        empty_radar_context_validation = validate_radar_context(
            MarketContext(symbol="UNKNOWN", raw_allowed_direction=None)
        ).to_dict()
        return {
            "final_mode": "NO_SIGNAL_THROTTLE_DATA",
            "clean_entry_signal": False,
            "pair_timing_candidate": False,
            "requires_market_context": True,
            "state_warmup": bool(state_metadata.get("state_warmup", False)),
            "first_event_is_continuation": bool(state_metadata.get("first_event_is_continuation", False)),
            "state_warmup_reason": state_metadata.get("state_warmup_reason"),
            "first_event_state": state_metadata.get("first_event_state"),
            "latest_phase": "NO_DATA",
            "main_watchlist": [],
            "watchlist": [],
            "active_candidate": None,
            "latest_meaningful_candidate": None,
            "latest_ignition_watch": None,
            "previous_major_leader": None,
            "historical_leader": None,
            "historical_leaders": [],
            "secondary_candidate": None,
            "counter_rotation": None,
            "candidate_lifecycle": _empty_candidate_lifecycle(candidate_lifecycle_window_seconds),
            "dominant_themes": [],
            "theme_scores": [],
            "event_counts": _event_counts([]),  # noqa: F821
            "symbol_activity": {},
            "burst_symbol_activity": {},
            "pure_pressure_blocks": [],
            "pure_top_blocks": [],
            "pure_active_candidate": None,
            "pure_block_ledger": [],
            "pure_block_count": 0,
            "v1_clean_block_ledger": [],
            "v1_clean_block_count": 0,
            "v1_active_clean_block": None,
            "clean_block_ledger_source": V1_CLEAN_BLOCK_LEDGER_SOURCE,
            "pressure_tier_snapshot": pressure_tier_snapshot,
            "pressure_tiers": pressure_tier_snapshot.get("symbols", []),
            "pressure_tier_summary": pressure_tier_snapshot.get("summary", {}),
            "time_range": {
                "start_utc": None,
                "end_utc": None,
                "duration_seconds": 0.0,
            },
            "counts": {
                "total_events": 0,
                "severity": {},
                "verdicts": {},
                "event_types": _event_counts([]),  # noqa: F821
                "pairs": {},
            },
            "latest_window": {
                "seconds": latest_window_seconds,
                "event_count": 0,
                "unique_symbols": 0,
                "top_pairs": {},
                "largest_clean_block_seconds": 0.0,
            },
            "runtime_config": {
                "latest_window_minutes": latest_window_seconds / 60.0,
                "min_clean_block_minutes": clean_block_seconds / 60.0,
                "pure_block_gap_policy": "PAIR_ROTATION_ONLY",
                "pure_block_max_gap_seconds": None,
                "clean_block_ledger_source": V1_CLEAN_BLOCK_LEDGER_SOURCE,
                "clean_block_rule": V1_CLEAN_BLOCK_RULE,
                "legacy_pure_block_rule": V1_CLEAN_BLOCK_LEGACY_RULE,
                "scanner_cycle_max_gap_seconds": scanner_cycle_gap_seconds,
                "burst_block_max_gap_seconds": clean_gap_seconds,
                "microboost_window_minutes": microboost_window_minutes,
                "candidate_lifecycle_window_seconds": candidate_lifecycle_window_seconds,
                "fragmented_min_unique_pairs": fragmented_min_unique_pairs,
                "fragmented_max_clean_block_minutes": fragmented_max_clean_block_minutes,
            },
            "top_microboost": [],
            "microboost_summary": build_microboost_summary(
                [],
                window_minutes=microboost_window_minutes,
                clean_block_seconds=clean_block_seconds,
            ),
            "clean_watch_candidates": [],
            "clean_block_watch_routes": [],
            "clean_block_watch_entries": [],
            "signal_watch_promotion_diagnostics": [],
            "microboost_core_event": None,
            "microboost_continuation_entry": None,
            "microboost_counter_entry": None,
            "microboost_watch_entry": None,
            "direction_recovery": _empty_direction_recovery_counters(),
            "pressure_cluster_summary": summarize_pressure_clusters([])
            if _env_bool("SIGNAL_PRESSURE_CLUSTER_DEDUP_ENABLED", False)
            else None,
            "outcome_memory_summary": summarize_outcome_memory([])
            if _env_bool("SIGNAL_OUTCOME_MEMORY_ENABLED", False)
            else None,
            "regime_invalidation": validate_regime_state(symbol="UNKNOWN", direction=None).to_dict()
            if _env_bool("SIGNAL_REGIME_INVALIDATION_ENABLED", False)
            else None,
            "promotion_score": score_signal_promotion().to_dict()
            if _env_bool("SIGNAL_PROMOTION_SCORE_ENABLED", False)
            else None,
            "followthrough_scores": [],
            "signal_watch_gate": _empty_signal_watch_gate("NO_SIGNAL_THROTTLE_DATA"),
            "allowed_quorum": compute_allowed_quorum([]),  # noqa: F821
            "pair_eligible_for_analysis": False,
            "watch_promotion_blockers": {},
            "radar_context_validation": empty_radar_context_validation,
            "market_context_validation": empty_market_context_validation,
            "signal_throttle_fusion_v3": build_signal_throttle_fusion_v3_diagnostic(
                None,
                radar_context_validation=empty_radar_context_validation,
                execution_context_validation=empty_market_context_validation,
                microboost_summary={},
            ),
            "data_quality": _data_quality_block(
                events=[],
                source=source,
                source_found=source_found,
                row_count=row_count,
                unparsed_count=unparsed_count,
                timezone_assumption=timezone_assumption,
                state_metadata=state_metadata,
            ),
            "currency_pressure": {currency: 0 for currency in _CURRENCIES},
            "top_clean_blocks": [],
            "top_burst_blocks": [],
            "recommended_action": "WAIT_FOR_SIGNAL_THROTTLE_DATA",
        }

    pure_blocks = build_pure_pressure_blocks(ordered)
    scanner_cycle_blocks = build_scanner_cycle_pressure_blocks(
        ordered,
        max_symbol_gap_seconds=scanner_cycle_gap_seconds,
    )
    burst_blocks = build_pressure_blocks(ordered, max_gap_seconds=clean_gap_seconds)
    symbol_activity = build_symbol_activity(
        ordered,
        max_gap_seconds=None,
        now=ordered[-1].timestamp,
    )
    burst_symbol_activity = build_symbol_activity(
        ordered,
        max_gap_seconds=clean_gap_seconds,
        now=ordered[-1].timestamp,
    )
    lifecycle_blocks = scanner_cycle_blocks
    latest_cutoff = ordered[-1].timestamp - timedelta(seconds=latest_window_seconds)
    latest_events = [event for event in ordered if event.timestamp >= latest_cutoff]
    latest_blocks = build_pure_pressure_blocks(latest_events)
    microboost_cutoff = ordered[-1].timestamp - timedelta(minutes=microboost_window_minutes)
    microboost_events = [event for event in ordered if event.timestamp >= microboost_cutoff]
    microboost_blocks = build_pressure_blocks(microboost_events, max_gap_seconds=clean_gap_seconds)
    latest_largest_block = max((block.duration_seconds for block in latest_blocks), default=0.0)
    latest_phase = classify_latest_phase(
        latest_events=latest_events,
        latest_largest_block_seconds=latest_largest_block,
        clean_block_seconds=clean_block_seconds,
        fragmented_min_unique_pairs=fragmented_min_unique_pairs,
        fragmented_max_clean_block_seconds=fragmented_max_clean_block_seconds,
    )
    pair_counts = Counter(event.symbol for event in ordered)
    latest_pair_counts = Counter(event.symbol for event in latest_events)
    severity_counts = Counter(event.severity for event in ordered)
    verdict_counts = Counter(event.verdict for event in ordered if event.verdict)
    event_type_counts = _event_counts(ordered)  # noqa: F821
    currency_pressure = compute_currency_pressure(ordered)
    theme_scores = classify_themes(pair_counts=pair_counts, currency_pressure=currency_pressure)
    pressure_cluster_summary = (
        summarize_pressure_clusters(ordered)
        if _env_bool("SIGNAL_PRESSURE_CLUSTER_DEDUP_ENABLED", False)
        else None
    )
    dominant_themes = theme_scores[:5]
    main_watchlist = [symbol for symbol, _ in latest_pair_counts.most_common(8)]
    if not main_watchlist:
        main_watchlist = [symbol for symbol, _ in pair_counts.most_common(8)]

    candidate_lifecycle = build_candidate_lifecycle(
        ordered,
        blocks=lifecycle_blocks,
        clean_block_seconds=clean_block_seconds,
        window_seconds=candidate_lifecycle_window_seconds,
    )
    v1_clean_block_ledger = _v1_clean_block_ledger_payload(
        lifecycle_blocks,
        clean_block_seconds=clean_block_seconds,
    )
    clean_watch_candidates = v1_clean_block_ledger
    pure_block_ledger = _pure_pressure_ledger_payload(pure_blocks, clean_block_seconds=clean_block_seconds)
    pure_top_blocks = [
        _pure_pressure_block_payload(block, clean_block_seconds)
        for block in rank_pressure_blocks(pure_blocks)[:10]
    ]
    pure_active_candidate = _pure_active_candidate(pure_blocks, clean_block_seconds=clean_block_seconds)
    v1_active_clean_block = _v1_active_clean_block(v1_clean_block_ledger)
    pressure_tier_snapshot = _build_pressure_tier_snapshot(
        events=ordered,
        blocks=lifecycle_blocks,
        symbol_activity=symbol_activity,
        clean_watch_candidates=clean_watch_candidates,
        candidate_lifecycle=candidate_lifecycle,
        theme_scores=theme_scores,
        clean_block_seconds=clean_block_seconds,
        state_metadata=state_metadata,
    )
    clean_block_watch_routes = route_clean_blocks_to_watch(
        clean_watch_candidates,
        market_contexts=market_contexts,
        clean_block_seconds=clean_block_seconds,
    )
    clean_block_watch_entries = [route.payload for route in clean_block_watch_routes if route.emit_as_watch]
    signal_watch_promotion_diagnostics = [
        route.payload for route in clean_block_watch_routes if route.diagnostic
    ]
    lifecycle_candidate = candidate_lifecycle.get("active_candidate")
    latest_ignition_watch = candidate_lifecycle.get("latest_ignition_watch")

    latest_pair_timing_candidate = latest_phase == "PAIR_TIMING_BLOCK"
    pair_timing_candidate = latest_pair_timing_candidate or lifecycle_candidate is not None
    clean_entry_signal = False
    requires_market_context = True
    candidate = (
        _candidate_from_blocks(latest_blocks, clean_block_seconds)
        if latest_pair_timing_candidate
        else lifecycle_candidate
    )  # noqa: F821
    final_mode = _final_mode_from_lifecycle(
        latest_pair_timing_candidate=latest_pair_timing_candidate,
        lifecycle_candidate=lifecycle_candidate,
        latest_ignition_watch=latest_ignition_watch,
        latest_phase=latest_phase,
    )
    main_watchlist = _merge_watchlist(
        _candidate_lifecycle_symbols(candidate_lifecycle),
        main_watchlist,
    )
    validation_source = candidate or pure_active_candidate or {}
    validation_symbol = str(
        (validation_source or {}).get("symbol") or (main_watchlist[0] if main_watchlist else "UNKNOWN")
    )
    validation_direction = (
        _candidate_raw_pressure_direction(validation_source)
        if isinstance(validation_source, dict)
        else None
    ) or _latest_direction_for_symbol(ordered, validation_symbol)
    market_context = _market_context_for_report(market_contexts, validation_symbol)
    market_context_validation = (
        validate_execution_context(market_context).to_dict()
        if market_context is not None
        else missing_market_context_result(validation_symbol, validation_direction).to_dict()
    )
    radar_context_validation = (
        validate_radar_context(market_context).to_dict()
        if market_context is not None
        else validate_radar_context(
            MarketContext(symbol=validation_symbol, raw_allowed_direction=validation_direction)
        ).to_dict()
    )
    allowed_quorum = compute_allowed_quorum(ordered)
    ranked_microboost_blocks = rank_microboost_blocks(
        microboost_blocks,
        clean_block_seconds=clean_block_seconds,
    )
    microboost_summary = build_microboost_summary(
        microboost_blocks,
        window_minutes=microboost_window_minutes,
        clean_block_seconds=clean_block_seconds,
        theme_scores=theme_scores,
        allowed_quorum=allowed_quorum,
        market_contexts=market_contexts,
    )
    _attach_clean_block_source_to_microboost_summary(microboost_summary, clean_watch_candidates)
    _apply_microboost_direction_inheritance(microboost_summary, events=ordered)
    signal_throttle_fusion_v3 = build_signal_throttle_fusion_v3_diagnostic(
        v1_active_clean_block or pure_active_candidate,
        radar_context_validation=radar_context_validation,
        execution_context_validation=market_context_validation,
        microboost_summary=microboost_summary,
    )
    direction_recovery = _direction_recovery_counters(ordered, microboost_summary)
    signal_watch_gate = _signal_watch_gate(candidate, microboost_summary, clean_block_seconds=clean_block_seconds)
    microboost_continuation_entry = _continuation_entry_payload(
        microboost_summary,
        allowed_quorum,
        signal_watch_gate,
    )
    microboost_counter_entry = _counter_entry_payload(microboost_summary, signal_watch_gate)
    microboost_watch_entry = _microboost_watch_payload(
        microboost_summary,
        signal_watch_gate,
        continuation_entry=microboost_continuation_entry,
        counter_entry=microboost_counter_entry,
    )
    pair_eligible_for_analysis = _pair_eligible_for_analysis(
        allowed_quorum=allowed_quorum,
        candidate=candidate,
        main_watchlist=main_watchlist,
    )
    watch_promotion_blockers = _watch_promotion_blockers(
        allowed_quorum=allowed_quorum,
        microboost_summary=microboost_summary,
        signal_watch_gate=signal_watch_gate,
        market_context_validation=market_context_validation,
    )
    microboost_watch_miss_diagnostic = (
        _microboost_watch_miss_diagnostic(microboost_blocks, clean_block_seconds=clean_block_seconds)
        if not microboost_summary.get("latest")
        else None
    )
    microboost_core_event = (
        to_microboost_core_event(microboost_summary["latest"])
        if isinstance(microboost_summary.get("latest"), dict)
        else None
    )
    outcome_memory_summary = (
        summarize_outcome_memory(_outcome_memory_sources(ordered, market_contexts))
        if _env_bool("SIGNAL_OUTCOME_MEMORY_ENABLED", False)
        else None
    )
    regime_invalidation = (
        validate_regime_state(
            symbol=validation_symbol,
            direction=validation_direction,
            market_context=market_context,
            market_context_validation=market_context_validation,
            basket_validation=_basket_validation_from_context(market_context),
            outcome_memory_summary=outcome_memory_summary,
        ).to_dict()
        if _env_bool("SIGNAL_REGIME_INVALIDATION_ENABLED", False)
        else None
    )
    promotion_pressure_cluster_summary = pressure_cluster_summary
    if promotion_pressure_cluster_summary is None and _env_bool("SIGNAL_PROMOTION_SCORE_ENABLED", False):
        promotion_pressure_cluster_summary = summarize_pressure_clusters(ordered)
    promotion_score = (
        score_signal_promotion(
            candidate=candidate,
            allowed_quorum=allowed_quorum,
            microboost_summary=microboost_summary,
            market_context_validation=market_context_validation,
            pressure_cluster_summary=promotion_pressure_cluster_summary,
            outcome_memory_summary=outcome_memory_summary,
            regime_invalidation=regime_invalidation,
        ).to_dict()
        if _env_bool("SIGNAL_PROMOTION_SCORE_ENABLED", False)
        else None
    )
    followthrough_scores = build_signal_throttle_followthrough_scores(
        clean_watch_candidates=clean_watch_candidates,
        pressure_tiers=pressure_tier_snapshot.get("symbols", []),
        market_contexts=market_contexts,
        microboost_summary=microboost_summary,
    )

    return {
        "final_mode": final_mode,
        "clean_entry_signal": clean_entry_signal,
        "pair_timing_candidate": pair_timing_candidate,
        "requires_market_context": requires_market_context,
        "state_warmup": bool(state_metadata.get("state_warmup", False)),
        "first_event_is_continuation": bool(state_metadata.get("first_event_is_continuation", False)),
        "state_warmup_reason": state_metadata.get("state_warmup_reason"),
        "first_event_state": state_metadata.get("first_event_state"),
        "latest_phase": latest_phase,
        "main_watchlist": main_watchlist,
        "watchlist": main_watchlist,
        "active_candidate": candidate_lifecycle.get("active_candidate_symbol"),
        "latest_meaningful_candidate": candidate_lifecycle.get("latest_meaningful_candidate_symbol"),
        "latest_ignition_watch": candidate_lifecycle.get("latest_ignition_watch_symbol"),
        "previous_major_leader": candidate_lifecycle.get("previous_major_leader_symbol"),
        "historical_leader": candidate_lifecycle.get("historical_leader_symbol"),
        "historical_leaders": candidate_lifecycle.get("historical_leaders", []),
        "secondary_candidate": candidate_lifecycle.get("secondary_candidate_symbol"),
        "counter_rotation": candidate_lifecycle.get("counter_rotation"),
        "candidate_lifecycle": candidate_lifecycle,
        "clean_watch_candidates": clean_watch_candidates,
        "clean_block_watch_routes": [route.to_dict() for route in clean_block_watch_routes],
        "clean_block_watch_entries": clean_block_watch_entries,
        "signal_watch_promotion_diagnostics": signal_watch_promotion_diagnostics,
        "dominant_themes": dominant_themes,
        "theme_scores": theme_scores,
        "candidate": candidate,
        "top_microboost": [_microboost_payload(block) for block in ranked_microboost_blocks[:10]],
        "microboost_summary": microboost_summary,
        "microboost_core_event": microboost_core_event,
        "microboost_continuation_entry": microboost_continuation_entry,
        "microboost_counter_entry": microboost_counter_entry,
        "microboost_watch_entry": microboost_watch_entry,
        "microboost_watch_miss_diagnostic": microboost_watch_miss_diagnostic,
        "direction_recovery": direction_recovery,
        "pressure_cluster_summary": pressure_cluster_summary,
        "outcome_memory_summary": outcome_memory_summary,
        "regime_invalidation": regime_invalidation,
        "promotion_score": promotion_score,
        "followthrough_scores": followthrough_scores,
        "signal_watch_gate": signal_watch_gate,
        "allowed_quorum": allowed_quorum,
        "pair_eligible_for_analysis": pair_eligible_for_analysis,
        "watch_promotion_blockers": watch_promotion_blockers,
        "event_counts": event_type_counts,
        "symbol_activity": symbol_activity,
        "burst_symbol_activity": burst_symbol_activity,
        "pure_pressure_blocks": pure_block_ledger,
        "pure_top_blocks": pure_top_blocks,
        "pure_active_candidate": pure_active_candidate,
        "pure_block_ledger": pure_block_ledger,
        "pure_block_count": len(pure_block_ledger),
        "v1_clean_block_ledger": v1_clean_block_ledger,
        "v1_clean_block_count": len(v1_clean_block_ledger),
        "v1_active_clean_block": v1_active_clean_block,
        "clean_block_ledger_source": V1_CLEAN_BLOCK_LEDGER_SOURCE,
        "pressure_tier_snapshot": pressure_tier_snapshot,
        "pressure_tiers": pressure_tier_snapshot.get("symbols", []),
        "pressure_tier_summary": pressure_tier_snapshot.get("summary", {}),
        "time_range": {
            "start_utc": ordered[0].timestamp.isoformat(),
            "end_utc": ordered[-1].timestamp.isoformat(),
            "duration_seconds": (ordered[-1].timestamp - ordered[0].timestamp).total_seconds(),
        },
        "counts": {
            "total_events": len(ordered),
            "severity": dict(severity_counts),
            "verdicts": dict(verdict_counts),
            "event_types": event_type_counts,
            "pairs": dict(pair_counts.most_common()),
        },
        "latest_window": {
            "seconds": latest_window_seconds,
            "event_count": len(latest_events),
            "unique_symbols": len({event.symbol for event in latest_events}),
            "top_pairs": dict(latest_pair_counts.most_common(10)),
            "largest_clean_block_seconds": latest_largest_block,
        },
        "runtime_config": {
            "latest_window_minutes": latest_window_seconds / 60.0,
            "min_clean_block_minutes": clean_block_seconds / 60.0,
            "pure_block_gap_policy": "PAIR_ROTATION_ONLY",
            "pure_block_max_gap_seconds": None,
            "clean_block_ledger_source": V1_CLEAN_BLOCK_LEDGER_SOURCE,
            "clean_block_rule": V1_CLEAN_BLOCK_RULE,
            "legacy_pure_block_rule": V1_CLEAN_BLOCK_LEGACY_RULE,
            "scanner_cycle_max_gap_seconds": scanner_cycle_gap_seconds,
            "burst_block_max_gap_seconds": clean_gap_seconds,
            "microboost_window_minutes": microboost_window_minutes,
            "candidate_lifecycle_window_seconds": candidate_lifecycle_window_seconds,
            "fragmented_min_unique_pairs": fragmented_min_unique_pairs,
            "fragmented_max_clean_block_minutes": fragmented_max_clean_block_minutes,
        },
        "data_quality": _data_quality_block(
            events=ordered,
            source=source,
            source_found=source_found,
            row_count=row_count,
            unparsed_count=unparsed_count,
            timezone_assumption=timezone_assumption,
            state_metadata=state_metadata,
        ),
        "currency_pressure": currency_pressure,
        "top_clean_blocks": [block.to_dict() for block in rank_pressure_blocks(lifecycle_blocks)[:10]],
        "top_pure_rotation_blocks": [block.to_dict() for block in rank_pressure_blocks(pure_blocks)[:10]],
        "top_burst_blocks": [block.to_dict() for block in rank_pressure_blocks(burst_blocks)[:10]],
        "radar_context_validation": radar_context_validation,
        "market_context_validation": market_context_validation,
        "signal_throttle_fusion_v3": signal_throttle_fusion_v3,
        "recommended_action": _recommended_action(latest_phase, candidate_lifecycle),
    }


def analyze_signal_throttle_csv(path: str | Path) -> dict[str, Any]:
    csv_path = Path(path)
    if not csv_path.exists():
        return analyze_signal_throttle_events(
            [],
            source="csv",
            source_found=False,
            row_count=0,
            unparsed_count=0,
        )
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    events = parse_signal_throttle_rows(rows)
    state_metadata = _state_metadata_from_rows(rows, events)
    return analyze_signal_throttle_events(
        events,
        source="csv",
        source_found=True,
        row_count=len(rows),
        unparsed_count=max(0, len(rows) - len(events)),
        state_metadata=state_metadata,
    )


def emit_signal_throttle_raw_event(event: SignalThrottleLogEvent) -> bool:
    """Emit a parseable raw SignalThrottle event on a dedicated runtime lane.

    The analyzer keeps an in-memory ledger, but production log exports also need
    the raw sequence so clean blocks can be reconstructed outside the process.
    This intentionally does not use ``signal_json``.
    """

    if os.getenv("SIGNAL_THROTTLE_RAW_LOG_ENABLED", "true").strip().lower() != "true":
        return False
    message = str(event.message or "").strip()
    if not message:
        return False
    prefix = os.getenv("SIGNAL_THROTTLE_RAW_LOG_PREFIX", DEFAULT_SIGNAL_THROTTLE_RAW_PREFIX)
    if not message.startswith(prefix):
        message = f"{prefix} {message}"
    logger = logging.getLogger(os.getenv("SIGNAL_THROTTLE_RAW_LOGGER", DEFAULT_SIGNAL_THROTTLE_RAW_LOGGER))
    level_name = os.getenv("SIGNAL_THROTTLE_RAW_LOG_LEVEL", DEFAULT_SIGNAL_THROTTLE_RAW_LEVEL).strip().upper()
    level = getattr(logging, level_name, logging.WARNING)
    logger.log(level if isinstance(level, int) else logging.WARNING, _with_raw_lineage_metadata(message, event))
    return True


def _with_raw_lineage_metadata(message: str, event: SignalThrottleLogEvent) -> str:
    parts: list[str] = []
    for key, value in (
        ("deployment_id", event.deployment_id),
        ("scanner_cycle_id", event.scanner_cycle_id),
        ("scanner_epoch", event.scanner_epoch),
        ("observed_cycle_index", event.observed_cycle_index),
    ):
        if value is None or f"{key}=" in message:
            continue
        parts.append(f"{key}={value}")
    if not parts:
        return message
    return f"{message} {' '.join(parts)}"


def _runtime_deployment_id() -> str:
    return os.getenv("RAILWAY_DEPLOYMENT_ID") or os.getenv("DEPLOYMENT_ID") or "unknown"


def _scanner_cycle_id_is_older_than(
    cycle_id: str,
    current_epoch: datetime,
    *,
    keep_windows: int,
    window_seconds: float,
) -> bool:
    match = re.match(r"^SCAN_(?P<stamp>\d{8}T\d{6}Z)_", str(cycle_id or ""))
    if not match:
        return False
    try:
        cycle_epoch = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return False
    return (current_epoch - cycle_epoch).total_seconds() > max(1, keep_windows) * max(1.0, window_seconds)


class SignalThrottleLiveAnalyzer:
    """Process-local live SignalThrottle intelligence buffer.

    Runtime callers should feed structured events here at the same point they
    emit engine logs.  CSV parsing remains only a test/offline import path.
    """

    def __init__(
        self,
        *,
        latest_window_minutes: int = 60,
        latest_window_seconds: int | None = None,
        retention_seconds: int | None = None,
        max_events: int = 20000,
        active_block_ttl_seconds: int = 300,
        clean_gap_seconds: int = 75,
        min_clean_block_minutes: float = 5.0,
        clean_block_seconds: int | None = None,
        microboost_window_minutes: int = 15,
        candidate_lifecycle_window_seconds: int = _DEFAULT_CANDIDATE_LIFECYCLE_WINDOW_SECONDS,
        allowed_quorum_window_seconds: int = 120,
        fragmented_min_unique_pairs: int = 5,
        fragmented_max_clean_block_minutes: float = 1.0,
    ) -> None:
        self.latest_window_seconds = int(latest_window_seconds or latest_window_minutes * 60)
        self.candidate_lifecycle_window_seconds = int(candidate_lifecycle_window_seconds)
        self.retention_seconds = int(
            retention_seconds
            if retention_seconds is not None
            else max(self.latest_window_seconds, self.candidate_lifecycle_window_seconds)
        )
        self.max_events = max_events
        self.active_block_ttl_seconds = active_block_ttl_seconds
        self.clean_gap_seconds = clean_gap_seconds
        self.clean_block_seconds = int(clean_block_seconds or min_clean_block_minutes * 60)
        self.microboost_window_minutes = microboost_window_minutes
        self.allowed_quorum_window_seconds = allowed_quorum_window_seconds
        self.fragmented_min_unique_pairs = fragmented_min_unique_pairs
        self.fragmented_max_clean_block_minutes = fragmented_max_clean_block_minutes
        self.scanner_cycle_window_seconds = _env_float("SIGNAL_THROTTLE_SCANNER_CYCLE_MAX_GAP_SECONDS", 300.0)
        self._scanner_cycle_symbol_order: dict[str, dict[str, int]] = {}
        self._events: deque[SignalThrottleLogEvent] = deque()
        self._lock = threading.Lock()

    def record(self, event: SignalThrottleLogEvent) -> None:
        with self._lock:
            self._events.append(event)
            self._purge_locked(event.timestamp)

    def _record_runtime_event(self, event: SignalThrottleLogEvent) -> None:
        enriched = self._with_runtime_lineage(event)
        self.record(enriched)
        emit_signal_throttle_raw_event(enriched)

    def record_log_event(self, event: dict[str, Any]) -> bool:
        parsed = parse_engine_log_event(event)
        if parsed is None:
            return False
        self.record(parsed)
        return True

    def record_allowed(
        self,
        *,
        symbol: str,
        verdict: str,
        timestamp: datetime | None = None,
    ) -> None:
        now = _coerce_timestamp(timestamp)
        self._record_runtime_event(
            SignalThrottleLogEvent(
                timestamp=now,
                severity="info",
                message=f"[SignalThrottle] {symbol} allowed - verdict {verdict}",
                symbol=symbol.upper(),
                event_type="ALLOWED",
                verdict=verdict,
                direction=normalize_direction(None, verdict),
                raw_verdict=verdict,
                effective_action="ALLOWED",
                count=1,
                remaining=None,
                allowed_streak=1,
                pressure_source="SignalThrottle",
                source_stream="ALLOWED",
                deployment_id=_runtime_deployment_id(),
                eligible_for_pressure_block=True,
                eligible_for_execution=True,
            )
        )

    def record_throttled(
        self,
        *,
        symbol: str,
        verdict: str | None = None,
        count: int | None = None,
        remaining: int | None = None,
        max_signals: int | None = None,
        window_seconds: float | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        now = _coerce_timestamp(timestamp)
        count_text = "?" if count is None else str(count)
        max_text = "?" if max_signals is None else str(max_signals)
        window_text = _format_optional_number(window_seconds)
        self._record_runtime_event(
            SignalThrottleLogEvent(
                timestamp=now,
                severity="error",
                message=(
                    f"[SignalThrottle] {symbol} THROTTLED - "
                    f"{count_text} signals in last {window_text}s (max {max_text})"
                ),
                symbol=symbol.upper(),
                event_type="THROTTLED",
                effective_action="HOLD",
                count=count,
                remaining=remaining,
                max_signals=max_signals,
                window_seconds=window_seconds,
                pressure_source="SignalThrottle",
                source_stream="RAW_THROTTLED",
                deployment_id=_runtime_deployment_id(),
                eligible_for_pressure_block=True,
                eligible_for_execution=False,
                execution_block_reason="signal_throttled",
                throttled_inferred_direction=normalize_direction(None, verdict),
            )
        )
        if verdict:
            remaining_text = "?" if remaining is None else str(remaining)
            self._record_runtime_event(
                SignalThrottleLogEvent(
                    timestamp=now,
                    severity="info",
                    message=(
                        f"[SignalThrottle] {symbol} THROTTLED - verdict {verdict} "
                        f"downgraded to HOLD (count={count_text}, remaining={remaining_text})"
                    ),
                    symbol=symbol.upper(),
                    event_type="DOWNGRADED_TO_HOLD",
                    verdict=verdict,
                    direction=normalize_direction(None, verdict),
                    raw_verdict=verdict,
                    effective_action="HOLD",
                    is_downgraded=True,
                    count=count,
                    remaining=remaining,
                    max_signals=max_signals,
                    window_seconds=window_seconds,
                    pressure_source="SignalThrottle",
                    source_stream="DOWNGRADED",
                    deployment_id=_runtime_deployment_id(),
                    eligible_for_pressure_block=True,
                    eligible_for_execution=False,
                    execution_block_reason="signal_throttled",
                )
            )

    def record_downgraded(
        self,
        *,
        symbol: str,
        verdict: str | None = None,
        direction: str | None = None,
        reason: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Record a directional candidate that was downgraded before throttling."""
        now = _coerce_timestamp(timestamp)
        source_verdict = str(verdict or "").strip().upper() or None
        normalized_direction = normalize_direction(direction, None) or normalize_direction(
            None,
            source_verdict,
        )
        reason_text = f" reason={reason}" if reason else ""
        if source_verdict:
            verdict_text = source_verdict
        elif normalized_direction:
            verdict_text = f"EXECUTE_{normalized_direction}"
        else:
            verdict_text = "UNKNOWN"
        self._record_runtime_event(
            SignalThrottleLogEvent(
                timestamp=now,
                severity="info",
                message=f"[SignalThrottle] {symbol} verdict {verdict_text} downgraded to HOLD{reason_text}",
                symbol=symbol.upper(),
                event_type="DOWNGRADED_TO_HOLD",
                verdict=verdict_text if verdict_text != "UNKNOWN" else None,
                direction=normalized_direction,
                raw_verdict=verdict_text if verdict_text != "UNKNOWN" else None,
                effective_action="HOLD",
                is_downgraded=True,
                pressure_source="SignalThrottle",
                source_stream="DOWNGRADED",
                deployment_id=_runtime_deployment_id(),
                eligible_for_pressure_block=True,
                eligible_for_execution=False,
                execution_block_reason=reason or "downgraded_to_hold",
            )
        )

    def record_pressure_canary(
        self,
        *,
        symbol: str,
        verdict: str | None = None,
        direction: str | None = None,
        reason: str | None = None,
        direction_source: str | None = None,
        direction_confidence: str | None = None,
        direction_inherited: bool = False,
        inherited_direction: str | None = None,
        inherited_direction_age_seconds: float | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """Record non-executable throttle pressure without creating an order signal."""
        now = _coerce_timestamp(timestamp)
        verdict_text = str(verdict or "NO_TRADE").strip().upper() or "NO_TRADE"
        normalized_direction = normalize_direction(direction, None) or normalize_direction(None, verdict_text)
        reason_text = f" reason={reason}" if reason else ""
        direction_text = normalized_direction or "WAIT"
        normalized_inherited = normalize_direction(inherited_direction, None)
        metadata_parts: list[str] = []
        if direction_source:
            metadata_parts.append(f"direction_source={str(direction_source).strip().upper()}")
        if direction_confidence:
            metadata_parts.append(f"direction_confidence={str(direction_confidence).strip().upper()}")
        if direction_inherited:
            metadata_parts.append("direction_inherited=true")
        if normalized_inherited:
            metadata_parts.append(f"inherited_direction={normalized_inherited}")
        if inherited_direction_age_seconds is not None:
            metadata_parts.append(f"inherited_direction_age_seconds={float(inherited_direction_age_seconds):.3f}")
        metadata_text = f" {' '.join(metadata_parts)}" if metadata_parts else ""
        self._record_runtime_event(
            SignalThrottleLogEvent(
                timestamp=now,
                severity="info",
                message=(
                    f"event=signal_throttle_check symbol={symbol.upper()} "
                    f"verdict={verdict_text} direction={direction_text} "
                    f"status=pressure_canary{reason_text}{metadata_text}"
                ),
                symbol=symbol.upper(),
                event_type="PRESSURE_CANARY",
                verdict=verdict_text,
                direction=normalized_direction,
                raw_verdict=verdict_text,
                effective_action="OBSERVE",
                is_downgraded=False,
                pressure_strength="CANARY",
                pressure_source="signal_throttle_check",
                source_stream="CANARY",
                deployment_id=_runtime_deployment_id(),
                eligible_for_pressure_block=True,
                eligible_for_execution=False,
                execution_block_reason=reason or "non_execute_verdict",
                direction_source=str(direction_source).strip().upper() if direction_source else None,
                direction_confidence=str(direction_confidence).strip().upper() if direction_confidence else None,
                direction_inherited=bool(direction_inherited),
                inherited_direction=normalized_inherited,
                inherited_direction_age_seconds=inherited_direction_age_seconds,
            )
        )

    def snapshot(self, *, market_contexts: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
        report = analyze_signal_throttle_events(
            events,
            latest_window_seconds=self.latest_window_seconds,
            clean_gap_seconds=self.clean_gap_seconds,
            clean_block_seconds=self.clean_block_seconds,
            microboost_window_minutes=self.microboost_window_minutes,
            candidate_lifecycle_window_seconds=self.candidate_lifecycle_window_seconds,
            fragmented_min_unique_pairs=self.fragmented_min_unique_pairs,
            fragmented_max_clean_block_minutes=self.fragmented_max_clean_block_minutes,
            market_contexts=market_contexts,
        )
        report.setdefault("runtime_config", {})
        report["runtime_config"]["retention_seconds"] = self.retention_seconds
        report["runtime_config"]["active_block_ttl_seconds"] = self.active_block_ttl_seconds
        report["runtime_config"]["allowed_quorum_window_seconds"] = self.allowed_quorum_window_seconds
        report["runtime_config"]["max_events_in_memory"] = self.max_events
        report["symbol_activity"] = build_symbol_activity(
            events,
            max_gap_seconds=None,
            now=datetime.now(UTC),
        )
        report["burst_symbol_activity"] = build_symbol_activity(
            events,
            max_gap_seconds=self.clean_gap_seconds,
            now=datetime.now(UTC),
        )
        return report

    def _with_runtime_lineage(self, event: SignalThrottleLogEvent) -> SignalThrottleLogEvent:
        scanner_cycle_id, scanner_epoch, observed_cycle_index = self._scanner_cycle_metadata(
            event.timestamp,
            event.symbol,
        )
        values = asdict(event)
        values["deployment_id"] = event.deployment_id or _runtime_deployment_id()
        values["scanner_cycle_id"] = event.scanner_cycle_id or scanner_cycle_id
        values["scanner_epoch"] = event.scanner_epoch or scanner_epoch
        values["observed_cycle_index"] = event.observed_cycle_index or observed_cycle_index
        return SignalThrottleLogEvent(**values)

    def _scanner_cycle_metadata(self, timestamp: datetime, symbol: str) -> tuple[str, str, int]:
        window = max(1.0, float(self.scanner_cycle_window_seconds or 300.0))
        stamp = _coerce_timestamp(timestamp)
        epoch_seconds = int(stamp.timestamp() // window * window)
        epoch = datetime.fromtimestamp(epoch_seconds, tz=UTC)
        scanner_epoch = epoch.isoformat()
        cycle_id = f"SCAN_{epoch.strftime('%Y%m%dT%H%M%SZ')}_{int(window)}S"
        order = self._scanner_cycle_symbol_order.setdefault(cycle_id, {})
        symbol_key = str(symbol or "").upper()
        if symbol_key not in order:
            order[symbol_key] = len(order) + 1
        self._scanner_cycle_symbol_order = {
            key: value
            for key, value in self._scanner_cycle_symbol_order.items()
            if key == cycle_id or not _scanner_cycle_id_is_older_than(key, epoch, keep_windows=3, window_seconds=window)
        }
        return cycle_id, scanner_epoch, order[symbol_key]

    def _purge_locked(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.retention_seconds)
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()
        while len(self._events) > self.max_events:
            self._events.popleft()


def build_pressure_blocks(
    events: Iterable[SignalThrottleLogEvent],
    *,
    max_gap_seconds: int | None = 75,
) -> list[PressureBlock]:
    indexed_events = list(enumerate(sorted(events, key=lambda item: item.timestamp)))
    states: dict[str, tuple[list[SignalThrottleLogEvent], int]] = {}
    blocks: list[PressureBlock] = []

    for index, event in indexed_events:
        state = states.get(event.symbol)
        if state is None:
            states[event.symbol] = ([event], index)
            continue

        current, previous_index = state
        previous = current[-1]
        gap = (event.timestamp - previous.timestamp).total_seconds()
        gap_is_open = max_gap_seconds is not None and gap > max_gap_seconds
        if not gap_is_open and not _has_hard_rotation_interrupt(
            indexed_events=indexed_events,
            symbol=event.symbol,
            previous_index=previous_index,
            current_index=index,
        ):
            current.append(event)
        else:
            blocks.append(_make_block(current))
            current = [event]
        states[event.symbol] = (current, index)

    blocks.extend(_make_block(current) for current, _ in states.values())
    return sorted(blocks, key=lambda block: (block.start, block.symbol))


def build_pure_pressure_blocks(events: Iterable[SignalThrottleLogEvent]) -> list[PressureBlock]:
    """Build the official gap-agnostic Pure Pressure Ledger blocks."""

    return build_pressure_blocks(events, max_gap_seconds=None)


def build_scanner_cycle_pressure_blocks(
    events: Iterable[SignalThrottleLogEvent],
    *,
    max_symbol_gap_seconds: float | None = 300.0,
) -> list[PressureBlock]:
    """Build per-symbol pressure spans for multi-pair scanner streams.

    Production emits many symbols in a repeated scan cycle. In that stream, a
    different symbol between two same-symbol observations is scheduler
    interleaving, not proof that the first symbol stopped carrying pressure.
    This lane preserves same-symbol persistence and only starts a new block
    when that symbol itself goes quiet beyond the scanner-cycle window.
    """

    by_symbol: dict[str, list[SignalThrottleLogEvent]] = {}
    for event in sorted(events, key=lambda item: item.timestamp):
        if event.eligible_for_pressure_block is False:
            continue
        symbol = str(event.symbol or "").upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(event)

    blocks: list[PressureBlock] = []
    for symbol_events in by_symbol.values():
        current: list[SignalThrottleLogEvent] = []
        for event in symbol_events:
            if not current:
                current = [event]
                continue
            gap = (event.timestamp - current[-1].timestamp).total_seconds()
            if max_symbol_gap_seconds is not None and gap > max_symbol_gap_seconds:
                blocks.append(_make_block(current))
                current = [event]
            else:
                current.append(event)
        if current:
            blocks.append(_make_block(current))
    return sorted(blocks, key=lambda block: (block.start, block.symbol))


def build_symbol_activity(
    events: Iterable[SignalThrottleLogEvent],
    *,
    max_gap_seconds: int | None = 75,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    ordered = sorted(events, key=lambda item: item.timestamp)
    if not ordered:
        return {}
    now_utc = _coerce_timestamp(now) if now is not None else ordered[-1].timestamp
    blocks = build_pressure_blocks(ordered, max_gap_seconds=max_gap_seconds)
    latest_event_by_symbol: dict[str, SignalThrottleLogEvent] = {}
    for event in ordered:
        latest_event_by_symbol[event.symbol.upper()] = event

    latest_block_by_symbol: dict[str, PressureBlock] = {}
    for block in blocks:
        latest = latest_block_by_symbol.get(block.symbol.upper())
        if latest is None or block.end >= latest.end:
            latest_block_by_symbol[block.symbol.upper()] = block

    activity: dict[str, dict[str, Any]] = {}
    for symbol, event in latest_event_by_symbol.items():
        block = latest_block_by_symbol.get(symbol)
        idle_seconds = max(0.0, (now_utc - event.timestamp).total_seconds())
        activity[symbol] = {
            "latest_event_utc": event.timestamp.isoformat(),
            "latest_event_type": event.event_type,
            "latest_direction": event.direction,
            "idle_seconds": round(idle_seconds, 3),
            "latest_block_start_utc": None if block is None else block.start.isoformat(),
            "latest_block_end_utc": None if block is None else block.end.isoformat(),
            "latest_block_duration_seconds": None if block is None else block.duration_seconds,
            "latest_block_effective_ticks": None if block is None else block.effective_ticks,
            "latest_block_effective_density_per_minute": (
                None if block is None else block.effective_density_per_minute
            ),
        }
    return activity


def _has_hard_rotation_interrupt(
    *,
    indexed_events: list[tuple[int, SignalThrottleLogEvent]],
    symbol: str,
    previous_index: int,
    current_index: int,
) -> bool:
    previous_event = indexed_events[previous_index][1]
    current_event = indexed_events[current_index][1]
    allowed_seconds = {
        previous_event.timestamp.replace(microsecond=0),
        current_event.timestamp.replace(microsecond=0),
    }
    for _, event in indexed_events[previous_index + 1 : current_index]:
        if event.symbol == symbol:
            continue
        if event.timestamp.replace(microsecond=0) in allowed_seconds:
            continue
        return True
    return False


def rank_pressure_blocks(blocks: Iterable[PressureBlock]) -> list[PressureBlock]:
    return sorted(
        blocks,
        key=lambda block: (
            block.duration_seconds >= 300,
            block.effective_ticks or block.events,
            block.effective_density_per_minute or block.density_per_minute,
            block.events,
        ),
        reverse=True,
    )


def build_candidate_lifecycle(
    events: list[SignalThrottleLogEvent],
    *,
    blocks: list[PressureBlock],
    clean_block_seconds: int,
    window_seconds: int = _DEFAULT_CANDIDATE_LIFECYCLE_WINDOW_SECONDS,
) -> dict[str, Any]:
    if not events:
        return _empty_candidate_lifecycle(window_seconds)

    historical_leaders = _historical_leaders(events)
    cutoff = events[-1].timestamp - timedelta(seconds=window_seconds)
    lifecycle_blocks = [block for block in blocks if block.end >= cutoff]
    meaningful_blocks = [
        block for block in lifecycle_blocks if _is_meaningful_candidate_block(block, clean_block_seconds)
    ]
    latest_meaningful_block = max(
        meaningful_blocks,
        key=lambda block: (block.end, _block_strength_key(block)),
        default=None,
    )

    all_meaningful_blocks = [block for block in blocks if _is_meaningful_candidate_block(block, clean_block_seconds)]
    active_candidate = (
        _candidate_payload_from_block(latest_meaningful_block, clean_block_seconds)
        if latest_meaningful_block is not None
        else None
    )

    latest_ignition_block = max(
        [
            block
            for block in lifecycle_blocks
            if _is_ignition_watch_block(block, clean_block_seconds)
            and (latest_meaningful_block is None or block.end > latest_meaningful_block.end)
        ],
        key=lambda block: (block.end, _block_strength_key(block)),
        default=None,
    )
    latest_ignition_watch = (
        _candidate_payload_from_block(latest_ignition_block, clean_block_seconds)
        if latest_ignition_block is not None
        else None
    )

    previous_blocks = [
        block
        for block in all_meaningful_blocks
        if latest_meaningful_block is not None
        and block.end <= latest_meaningful_block.start
        and block.symbol != latest_meaningful_block.symbol
    ]
    previous_major_block = max(
        [block for block in previous_blocks if _is_major_leader_block(block, clean_block_seconds)],
        key=_block_strength_key,
        default=None,
    )
    previous_major_leader = (
        _candidate_payload_from_block(previous_major_block, clean_block_seconds)
        if previous_major_block is not None
        else None
    )

    secondary_block = max(
        [
            block
            for block in previous_blocks
            if previous_major_block is None or block.symbol != previous_major_block.symbol
        ],
        key=lambda block: (block.end, _block_strength_key(block)),
        default=None,
    )
    secondary_candidate = (
        _candidate_payload_from_block(secondary_block, clean_block_seconds) if secondary_block is not None else None
    )

    counter_rotation_block = _counter_rotation_block(all_meaningful_blocks, latest_meaningful_block)
    counter_rotation = None
    if counter_rotation_block is not None and counter_rotation_block.direction:
        counter_rotation = f"{counter_rotation_block.symbol}_{counter_rotation_block.direction}"

    status = _candidate_lifecycle_status(active_candidate, latest_ignition_watch)
    historical_leader_symbol = historical_leaders[0]["symbol"] if historical_leaders else None
    return {
        "status": status,
        "window_seconds": int(window_seconds),
        "active_candidate": active_candidate,
        "active_candidate_symbol": None if active_candidate is None else active_candidate["symbol"],
        "latest_meaningful_candidate": active_candidate,
        "latest_meaningful_candidate_symbol": None if active_candidate is None else active_candidate["symbol"],
        "latest_ignition_watch": latest_ignition_watch,
        "latest_ignition_watch_symbol": None if latest_ignition_watch is None else latest_ignition_watch["symbol"],
        "previous_major_leader": previous_major_leader,
        "previous_major_leader_symbol": (None if previous_major_leader is None else previous_major_leader["symbol"]),
        "secondary_candidate": secondary_candidate,
        "secondary_candidate_symbol": None if secondary_candidate is None else secondary_candidate["symbol"],
        "counter_rotation": counter_rotation,
        "historical_leader_symbol": historical_leader_symbol,
        "historical_leaders": historical_leaders,
        "reason": _candidate_lifecycle_reason(active_candidate, latest_ignition_watch),
    }


def classify_latest_phase(
    *,
    latest_events: Iterable[SignalThrottleLogEvent],
    latest_largest_block_seconds: float,
    clean_block_seconds: int = 300,
    fragmented_min_unique_pairs: int = 5,
    fragmented_max_clean_block_seconds: float = 60.0,
) -> str:
    latest = list(latest_events)
    if not latest:
        return "NO_RECENT_DATA"
    unique_symbols = len({event.symbol for event in latest})
    if latest_largest_block_seconds >= clean_block_seconds:
        return "PAIR_TIMING_BLOCK"
    if (
        len(latest) >= 100
        and unique_symbols >= fragmented_min_unique_pairs
        and latest_largest_block_seconds <= fragmented_max_clean_block_seconds
    ):
        return "BROAD_ROTATION_FRAGMENTED"
    if unique_symbols >= 3:
        return "THEME_PRESSURE"
    return "LOW_ACTIVITY"


def compute_currency_pressure(events: Iterable[SignalThrottleLogEvent]) -> dict[str, int]:
    pressure: dict[str, int] = {currency: 0 for currency in _CURRENCIES}
    for event in events:
        base_quote = _split_symbol(event.symbol)
        if base_quote is None or event.direction not in {"BUY", "SELL"}:
            continue
        base, quote = base_quote
        sign = 1 if event.direction == "BUY" else -1
        if base in pressure:
            pressure[base] = pressure.get(base, 0) + sign
        if quote in pressure:
            pressure[quote] = pressure.get(quote, 0) - sign
    return pressure


def classify_themes(*, pair_counts: Counter[str], currency_pressure: dict[str, int]) -> list[dict[str, Any]]:
    cross_counts: Counter[str] = Counter()
    for symbol, count in pair_counts.items():
        base_quote = _split_symbol(symbol)
        if base_quote is None:
            continue
        base, quote = base_quote
        if base in _CURRENCIES:
            cross_counts[base] += count
        if quote in _CURRENCIES:
            cross_counts[quote] += count

    themes: list[dict[str, Any]] = []
    for currency, raw_pressure in currency_pressure.items():
        if raw_pressure == 0:
            continue
        cross_events = int(cross_counts.get(currency, 0))
        themes.append(
            {
                "theme": f"{currency}_{'STRENGTH' if raw_pressure > 0 else 'WEAKNESS'}",
                "score": int(abs(raw_pressure) + cross_events),
                "raw_pressure": int(raw_pressure),
                "cross_events": cross_events,
            }
        )
    return sorted(
        themes,
        key=lambda item: (int(item["score"]), abs(int(item["raw_pressure"])), str(item["theme"])),
        reverse=True,
    )[:8]


def _empty_candidate_lifecycle(window_seconds: int) -> dict[str, Any]:
    return {
        "status": "WAIT_FOR_MEANINGFUL_PAIR_BLOCK",
        "window_seconds": int(window_seconds),
        "active_candidate": None,
        "active_candidate_symbol": None,
        "latest_meaningful_candidate": None,
        "latest_meaningful_candidate_symbol": None,
        "latest_ignition_watch": None,
        "latest_ignition_watch_symbol": None,
        "previous_major_leader": None,
        "previous_major_leader_symbol": None,
        "secondary_candidate": None,
        "secondary_candidate_symbol": None,
        "counter_rotation": None,
        "historical_leader_symbol": None,
        "historical_leaders": [],
        "reason": "no_signal_throttle_data",
    }


def _clean_watch_candidates_from_blocks(blocks: list[PressureBlock], clean_block_seconds: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    clean_blocks = [block for block in blocks if block.duration_seconds >= clean_block_seconds]
    for block in sorted(clean_blocks, key=lambda item: (item.end, item.symbol, item.start)):
        payload = _candidate_payload_from_block(block, clean_block_seconds)
        payload["duration_seconds"] = round(block.duration_seconds, 3)
        payload.update(clean_block_lineage_fields(payload, clean_block_seconds=clean_block_seconds))
        key = str(payload.get("source_clean_block_id") or f"{block.symbol}|{block.start}|{block.end}")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(payload)
    return candidates


def _attach_clean_block_source_to_microboost_summary(
    microboost_summary: dict[str, Any],
    clean_watch_candidates: list[dict[str, Any]],
) -> None:
    if not isinstance(microboost_summary, dict) or not clean_watch_candidates:
        return
    blocks = microboost_summary.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict):
                _attach_clean_block_source_to_microboost_block(block, clean_watch_candidates)
    latest = microboost_summary.get("latest")
    if isinstance(latest, dict):
        _attach_clean_block_source_to_microboost_block(latest, clean_watch_candidates)


def _attach_clean_block_source_to_microboost_block(
    block: dict[str, Any],
    clean_watch_candidates: list[dict[str, Any]],
) -> None:
    source = _matching_clean_block_source(block, clean_watch_candidates)
    if source is None:
        return
    source_id = source.get("source_clean_block_id")
    block["source_clean_block_id"] = source_id
    block["source_pressure_block_id"] = source.get("source_pressure_block_id") or source_id
    block["source_signal_throttle_event_range"] = {
        "start_utc": source.get("clean_block_start_utc") or source.get("block_start_utc"),
        "end_utc": source.get("clean_block_end_utc") or source.get("block_end_utc"),
    }
    block["source_age_seconds"] = _source_age_seconds(block, source)
    block["source_lineage_match"] = source.get("source_lineage_match") or "OVERLAP"
    for key in (
        "clean_block_valid",
        "clean_block_start_utc",
        "clean_block_end_utc",
        "clean_block_valid_since_utc",
        "clean_block_duration_seconds",
        "clean_block_event_count",
        "clean_block_direction",
        "source_clean_block_start_utc",
        "source_clean_block_first_valid_end_utc",
        "source_clean_block_latest_end_utc",
        "source_clean_block_latest_duration_seconds",
        "watch_promotion_source",
        "ledger_type",
        "ledger_source",
        "split_rule",
        "gap_policy",
        "scanner_cycle_aware",
        "source_stream_profile",
        "raw_signal_throttle_severity_profile",
        "raw_signal_throttle_error_count",
        "raw_signal_throttle_primary_severity",
        "raw_pressure_origin",
        "raw_signal_throttle_event_count",
        "allowed_events",
        "throttled_events",
        "downgraded_events",
    ):
        if source.get(key) is not None:
            block[key] = source.get(key)


def _matching_clean_block_source(
    block: dict[str, Any],
    clean_watch_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    symbol = str(block.get("symbol") or "").upper()
    if not symbol:
        return None
    block_start = _parse_timestamp(str(block.get("start_utc") or ""))
    block_end = _parse_timestamp(str(block.get("end_utc") or ""))
    matches = []
    for candidate in clean_watch_candidates:
        if str(candidate.get("symbol") or "").upper() != symbol:
            continue
        clean_start = _parse_timestamp(str(candidate.get("clean_block_start_utc") or candidate.get("block_start_utc") or ""))
        clean_end = _parse_timestamp(str(candidate.get("clean_block_end_utc") or candidate.get("block_end_utc") or ""))
        if clean_start is None or clean_end is None:
            continue
        if block_end is not None and clean_start <= block_end <= clean_end:
            matches.append(_lineage_match_payload(candidate, "OVERLAP"))
            continue
        if block_start is not None and block_end is not None and block_start >= clean_start and block_end <= clean_end:
            matches.append(_lineage_match_payload(candidate, "OVERLAP"))
    if matches:
        return max(matches, key=lambda item: str(item.get("clean_block_end_utc") or item.get("block_end_utc") or ""))
    return _recent_same_symbol_clean_block_source(block, clean_watch_candidates)


def _recent_same_symbol_clean_block_source(
    block: dict[str, Any],
    clean_watch_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    symbol = str(block.get("symbol") or "").upper()
    if not symbol:
        return None
    block_end = _parse_timestamp(str(block.get("end_utc") or ""))
    max_age_seconds = max(0.0, _env_float("SIGNAL_THROTTLE_SOURCE_MAX_AGE_SECONDS", 300.0))
    fallback_matches: list[dict[str, Any]] = []
    for candidate in clean_watch_candidates:
        if str(candidate.get("symbol") or "").upper() != symbol:
            continue
        if candidate.get("clean_block_valid") is False:
            continue
        clean_end = _parse_timestamp(str(candidate.get("clean_block_end_utc") or candidate.get("block_end_utc") or ""))
        if clean_end is None:
            continue
        if block_end is not None:
            age_seconds = (block_end - clean_end).total_seconds()
            if age_seconds < 0.0 or age_seconds > max_age_seconds:
                continue
        fallback_matches.append(_lineage_match_payload(candidate, "RECENT_SAME_SYMBOL_CLEAN_BLOCK"))
    return max(
        fallback_matches,
        key=lambda item: str(item.get("clean_block_end_utc") or item.get("block_end_utc") or ""),
        default=None,
    )


def _lineage_match_payload(candidate: dict[str, Any], match_type: str) -> dict[str, Any]:
    payload = dict(candidate)
    payload["source_lineage_match"] = match_type
    return payload


def _source_age_seconds(block: dict[str, Any], source: dict[str, Any]) -> float:
    block_end = _parse_timestamp(str(block.get("end_utc") or ""))
    source_end = _parse_timestamp(
        str(
            source.get("source_clean_block_latest_end_utc")
            or source.get("clean_block_end_utc")
            or source.get("block_end_utc")
            or ""
        )
    )
    if block_end is None or source_end is None:
        return 0.0
    return round(max(0.0, (block_end - source_end).total_seconds()), 3)


def _candidate_payload_from_block(block: PressureBlock, clean_block_seconds: int) -> dict[str, Any]:
    valid_since = block.start + timedelta(seconds=clean_block_seconds)
    role = "latest_meaningful_candidate" if block.duration_seconds >= clean_block_seconds else "latest_ignition_watch"
    raw_pressure_direction = block.direction if block.direction in {"BUY", "SELL"} else None
    payload = {
        "symbol": block.symbol,
        "block_start_utc": block.start.isoformat(),
        "block_end_utc": block.end.isoformat(),
        "valid_since_utc": valid_since.isoformat() if block.duration_seconds >= clean_block_seconds else None,
        "duration_minutes": round(block.duration_seconds / 60.0, 2),
        "density_per_minute": block.density_per_minute,
        "events": block.events,
        "effective_ticks": block.effective_ticks,
        "suppressed_ticks": block.suppressed_ticks,
        "effective_density_per_minute": block.effective_density_per_minute,
        "direction": "UNRESOLVED",
        "raw_pressure_direction": raw_pressure_direction or "NONE",
        "candidate_direction": None,
        "phase": _candidate_phase(block),
        "role": role,
    }
    payload.update(_pressure_profile_payload(block))
    payload.update(_source_profile_payload(block))
    payload.update(clean_block_lineage_fields(payload, clean_block_seconds=clean_block_seconds))
    return payload


def _pure_pressure_block_payload(block: PressureBlock, clean_block_seconds: int) -> dict[str, Any]:
    raw_pressure_direction = block.direction if block.direction in {"BUY", "SELL"} else None
    payload = block.to_dict()
    payload.update(
        {
            "block_start_utc": block.start.isoformat(),
            "block_end_utc": block.end.isoformat(),
            "duration_minutes": round(block.duration_seconds / 60.0, 2),
            "direction": "UNRESOLVED",
            "raw_pressure_direction": raw_pressure_direction or "NONE",
            "candidate_direction": None,
            "pressure_direction": raw_pressure_direction,
            "ledger_type": PURE_PRESSURE_LEDGER_TYPE,
            "ledger_source": PURE_PRESSURE_LEDGER_SOURCE,
            "scanner_cycle_aware": False,
            "pure_block_valid": _is_meaningful_candidate_block(block, clean_block_seconds),
            "source_signal_throttle_event_range": {
                "start_utc": block.start.isoformat(),
                "end_utc": block.end.isoformat(),
            },
            "final_direction": "WAIT",
            "signal_valid": False,
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "advisory_only": True,
        }
    )
    payload.update(_block_direction_metadata_payload(block))
    payload.update(score_pure_pressure_block(block, clean_block_seconds=clean_block_seconds).to_dict())
    payload["ledger_type"] = PURE_PRESSURE_LEDGER_TYPE
    payload["ledger_source"] = PURE_PRESSURE_LEDGER_SOURCE
    payload["scanner_cycle_aware"] = False
    payload["split_rule"] = "PAIR_ROTATION_ONLY"
    payload["gap_policy"] = "QUALITY_ONLY"
    payload["clean_block_min_duration_seconds"] = int(clean_block_seconds)
    payload.update(clean_block_lineage_fields(payload, clean_block_seconds=clean_block_seconds))
    payload["source_pressure_block_id"] = (
        payload.get("source_pressure_block_id") or payload.get("source_clean_block_id")
    )
    return payload


def _pure_pressure_ledger_payload(
    blocks: list[PressureBlock],
    *,
    clean_block_seconds: int,
) -> list[dict[str, Any]]:
    return [_pure_pressure_block_payload(block, clean_block_seconds) for block in blocks]


def _v1_clean_block_ledger_payload(
    blocks: list[PressureBlock],
    *,
    clean_block_seconds: int,
) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for block in sorted(blocks, key=lambda item: (item.end, item.symbol, item.start)):
        if block.duration_seconds < clean_block_seconds:
            continue
        payload = _pure_pressure_block_payload(block, clean_block_seconds)
        payload["ledger_type"] = V1_CLEAN_BLOCK_LEDGER_TYPE
        payload["ledger_source"] = V1_CLEAN_BLOCK_LEDGER_SOURCE
        payload["clean_block_rule"] = V1_CLEAN_BLOCK_RULE
        payload["legacy_pure_block_rule"] = V1_CLEAN_BLOCK_LEGACY_RULE
        payload["scanner_cycle_aware"] = True
        payload["split_rule"] = "SCANNER_CYCLE_AWARE_PAIR_PERSISTENCE"
        payload["gap_policy"] = "SCANNER_CYCLE_QUALITY_ONLY"
        payload["clean_block_min_duration_seconds"] = int(clean_block_seconds)
        payload["allowed_events"] = block.allowed_events
        payload["throttled_events"] = block.throttled_events
        payload["downgraded_events"] = block.downgraded_events
        payload["raw_signal_throttle_event_count"] = block.events
        ledger.append(payload)
    return ledger


def _v1_active_clean_block(ledger: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ledger:
        return None
    return max(
        ledger,
        key=lambda item: (
            str(item.get("clean_block_end_utc") or item.get("block_end_utc") or ""),
            float(item.get("clean_block_duration_seconds") or item.get("duration_seconds") or 0.0),
            int(item.get("effective_ticks") or item.get("events") or 0),
        ),
    )


def _pure_active_candidate(
    blocks: list[PressureBlock],
    *,
    clean_block_seconds: int,
) -> dict[str, Any] | None:
    ranked = rank_pressure_blocks(blocks)
    if not ranked:
        return None
    meaningful = [block for block in ranked if _is_meaningful_candidate_block(block, clean_block_seconds)]
    return _pure_pressure_block_payload((meaningful or ranked)[0], clean_block_seconds)


def _is_meaningful_candidate_block(block: PressureBlock, clean_block_seconds: int) -> bool:
    return block.duration_seconds >= clean_block_seconds


_MICROBOOST_WATCH_MIN_DURATION_SECONDS = 18.0
_MICROBOOST_WATCH_MIN_TICKS = 5
_MICROBOOST_WATCH_MIN_DENSITY = 8.0


def _is_ignition_watch_block(block: PressureBlock, clean_block_seconds: int) -> bool:
    effective_ticks = block.effective_ticks or block.events
    effective_density = block.effective_density_per_minute or block.density_per_minute
    return (
        _MICROBOOST_WATCH_MIN_DURATION_SECONDS <= block.duration_seconds < clean_block_seconds
        and effective_ticks >= _MICROBOOST_WATCH_MIN_TICKS
        and effective_density >= _MICROBOOST_WATCH_MIN_DENSITY
    )


def _microboost_watch_miss_diagnostic(
    blocks: list[PressureBlock], *, clean_block_seconds: int
) -> dict[str, Any] | None:
    """Patch 1/2 (pure -- no logging): explain why the latest microboost block did NOT
    qualify as a watch-eligible block, and whether it WOULD under the looser shadow
    thresholds. The pipeline emits this (flag-gated) so a deployment that produces zero
    SignalWatchJSON is not silent about the reason (window-quiet vs threshold). Diagnostic
    only -- never carries execution intent.
    """
    candidates = [block for block in blocks if block.duration_seconds is not None]
    if not candidates:
        return None
    block = max(candidates, key=lambda item: item.end)
    if _is_ignition_watch_block(block, clean_block_seconds):
        return None
    effective_ticks = int(block.effective_ticks or block.events or 0)
    effective_density = float(block.effective_density_per_minute or block.density_per_minute or 0.0)
    duration = float(block.duration_seconds or 0.0)
    blocked_by: list[str] = []
    if effective_ticks < _MICROBOOST_WATCH_MIN_TICKS:
        blocked_by.append("MICROBOOST_TICKS_BELOW_THRESHOLD")
    if effective_density < _MICROBOOST_WATCH_MIN_DENSITY:
        blocked_by.append("MICROBOOST_DENSITY_BELOW_THRESHOLD")
    if duration < _MICROBOOST_WATCH_MIN_DURATION_SECONDS:
        blocked_by.append("MICROBOOST_DURATION_BELOW_THRESHOLD")
    elif duration >= clean_block_seconds:
        blocked_by.append("MICROBOOST_DURATION_EXCEEDS_CLEAN_BLOCK")
    shadow_ticks = int(_env_float("MICROBOOST_SHADOW_MIN_TICKS", 3.0))
    shadow_density = _env_float("MICROBOOST_SHADOW_MIN_DENSITY", 5.0)
    shadow_duration = _env_float("MICROBOOST_SHADOW_MIN_DURATION_SECONDS", 10.0)
    shadow_watch_candidate = (
        effective_ticks >= shadow_ticks
        and effective_density >= shadow_density
        and duration >= shadow_duration
    )
    return {
        "symbol": block.symbol,
        "raw_direction": block.direction,
        "effective_ticks": effective_ticks,
        "effective_density": round(effective_density, 2),
        "duration_seconds": round(duration, 1),
        "threshold_ticks": _MICROBOOST_WATCH_MIN_TICKS,
        "threshold_density": _MICROBOOST_WATCH_MIN_DENSITY,
        "threshold_duration_seconds": _MICROBOOST_WATCH_MIN_DURATION_SECONDS,
        "eligible_for_watch": False,
        "blocked_by": blocked_by,
        "shadow_watch_candidate": bool(shadow_watch_candidate),
        "shadow_thresholds": {
            "ticks": shadow_ticks,
            "density": shadow_density,
            "duration_seconds": shadow_duration,
        },
    }


def _is_major_leader_block(block: PressureBlock, clean_block_seconds: int) -> bool:
    return block.duration_seconds >= clean_block_seconds * 2 or (block.effective_ticks or block.events) >= 100


def _block_strength_key(block: PressureBlock) -> tuple[float, float, int, int]:
    return (
        float(block.effective_ticks or block.events),
        float(block.effective_density_per_minute or block.density_per_minute),
        int(block.events),
        int(block.duration_seconds),
    )


def _historical_leaders(events: list[SignalThrottleLogEvent], limit: int = 3) -> list[dict[str, Any]]:
    totals: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    for event in events:
        totals[event.symbol] += event.effective_ticks
        rows[event.symbol] += 1
    return [
        {
            "symbol": symbol,
            "effective_ticks": int(effective_ticks),
            "rows": int(rows[symbol]),
            "direction": _latest_direction_for_symbol(events, symbol),
        }
        for symbol, effective_ticks in sorted(
            totals.items(),
            key=lambda item: (int(item[1]), int(rows[item[0]]), item[0]),
            reverse=True,
        )[:limit]
    ]


def _counter_rotation_block(
    blocks: list[PressureBlock],
    active_block: PressureBlock | None,
) -> PressureBlock | None:
    if active_block is None or active_block.direction not in {"BUY", "SELL"}:
        return None
    return max(
        [
            block
            for block in blocks
            if block.direction in {"BUY", "SELL"}
            and block.direction != active_block.direction
            and block.symbol != active_block.symbol
            and block.end <= active_block.start
        ],
        key=lambda block: (block.end, _block_strength_key(block)),
        default=None,
    )


def _candidate_lifecycle_status(
    active_candidate: dict[str, Any] | None,
    latest_ignition_watch: dict[str, Any] | None,
) -> str:
    if active_candidate and latest_ignition_watch:
        return "PAIR_SIGNAL_CANDIDATE_WITH_LATEST_IGNITION"
    if active_candidate:
        return "PAIR_SIGNAL_CANDIDATE_FROM_ROTATION_CONTEXT"
    if latest_ignition_watch:
        return "LATEST_IGNITION_WATCH_ONLY"
    return "WAIT_FOR_MEANINGFUL_PAIR_BLOCK"


def _candidate_lifecycle_reason(
    active_candidate: dict[str, Any] | None,
    latest_ignition_watch: dict[str, Any] | None,
) -> str:
    if active_candidate and latest_ignition_watch:
        return "latest_isolated_ignition_does_not_replace_latest_meaningful_candidate"
    if active_candidate:
        return "latest_meaningful_pair_block_selected_from_rotation_lifecycle"
    if latest_ignition_watch:
        return "latest_pressure_is_ignition_watch_only_until_clean_block_forms"
    return "no_meaningful_pair_block_in_lifecycle_window"


def _candidate_lifecycle_symbols(candidate_lifecycle: dict[str, Any]) -> list[str]:
    symbols = [
        candidate_lifecycle.get("active_candidate_symbol"),
        candidate_lifecycle.get("latest_ignition_watch_symbol"),
        candidate_lifecycle.get("previous_major_leader_symbol"),
        candidate_lifecycle.get("secondary_candidate_symbol"),
    ]
    for leader in candidate_lifecycle.get("historical_leaders", []):
        if isinstance(leader, dict):
            symbols.append(leader.get("symbol"))
    return [str(symbol) for symbol in symbols if symbol]


def _merge_watchlist(priority_symbols: list[str], fallback_symbols: list[str]) -> list[str]:
    merged: list[str] = []
    for symbol in [*priority_symbols, *fallback_symbols]:
        normalized = str(symbol or "").upper()
        if not normalized or normalized in merged:
            continue
        merged.append(normalized)
        if len(merged) >= 8:
            break
    return merged


def _final_mode_from_lifecycle(
    *,
    latest_pair_timing_candidate: bool,
    lifecycle_candidate: dict[str, Any] | None,
    latest_ignition_watch: dict[str, Any] | None,
    latest_phase: str,
) -> str:
    if latest_pair_timing_candidate:
        return "PAIR_SIGNAL_CANDIDATE"
    if lifecycle_candidate and latest_ignition_watch:
        return "PAIR_SIGNAL_CANDIDATE_WITH_LATEST_IGNITION"
    if lifecycle_candidate:
        return "PAIR_SIGNAL_CANDIDATE_FROM_ROTATION_CONTEXT"
    if latest_ignition_watch:
        return "LATEST_IGNITION_WATCH"
    if latest_phase in {"BROAD_ROTATION_FRAGMENTED", "THEME_PRESSURE"}:
        return "THEME_ALERT_AND_PAIR_SELECTION"
    return "THEME_ALERT_AND_PAIR_SELECTION"


def _counter_watch_without_clean_block_ok(latest: dict[str, Any]) -> bool:
    """Increment A (flag default OFF): allow a directional, ignition-class microboost
    block at a main extreme to reach the counter engine even without a 5-minute clean
    throttle block, so short absorption bursts surface as MICROBOOST_COUNTER_ENTRY
    watches (e.g. EARLY_SELL_WATCH) instead of a generic MICROBOOST_WATCH.

    Watch-only: the counter engine is still invoked with watch_only=True, so the
    result keeps ``valid_for_execution=false`` -- this never opens execution. The
    quality bar reuses the already-vetted ignition-watch thresholds (>=18s duration,
    >=5 effective ticks, density >=8/min); it deliberately does NOT lower the bar to
    sub-18s noise. Enable with ``MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK=true``.
    """
    if not _env_bool("MICROBOOST_COUNTER_WATCH_WITHOUT_CLEAN_BLOCK", False):
        return False
    direction = str(latest.get("direction") or latest.get("raw_direction") or "").upper()
    if direction not in {"BUY", "SELL"}:
        return False
    phase_priced = str(latest.get("phase_priced") or "").upper()
    if phase_priced not in {
        "RESISTANCE_PRESSURE_WARNING",
        "EXHAUSTION_AT_RESISTANCE",
        "SUPPORT_PRESSURE_WARNING",
        "EXHAUSTION_AT_SUPPORT",
    }:
        return False
    ticks = latest.get("effective_ticks") or latest.get("effective_tick_count") or 0
    density = latest.get("effective_density_per_minute") or latest.get("effective_density") or 0.0
    duration_minutes = latest.get("duration_minutes") or 0.0
    duration_seconds = duration_minutes * 60.0 if duration_minutes else float(latest.get("duration_seconds") or 0.0)
    return duration_seconds >= 18.0 and float(ticks) >= 5 and float(density) >= 8.0


def _counter_entry_payload(
    microboost_summary: dict[str, Any],
    signal_watch_gate: dict[str, Any],
) -> dict[str, Any] | None:
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return None
    if not signal_watch_gate["eligible"] and not _counter_watch_without_clean_block_ok(latest):
        payload = _blocked_microboost_payload(
            latest,
            signal_family="MICROBOOST_COUNTER_ENTRY",
            signal_watch_gate=signal_watch_gate,
        )
        latest["counter_entry"] = payload
        microboost_summary["counter_entry"] = payload
        return payload
    result = MicroboostCounterEntryEngine(
        min_rr_valid=_env_float("SIGNAL_JSON_MIN_RR_VALID", 2.5),
        tp1_rr_required=_env_float("SIGNAL_JSON_TP1_RR_REQUIRED", 2.0),
        counter_entry_risk_multiplier=_env_float("SIGNAL_JSON_COUNTER_ENTRY_RISK_MULTIPLIER", 0.5),
        counter_entry_expiry_minutes=int(_env_float("SIGNAL_JSON_COUNTER_ENTRY_EXPIRY_MINUTES", 30.0)),
        direct_absorption_enabled=_env_bool("DIRECT_ABSORPTION_VALID_ENABLED", True),
        direct_absorption_require_theme_alignment=_env_bool("DIRECT_ABSORPTION_REQUIRE_THEME_ALIGNMENT", False),
        direct_absorption_require_rr=_env_bool("DIRECT_ABSORPTION_REQUIRE_RR", True),
        allow_rr_fallback=_env_bool("SIGNAL_JSON_ALLOW_RR_FALLBACK", True),
        direction_conflict_resolver_enabled=_env_bool("SIGNAL_DIRECTION_CONFLICT_RESOLVER_ENABLED", False),
    ).evaluate(latest, watch_only=True)
    payload = result.to_dict()
    payload.update(microboost_role_fields_from(latest))
    payload.update(_signal_watch_source_fields(signal_watch_gate, payload["status"] != "NONE"))
    _maybe_attach_structure_preview(payload, latest.get("market_context_snapshot"))
    latest["counter_entry"] = payload
    microboost_summary["counter_entry"] = payload
    return payload


def _continuation_entry_payload(
    microboost_summary: dict[str, Any],
    allowed_quorum: dict[str, Any],
    signal_watch_gate: dict[str, Any],
) -> dict[str, Any] | None:
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return None
    if not signal_watch_gate["eligible"]:
        payload = _blocked_microboost_payload(
            latest,
            signal_family="MICROBOOST_TREND_CONTINUATION",
            signal_watch_gate=signal_watch_gate,
        )
        latest["continuation_entry"] = payload
        microboost_summary["continuation_entry"] = payload
        return payload
    result = MicroboostContinuationEngine(
        min_density_per_minute=_env_float("SIGNAL_JSON_CONTINUATION_MIN_DENSITY", 25.0),
        min_duration_seconds=_env_float("SIGNAL_JSON_CONTINUATION_MIN_DURATION_SECONDS", 60.0),
        min_rr_valid=_env_float("SIGNAL_JSON_MIN_RR_VALID", 2.5),
        tp1_rr_required=_env_float("SIGNAL_JSON_TP1_RR_REQUIRED", 2.0),
        allow_rr_fallback=_env_bool("SIGNAL_JSON_ALLOW_RR_FALLBACK", True),
    ).evaluate(latest, allowed_quorum=allowed_quorum)
    payload = result.to_dict()
    payload.update(microboost_role_fields_from(latest))
    payload.update(_signal_watch_source_fields(signal_watch_gate, payload["status"] != "NONE"))
    latest["continuation_entry"] = payload
    microboost_summary["continuation_entry"] = payload
    return payload


def resolve_signal_watch_headline_from_pattern(
    *,
    raw_direction: str | None,
    price_position: str | None,
    phase_priced: str | None,
    selected_pattern_id: str | None = None,
    entry_permission: str | None = None,
    management_action: str | None = None,
    pattern_family: str | None = None,
    duration_seconds: float | None = None,
    timing_watch_min_seconds: float = 60.0,
) -> dict[str, Any]:
    """Increment C (flag-guarded, default OFF): upgrade a *generic* MICROBOOST_WATCH
    headline into the directional counter scenario it already implies, reusing the
    ``MicroboostCounterEntryEngine`` vocabulary (EARLY_SELL_WATCH / SELL_TIMING_WATCH /
    EARLY_BUY_WATCH / BUY_TIMING_WATCH) instead of inventing new status names.

    Pure function: it returns only headline OVERRIDES; the caller decides whether to
    apply them. It NEVER sets ``valid_for_execution``, NEVER touches ``final_direction``
    (stays WAIT), and NEVER emits a SignalJSON -- this is a classification/language fix,
    not an execution change. ``raw_direction`` is the raw pressure direction and is
    preserved by the caller; ``candidate_direction`` becomes the *scenario* direction
    (the opposite side an absorption watch leans, e.g. BUY-stalled-at-resistance -> SELL).

    Returns ``{"resolved": False}`` when the pattern context is not strong enough to
    justify a direction-aware headline -- the watch then stays a generic MICROBOOST_WATCH.
    """
    raw = str(raw_direction or "").upper()
    if raw not in {"BUY", "SELL"}:
        return {"resolved": False}

    pos = str(price_position or "").upper()
    priced = str(phase_priced or "").upper()
    pattern = str(selected_pattern_id or "").upper()
    permission = str(entry_permission or "").upper()
    mgmt = str(management_action or "").upper()
    pattern_absorption = (
        "ABSORPTION" in pattern
        or "EXHAUSTION" in pattern
        or "EXHAUSTION" in str(pattern_family or "").upper()
    )

    resistance_scenario = (
        raw == "BUY"
        and pos in {"MAIN_RESISTANCE", "UPPER_RANGE"}
        and (
            priced in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"}
            or pattern_absorption
            or permission == "NO_NEW_BUY"
            or "SELL_WATCH" in mgmt
            or "PROTECT_LONG" in mgmt
        )
    )
    support_scenario = (
        raw == "SELL"
        and pos in {"MAIN_SUPPORT", "LOWER_RANGE"}
        and (
            priced in {"SUPPORT_PRESSURE_WARNING", "EXHAUSTION_AT_SUPPORT"}
            or pattern_absorption
            or permission == "NO_NEW_SELL"
            or "BUY_WATCH" in mgmt
            or "PROTECT_SHORT" in mgmt
        )
    )
    if not resistance_scenario and not support_scenario:
        return {"resolved": False}

    timing = duration_seconds is not None and duration_seconds >= timing_watch_min_seconds
    if resistance_scenario:
        scenario_direction = "SELL"
        status = "SELL_TIMING_WATCH" if timing else "EARLY_SELL_WATCH"
        action = "WAIT_REJECTION_OR_BREAKOUT_CONFIRMATION"
        extreme = "MAIN_RESISTANCE"
    else:
        scenario_direction = "BUY"
        status = "BUY_TIMING_WATCH" if timing else "EARLY_BUY_WATCH"
        action = "WAIT_REJECTION_OR_BREAKDOWN_CONFIRMATION"
        extreme = "MAIN_SUPPORT"

    return {
        "resolved": True,
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "resolved_family": "MICROBOOST_COUNTER_ENTRY",
        "status": status,
        "candidate_direction": scenario_direction,
        "watch_direction": scenario_direction,
        "direction_status": "MICROBOOST_COUNTER_ENTRY_WATCH",
        "direction_validation_status": "WATCH_ONLY_PENDING_CONFIRMATION",
        "action": action,
        "requires_m15_close": True,
        "headline_resolve_reason": f"{pattern or 'COUNTER_SCENARIO'}_{raw}_AT_{extreme}",
    }


def _microboost_watch_payload(
    microboost_summary: dict[str, Any],
    signal_watch_gate: dict[str, Any],
    *,
    continuation_entry: dict[str, Any] | None,
    counter_entry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return None
    if _has_emit_candidate(continuation_entry) or _has_emit_candidate(counter_entry):
        return None

    snapshot = latest.get("market_context_snapshot")
    if not isinstance(snapshot, dict):
        return None
    signal_price = _first_number(
        snapshot.get("price_at_signal_end"),
        snapshot.get("price_at_5m_confirm"),
        snapshot.get("price_at_signal_start"),
        snapshot.get("bid"),
        snapshot.get("ask"),
    )
    if signal_price is None:
        return None
    start_price = _first_number(snapshot.get("price_at_signal_start"))
    end_price = _first_number(snapshot.get("price_at_signal_end"))
    entry_zone = sorted(
        {
            round(start_price if start_price is not None else signal_price, 5),
            round(end_price if end_price is not None else signal_price, 5),
            round(signal_price, 5),
        }
    )
    direction = str(latest.get("direction") or "").upper()
    candidate_direction = direction if direction in {"BUY", "SELL"} else None
    clean_block_fallback = False
    if candidate_direction:
        direction_source = "BLOCK_DIRECT"
        direction_confidence = "HIGH"
    else:
        direction_source = str(latest.get("direction_source") or "DIRECTION_MISSING")
        direction_confidence = str(latest.get("direction_confidence") or "NONE")
        inherited_direction = str(latest.get("inherited_direction") or "").upper()
        if inherited_direction in {"BUY", "SELL"}:
            candidate_direction = inherited_direction
        elif signal_watch_gate.get("clean_block_fallback"):
            # Clean-block direction fallback: the clean SignalThrottle block carries a BUY/SELL
            # direction even though microboost has not confirmed it. Use it so the Watch is not
            # skipped (gate already enforced the flag + non-conflict). Stays non-executable.
            gate_direction = str(signal_watch_gate.get("direction") or "").upper()
            if gate_direction in {"BUY", "SELL"}:
                candidate_direction = gate_direction
                direction_source = "CLEAN_BLOCK_DIRECTION_FALLBACK"
                direction_confidence = "CLEAN_BLOCK_CONTEXT"
                clean_block_fallback = True
    watch_resolved_family = "WATCH_ONLY_PENDING_CONTEXT" if candidate_direction else "WATCH_ONLY_DIRECTION_MISSING"
    requires_m15_close = bool(latest.get("inherited_requires_m15_close"))
    signal_time = latest.get("end_utc") or latest.get("start_utc")

    payload = {
        "enabled": True,
        "status": "MICROBOOST_WATCH",
        "signal_family": "MICROBOOST_WATCH",
        "cluster_id": latest.get("cluster_id"),
        "symbol": str(latest.get("symbol") or "").upper(),
        "raw_direction": candidate_direction,
        "candidate_direction": candidate_direction,
        "validated_direction": None,
        "watch_direction": candidate_direction,
        "direction_source": direction_source,
        "direction_confidence": direction_confidence,
        "resolved_family": watch_resolved_family,
        "requires_m15_close": requires_m15_close,
        "direction_inheritance_window_seconds": _env_float("MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS", 600.0),
        "final_direction": "WAIT",
        "direction_status": "MICROBOOST_WAIT_STATE",
        "direction_validation_status": "WATCH_ONLY_PENDING_CONFIRMATION",
        "action": latest.get("action") or "WAIT_MARKET_CONTEXT_OR_STRUCTURE_CONFIRMATION",
        "reason": latest.get("reason") or signal_watch_gate["reason"],
        "signal_valid_time": signal_time,
        "signal_valid_time_utc": signal_time,
        "signal_valid_price": signal_price,
        "entry_reference_price": signal_price,
        "entry_zone": entry_zone or [signal_price],
        "price_position": latest.get("price_position") or snapshot.get("price_position"),
        "m15_phase": latest.get("m15_phase") or snapshot.get("m15_phase"),
        "h1_phase": latest.get("h1_phase") or snapshot.get("h1_phase"),
        "phase_unpriced": latest.get("phase_unpriced"),
        "phase_priced": latest.get("phase_priced"),
        "effective_ticks": latest.get("effective_tick_count") or latest.get("effective_ticks"),
        "effective_density": latest.get("effective_density_per_minute") or latest.get("effective_density"),
        "duration_minutes": latest.get("duration_minutes"),
        "rr_status": "WATCH",
        "market_context_applied": True,
        "valid_for_execution": False,
        "requires_market_context": bool(latest.get("requires_market_context", False)),
        "confidence_bucket": "MICROBOOST_WATCH_ONLY",
        "emit_reason": "MICROBOOST_WAIT_STATE",
        "signal_quality": "WATCH_ONLY",
        **microboost_role_fields_from(latest),
        **_golden_pattern_fields(latest),
        **_signal_watch_source_fields(signal_watch_gate, bool(signal_watch_gate.get("eligible"))),
    }
    if candidate_direction and not clean_block_fallback and _env_bool("SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED", False):
        duration_minutes = latest.get("duration_minutes")
        duration_seconds = (
            float(duration_minutes) * 60.0
            if duration_minutes
            else float(latest.get("duration_seconds") or 0.0)
        )
        headline = resolve_signal_watch_headline_from_pattern(
            raw_direction=candidate_direction,
            price_position=payload.get("price_position"),
            phase_priced=latest.get("phase_priced"),
            selected_pattern_id=latest.get("selected_pattern_id"),
            entry_permission=latest.get("entry_permission"),
            management_action=latest.get("management_action"),
            pattern_family=latest.get("pattern_family"),
            duration_seconds=duration_seconds,
            timing_watch_min_seconds=_env_float("SIGNAL_JSON_TIMING_WATCH_MIN_SECONDS", 60.0),
        )
        if headline.get("resolved"):
            # raw_direction stays the raw pressure side; candidate/headline become the
            # counter scenario. final_direction (WAIT) + valid_for_execution (False) are
            # deliberately NOT in `headline`, so they are never touched here.
            payload.update({key: value for key, value in headline.items() if key != "resolved"})
            _apply_direction_conflict_resolution_to_watch_payload(payload, snapshot)
    _maybe_attach_structure_preview(payload, snapshot)
    if clean_block_fallback and candidate_direction in {"BUY", "SELL"}:
        _apply_clean_block_fallback_branding(payload, candidate_direction)
    latest["microboost_watch"] = payload
    microboost_summary["watch_entry"] = payload
    return payload


def _apply_direction_conflict_resolution_to_watch_payload(payload: dict[str, Any], snapshot: dict[str, Any]) -> None:
    if not _env_bool("SIGNAL_DIRECTION_CONFLICT_RESOLVER_ENABLED", False):
        return
    resolution = resolve_direction_conflict(
        symbol=str(payload.get("symbol") or ""),
        raw_direction=payload.get("raw_direction"),
        candidate_direction=payload.get("candidate_direction") or payload.get("watch_direction"),
        market_context=snapshot,
        basket_validation=snapshot.get("basket_validation") if isinstance(snapshot, dict) else None,
    )
    payload["direction_conflict"] = resolution.direction_conflict
    payload["raw_direction_supported"] = resolution.raw_direction_status == "SUPPORTS_RAW_DIRECTION"
    payload["counter_direction_allowed"] = resolution.counter_direction_allowed
    payload["counter_direction_block_reason"] = resolution.counter_direction_block_reason
    payload["direction_conflict_resolution"] = resolution.to_dict()
    if resolution.counter_direction_allowed:
        return
    raw = resolution.raw_direction
    payload["status"] = "MICROBOOST_WATCH"
    payload["signal_family"] = "MICROBOOST_WATCH"
    payload["resolved_family"] = "WATCH_ONLY_DIRECTION_CONFLICT"
    payload["candidate_direction"] = raw
    payload["watch_direction"] = raw
    payload["final_direction"] = "WAIT"
    payload["direction_status"] = "COUNTER_DIRECTION_BLOCKED_BY_RAW_BASKET"
    payload["direction_validation_status"] = "COUNTER_DIRECTION_BLOCKED_BY_RAW_BASKET"
    payload["action"] = resolution.action
    payload["reason"] = resolution.counter_direction_block_reason or "counter_direction_blocked_by_direction_conflict"
    payload["valid_for_execution"] = False
    payload["signal_quality"] = "WATCH_ONLY"


def _apply_clean_block_fallback_branding(payload: dict[str, Any], direction: str) -> None:
    """Clean-block direction fallback Watch (flag-guarded, default OFF).

    A valid clean SignalThrottle block with its own direction MUST surface as a Watch even when
    microboost has not confirmed the timing. Watch-only: final stays WAIT / non-executable, and a
    ``market_structure`` PENDING object is always attached so downstream is never blind. Never an
    entry command -- execution stays blocked until structure/tradeplan/RR/final gate pass.
    """
    side = "BUY" if direction == "BUY" else "SELL"
    payload["status"] = f"CLEAN_BLOCK_{side}_WATCH"
    payload["signal_family"] = f"CLEAN_BLOCK_{side}_WATCH"
    payload["resolved_family"] = "CLEAN_BLOCK_DIRECTION_FALLBACK"
    payload["raw_direction"] = direction
    payload["candidate_direction"] = direction
    payload["watch_direction"] = direction
    payload["validated_direction"] = None
    payload["final_direction"] = "WAIT"
    payload["action"] = "WAIT_PRICE_THEME_STRUCTURE"
    payload["direction_validation_status"] = "CLEAN_BLOCK_DIRECTION_FALLBACK_PENDING_STRUCTURE"
    payload["rr_status"] = "UNVALIDATED"
    payload["confidence_bucket"] = "CLEAN_BLOCK_WATCH_ONLY"
    payload["signal_quality"] = "WATCH_ONLY"
    payload["signal_valid"] = False
    payload["tradeplan_valid"] = False
    payload["execution_valid_now"] = False
    payload["valid_for_execution"] = False
    payload["is_final_signal"] = False
    payload["reason"] = "clean_block_watch_requires_structure_context_but_execution_not_authorized"
    # Mandatory market_structure object -- attached as PENDING when no richer structure exists,
    # independent of SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED, so a clean-block Watch is never
    # emitted structure-blind. setdefault keeps any real structure already attached upstream.
    payload.setdefault(
        "market_structure",
        {
            "structure_ready": False,
            "structure_source": "CLEAN_BLOCK_CONTEXT",
            "structure_bias": f"{side}_WATCH",
            "market_structure_status": "PENDING_PRICE_THEME_STRUCTURE",
            "invalidation_level": None,
            "key_support": None,
            "key_resistance": None,
            "reason": "clean_block_watch_requires_structure_context_but_execution_not_authorized",
        },
    )


def _maybe_attach_structure_preview(payload: dict[str, Any], snapshot: Any) -> None:
    """P2A (flag-guarded, default OFF): attach a NON-EXECUTABLE structure view to a watch
    payload. Two independent layers, both default OFF and both byte-for-byte no-ops:

    * ``SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED`` (P2A-General) -> EVERY official
      ``*_WATCH`` gets ``market_structure_status`` + ``structure_class`` +
      ``structure_pending_reason``, plus a directional ``tradeplan_preview`` when a
      candidate direction and structure exist (else an explicit incomplete preview).
    * ``SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED`` (P2A Opsi A) -> EARLY_SELL_WATCH only.

    NEVER changes status / final_direction / requires_m15_close / valid_for_execution and
    never emits a SignalJSON. Market structure -- not the pattern name -- is the reference:
    if structure is ready a preview is built, otherwise the watch explains what is missing.
    """
    if _env_bool("SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED", False):
        block = _market_structure_general(payload, snapshot)
        if block:
            payload.update(block)
        return
    if _env_bool("SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED", False):
        preview = _market_structure_preview(payload, snapshot)
        if preview:
            payload.update(preview)


PREVIEW_MIN_TP1_RR = 1.5
# A structural SL must be a real swing/zone invalidation. If TP1 clears RR far beyond this
# ceiling the SL is sub-structural (noise-tight) -- e.g. a degenerate intraday level with the
# resistance/support ladder missing -- so the preview is held PENDING instead of presenting a
# fake STRUCTURE_READY with an implausible RR. Tunable; the real fix is an H4/Daily swing feed.
PREVIEW_MAX_TP1_RR = 6.0
# A structural SL must also clear noise in ABSOLUTE terms -- a 1-2 pip "invalidation" a tick
# from entry is a degenerate micro-box, not structure (RR can still sit in-band). Require the
# SL distance >= max(noise floor, a fraction of the M15 candle range as a volatility proxy).
PREVIEW_MIN_SL_PIPS = 3.0
PREVIEW_MIN_SL_M15_RANGE_FRAC = 0.4


def _preview_pip_size(payload: dict[str, Any], snap: dict[str, Any]) -> float:
    raw_cal = payload.get("pair_calibration")
    cal: dict[str, Any] = raw_cal if isinstance(raw_cal, dict) else {}
    pip = _first_number(cal.get("pip_size"), snap.get("pip_value"))
    if pip:
        return float(pip)
    return 0.01 if str(payload.get("symbol") or "").upper().endswith("JPY") else 0.0001


def _directional_structure_preview(payload: dict[str, Any], snap: dict[str, Any], direction: str) -> dict[str, Any]:
    """Symmetric structural preview core (SELL or BUY).

    SELL: SL is a resistance ABOVE entry (invalidation), targets are the support ladder
    BELOW. BUY: SL is a support BELOW entry, targets are the resistance ladder ABOVE.
    SL is structural-only (never a buffer); TP1 must clear RR >= PREVIEW_MIN_TP1_RR or the
    nearer level becomes ``nearby_structure_marker``. No fabricated levels;
    ``execution_usable`` is always False. Returns the public {market_structure,
    tradeplan_preview} plus internal ``_structure_ready/_sl/_tp1`` (stripped by callers).
    """
    entry = _first_number(payload.get("signal_valid_price"), payload.get("entry_reference_price"))
    pip = _preview_pip_size(payload, snap)
    if direction == "SELL":
        setup_type = "SELL_REJECTION_WATCH"
        sl_sources = (
            ("MARKET_STRUCTURE_RESISTANCE_HIGH", snap.get("resistance_high")),
            ("MARKET_STRUCTURE_KEY_RESISTANCE", snap.get("key_resistance")),
            ("MARKET_STRUCTURE_MAIN_RESISTANCE", snap.get("main_resistance")),
        )
        tp_raw = (snap.get("tp1_support"), snap.get("tp2_support"), snap.get("tp3_support"))
        key_level = _first_number(snap.get("key_resistance"), snap.get("main_resistance"), snap.get("resistance_high"))
        nearest_level = _first_number(snap.get("key_support"), snap.get("main_support"), snap.get("support_low"))
        key_name, nearest_name = "key_resistance", "nearest_support"
    else:  # BUY
        setup_type = "BUY_RECLAIM_WATCH"
        sl_sources = (
            ("MARKET_STRUCTURE_SUPPORT_LOW", snap.get("support_low")),
            ("MARKET_STRUCTURE_KEY_SUPPORT", snap.get("key_support")),
            ("MARKET_STRUCTURE_MAIN_SUPPORT", snap.get("main_support")),
        )
        tp_raw = (snap.get("tp1_resistance"), snap.get("tp2_resistance"), snap.get("tp3_resistance"))
        key_level = _first_number(snap.get("key_support"), snap.get("main_support"), snap.get("support_low"))
        nearest_level = _first_number(snap.get("key_resistance"), snap.get("main_resistance"), snap.get("resistance_high"))
        key_name, nearest_name = "key_support", "nearest_resistance"

    sl = None
    sl_source = "MISSING_STRUCTURE_INVALIDATION"
    for source, raw in sl_sources:
        value = _first_number(raw)
        if value is None or entry is None:
            continue
        if (direction == "SELL" and value > entry) or (direction == "BUY" and value < entry):
            sl, sl_source = value, source
            break

    risk = abs(sl - entry) if (sl is not None and entry is not None and sl != entry) else None

    def _rr(level: float) -> float | None:
        if entry is None or risk is None:
            return None
        return (entry - level) / risk if direction == "SELL" else (level - entry) / risk

    on_profit_side = [
        t
        for t in (_first_number(x) for x in tp_raw)
        if t is not None and entry is not None and (t < entry if direction == "SELL" else t > entry)
    ]
    candidates = sorted(set(on_profit_side), reverse=(direction == "SELL"))
    nearby_marker = None
    targets: list[float] = []
    for target in candidates:
        target_rr = _rr(target)
        if risk and not targets and target_rr is not None and target_rr < PREVIEW_MIN_TP1_RR:
            if nearby_marker is None:
                nearby_marker = target
            continue
        targets.append(target)
    tp1 = targets[0] if targets else None
    tp2 = targets[1] if len(targets) > 1 else None
    tp3 = targets[2] if len(targets) > 2 else None
    risk_pips = round(risk / pip, 1) if (risk and pip) else None
    tp1_rr = _rr(tp1) if tp1 is not None else None
    rr_to_tp1 = round(tp1_rr, 2) if tp1_rr is not None else None
    # Minimum structural SL distance: a real invalidation must clear noise/volatility, not sit a
    # tick from entry. Volatility proxy = M15 candle range; backstopped by an absolute pip floor.
    m15_hi, m15_lo = _first_number(snap.get("m15_high")), _first_number(snap.get("m15_low"))
    m15_range_pips = (m15_hi - m15_lo) / pip if (m15_hi is not None and m15_lo is not None and m15_hi > m15_lo) else None
    min_sl_pips = max(PREVIEW_MIN_SL_PIPS, PREVIEW_MIN_SL_M15_RANGE_FRAC * m15_range_pips) if m15_range_pips else PREVIEW_MIN_SL_PIPS
    sl_too_tight = risk_pips is not None and risk_pips < min_sl_pips
    structure_ready = bool(
        sl is not None
        and rr_to_tp1 is not None
        and PREVIEW_MIN_TP1_RR <= rr_to_tp1 <= PREVIEW_MAX_TP1_RR
        and not sl_too_tight
    )

    market_structure = {
        "structure_bias": setup_type,
        "price_position": payload.get("price_position"),
        key_name: key_level,
        "invalidation_level": sl,
        nearest_name: nearest_level,
        "structure_ready": structure_ready,
    }
    tradeplan_preview = {
        "setup_type": setup_type,
        "entry_zone": payload.get("entry_zone"),
        "sl": sl,
        "sl_source": sl_source,
        "invalidation_level": sl,
        "nearby_structure_marker": nearby_marker,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "risk_pips": risk_pips,
        "rr_to_tp1": rr_to_tp1,
        "target_mode": "STRUCTURE_PREVIEW" if structure_ready else "PREVIEW_CONTEXT_INCOMPLETE",
        "execution_usable": False,
    }
    always = {"setup_type", "entry_zone", "sl", "sl_source", "invalidation_level", "target_mode", "execution_usable"}
    return {
        "market_structure": {key: value for key, value in market_structure.items() if value is not None},
        "tradeplan_preview": {
            key: value for key, value in tradeplan_preview.items() if key in always or value is not None
        },
        "_structure_ready": structure_ready,
        "_sl": sl,
        "_tp1": tp1,
        "_rr_to_tp1": rr_to_tp1,
        "_sl_too_tight": sl_too_tight,
    }


def _structure_pending_reasons(
    payload: dict[str, Any], direction: str, sl: Any, tp1: Any, rr_to_tp1: Any = None, sl_too_tight: bool = False
) -> list[str]:
    """Explain WHY structure is not ready, from existing payload fields (no HTF feed needed)."""
    reasons: list[str] = []
    h1 = str(payload.get("h1_phase") or "").upper()
    m15 = str(payload.get("m15_phase") or "").upper()
    pos = str(payload.get("price_position") or "").upper()
    if direction == "BUY":
        if "DOWN" in h1 or "BEAR" in h1:
            reasons.append("H1_DOWNTREND_CONFLICT")
        if "LOWER_HIGH" in m15 or "BEARISH" in m15:
            reasons.append("M15_LOWER_HIGH_NOT_RECLAIMED")
    elif direction == "SELL":
        if "UP" in h1 or "BULL" in h1:
            reasons.append("H1_UPTREND_CONFLICT")
        if "HIGHER_LOW" in m15 or "BULLISH" in m15:
            reasons.append("M15_HIGHER_LOW_NOT_BROKEN")
    if pos == "MID_RANGE":
        reasons.append("MID_RANGE_NO_STRUCTURAL_ENTRY_ZONE")
    if sl is None:
        reasons.append("STRUCTURAL_SL_NOT_AVAILABLE")
    elif sl_too_tight or (rr_to_tp1 is not None and rr_to_tp1 > PREVIEW_MAX_TP1_RR):
        # SL exists but is degenerate -- either too tight in absolute/volatility terms (a tick
        # from entry) or implausibly tight vs the first target (RR ceiling). Not a real structural
        # invalidation; needs a wider swing/HTF level (resistance/support ladder missing).
        reasons.append("STRUCTURAL_SL_TOO_TIGHT")
    if tp1 is None:
        reasons.append("STRUCTURAL_TARGET_NOT_AVAILABLE")
    return reasons


def _structure_class(payload: dict[str, Any], direction: str) -> str:
    pos = str(payload.get("price_position") or "").upper()
    h1 = str(payload.get("h1_phase") or "").upper()
    if direction == "SELL":
        if pos in {"MAIN_RESISTANCE", "UPPER_RANGE"}:
            return "COUNTER_PRESSURE_AT_RESISTANCE"
        if "DOWN" in h1 or "BEAR" in h1:
            return "SELL_CONTINUATION_CONTEXT"
        return "SELL_RECLAIM_REQUIRED"
    if direction == "BUY":
        if pos in {"MAIN_SUPPORT", "LOWER_RANGE"}:
            return "COUNTER_PRESSURE_AT_SUPPORT"
        if "UP" in h1 or "BULL" in h1:
            return "BUY_CONTINUATION_CONTEXT"
        return "BUY_RECLAIM_REQUIRED"
    return "DIRECTION_PENDING"


def _market_structure_general(payload: dict[str, Any], snapshot: Any) -> dict[str, Any] | None:
    """P2A-General: every official ``*_WATCH`` gets a market_structure_status. When a
    candidate direction + structure exist -> directional preview + STRUCTURE_READY/PENDING;
    when direction is unresolved -> STRUCTURE_PENDING with DIRECTION_NOT_RESOLVED. Never
    fabricates SL/TP and never opens execution."""
    if not str(payload.get("status") or "").endswith("_WATCH"):
        return None
    snap = snapshot if isinstance(snapshot, dict) else {}
    direction = str(payload.get("candidate_direction") or payload.get("watch_direction") or "").upper()
    if direction in {"BUY", "SELL"}:
        core = _directional_structure_preview(payload, snap, direction)
        ready = bool(core["_structure_ready"])
        market_structure = dict(core["market_structure"])
        market_structure["market_structure_status"] = "STRUCTURE_READY" if ready else "STRUCTURE_PENDING"
        market_structure["structure_class"] = _structure_class(payload, direction)
        if not ready:
            reasons = _structure_pending_reasons(
                payload, direction, core["_sl"], core["_tp1"], core["_rr_to_tp1"], core["_sl_too_tight"]
            )
            if reasons:
                market_structure["structure_pending_reason"] = reasons
        return {"market_structure": market_structure, "tradeplan_preview": core["tradeplan_preview"]}

    # Direction not resolved: explain why, no directional plan.
    reasons = ["DIRECTION_NOT_RESOLVED", *_structure_pending_reasons(payload, direction, None, None)]
    market_structure = {
        "structure_bias": "DIRECTION_PENDING",
        "price_position": payload.get("price_position"),
        "structure_ready": False,
        "market_structure_status": "STRUCTURE_PENDING",
        "structure_class": "DIRECTION_PENDING",
        "structure_pending_reason": reasons,
    }
    tradeplan_preview = {
        "setup_type": "STRUCTURE_PENDING",
        "entry_zone": payload.get("entry_zone"),
        "sl": None,
        "sl_source": "MISSING_STRUCTURE_INVALIDATION",
        "tp1": None,
        "rr_to_tp1": None,
        "target_mode": "PREVIEW_CONTEXT_INCOMPLETE",
        "execution_usable": False,
    }
    return {
        "market_structure": {key: value for key, value in market_structure.items() if value is not None},
        "tradeplan_preview": tradeplan_preview,
    }


def _market_structure_preview(payload: dict[str, Any], snapshot: Any) -> dict[str, Any] | None:
    """P2A Opsi A: build ``{market_structure, tradeplan_preview}`` for an EARLY_SELL_WATCH
    via the shared directional core (SELL). Returns None for any other status. SL is the
    structural invalidation only; see ``_directional_structure_preview``.
    """
    if str(payload.get("status") or "") != "EARLY_SELL_WATCH":
        return None
    snap = snapshot if isinstance(snapshot, dict) else {}
    core = _directional_structure_preview(payload, snap, "SELL")
    return {"market_structure": core["market_structure"], "tradeplan_preview": core["tradeplan_preview"]}


def _price_phase_consistency(
    direction: str,
    *,
    m15_phase: Any,
    h1_phase: Any,
    price_position: Any,
    phase_priced: Any,
) -> str:
    """Classify an inherited direction against price phase: CONSISTENT / AMBIGUOUS / CONFLICT.

    First-pass heuristic (tunable). CONFLICT = hard-opposite context (reject inheritance);
    CONSISTENT = phase affirmatively aligned (inherit, MEDIUM); AMBIGUOUS = insufficient/neutral
    phase (inherit but LOW + requires_m15_close).
    """
    d = str(direction or "").upper()
    m15 = str(m15_phase or "").upper()
    h1 = str(h1_phase or "").upper()
    pos = str(price_position or "").upper()
    priced = str(phase_priced or "").upper()
    if d == "BUY":
        if (
            (pos == "MAIN_RESISTANCE" and priced == "RESISTANCE_PRESSURE_WARNING")
            or m15 in {"BEARISH_BREAKDOWN", "STRONG_BEARISH"}
            or h1 == "DOWNTREND_STRONG"
        ):
            return "CONFLICT"
        if "BULL" in h1 or "UPTREND" in h1 or "BULL" in m15:
            return "CONSISTENT"
        return "AMBIGUOUS"
    if d == "SELL":
        if (
            (pos == "MAIN_SUPPORT" and priced == "SUPPORT_RECLAIM_WARNING")
            or m15 in {"BULLISH_BREAKOUT", "STRONG_BULLISH"}
            or h1 == "UPTREND_STRONG"
        ):
            return "CONFLICT"
        if "BEAR" in h1 or "DOWNTREND" in h1 or "BEAR" in m15:
            return "CONSISTENT"
        return "AMBIGUOUS"
    return "AMBIGUOUS"


def resolve_microboost_direction(
    latest: dict[str, Any],
    *,
    events: Iterable[Any],
    now: datetime | None = None,
    window_seconds: float = 600.0,
) -> dict[str, Any]:
    """Resolve a microboost block's direction, inheriting from the nearest directional
    SignalThrottleIntel events when the block itself is directionless.

    Pure + deterministic. Inheritance NEVER promotes execution -- callers keep
    ``valid_for_execution=false`` and use the result only to open classification.

    Guards (locked by review addendum v2):
      * same symbol, within ``window_seconds``;
      * mixed BUY+SELL in window -> DIRECTION_CONFLICT_RECENT_INTEL (REJECTED);
      * no directional intel in window -> DIRECTION_MISSING (NONE);
      * price-phase conflict -> DIRECTION_CONFLICT_PRICE_PHASE (REJECTED);
      * price-phase ambiguous -> INHERITED_BUT_PHASE_AMBIGUOUS (LOW, requires_m15_close).
    """
    block_direction = str(latest.get("direction") or "").upper()
    if block_direction in {"BUY", "SELL"}:
        return {
            "inherited_direction": block_direction,
            "direction_source": "BLOCK_DIRECT",
            "direction_confidence": "HIGH",
        }

    symbol = str(latest.get("symbol") or "").upper()
    events_list = list(events)
    reference = now
    if reference is None:
        stamps = [getattr(ev, "timestamp", None) for ev in events_list]
        stamps = [stamp for stamp in stamps if stamp is not None]
        reference = max(stamps) if stamps else None

    directions: set[str] = set()
    had_symbol_directional = False
    for event in events_list:
        event_symbol = str(getattr(event, "symbol", "") or "").upper()
        event_direction = str(getattr(event, "direction", "") or "").upper()
        if event_symbol != symbol or event_direction not in {"BUY", "SELL"}:
            continue
        had_symbol_directional = True
        event_time = getattr(event, "timestamp", None)
        if reference is not None and event_time is not None:  # noqa: SIM102
            if (reference - event_time).total_seconds() > window_seconds:
                continue
        directions.add(event_direction)

    if not directions:
        # Separate "had directional intel but stale (outside window)" from "no intel at all"
        # so canary counters can distinguish stale_intel_count vs direction_missing_count.
        source = "DIRECTION_STALE_INTEL" if had_symbol_directional else "DIRECTION_MISSING"
        return {"inherited_direction": None, "direction_source": source, "direction_confidence": "NONE"}
    if len(directions) > 1:
        return {
            "inherited_direction": None,
            "direction_source": "DIRECTION_CONFLICT_RECENT_INTEL",
            "direction_confidence": "REJECTED",
        }

    candidate = next(iter(directions))
    consistency = _price_phase_consistency(
        candidate,
        m15_phase=latest.get("m15_phase"),
        h1_phase=latest.get("h1_phase"),
        price_position=latest.get("price_position"),
        phase_priced=latest.get("phase_priced"),
    )
    if consistency == "CONFLICT":
        return {
            "inherited_direction": None,
            "direction_source": "DIRECTION_CONFLICT_PRICE_PHASE",
            "direction_confidence": "REJECTED",
        }
    if consistency == "AMBIGUOUS":
        return {
            "inherited_direction": candidate,
            "direction_source": "INHERITED_BUT_PHASE_AMBIGUOUS",
            "direction_confidence": "LOW",
            "requires_m15_close": True,
        }
    return {
        "inherited_direction": candidate,
        "direction_source": "INHERITED_FROM_PRESSURE_INTEL",
        "direction_confidence": "MEDIUM",
    }


def _apply_microboost_direction_inheritance(
    microboost_summary: dict[str, Any],
    *,
    events: Iterable[Any],
) -> None:
    """Gated (default OFF via ``MICROBOOST_DIRECTION_INHERIT_ENABLED``): annotate the
    latest microboost block with inherited-direction metadata.

    Sets only watch-scoped fields and NEVER overwrites ``direction`` -- so
    continuation/counter engines and execution remain untouched.
    """
    if not _env_bool("MICROBOOST_DIRECTION_INHERIT_ENABLED", False):
        return
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return
    if str(latest.get("direction") or "").upper() in {"BUY", "SELL"}:
        return
    window = _env_float("MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS", 600.0)
    resolution = resolve_microboost_direction(latest, events=events, window_seconds=window)
    latest["direction_source"] = resolution["direction_source"]
    latest["direction_confidence"] = resolution["direction_confidence"]
    if resolution.get("inherited_direction"):
        latest["inherited_direction"] = resolution["inherited_direction"]
    if resolution.get("requires_m15_close"):
        latest["inherited_requires_m15_close"] = True


def _has_emit_candidate(payload: dict[str, Any] | None) -> bool:
    return isinstance(payload, dict) and str(payload.get("status") or "NONE") != "NONE"


def _signal_watch_gate(
    candidate: dict[str, Any] | None,
    microboost_summary: dict[str, Any],
    *,
    clean_block_seconds: int = 300,
) -> dict[str, Any]:
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return _empty_signal_watch_gate("MICROBOOST_VALIDATION_NOT_AVAILABLE", candidate)
    if not isinstance(candidate, dict):
        candidate = _candidate_from_microboost_lineage(latest)
    if not isinstance(candidate, dict):
        return _empty_signal_watch_gate("SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED")

    latest_symbol = str(latest.get("symbol") or "").upper()
    candidate_symbol = str(candidate.get("symbol") or "").upper()
    latest_lineage_candidate = _candidate_from_microboost_lineage(latest)
    if isinstance(latest_lineage_candidate, dict):
        candidate = latest_lineage_candidate
        candidate_symbol = latest_symbol

    candidate_direction = _candidate_raw_pressure_direction(candidate)
    latest_direction = str(latest.get("direction") or "").upper()
    candidate_lineage = clean_block_lineage_fields(candidate, clean_block_seconds=clean_block_seconds)
    if latest_symbol != candidate_symbol:
        return _empty_signal_watch_gate(
            "MICROBOOST_PAIR_NOT_CLEAN_BLOCK_CANDIDATE",
            candidate,
            include_lineage=False,
        )

    def _eligible(reason: str, *, clean_block_fallback: bool = False) -> dict[str, Any]:
        gate = {
            "eligible": True,
            "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
            "reason": reason,
            "symbol": candidate_symbol,
            "direction": candidate_direction,
            "valid_since_utc": candidate.get("valid_since_utc"),
            "block_start_utc": candidate.get("block_start_utc"),
            "block_end_utc": candidate.get("block_end_utc"),
        }
        for key in (
            "source_clean_block_id",
            "source_pressure_block_id",
            "clean_block_valid",
            "clean_block_start_utc",
            "clean_block_end_utc",
            "clean_block_valid_since_utc",
            "clean_block_duration_seconds",
            "clean_block_event_count",
            "clean_block_direction",
            "source_clean_block_start_utc",
            "source_clean_block_first_valid_end_utc",
            "source_clean_block_latest_end_utc",
            "source_clean_block_latest_duration_seconds",
            "watch_promotion_source",
        ):
            if candidate_lineage.get(key) is not None:
                gate[key] = candidate_lineage.get(key)
        if clean_block_fallback:
            gate["clean_block_fallback"] = True
        return gate

    # Normal: microboost confirms the clean-block direction.
    if latest_direction in {"BUY", "SELL"} and latest_direction == candidate_direction:
        return _eligible("clean_signal_throttle_block_confirmed_for_microboost_validation")

    # Clean-block direction fallback (flag-guarded SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK,
    # default OFF). Design contract: a valid clean SignalThrottle block (>= clean_block_seconds)
    # carrying its OWN BUY/SELL direction MUST still produce a Watch when the microboost direction
    # is MISSING (not yet confirmed). Microboost confirms timing; it is NOT the sole key to allow a
    # Watch. An OPPOSITE microboost direction stays a conflict and is still rejected. Watch-only --
    # never opens execution (downstream keeps final_direction=WAIT, valid_for_execution=false).
    if (
        candidate_direction in {"BUY", "SELL"}
        and latest_direction not in {"BUY", "SELL"}
        and _env_bool("SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK", False)
    ):
        return _eligible("CLEAN_BLOCK_DIRECTION_FALLBACK", clean_block_fallback=True)

    # Opposite microboost direction, fallback disabled, or candidate has no direction.
    return _empty_signal_watch_gate("MICROBOOST_DIRECTION_NOT_CLEAN_BLOCK_DIRECTION", candidate)


def _candidate_from_microboost_lineage(latest: dict[str, Any]) -> dict[str, Any] | None:
    if not latest.get("source_clean_block_id") or latest.get("clean_block_valid") is not True:
        return None
    symbol = str(latest.get("symbol") or "").upper()
    if not symbol:
        return None
    direction = str(latest.get("clean_block_direction") or latest.get("direction") or "").upper()
    payload = {
        "symbol": symbol,
        "block_start_utc": latest.get("clean_block_start_utc"),
        "block_end_utc": latest.get("clean_block_end_utc"),
        "valid_since_utc": latest.get("source_clean_block_valid_since_utc")
        or latest.get("clean_block_valid_since_utc"),
        "duration_seconds": latest.get("clean_block_duration_seconds"),
        "duration_minutes": (
            round(float(latest.get("clean_block_duration_seconds") or 0.0) / 60.0, 3)
            if latest.get("clean_block_duration_seconds") is not None
            else None
        ),
        "events": latest.get("clean_block_event_count"),
        "raw_pressure_direction": direction if direction in {"BUY", "SELL"} else "NONE",
        "direction": direction if direction in {"BUY", "SELL"} else "UNRESOLVED",
        "source_clean_block_id": latest.get("source_clean_block_id"),
        "source_pressure_block_id": latest.get("source_pressure_block_id") or latest.get("source_clean_block_id"),
        "clean_block_valid": True,
        "clean_block_start_utc": latest.get("clean_block_start_utc"),
        "clean_block_end_utc": latest.get("clean_block_end_utc"),
        "clean_block_valid_since_utc": latest.get("clean_block_valid_since_utc"),
        "clean_block_duration_seconds": latest.get("clean_block_duration_seconds"),
        "clean_block_event_count": latest.get("clean_block_event_count"),
        "clean_block_direction": direction if direction in {"BUY", "SELL"} else None,
        "source_clean_block_start_utc": latest.get("source_clean_block_start_utc"),
        "source_clean_block_first_valid_end_utc": latest.get("source_clean_block_first_valid_end_utc"),
        "source_clean_block_latest_end_utc": latest.get("source_clean_block_latest_end_utc"),
        "source_clean_block_latest_duration_seconds": latest.get("source_clean_block_latest_duration_seconds"),
        "watch_promotion_source": "MICROBOOST_ATTACHED_CLEAN_BLOCK_LINEAGE",
        "source_lineage_match": latest.get("source_lineage_match"),
    }
    return payload


def _empty_signal_watch_gate(
    reason: str,
    candidate: dict[str, Any] | None = None,
    *,
    include_lineage: bool = True,
) -> dict[str, Any]:
    candidate = candidate or {}
    candidate_lineage = clean_block_lineage_fields(candidate) if candidate and include_lineage else {}
    candidate_direction = _candidate_raw_pressure_direction(candidate) if candidate else None
    return {
        "eligible": False,
        "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": reason,
        "symbol": candidate.get("symbol"),
        "direction": candidate_direction,
        "valid_since_utc": candidate.get("valid_since_utc"),
        "block_start_utc": candidate.get("block_start_utc"),
        "block_end_utc": candidate.get("block_end_utc"),
        "source_clean_block_id": candidate_lineage.get("source_clean_block_id"),
        "source_pressure_block_id": candidate_lineage.get("source_pressure_block_id"),
        "clean_block_valid": candidate_lineage.get("clean_block_valid"),
        "clean_block_start_utc": candidate_lineage.get("clean_block_start_utc"),
        "clean_block_end_utc": candidate_lineage.get("clean_block_end_utc"),
        "clean_block_valid_since_utc": candidate_lineage.get("clean_block_valid_since_utc"),
        "clean_block_duration_seconds": candidate_lineage.get("clean_block_duration_seconds"),
        "clean_block_event_count": candidate_lineage.get("clean_block_event_count"),
        "clean_block_direction": candidate_lineage.get("clean_block_direction"),
        "source_clean_block_start_utc": candidate_lineage.get("source_clean_block_start_utc"),
        "source_clean_block_first_valid_end_utc": candidate_lineage.get("source_clean_block_first_valid_end_utc"),
        "source_clean_block_latest_end_utc": candidate_lineage.get("source_clean_block_latest_end_utc"),
        "source_clean_block_latest_duration_seconds": candidate_lineage.get(
            "source_clean_block_latest_duration_seconds"
        ),
        "watch_promotion_source": candidate_lineage.get("watch_promotion_source"),
    }


def _candidate_raw_pressure_direction(candidate: dict[str, Any]) -> str | None:
    for key in ("raw_pressure_direction", "clean_block_direction", "direction"):
        value = str(candidate.get(key) or "").upper()
        if value in {"BUY", "SELL"}:
            return value
    return None


def _signal_watch_source_fields(
    signal_watch_gate: dict[str, Any],
    microboost_validated: bool,
) -> dict[str, Any]:
    fields = {
        "signal_watch_source": signal_watch_gate["source"],
        "source_clean_block_confirmed": bool(signal_watch_gate["eligible"]),
        "source_clean_block_valid_since_utc": signal_watch_gate.get("valid_since_utc"),
        "microboost_validation_status": "PASSED" if microboost_validated else "NO_SIGNAL_PATTERN",
    }
    for key in (
        "source_clean_block_id",
        "source_pressure_block_id",
        "clean_block_valid",
        "clean_block_start_utc",
        "clean_block_end_utc",
        "clean_block_valid_since_utc",
        "clean_block_duration_seconds",
        "clean_block_event_count",
        "clean_block_direction",
        "source_clean_block_start_utc",
        "source_clean_block_first_valid_end_utc",
        "source_clean_block_latest_end_utc",
        "source_clean_block_latest_duration_seconds",
        "watch_promotion_source",
    ):
        if signal_watch_gate.get(key) is not None:
            fields[key] = signal_watch_gate.get(key)
    return fields


def _pair_eligible_for_analysis(
    *,
    allowed_quorum: dict[str, Any],
    candidate: dict[str, Any] | None,
    main_watchlist: list[str],
) -> bool:
    """SignalThrottle presence makes a pair eligible for analysis.

    Theme and structure are confidence/context inputs.  They must not erase a
    pressure candidate before diagnostics or terminal no-trade output can be
    emitted.
    """
    if isinstance(candidate, dict) and str(candidate.get("symbol") or "").strip():
        return True
    if str(allowed_quorum.get("symbol") or "").strip():
        return True
    return bool(main_watchlist)


def _watch_promotion_blockers(
    *,
    allowed_quorum: dict[str, Any],
    microboost_summary: dict[str, Any],
    signal_watch_gate: dict[str, Any],
    market_context_validation: dict[str, Any],
) -> dict[str, int]:
    blockers: Counter[str] = Counter()
    quorum_streak = _coerce_non_negative_int(allowed_quorum.get("streak")) or 0
    blocker_count = max(1, quorum_streak)
    quorum_reached = bool(allowed_quorum.get("quorum_reached"))
    microboost_count = _coerce_non_negative_int(microboost_summary.get("count_total")) or 0

    if quorum_reached:
        blockers["ALLOWED_QUORUM_PENDING_VALIDATION"] += blocker_count
        if microboost_count <= 0:
            blockers["MICROBOOST_NOT_FORMED"] += blocker_count

    if not bool(signal_watch_gate.get("eligible")):
        reason = str(signal_watch_gate.get("reason") or "SIGNAL_WATCH_GATE_NOT_ELIGIBLE").upper()
        blockers[reason] += blocker_count if quorum_reached else 1

    validation_reason = str(market_context_validation.get("reason") or "").upper()
    if "LOW_CONTEXT_COHERENCE" in validation_reason:
        blockers["LOW_CONTEXT_COHERENCE"] += blocker_count
    if "MISSING_MARKET_CONTEXT" in validation_reason:
        if "PRICE_AT_SIGNAL" in validation_reason:
            blockers["PRICE_CONTEXT_MISSING"] += blocker_count
        if "M15_PHASE" in validation_reason or "H1_PHASE" in validation_reason:
            blockers["PRICE_PHASE_MISSING"] += blocker_count
        if "SPREAD_NORMAL" in validation_reason:
            blockers["SPREAD_CONTEXT_MISSING"] += blocker_count
    elif validation_reason in {"PRICE_OR_PHASE_NOT_ALIGNED", "WAIT_PRICE_PHASE_ALIGNMENT"}:
        blockers["PRICE_PHASE_NOT_ALIGNED"] += blocker_count

    if microboost_count > 0 and bool(microboost_summary.get("requires_market_context")):
        blockers["MARKET_CONTEXT_REQUIRED"] += blocker_count

    return dict(blockers)


def _blocked_microboost_payload(
    latest: dict[str, Any],
    *,
    signal_family: str,
    signal_watch_gate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "enabled": False,
        "status": "NONE",
        "signal_family": signal_family,
        "symbol": str(latest.get("symbol") or "").upper(),
        "raw_direction": latest.get("direction"),
        "candidate_direction": None,
        "validated_direction": None,
        "final_direction": "WAIT",
        "direction_status": "SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED",
        "action": "WAIT_SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": signal_watch_gate["reason"],
        **microboost_role_fields_from(latest),
        **_golden_pattern_fields(latest),
        **_signal_watch_source_fields(signal_watch_gate, False),
    }


def _golden_pattern_fields(source: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "matched_patterns",
        "selected_pattern_id",
        "pattern_tier",
        "pattern_family",
        "pattern_score",
        "pattern_match_score",
        "execution_readiness_score",
        "golden_reference",
        "pattern_scope",
        "applies_to",
        "golden_references",
        "pair_specific_calibration",
        "pair_role",
        "reference_cases",
        "pair_calibration",
        "pattern_context",
        "tradeplan_preview",
        "execution_gate",
        "lifecycle",
        "entry_permission",
        "management_action",
        "hold_policy",
        "chase_allowed",
        "block_reason",
        "pattern_evidence",
        "pattern_search_space",
        "pattern_db_candidates_scanned",
        "pattern_db_exact_matches",
        "pattern_db_fuzzy_matches",
        "pattern_bottlenecks",
        "pattern_match_diagnostics",
        "watch_direction",
        "direction_validation_status",
        "targets_execution_usable",
        "target_source",
        "target_block_reason",
        "decision_update_trigger",
        "pending_age_seconds",
    )
    return {key: source.get(key) for key in keys if key in source}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_pressure_tier_snapshot(
    *,
    events: list[SignalThrottleLogEvent],
    blocks: list[PressureBlock],
    symbol_activity: dict[str, dict[str, Any]],
    clean_watch_candidates: list[dict[str, Any]],
    candidate_lifecycle: dict[str, Any],
    theme_scores: list[dict[str, Any]],
    clean_block_seconds: int,
    state_metadata: dict[str, Any],
) -> dict[str, Any]:
    live_window_seconds = int(_env_float("SIGNAL_THROTTLE_PRESSURE_TIER_LIVE_WINDOW_MINUTES", 120.0) * 60)
    session_window_seconds = int(_env_float("SIGNAL_THROTTLE_PRESSURE_TIER_SESSION_WINDOW_HOURS", 24.0) * 3600)
    deployment_ids = _pressure_tier_deployment_ids(state_metadata)
    if not _env_bool("SIGNAL_THROTTLE_PRESSURE_TIER_ENABLED", True):
        return _disabled_pressure_tier_snapshot(
            deployment_ids=deployment_ids,
            live_window_seconds=live_window_seconds,
            session_window_seconds=session_window_seconds,
            clean_block_seconds=clean_block_seconds,
            source_event_count=len(events),
            source_block_count=len(blocks),
        )
    snapshot = build_pressure_tier_snapshot(
        events,
        blocks=blocks,
        symbol_activity=symbol_activity,
        clean_watch_candidates=clean_watch_candidates,
        candidate_lifecycle=candidate_lifecycle,
        theme_scores=theme_scores,
        clean_block_seconds=clean_block_seconds,
        live_window_seconds=live_window_seconds,
        session_window_seconds=session_window_seconds,
        deployment_ids=deployment_ids,
    )
    if _env_bool("SIGNAL_THROTTLE_PRESSURE_TIER_EXECUTION_IMPACT", False):
        snapshot["execution_impact_guard"] = "FORCED_FALSE_DIAGNOSTIC_ONLY"
    return snapshot


def _pressure_tier_deployment_ids(state_metadata: dict[str, Any]) -> list[str]:
    raw = state_metadata.get("deployment_ids") or state_metadata.get("deployment_id")
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return sorted({str(item).strip() for item in raw if str(item).strip()})
    text = str(raw).strip()
    if not text:
        return []
    return sorted({part.strip() for part in re.split(r"[,;\s]+", text) if part.strip()})


def _disabled_pressure_tier_snapshot(
    *,
    deployment_ids: list[str],
    live_window_seconds: int,
    session_window_seconds: int,
    clean_block_seconds: int,
    source_event_count: int = 0,
    source_block_count: int = 0,
) -> dict[str, Any]:
    tiers = {
        "tier_1": [],
        "tier_2": [],
        "tier_3": [],
        "stale_archive": [],
        "unsafe_mixed_deployment": [],
    }
    return {
        "enabled": False,
        "disabled_reason": "SIGNAL_THROTTLE_PRESSURE_TIER_ENABLED_FALSE",
        "mixed_deployment": len(deployment_ids) > 1,
        "deployment_ids": deployment_ids,
        "scope_config": {
            "live_window_seconds": int(live_window_seconds),
            "session_window_seconds": int(session_window_seconds),
            "clean_block_seconds": int(clean_block_seconds),
        },
        "source_event_count": max(0, int(source_event_count)),
        "source_block_count": max(0, int(source_block_count)),
        "symbol_count": 0,
        "tier_is_execution_signal": False,
        "tier_execution_impact": False,
        "tiers": tiers,
        "summary": {key: 0 for key in tiers},
        "symbols": [],
    }


def _market_context_for_report(market_contexts: dict[str, Any] | None, symbol: str) -> MarketContext | None:
    if not market_contexts:
        return None
    normalized_symbol = str(symbol or "").upper()
    raw = (
        market_contexts.get(normalized_symbol)
        or market_contexts.get(normalized_symbol.lower())
        or market_contexts.get(str(symbol or ""))
    )
    if raw is None:
        return None
    return _coerce_market_context_for_report(raw, normalized_symbol)


def _coerce_market_context_for_report(raw: Any, symbol: str) -> MarketContext | None:
    if isinstance(raw, MarketContext):
        return raw
    if not isinstance(raw, Mapping):
        return None
    allowed_fields = {field.name for field in fields(MarketContext)}
    payload = {key: value for key, value in raw.items() if key in allowed_fields}
    payload.setdefault("symbol", symbol)
    payload.setdefault(
        "raw_allowed_direction",
        raw.get("raw_allowed_direction")
        or raw.get("direction")
        or raw.get("raw_direction")
        or raw.get("candidate_direction")
        or raw.get("validated_direction"),
    )
    try:
        return MarketContext(**payload)
    except TypeError:
        return None


def _outcome_memory_sources(
    events: list[SignalThrottleLogEvent],
    market_contexts: dict[str, Any] | None,
) -> list[Any]:
    contexts: list[Any] = []
    if market_contexts:
        for symbol, raw in market_contexts.items():
            context = _coerce_market_context_for_report(raw, str(symbol).upper())
            if context is not None:
                contexts.append(context)
    return contexts or list(events)


def _basket_validation_from_context(context: MarketContext | None) -> dict[str, Any] | None:
    if context is None or not isinstance(context.basket_validation, dict):
        return None
    return dict(context.basket_validation)


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _data_quality_block(
    *,
    events: list[SignalThrottleLogEvent],
    source: str,
    source_found: bool,
    row_count: int | None,
    unparsed_count: int,
    timezone_assumption: str,
    state_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed_signal_count = len(events)
    resolved_row_count = parsed_signal_count if row_count is None else row_count
    state_metadata = state_metadata or _state_metadata_from_events(events)
    return {
        "source": source,
        "log_scope": "SIGNAL_THROTTLE_INTEL",
        "file_found": source_found if source == "csv" else None,
        "process_local": source == "live_process",
        "global_aggregation": False,
        "row_count": resolved_row_count,
        "parsed_signal_count": parsed_signal_count,
        "unparsed_count": max(0, unparsed_count),
        "start_utc": events[0].timestamp.isoformat() if events else None,
        "end_utc": events[-1].timestamp.isoformat() if events else None,
        "timezone_assumption": timezone_assumption,
        "state_warmup": bool(state_metadata.get("state_warmup", False)),
        "first_event_is_continuation": bool(state_metadata.get("first_event_is_continuation", False)),
        "state_warmup_reason": state_metadata.get("state_warmup_reason"),
        "first_event_state": state_metadata.get("first_event_state"),
        "deployment_ids": state_metadata.get("deployment_ids", []),
        "scanner_cycle_ids": state_metadata.get("scanner_cycle_ids", []),
        "scanner_cycle_id_count": state_metadata.get("scanner_cycle_id_count", 0),
    }


def _make_block(events: list[SignalThrottleLogEvent]) -> PressureBlock:
    start = events[0].timestamp
    end = events[-1].timestamp
    duration_seconds = max((end - start).total_seconds(), 0.0)
    gaps = [(events[index].timestamp - events[index - 1].timestamp).total_seconds() for index in range(1, len(events))]
    density = len(events) / max(duration_seconds / 60.0, 1.0 / 60.0)
    suppressed_ticks = sum(max(0, int(event.suppressed)) for event in events)
    effective_ticks = sum(event.effective_ticks for event in events)
    effective_density = effective_ticks / max(duration_seconds / 60.0, 1.0 / 60.0)
    allowed_events = sum(1 for event in events if event.event_type == "ALLOWED")
    throttled_events = sum(1 for event in events if event.event_type == "THROTTLED")
    downgraded_events = sum(1 for event in events if event.event_type == "DOWNGRADED_TO_HOLD")
    direction = _dominant_direction(events)
    direction_metadata = _direction_metadata_for_block(events, direction)
    scanner_metadata = _scanner_lineage_for_block(events)
    source_profile = _source_profile_for_events(events)
    return PressureBlock(
        symbol=events[0].symbol,
        start=start,
        end=end,
        events=len(events),
        duration_seconds=duration_seconds,
        density_per_minute=round(density, 2),
        max_gap_seconds=max(gaps, default=0.0),
        avg_gap_seconds=round(sum(gaps) / len(gaps), 3) if gaps else 0.0,
        direction=direction,
        effective_ticks=effective_ticks,
        suppressed_ticks=suppressed_ticks,
        allowed_events=allowed_events,
        throttled_events=throttled_events,
        downgraded_events=downgraded_events,
        effective_density_per_minute=round(effective_density, 2),
        deployment_ids=scanner_metadata["deployment_ids"],
        scanner_cycle_ids=scanner_metadata["scanner_cycle_ids"],
        scanner_epoch_start_utc=scanner_metadata["scanner_epoch_start_utc"],
        scanner_epoch_end_utc=scanner_metadata["scanner_epoch_end_utc"],
        observed_cycle_index_min=scanner_metadata["observed_cycle_index_min"],
        observed_cycle_index_max=scanner_metadata["observed_cycle_index_max"],
        source_stream_profile=source_profile["source_stream_profile"],
        raw_signal_throttle_severity_profile=source_profile["raw_signal_throttle_severity_profile"],
        raw_signal_throttle_error_count=source_profile["raw_signal_throttle_error_count"],
        raw_signal_throttle_primary_severity=source_profile["raw_signal_throttle_primary_severity"],
        raw_pressure_origin=source_profile["raw_pressure_origin"],
        **direction_metadata,
    )


def _scanner_lineage_for_block(events: list[SignalThrottleLogEvent]) -> dict[str, Any]:
    deployment_ids = tuple(
        sorted({str(event.deployment_id).strip() for event in events if str(event.deployment_id or "").strip()})
    )
    scanner_cycle_ids = tuple(
        sorted({str(event.scanner_cycle_id).strip() for event in events if str(event.scanner_cycle_id or "").strip()})
    )
    scanner_epochs = [
        str(event.scanner_epoch).strip()
        for event in events
        if str(event.scanner_epoch or "").strip()
    ]
    observed_indexes = [
        int(event.observed_cycle_index)
        for event in events
        if event.observed_cycle_index is not None
    ]
    return {
        "deployment_ids": deployment_ids,
        "scanner_cycle_ids": scanner_cycle_ids,
        "scanner_epoch_start_utc": min(scanner_epochs) if scanner_epochs else None,
        "scanner_epoch_end_utc": max(scanner_epochs) if scanner_epochs else None,
        "observed_cycle_index_min": min(observed_indexes) if observed_indexes else None,
        "observed_cycle_index_max": max(observed_indexes) if observed_indexes else None,
    }


def _extract_field(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
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


def _extract_state_fields(message: str) -> dict[str, Any]:
    count = _extract_optional_int(message, _COUNT_KV_RE, _COUNT_SIGNAL_RE, group="count")
    remaining = _extract_optional_int(message, _REMAINING_RE, group="remaining")
    allowed_streak = _extract_optional_int(message, _STREAK_RE, group="streak")
    count_after = _extract_kv_optional_int(message, "count_after")
    remaining_after = _extract_kv_optional_int(message, "remaining_after")
    streak_after = _extract_kv_optional_int(message, "streak_after")
    inferred_direction = normalize_direction(_extract_kv_text(message, "throttled_inferred_direction"), None)
    return {
        "count": count_after if count_after is not None else count,
        "remaining": remaining_after if remaining_after is not None else remaining,
        "allowed_streak": streak_after if streak_after is not None else allowed_streak,
        "max_signals": _extract_optional_int(message, _MAX_KV_RE, _MAX_PAREN_RE, group="max"),
        "window_seconds": _extract_optional_float(message, _WINDOW_KV_RE, _WINDOW_SIGNAL_RE, group="window"),
        "suppressed": _extract_suppressed(message),
        "base_ccy": _extract_kv_optional_text(message, "base_ccy"),
        "quote_ccy": _extract_kv_optional_text(message, "quote_ccy"),
        "symbol_orientation": _extract_kv_optional_text(message, "symbol_orientation"),
        "verdict_source": _extract_kv_optional_text(message, "verdict_source"),
        "verdict_features_hash": _extract_kv_optional_text(message, "verdict_features_hash"),
        "window_count_before": _extract_kv_optional_int(message, "count_before"),
        "window_count_after": count_after,
        "window_remaining_before": _extract_kv_optional_int(message, "remaining_before"),
        "window_remaining_after": remaining_after,
        "allowed_streak_before": _extract_kv_optional_int(message, "streak_before"),
        "allowed_streak_after": streak_after,
        "throttled_inferred_direction": inferred_direction,
    }


def _extract_optional_int(message: str, *patterns: re.Pattern[str], group: str) -> int | None:
    for pattern in patterns:
        match = pattern.search(message)
        if not match:
            continue
        try:
            return max(0, int(match.group(group)))
        except (IndexError, TypeError, ValueError):
            continue
    return None


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return None


def _extract_kv_optional_int(message: str, key: str) -> int | None:
    text = _extract_kv_text(message, key)
    if not text or text.upper() == "NONE":
        return None
    return _coerce_non_negative_int(text)


def _extract_kv_optional_text(message: str, key: str) -> str | None:
    text = _extract_kv_text(message, key)
    if not text or text.upper() == "NONE":
        return None
    return text


def _extract_optional_float(message: str, *patterns: re.Pattern[str], group: str) -> float | None:
    for pattern in patterns:
        match = pattern.search(message)
        if not match:
            continue
        try:
            return max(0.0, float(match.group(group)))
        except (IndexError, TypeError, ValueError):
            continue
    return None


def _extract_kv_text(message: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}=(?P<value>\S+)", message, re.IGNORECASE)
    if not match:
        return ""
    return match.group("value").strip()


def _extract_json_text(message: str, key: str) -> str:
    payload_start = str(message or "").find("{")
    if payload_start < 0:
        return ""
    try:
        payload = json.loads(str(message)[payload_start:])
    except json.JSONDecodeError:
        return ""
    value = payload.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _extract_kv_float(message: str, key: str) -> float | None:
    text = _extract_kv_text(message, key)
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except (TypeError, ValueError):
        return None


def _extract_suppressed(message: str) -> int:
    match = _SUPPRESSED_RE.search(message)
    if not match:
        return 0
    try:
        return max(0, int(match.group("suppressed")))
    except (TypeError, ValueError):
        return 0


def _state_metadata_from_events(events: list[SignalThrottleLogEvent]) -> dict[str, Any]:
    if not events:
        return _state_metadata_payload(None)
    first = events[0]
    state = {
        "symbol": first.symbol,
        "timestamp_utc": first.timestamp.isoformat(),
        "event_type": first.event_type,
        "count": first.count,
        "remaining": first.remaining,
        "streak": first.allowed_streak,
        "max_signals": first.max_signals,
        "window_seconds": first.window_seconds,
        "suppressed": first.suppressed,
    }
    metadata = _state_metadata_payload(state)
    deployment_ids = sorted({str(event.deployment_id).strip() for event in events if str(event.deployment_id or "").strip()})
    scanner_cycle_ids = sorted(
        {str(event.scanner_cycle_id).strip() for event in events if str(event.scanner_cycle_id or "").strip()}
    )
    if deployment_ids:
        metadata["deployment_ids"] = deployment_ids
    if scanner_cycle_ids:
        metadata["scanner_cycle_ids"] = scanner_cycle_ids
        metadata["scanner_cycle_id_count"] = len(scanner_cycle_ids)
    return metadata


def _state_metadata_from_rows(
    rows: list[dict[str, Any]],
    events: list[SignalThrottleLogEvent],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    deployment_ids: set[str] = set()
    for row in rows:
        message = _extract_field(row, "message", "body", "log", "text")
        deployment_id = _extract_deployment_id(message)
        if deployment_id:
            deployment_ids.add(deployment_id)
        if "[SignalThrottle" not in message:
            continue
        timestamp = _parse_timestamp(_extract_field(row, "timestamp", "time", "@timestamp", "datetime"))
        if timestamp is None:
            continue
        symbol = _state_symbol_from_message(message)
        if not symbol:
            continue
        fields = _extract_state_fields(message)
        records.append(
            {
                "symbol": symbol,
                "timestamp": timestamp,
                "event_type": "INTEL" if "[SignalThrottleIntel]" in message else "SIGNAL_THROTTLE",
                **fields,
            }
        )

    if not records:
        metadata = _state_metadata_from_events(events)
        if deployment_ids:
            metadata["deployment_ids"] = sorted(deployment_ids)
        return metadata

    records.sort(key=lambda item: item["timestamp"])
    first_symbol = events[0].symbol if events else str(records[0]["symbol"])
    first_timestamp = events[0].timestamp if events else records[0]["timestamp"]
    first_event_type = events[0].event_type if events else str(records[0]["event_type"])
    state: dict[str, Any] = {
        "symbol": first_symbol,
        "timestamp_utc": first_timestamp.isoformat(),
        "event_type": first_event_type,
        "count": None,
        "remaining": None,
        "streak": None,
        "max_signals": None,
        "window_seconds": None,
        "suppressed": 0,
    }
    for record in records:
        if record["timestamp"] < first_timestamp:
            continue
        if str(record["symbol"]).upper() != first_symbol.upper():
            break
        if (record["timestamp"] - first_timestamp).total_seconds() > 30:
            break
        for source_name, target_name in (
            ("count", "count"),
            ("remaining", "remaining"),
            ("allowed_streak", "streak"),
            ("max_signals", "max_signals"),
            ("window_seconds", "window_seconds"),
        ):
            if state[target_name] is None and record.get(source_name) is not None:
                state[target_name] = record[source_name]
        state["suppressed"] = max(int(state["suppressed"] or 0), int(record.get("suppressed") or 0))
    metadata = _state_metadata_payload(state)
    if deployment_ids:
        metadata["deployment_ids"] = sorted(deployment_ids)
    return metadata


def _state_symbol_from_message(message: str) -> str | None:
    if _SIGNAL_THROTTLE_CHECK_RE.search(message):
        symbol = _extract_kv_text(message, "symbol").upper()
        return symbol or None
    for pattern in (_INTEL_RE, _THROTTLED_RE, _ALLOWED_RE, _DOWNGRADED_RE):
        match = pattern.search(message)
        if match:
            return match.group("symbol").upper()
    return None


def _extract_deployment_id(message: str) -> str | None:
    kv_value = _extract_kv_text(message, "deployment_id")
    if kv_value:
        return kv_value
    payload_start = message.find("{")
    if payload_start < 0:
        return None
    try:
        payload = json.loads(message[payload_start:])
    except json.JSONDecodeError:
        return None
    value = payload.get("deployment_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _state_metadata_payload(first_state: dict[str, Any] | None) -> dict[str, Any]:
    reasons = _continuation_reasons(first_state)
    first_event_is_continuation = bool(reasons)
    return {
        "state_warmup": first_event_is_continuation,
        "first_event_is_continuation": first_event_is_continuation,
        "state_warmup_reason": ",".join(reasons) if reasons else None,
        "first_event_state": first_state,
    }


def _continuation_reasons(first_state: dict[str, Any] | None) -> list[str]:
    if not first_state:
        return []
    count = _coerce_optional_int(first_state.get("count"))
    remaining = _coerce_optional_int(first_state.get("remaining"))
    streak = _coerce_optional_int(first_state.get("streak"))
    max_signals = _coerce_optional_int(first_state.get("max_signals"))
    suppressed = _coerce_optional_int(first_state.get("suppressed")) or 0

    reasons: list[str] = []
    if streak is not None and count is not None and streak > count:
        reasons.append("streak_exceeds_window_count")
    elif streak is not None and streak > 1 and count is None:
        reasons.append("streak_started_before_report")
    if count is not None and count > 1:
        reasons.append("window_count_started_nonzero")
    if max_signals is not None and remaining is not None and remaining < max(max_signals - 1, 0):
        reasons.append("remaining_capacity_already_consumed")
    if suppressed > 0:
        reasons.append("suppressed_events_before_visible_log")
    return reasons


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_optional_number(value: float | None) -> str:
    if isinstance(value, Real) and not isinstance(value, bool):
        return f"{float(value):.0f}"
    return "?"


def _split_symbol(symbol: str) -> tuple[str, str] | None:
    if len(symbol) != 6:
        return None
    base = symbol[:3]
    quote = symbol[3:]
    if quote in _CURRENCIES and (base in _CURRENCIES or base in _METAL_BASES):
        return base, quote
    return None


def _recommended_action(latest_phase: str, candidate_lifecycle: dict[str, Any] | None = None) -> str:
    active_symbol = str((candidate_lifecycle or {}).get("active_candidate_symbol") or "")
    if active_symbol and latest_phase != "PAIR_TIMING_BLOCK":
        return f"FETCH_{active_symbol}_PRICE_CONTEXT_M15_H1_BEFORE_SIGNAL_OUTPUT"
    if latest_phase == "PAIR_TIMING_BLOCK":
        return "FETCH_PRICE_PHASE_M15_H1_BEFORE_SIGNAL_OUTPUT"
    if latest_phase in {"BROAD_ROTATION_FRAGMENTED", "THEME_PRESSURE"}:
        return "OUTPUT_THEME_ALERT_AND_WATCHLIST"
    return "WAIT_FOR_CLEAN_PRESSURE"


def _event_counts(events: list[SignalThrottleLogEvent]) -> dict[str, int]:
    """Count events by type."""
    counts: dict[str, int] = {"allowed": 0, "throttled": 0, "downgraded_to_hold": 0}
    for event in events:
        key = str(event.event_type).strip().lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _empty_direction_recovery_counters() -> dict[str, int]:
    return {
        "pressure_canary_direction_null_count": 0,
        "pressure_canary_direction_recovered_count": 0,
        "microboost_raw_direction_null_count": 0,
        "microboost_raw_direction_recovered_count": 0,
    }


def _direction_recovery_counters(
    events: list[SignalThrottleLogEvent],
    microboost_summary: dict[str, Any],
) -> dict[str, int]:
    counters = _empty_direction_recovery_counters()
    for event in events:
        if event.event_type != "PRESSURE_CANARY":
            continue
        if _pressure_event_direction(event) not in {"BUY", "SELL"}:
            counters["pressure_canary_direction_null_count"] += 1
        elif event.direction_inherited or event.direction_source == "SIGNAL_THROTTLE_INTEL_CACHE":
            counters["pressure_canary_direction_recovered_count"] += 1

    microboost_blocks: list[dict[str, Any]] = []
    latest = microboost_summary.get("latest")
    if isinstance(latest, dict):
        microboost_blocks.append(latest)
    raw_blocks = microboost_summary.get("blocks")
    if isinstance(raw_blocks, list):
        for block in raw_blocks:
            if isinstance(block, dict) and block not in microboost_blocks:
                microboost_blocks.append(block)

    seen: set[str] = set()
    for block in microboost_blocks:
        key = str(block.get("cluster_id") or f"{block.get('symbol')}:{block.get('start_utc')}")
        if key in seen:
            continue
        seen.add(key)
        if str(block.get("direction") or "").upper() not in {"BUY", "SELL"}:
            counters["microboost_raw_direction_null_count"] += 1
        elif bool(block.get("direction_inherited")) or block.get("direction_source") == "SIGNAL_THROTTLE_INTEL_CACHE":
            counters["microboost_raw_direction_recovered_count"] += 1
    return counters


def _candidate_from_blocks(blocks: list[PressureBlock], clean_block_seconds: int) -> dict[str, Any] | None:
    """Extract candidate from pressure blocks."""
    if not blocks:
        return None

    # Find the largest clean block
    clean_blocks = [b for b in blocks if b.duration_seconds >= clean_block_seconds]
    if not clean_blocks:
        return None

    best_block = max(clean_blocks, key=lambda b: b.duration_seconds)
    valid_since = best_block.start + timedelta(seconds=clean_block_seconds)
    raw_pressure_direction = best_block.direction if best_block.direction in {"BUY", "SELL"} else None
    payload = {
        "symbol": best_block.symbol,
        "block_start_utc": best_block.start.isoformat(),
        "block_end_utc": best_block.end.isoformat(),
        "valid_since_utc": valid_since.isoformat(),
        "duration_minutes": round(best_block.duration_seconds / 60.0, 2),
        "density_per_minute": best_block.density_per_minute,
        "events": best_block.events,
        "effective_ticks": best_block.effective_ticks,
        "suppressed_ticks": best_block.suppressed_ticks,
        "effective_density_per_minute": best_block.effective_density_per_minute,
        "direction": "UNRESOLVED",
        "raw_pressure_direction": raw_pressure_direction or "NONE",
        "candidate_direction": None,
        "phase": _candidate_phase(best_block),
    }
    payload.update(_block_direction_metadata_payload(best_block))
    payload.update(_pressure_profile_payload(best_block))
    return payload


def _microboost_payload(block: PressureBlock) -> dict[str, Any]:
    """Create payload for microboost block."""
    payload = {
        "symbol": block.symbol,
        "duration_seconds": block.duration_seconds,
        "events": block.events,
        "density_per_minute": block.density_per_minute,
        "effective_ticks": block.effective_ticks,
        "suppressed_ticks": block.suppressed_ticks,
        "effective_density_per_minute": block.effective_density_per_minute,
        "direction": block.direction,
        "start_utc": block.start.isoformat(),
        "end_utc": block.end.isoformat(),
    }
    payload.update(_block_direction_metadata_payload(block))
    payload.update(_pressure_profile_payload(block))
    return payload


def rank_microboost_blocks(blocks: list[PressureBlock], *, clean_block_seconds: int) -> list[PressureBlock]:
    """Rank microboost blocks by relevance."""
    return sorted(
        blocks,
        key=lambda block: (
            block.duration_seconds >= clean_block_seconds,
            block.effective_ticks or block.events,
            block.effective_density_per_minute or block.density_per_minute,
            block.events,
        ),
        reverse=True,
    )


def _pressure_event_direction(event: SignalThrottleLogEvent) -> str | None:
    """Resolve direction for pressure analytics, where HOLD may still carry raw side."""
    return normalize_direction(event.direction, None) or normalize_direction(None, event.verdict)


def compute_allowed_quorum(events: list[SignalThrottleLogEvent]) -> dict[str, Any]:
    """Compute allowed quorum statistics."""
    allowed_events = [e for e in events if e.event_type == "ALLOWED"]
    if not allowed_events:
        return {"count": 0, "symbols": [], "recent_window": {}}

    streak_symbol: str | None = None
    streak_direction: str | None = None
    streak = 0
    for event in allowed_events:
        direction = _pressure_event_direction(event)
        symbol = event.symbol.upper()
        if direction and symbol == streak_symbol and direction == streak_direction:
            streak += 1
            continue
        streak_symbol = symbol if direction else None
        streak_direction = direction
        streak = 1 if direction else 0

    return {
        "symbol": streak_symbol,
        "direction": streak_direction,
        "streak": streak,
        "quorum_size": 3,
        "quorum_reached": streak >= 3,
    }


def _dominant_direction(events: list[SignalThrottleLogEvent]) -> str | None:
    counts: Counter[str] = Counter()
    for event in events:
        direction = _pressure_event_direction(event)
        if direction:
            counts[direction] += 1
    if not counts:
        return None
    direction, count = counts.most_common(1)[0]
    return direction if count > 0 else None


def _latest_direction_for_symbol(events: list[SignalThrottleLogEvent], symbol: str) -> str | None:
    normalized_symbol = symbol.upper()
    for event in reversed(events):
        if event.symbol.upper() != normalized_symbol:
            continue
        direction = _pressure_event_direction(event)
        if direction:
            return direction
    return None


def _direction_metadata_for_block(events: list[SignalThrottleLogEvent], direction: str | None) -> dict[str, Any]:
    if direction not in {"BUY", "SELL"}:
        return {}
    for event in reversed(events):
        if _pressure_event_direction(event) != direction:
            continue
        if not event.direction_source and not event.direction_inherited:
            continue
        inherited_direction = event.inherited_direction if event.inherited_direction in {"BUY", "SELL"} else direction
        return {
            "direction_source": event.direction_source,
            "direction_confidence": event.direction_confidence,
            "direction_inherited": bool(event.direction_inherited),
            "inherited_direction": inherited_direction if event.direction_inherited else event.inherited_direction,
            "inherited_direction_age_seconds": event.inherited_direction_age_seconds,
        }
    return {}


def _block_direction_metadata_payload(block: PressureBlock) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if block.direction_source:
        payload["direction_source"] = block.direction_source
    if block.direction_confidence:
        payload["direction_confidence"] = block.direction_confidence
    if block.direction_inherited:
        payload["direction_inherited"] = True
    if block.inherited_direction:
        payload["inherited_direction"] = block.inherited_direction
    if block.inherited_direction_age_seconds is not None:
        payload["inherited_direction_age_seconds"] = block.inherited_direction_age_seconds
    return payload


def _candidate_phase(block: PressureBlock) -> str:
    density = block.effective_density_per_minute or block.density_per_minute
    if density < 3.0:
        return "LOW_DENSITY_OPEN_LANE"
    if density < 8.0:
        return "CLEAN_PRESSURE_LANE"
    return "HIGH_DENSITY_PRESSURE_LANE"


def _pressure_profile_payload(block: PressureBlock) -> dict[str, Any]:
    profile = classify_pressure_block(
        duration_seconds=block.duration_seconds,
        event_count=block.effective_ticks or block.events,
        density_per_minute=block.effective_density_per_minute or block.density_per_minute,
        max_gap_seconds=block.max_gap_seconds,
    )
    return profile.to_dict()


def _source_profile_for_events(events: list[SignalThrottleLogEvent]) -> dict[str, Any]:
    stream_counts = Counter(_source_stream_key(event) for event in events)
    severity_counts = Counter(_severity_key(event.severity) for event in events)
    raw_error_count = int(severity_counts.get("ERROR", 0))
    primary_severity = _primary_severity(severity_counts)
    return {
        "source_stream_profile": tuple(sorted(stream_counts.items())),
        "raw_signal_throttle_severity_profile": tuple(sorted(severity_counts.items())),
        "raw_signal_throttle_error_count": raw_error_count,
        "raw_signal_throttle_primary_severity": primary_severity,
        "raw_pressure_origin": _raw_pressure_origin(stream_counts),
    }


def _source_profile_payload(block: PressureBlock) -> dict[str, Any]:
    return {
        "source_stream_profile": dict(block.source_stream_profile),
        "raw_signal_throttle_severity_profile": dict(block.raw_signal_throttle_severity_profile),
        "raw_signal_throttle_error_count": int(block.raw_signal_throttle_error_count),
        "raw_signal_throttle_primary_severity": block.raw_signal_throttle_primary_severity,
        "raw_pressure_origin": block.raw_pressure_origin,
    }


def _source_stream_key(event: SignalThrottleLogEvent) -> str:
    stream = str(event.source_stream or "").strip().upper()
    event_type = str(event.event_type or "").strip().upper()
    if stream == "CANARY" and event_type == "PRESSURE_CANARY":
        return "PRESSURE_CANARY"
    return stream or event_type or "UNKNOWN"


def _severity_key(value: str | None) -> str:
    text = str(value or "").strip().upper()
    return text or "UNKNOWN"


def _primary_severity(counts: Counter[str]) -> str | None:
    if not counts:
        return None
    priority = {"ERROR": 0, "CRITICAL": 1, "WARNING": 2, "WARN": 2, "INFO": 3, "DEBUG": 4, "UNKNOWN": 9}
    return min(counts, key=lambda key: (-counts[key], priority.get(key, 8), key))


def _raw_pressure_origin(stream_counts: Counter[str]) -> str:
    if stream_counts.get("RAW_THROTTLED", 0) > 0:
        return "SIGNAL_THROTTLE_RAW_THROTTLED"
    if stream_counts.get("DOWNGRADED", 0) > 0:
        return "SIGNAL_THROTTLE_DOWNGRADED"
    if stream_counts.get("ALLOWED", 0) > 0:
        return "SIGNAL_THROTTLE_ALLOWED"
    if stream_counts.get("PRESSURE_CANARY", 0) > 0:
        return "SIGNAL_THROTTLE_PRESSURE_CANARY"
    if stream_counts.get("INTEL", 0) > 0:
        return "SIGNAL_THROTTLE_INTEL"
    return "SIGNAL_THROTTLE_UNKNOWN"
