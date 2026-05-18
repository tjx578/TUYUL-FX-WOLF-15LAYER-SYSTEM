"""SignalThrottle live and historical log intelligence.

Runtime code feeds structured engine events directly through
``SignalThrottleLiveAnalyzer``.  CSV parsing is kept only for offline audits of
exported platform logs.  This module is intentionally pure: no broker calls,
no order execution, and no dependency on pandas.
"""

from __future__ import annotations

import csv
import json
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
from analysis.microboost_detector import build_microboost_summary
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
    if "[SignalThrottle]" not in message:
        return None

    timestamp = _parse_timestamp(_extract_field(row, "timestamp", "time", "@timestamp", "datetime"))
    if timestamp is None:
        return None

    severity = _extract_field(row, "severity", "level", default="info").lower()
    symbol = ""
    event_type = "UNKNOWN"
    verdict: str | None = None

    throttled = _THROTTLED_RE.search(message)
    allowed = _ALLOWED_RE.search(message)
    downgraded = _DOWNGRADED_RE.search(message)

    if downgraded:
        symbol = downgraded.group("symbol").upper()
        verdict = downgraded.group("verdict").upper()
        event_type = "DOWNGRADED_TO_HOLD"
        effective_action = "HOLD"
        is_downgraded = True
    elif allowed:
        symbol = allowed.group("symbol").upper()
        verdict = allowed.group("verdict").upper()
        event_type = "ALLOWED"
        effective_action = "ALLOWED"
        is_downgraded = False
    elif throttled:
        symbol = throttled.group("symbol").upper()
        event_type = "THROTTLED"
        effective_action = "HOLD"
        is_downgraded = False
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
        direction=normalize_direction(None, verdict),
        raw_verdict=verdict,
        effective_action=effective_action,
        is_downgraded=is_downgraded,
        suppressed=_extract_suppressed(message),
        count=state_fields.get("count"),
        remaining=state_fields.get("remaining"),
        allowed_streak=state_fields.get("allowed_streak"),
        max_signals=state_fields.get("max_signals"),
        window_seconds=state_fields.get("window_seconds"),
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
            "dominant_themes": [],
            "theme_scores": [],
            "event_counts": _event_counts([]),  # noqa: F821
            "top_microboost": [],
            "microboost_summary": build_microboost_summary(
                [],
                window_minutes=microboost_window_minutes,
                clean_block_seconds=clean_block_seconds,
            ),
            "allowed_quorum": compute_allowed_quorum([]),  # noqa: F821
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
        }

    blocks = build_pressure_blocks(ordered, max_gap_seconds=clean_gap_seconds)
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

    pair_timing_candidate = latest_phase == "PAIR_TIMING_BLOCK"
    clean_entry_signal = False
    requires_market_context = True
    final_mode = "PAIR_SIGNAL_CANDIDATE" if pair_timing_candidate else "THEME_ALERT_AND_PAIR_SELECTION"
    candidate = _candidate_from_blocks(latest_blocks, clean_block_seconds) if pair_timing_candidate else None  # noqa: F821
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
        "dominant_themes": dominant_themes,
        "theme_scores": theme_scores,
        "candidate": candidate,
        "top_microboost": [
            _microboost_payload(block)
            for block in ranked_microboost_blocks[:10]
        ],
        "microboost_summary": microboost_summary,
        "allowed_quorum": allowed_quorum,
        "event_counts": event_type_counts,
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
        "recommended_action": _recommended_action(latest_phase),
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
        retention_seconds: int = 7200,
        max_events: int = 20000,
        active_block_ttl_seconds: int = 300,
        clean_gap_seconds: int = 75,
        min_clean_block_minutes: float = 5.0,
        clean_block_seconds: int | None = None,
        microboost_window_minutes: int = 15,
        allowed_quorum_window_seconds: int = 120,
        fragmented_min_unique_pairs: int = 5,
        fragmented_max_clean_block_minutes: float = 1.0,
    ) -> None:
        self.latest_window_seconds = int(latest_window_seconds or latest_window_minutes * 60)
        self.retention_seconds = retention_seconds
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
            fragmented_min_unique_pairs=self.fragmented_min_unique_pairs,
            fragmented_max_clean_block_minutes=self.fragmented_max_clean_block_minutes,
            market_contexts=market_contexts,
        )
        report["runtime_config"]["retention_seconds"] = self.retention_seconds
        report["runtime_config"]["active_block_ttl_seconds"] = self.active_block_ttl_seconds
        report["runtime_config"]["allowed_quorum_window_seconds"] = self.allowed_quorum_window_seconds
        report["runtime_config"]["max_events_in_memory"] = self.max_events
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
    max_gap_seconds: int = 75,
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
        if gap <= max_gap_seconds and not _has_hard_rotation_interrupt(
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


def _recommended_action(latest_phase: str) -> str:
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
    return {
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


def _microboost_payload(block: PressureBlock) -> dict[str, Any]:
    """Create payload for microboost block."""
    return {
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
