"""Pure per-symbol isolated raw PairAdmission evaluator (rule 5scr.pair-admission.per-symbol-isolated.v3).

No database, runtime flag, writer, execution sink or ranking. The legacy global-stream builder
(``analysis.strategy_5scr_raw_admission_blocks``) is untouched; ``replay_pair_admission`` dispatches by
the rule version an episode was decided under so history is never re-labelled.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from analysis.strategy_5scr_raw_admission_blocks import (
    RawAdmissionPopulation,
    _effective_ticks,
    _utc,
    _value,
    build_raw_admission_population,
    is_raw_signal_throttle_authority,
    raw_signal_throttle_direction,
    raw_signal_throttle_event_id,
)
from contracts.strategy_5scr_per_symbol_admission import (
    LEGACY_GLOBAL_STREAM_RULE_VERSION,
    PER_SYMBOL_ADMISSION_RULE_VERSION,
    GlobalSafetyStateV1,
    PerSymbolAdmissionEvaluationV3,
    PerSymbolAdmissionPolicyV3,
    SymbolAdmissionLineageV3,
)

_RAW_SOURCE = "SignalThrottle"


def _symbol(event: Any) -> str:
    return str(_value(event, "symbol") or "").strip().upper()


def _looks_like_raw_authority(event: Any) -> bool:
    # A SignalThrottle event that would be raw authority except for a malformed field.
    return str(_value(event, "pressure_source") or "").strip() == _RAW_SOURCE


def _lineage_id(symbol: str, deployment_id: str, first_event_id: str) -> str:
    identity = json.dumps(
        [PER_SYMBOL_ADMISSION_RULE_VERSION, symbol, deployment_id, first_event_id], separators=(",", ":")
    )
    return "5scr-symbol-lineage:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _segments(events: list[Any], max_gap: float) -> list[tuple[list[Any], str | None]]:
    """Split ONE symbol's ordered events. Returns (events, boundary_reason_that_closed_them)."""

    segments: list[tuple[list[Any], str | None]] = []
    current: list[Any] = []
    direction: str | None = None
    for event in events:
        if current:
            previous = current[-1]
            gap = (_utc(_value(event, "timestamp")) - _utc(_value(previous, "timestamp"))).total_seconds()  # type: ignore[operator]
            next_direction = raw_signal_throttle_direction(event)
            reason = None
            if str(_value(previous, "deployment_id") or "") != str(_value(event, "deployment_id") or ""):
                reason = "DEPLOYMENT_BOUNDARY"
            elif gap > max_gap:
                reason = "SUSPENDED_SOURCE_GAP"
            elif direction is not None and next_direction is not None and next_direction != direction:
                reason = "DIRECTION_CHANGE_SUPERSEDED"
            if reason is not None:
                segments.append((current, reason))
                current, direction = [], None
        current.append(event)
        direction = direction or raw_signal_throttle_direction(event)
    if current:
        segments.append((current, None))
    return segments


def _build_symbol_lineages(
    symbol: str,
    events: list[Any],
    *,
    policy: PerSymbolAdmissionPolicyV3,
    as_of: datetime,
    fault: str | None,
    global_vetoes: tuple[str, ...],
) -> tuple[SymbolAdmissionLineageV3, ...]:
    segments = _segments(events, policy.max_gap_seconds)
    ids = [
        _lineage_id(symbol, str(_value(seg[0], "deployment_id") or ""), raw_signal_throttle_event_id(seg[0]))
        for seg, _ in segments
    ]
    lineages: list[SymbolAdmissionLineageV3] = []
    for index, (segment, boundary) in enumerate(segments):
        times = [_utc(_value(event, "timestamp")) for event in segment]
        concrete = [t for t in times if t is not None]
        opened, last = concrete[0], concrete[-1]
        gaps = [(b - a).total_seconds() for a, b in zip(concrete, concrete[1:], strict=False)]
        direction = next((d for d in map(raw_signal_throttle_direction, segment) if d is not None), None)
        if boundary is None and (as_of - last).total_seconds() > policy.max_gap_seconds:
            boundary = "SUSPENDED_SOURCE_GAP"
        state, superseded_by, closed_at = "ACTIVE", None, None
        if boundary == "DIRECTION_CHANGE_SUPERSEDED":
            state, superseded_by, closed_at = "SUPERSEDED", ids[index + 1], last
        elif boundary == "SUSPENDED_SOURCE_GAP":
            state, closed_at = "SUSPENDED", last
        elif boundary == "DEPLOYMENT_BOUNDARY":
            state, closed_at = "CLOSED", last

        crossing = next(
            (t for t in concrete if (t - opened).total_seconds() >= policy.min_duration_seconds),
            None,
        )
        granted_at = None
        if global_vetoes:
            decision, reason = "SUSPENDED", "GLOBAL_SAFETY_VETO:" + ",".join(global_vetoes)
        elif fault is not None:
            decision, reason = "SUSPENDED", fault
        elif crossing is not None and direction is not None:
            decision, reason, granted_at = "GRANTED", "PER_SYMBOL_THRESHOLD_REACHED", crossing
        elif state == "SUSPENDED":
            decision, reason = "SUSPENDED", "SUSPENDED_SOURCE_GAP"
        elif state != "ACTIVE":
            decision, reason = "REJECTED", "LINEAGE_ENDED_BELOW_THRESHOLD"
        elif crossing is not None:
            decision, reason = None, "DIRECTION_UNRESOLVED"
        else:
            decision, reason = None, "PENDING_THRESHOLD"
        lineages.append(
            SymbolAdmissionLineageV3(
                canonical_symbol=symbol,
                lineage_id=ids[index],
                direction=direction,  # type: ignore[arg-type]
                deployment_id=str(_value(segment[0], "deployment_id") or ""),
                opened_at=opened,
                last_event_at=last,
                closed_at=closed_at,
                superseded_by=superseded_by,
                state=state,
                state_reason_code=boundary,
                event_count=len(segment),
                effective_ticks=sum(_effective_ticks(event) for event in segment),
                max_gap_seconds=max(gaps, default=0.0),
                source_event_ids=tuple(raw_signal_throttle_event_id(event) for event in segment),
                evaluation_state="PENDING_THRESHOLD" if decision is None else decision,
                decision=decision,
                reason_code=reason,
                granted_at=granted_at,
            )
        )
    return tuple(lineages)


def evaluate_per_symbol_admission(
    events: Iterable[Any],
    *,
    universe: Iterable[str],
    policy: PerSymbolAdmissionPolicyV3,
    global_safety: GlobalSafetyStateV1,
    as_of: datetime,
) -> PerSymbolAdmissionEvaluationV3:
    """Evaluate every universe symbol independently; the result for a symbol depends only on its own events."""

    as_of_utc = _utc(as_of)
    if as_of_utc is None:
        raise ValueError("as_of must be timezone-aware")
    symbols = tuple(sorted({str(item).strip().upper() for item in universe}))
    if not symbols:
        raise ValueError("universe must not be empty")
    by_symbol: dict[str, list[Any]] = defaultdict(list)
    faults: dict[str, str] = {}
    seen: set[str] = set()
    out_of_universe = non_authority = duplicates = 0
    for event in events:
        symbol = _symbol(event)
        if symbol not in symbols:
            out_of_universe += 1
            continue
        if not is_raw_signal_throttle_authority(event):
            if _looks_like_raw_authority(event) and _value(event, "eligible_for_pressure_block") is not False:
                stream = str(_value(event, "source_stream") or "").strip().upper()
                if stream in {"RAW_THROTTLED", "ALLOWED", "DOWNGRADED"}:
                    faults.setdefault(symbol, "MALFORMED_RAW_EVENT")
                    continue
            non_authority += 1
            continue
        timestamp = _utc(_value(event, "timestamp"))
        if timestamp is None or timestamp > as_of_utc:
            faults.setdefault(symbol, "FUTURE_RAW_EVIDENCE")
            continue
        event_id = raw_signal_throttle_event_id(event)
        if event_id in seen:
            duplicates += 1
            continue
        seen.add(event_id)
        by_symbol[symbol].append(event)

    vetoes = global_safety.vetoes
    lineages = {
        symbol: _build_symbol_lineages(
            symbol,
            sorted(
                by_symbol.get(symbol, []), key=lambda e: (_utc(_value(e, "timestamp")), raw_signal_throttle_event_id(e))
            ),
            policy=policy,
            as_of=as_of_utc,
            fault=faults.get(symbol),
            global_vetoes=vetoes,
        )
        if by_symbol.get(symbol)
        else ()
        for symbol in symbols
    }
    return PerSymbolAdmissionEvaluationV3(
        policy=policy,
        evaluated_at_utc=as_of_utc,
        universe=symbols,
        global_vetoes=vetoes,
        lineages=lineages,
        symbol_faults=faults,
        ignored_out_of_universe_events=out_of_universe,
        ignored_non_authority_events=non_authority,
        duplicate_events=duplicates,
    )


def replay_pair_admission(
    rule_version: str,
    events: Iterable[Any],
    **kwargs: Any,
) -> RawAdmissionPopulation | PerSymbolAdmissionEvaluationV3:
    """Replay an episode with the semantics of the rule version that decided it. Never re-labels history."""

    if rule_version == LEGACY_GLOBAL_STREAM_RULE_VERSION:
        return build_raw_admission_population(events, max_gap_seconds=kwargs["max_gap_seconds"])
    if rule_version == PER_SYMBOL_ADMISSION_RULE_VERSION:
        return evaluate_per_symbol_admission(events, **kwargs)
    raise ValueError(f"unknown pair admission rule version: {rule_version}")


__all__ = ["evaluate_per_symbol_admission", "replay_pair_admission"]
