"""SignalThrottle live and historical log intelligence.

Runtime code feeds structured engine events directly through
``SignalThrottleLiveAnalyzer``.  CSV parsing is kept only for offline audits of
exported platform logs.  This module is intentionally pure: no broker calls,
no order execution, and no dependency on pandas.
"""

from __future__ import annotations

import csv
import json
import os
import re
import threading
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from numbers import Real
from pathlib import Path
from typing import Any

from analysis.market_context_validator import missing_market_context_result
from analysis.microboost_continuation_entry import MicroboostContinuationEngine
from analysis.microboost_counter_entry import MicroboostCounterEntryEngine
from analysis.microboost_detector import build_microboost_summary
from analysis.signal_throttle_pattern_detector import classify_pressure_block
from schemas.direction import normalize_direction

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
    eligible_for_pressure_block: bool | None = None
    eligible_for_execution: bool | None = None
    execution_block_reason: str | None = None

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
    direction: str | None = None
    effective_ticks: int = 0
    suppressed_ticks: int = 0
    effective_density_per_minute: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        payload.update(_pressure_profile_payload(self))
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
    if "[SignalThrottle]" not in message and not is_signal_throttle_check:
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
    eligible_for_pressure_block: bool | None = True
    eligible_for_execution: bool | None = None
    execution_block_reason: str | None = None

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
        eligible_for_execution = False
        execution_block_reason = _extract_kv_text(message, "reason") or "non_execute_verdict"
    elif downgraded:
        symbol = downgraded.group("symbol").upper()
        verdict = downgraded.group("verdict").upper()
        event_type = "DOWNGRADED_TO_HOLD"
        effective_action = "HOLD"
        is_downgraded = True
        eligible_for_execution = False
        execution_block_reason = "downgraded_to_hold"
    elif allowed:
        symbol = allowed.group("symbol").upper()
        verdict = allowed.group("verdict").upper()
        event_type = "ALLOWED"
        effective_action = "ALLOWED"
        is_downgraded = False
        eligible_for_execution = bool(verdict and verdict.startswith("EXECUTE"))
    elif throttled:
        symbol = throttled.group("symbol").upper()
        event_type = "THROTTLED"
        effective_action = "HOLD"
        is_downgraded = False
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
        direction=direction if is_signal_throttle_check else normalize_direction(None, verdict),
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
        eligible_for_pressure_block=eligible_for_pressure_block,
        eligible_for_execution=eligible_for_execution,
        execution_block_reason=execution_block_reason,
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

    ordered = sorted(events, key=lambda item: item.timestamp)
    state_metadata = state_metadata or _state_metadata_from_events(ordered)
    if not ordered:
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
            "microboost_continuation_entry": None,
            "microboost_counter_entry": None,
            "microboost_watch_entry": None,
            "signal_watch_gate": _empty_signal_watch_gate("NO_SIGNAL_THROTTLE_DATA"),
            "allowed_quorum": compute_allowed_quorum([]),  # noqa: F821
            "pair_eligible_for_analysis": False,
            "watch_promotion_blockers": {},
            "market_context_validation": missing_market_context_result("UNKNOWN").to_dict(),
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
            "recommended_action": "WAIT_FOR_SIGNAL_THROTTLE_DATA",
        }

    blocks = build_pressure_blocks(ordered, max_gap_seconds=clean_gap_seconds)
    symbol_activity = build_symbol_activity(
        ordered,
        max_gap_seconds=clean_gap_seconds,
        now=ordered[-1].timestamp,
    )
    lifecycle_blocks = build_pressure_blocks(ordered, max_gap_seconds=None)
    latest_cutoff = ordered[-1].timestamp - timedelta(seconds=latest_window_seconds)
    latest_events = [event for event in ordered if event.timestamp >= latest_cutoff]
    latest_blocks = build_pressure_blocks(latest_events, max_gap_seconds=clean_gap_seconds)
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
    validation_symbol = str((candidate or {}).get("symbol") or (main_watchlist[0] if main_watchlist else "UNKNOWN"))
    validation_direction = (candidate or {}).get("direction") or _latest_direction_for_symbol(
        ordered, validation_symbol
    )
    market_context_validation = missing_market_context_result(validation_symbol, validation_direction).to_dict()
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
    _apply_microboost_direction_inheritance(microboost_summary, events=ordered)
    signal_watch_gate = _signal_watch_gate(candidate, microboost_summary)
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
        "dominant_themes": dominant_themes,
        "theme_scores": theme_scores,
        "candidate": candidate,
        "top_microboost": [_microboost_payload(block) for block in ranked_microboost_blocks[:10]],
        "microboost_summary": microboost_summary,
        "microboost_continuation_entry": microboost_continuation_entry,
        "microboost_counter_entry": microboost_counter_entry,
        "microboost_watch_entry": microboost_watch_entry,
        "signal_watch_gate": signal_watch_gate,
        "allowed_quorum": allowed_quorum,
        "pair_eligible_for_analysis": pair_eligible_for_analysis,
        "watch_promotion_blockers": watch_promotion_blockers,
        "event_counts": event_type_counts,
        "symbol_activity": symbol_activity,
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
        "top_clean_blocks": [block.to_dict() for block in rank_pressure_blocks(blocks)[:10]],
        "market_context_validation": market_context_validation,
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
        self._events: deque[SignalThrottleLogEvent] = deque()
        self._lock = threading.Lock()

    def record(self, event: SignalThrottleLogEvent) -> None:
        with self._lock:
            self._events.append(event)
            self._purge_locked(event.timestamp)

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
        self.record(
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
        self.record(
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
                eligible_for_pressure_block=True,
                eligible_for_execution=False,
                execution_block_reason="signal_throttled",
            )
        )
        if verdict:
            remaining_text = "?" if remaining is None else str(remaining)
            self.record(
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
        self.record(
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
        timestamp: datetime | None = None,
    ) -> None:
        """Record non-executable throttle pressure without creating an order signal."""
        now = _coerce_timestamp(timestamp)
        verdict_text = str(verdict or "NO_TRADE").strip().upper() or "NO_TRADE"
        normalized_direction = normalize_direction(direction, None) or normalize_direction(None, verdict_text)
        reason_text = f" reason={reason}" if reason else ""
        direction_text = normalized_direction or "WAIT"
        self.record(
            SignalThrottleLogEvent(
                timestamp=now,
                severity="info",
                message=(
                    f"event=signal_throttle_check symbol={symbol.upper()} "
                    f"verdict={verdict_text} direction={direction_text} "
                    f"status=pressure_canary{reason_text}"
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
                eligible_for_pressure_block=True,
                eligible_for_execution=False,
                execution_block_reason=reason or "non_execute_verdict",
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
            max_gap_seconds=self.clean_gap_seconds,
            now=datetime.now(UTC),
        )
        return report

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


def _candidate_payload_from_block(block: PressureBlock, clean_block_seconds: int) -> dict[str, Any]:
    valid_since = block.start + timedelta(seconds=clean_block_seconds)
    role = "latest_meaningful_candidate" if block.duration_seconds >= clean_block_seconds else "latest_ignition_watch"
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
        "direction": block.direction,
        "phase": _candidate_phase(block),
        "role": role,
    }
    payload.update(_pressure_profile_payload(block))
    return payload


def _is_meaningful_candidate_block(block: PressureBlock, clean_block_seconds: int) -> bool:
    return block.duration_seconds >= clean_block_seconds and (block.effective_ticks or block.events) >= 10


def _is_ignition_watch_block(block: PressureBlock, clean_block_seconds: int) -> bool:
    effective_ticks = block.effective_ticks or block.events
    effective_density = block.effective_density_per_minute or block.density_per_minute
    return 18.0 <= block.duration_seconds < clean_block_seconds and effective_ticks >= 5 and effective_density >= 8.0


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


def _counter_entry_payload(
    microboost_summary: dict[str, Any],
    signal_watch_gate: dict[str, Any],
) -> dict[str, Any] | None:
    latest = microboost_summary.get("latest")
    if not isinstance(latest, dict):
        return None
    if not signal_watch_gate["eligible"]:
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
    ).evaluate(latest, watch_only=True)
    payload = result.to_dict()
    payload.update(_signal_watch_source_fields(signal_watch_gate, payload["status"] != "NONE"))
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
    payload.update(_signal_watch_source_fields(signal_watch_gate, payload["status"] != "NONE"))
    latest["continuation_entry"] = payload
    microboost_summary["continuation_entry"] = payload
    return payload


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
    if candidate_direction:
        direction_source = "BLOCK_DIRECT"
        direction_confidence = "HIGH"
    else:
        direction_source = str(latest.get("direction_source") or "DIRECTION_MISSING")
        direction_confidence = str(latest.get("direction_confidence") or "NONE")
        inherited_direction = str(latest.get("inherited_direction") or "").upper()
        if inherited_direction in {"BUY", "SELL"}:
            candidate_direction = inherited_direction
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
        **_golden_pattern_fields(latest),
        **_signal_watch_source_fields(signal_watch_gate, bool(signal_watch_gate.get("eligible"))),
    }
    latest["microboost_watch"] = payload
    microboost_summary["watch_entry"] = payload
    return payload


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
    for event in events_list:
        event_symbol = str(getattr(event, "symbol", "") or "").upper()
        event_direction = str(getattr(event, "direction", "") or "").upper()
        if event_symbol != symbol or event_direction not in {"BUY", "SELL"}:
            continue
        event_time = getattr(event, "timestamp", None)
        if reference is not None and event_time is not None:
            if (reference - event_time).total_seconds() > window_seconds:
                continue
        directions.add(event_direction)

    if not directions:
        return {"inherited_direction": None, "direction_source": "DIRECTION_MISSING", "direction_confidence": "NONE"}
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
) -> dict[str, Any]:
    latest = microboost_summary.get("latest")
    if not isinstance(candidate, dict):
        return _empty_signal_watch_gate("SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED")
    if not isinstance(latest, dict):
        return _empty_signal_watch_gate("MICROBOOST_VALIDATION_NOT_AVAILABLE", candidate)

    candidate_symbol = str(candidate.get("symbol") or "").upper()
    candidate_direction = str(candidate.get("direction") or "").upper()
    latest_symbol = str(latest.get("symbol") or "").upper()
    latest_direction = str(latest.get("direction") or "").upper()
    if latest_symbol != candidate_symbol:
        return _empty_signal_watch_gate("MICROBOOST_PAIR_NOT_CLEAN_BLOCK_CANDIDATE", candidate)
    if latest_direction not in {"BUY", "SELL"} or latest_direction != candidate_direction:
        return _empty_signal_watch_gate("MICROBOOST_DIRECTION_NOT_CLEAN_BLOCK_DIRECTION", candidate)

    return {
        "eligible": True,
        "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": "clean_signal_throttle_block_confirmed_for_microboost_validation",
        "symbol": candidate_symbol,
        "direction": candidate_direction,
        "valid_since_utc": candidate.get("valid_since_utc"),
        "block_start_utc": candidate.get("block_start_utc"),
        "block_end_utc": candidate.get("block_end_utc"),
    }


def _empty_signal_watch_gate(
    reason: str,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = candidate or {}
    return {
        "eligible": False,
        "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": reason,
        "symbol": candidate.get("symbol"),
        "direction": candidate.get("direction"),
        "valid_since_utc": candidate.get("valid_since_utc"),
        "block_start_utc": candidate.get("block_start_utc"),
        "block_end_utc": candidate.get("block_end_utc"),
    }


def _signal_watch_source_fields(
    signal_watch_gate: dict[str, Any],
    microboost_validated: bool,
) -> dict[str, Any]:
    return {
        "signal_watch_source": signal_watch_gate["source"],
        "source_clean_block_confirmed": bool(signal_watch_gate["eligible"]),
        "source_clean_block_valid_since_utc": signal_watch_gate.get("valid_since_utc"),
        "microboost_validation_status": "PASSED" if microboost_validated else "NO_SIGNAL_PATTERN",
    }


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
    return PressureBlock(
        symbol=events[0].symbol,
        start=start,
        end=end,
        events=len(events),
        duration_seconds=duration_seconds,
        density_per_minute=round(density, 2),
        max_gap_seconds=max(gaps, default=0.0),
        direction=_dominant_direction(events),
        effective_ticks=effective_ticks,
        suppressed_ticks=suppressed_ticks,
        effective_density_per_minute=round(effective_density, 2),
    )


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
    return {
        "count": _extract_optional_int(message, _COUNT_KV_RE, _COUNT_SIGNAL_RE, group="count"),
        "remaining": _extract_optional_int(message, _REMAINING_RE, group="remaining"),
        "allowed_streak": _extract_optional_int(message, _STREAK_RE, group="streak"),
        "max_signals": _extract_optional_int(message, _MAX_KV_RE, _MAX_PAREN_RE, group="max"),
        "window_seconds": _extract_optional_float(message, _WINDOW_KV_RE, _WINDOW_SIGNAL_RE, group="window"),
        "suppressed": _extract_suppressed(message),
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
    return _state_metadata_payload(state)


def _state_metadata_from_rows(
    rows: list[dict[str, Any]],
    events: list[SignalThrottleLogEvent],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for row in rows:
        message = _extract_field(row, "message", "body", "log", "text")
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
        return _state_metadata_from_events(events)

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
    return _state_metadata_payload(state)


def _state_symbol_from_message(message: str) -> str | None:
    if _SIGNAL_THROTTLE_CHECK_RE.search(message):
        symbol = _extract_kv_text(message, "symbol").upper()
        return symbol or None
    for pattern in (_INTEL_RE, _THROTTLED_RE, _ALLOWED_RE, _DOWNGRADED_RE):
        match = pattern.search(message)
        if match:
            return match.group("symbol").upper()
    return None


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
        "direction": best_block.direction,
        "phase": _candidate_phase(best_block),
    }
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


def compute_allowed_quorum(events: list[SignalThrottleLogEvent]) -> dict[str, Any]:
    """Compute allowed quorum statistics."""
    allowed_events = [e for e in events if e.event_type == "ALLOWED"]
    if not allowed_events:
        return {"count": 0, "symbols": [], "recent_window": {}}

    streak_symbol: str | None = None
    streak_direction: str | None = None
    streak = 0
    for event in allowed_events:
        direction = normalize_direction(event.direction, event.verdict)
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
        direction = normalize_direction(event.direction, event.verdict)
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
        direction = normalize_direction(event.direction, event.verdict)
        if direction:
            return direction
    return None


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
