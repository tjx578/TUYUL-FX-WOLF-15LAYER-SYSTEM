"""Outcome memory for advisory signal-pressure analysis.

The module labels post-signal movement when callers provide forward
MFE/MAE, future high/low, or close-delta data. It never fetches prices and
never promotes a candidate into execution.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from schemas.direction import normalize_direction

from .pressure_cluster_deduper import infer_pip_size

SUCCESS_OUTCOMES = frozenset({"TARGET_REACHED", "FOLLOWED_THROUGH"})
FAILURE_OUTCOMES = frozenset({"STOP_RISK", "FAILED"})
KNOWN_OUTCOMES = SUCCESS_OUTCOMES | FAILURE_OUTCOMES | frozenset({"MIXED_VOLATILE", "FLAT"})


@dataclass(frozen=True)
class OutcomeRecord:
    symbol: str
    direction: str | None
    outcome: str
    timestamp_utc: str | None
    signal_family: str | None
    status: str | None
    entry_price: float | None
    mfe_pips: float | None
    mae_pips: float | None
    close_delta_pips: float | None
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def label_outcome(
    event: Any,
    *,
    target_pips: float = 8.0,
    stop_pips: float = 5.0,
    min_edge_pips: float = 2.0,
) -> OutcomeRecord:
    """Label one candidate outcome from already-supplied forward data."""

    symbol = str(_get(event, "symbol") or "").upper()
    direction = _event_direction(event)
    timestamp = _coerce_datetime(
        _get(event, "timestamp")
        or _get(event, "signal_valid_time_utc")
        or _get(event, "signal_valid_time")
        or _get(event, "created_at")
    )
    entry_price = _first_float(
        _get(event, "entry_price"),
        _get(event, "signal_valid_price"),
        _get(event, "entry_reference_price"),
        _get(event, "price_at_signal_start"),
    )
    pip_size = infer_pip_size(symbol, _first_float(_get(event, "pip_size"), _get(event, "pip_value")))
    mfe_pips = _first_float(
        _get(event, "forward_mfe_pips"),
        _get(event, "mfe_pips"),
        _get(event, "max_favorable_excursion_pips"),
    )
    mae_pips = _first_float(
        _get(event, "forward_mae_pips"),
        _get(event, "mae_pips"),
        _get(event, "max_adverse_excursion_pips"),
    )
    close_delta_pips = _first_float(_get(event, "forward_close_delta_pips"), _get(event, "close_delta_pips"))

    future_high = _first_float(_get(event, "future_high"), _get(event, "high_after_signal"), _get(event, "forward_high"))
    future_low = _first_float(_get(event, "future_low"), _get(event, "low_after_signal"), _get(event, "forward_low"))
    future_close = _first_float(
        _get(event, "future_close"),
        _get(event, "close_after_signal"),
        _get(event, "forward_close"),
    )
    if entry_price is not None and direction in {"BUY", "SELL"}:
        if mfe_pips is None and future_high is not None and future_low is not None:
            mfe_pips = _mfe_from_extremes(direction, entry_price, future_high, future_low, pip_size)
        if mae_pips is None and future_high is not None and future_low is not None:
            mae_pips = _mae_from_extremes(direction, entry_price, future_high, future_low, pip_size)
        if close_delta_pips is None and future_close is not None:
            close_delta_pips = _close_delta(direction, entry_price, future_close, pip_size)

    outcome = _classify_outcome(
        mfe_pips=mfe_pips,
        mae_pips=mae_pips,
        close_delta_pips=close_delta_pips,
        target_pips=target_pips,
        stop_pips=stop_pips,
        min_edge_pips=min_edge_pips,
    )
    return OutcomeRecord(
        symbol=symbol or "UNKNOWN",
        direction=direction,
        outcome=outcome,
        timestamp_utc=timestamp.isoformat() if timestamp else None,
        signal_family=_optional_text(_get(event, "signal_family") or _get(event, "resolved_family")),
        status=_optional_text(_get(event, "status") or _get(event, "event_type")),
        entry_price=_round_or_none(entry_price, 6),
        mfe_pips=_round_or_none(mfe_pips, 2),
        mae_pips=_round_or_none(mae_pips, 2),
        close_delta_pips=_round_or_none(close_delta_pips, 2),
        evidence={
            "target_pips": float(target_pips),
            "stop_pips": float(stop_pips),
            "min_edge_pips": float(min_edge_pips),
            "has_forward_extremes": future_high is not None and future_low is not None,
            "has_forward_mfe_mae": mfe_pips is not None or mae_pips is not None,
            "has_close_delta": close_delta_pips is not None,
        },
    )


def summarize_outcome_memory(
    events: Iterable[Any],
    *,
    lookback: int = 50,
    min_samples_for_memory: int = 3,
    target_pips: float = 8.0,
    stop_pips: float = 5.0,
    min_edge_pips: float = 2.0,
) -> dict[str, Any]:
    records = [
        label_outcome(
            event,
            target_pips=target_pips,
            stop_pips=stop_pips,
            min_edge_pips=min_edge_pips,
        )
        for event in events
    ]
    records = _sort_records(records)[-max(1, int(lookback)) :]
    outcome_counts = Counter(record.outcome for record in records)
    known_records = [record for record in records if record.outcome in KNOWN_OUTCOMES]
    success_count = sum(record.outcome in SUCCESS_OUTCOMES for record in known_records)
    failure_count = sum(record.outcome in FAILURE_OUTCOMES for record in known_records)
    by_symbol_direction = _group_symbol_direction(records, min_samples_for_memory=min_samples_for_memory)
    return {
        "total_records": len(records),
        "known_records": len(known_records),
        "data_ready": bool(known_records),
        "outcome_counts": dict(outcome_counts.most_common()),
        "success_count": success_count,
        "failure_count": failure_count,
        "failure_rate": _rate(failure_count, len(known_records)),
        "success_rate": _rate(success_count, len(known_records)),
        "min_samples_for_memory": int(min_samples_for_memory),
        "lookback": int(lookback),
        "by_symbol_direction": by_symbol_direction,
        "recent_failures": [
            record.to_dict()
            for record in records
            if record.outcome in FAILURE_OUTCOMES
        ][-10:],
    }


def outcome_memory_for(summary: Mapping[str, Any] | None, symbol: str, direction: str | None) -> dict[str, Any] | None:
    key = f"{str(symbol or '').upper()}:{normalize_direction(direction, None) or 'NONE'}"
    groups = summary.get("by_symbol_direction") if isinstance(summary, Mapping) else None
    if not isinstance(groups, Mapping):
        return None
    item = groups.get(key)
    return dict(item) if isinstance(item, Mapping) else None


def _group_symbol_direction(
    records: list[OutcomeRecord],
    *,
    min_samples_for_memory: int,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[OutcomeRecord]] = defaultdict(list)
    for record in records:
        grouped[f"{record.symbol}:{record.direction or 'NONE'}"].append(record)

    payload: dict[str, dict[str, Any]] = {}
    for key, items in sorted(grouped.items()):
        known = [record for record in items if record.outcome in KNOWN_OUTCOMES]
        successes = sum(record.outcome in SUCCESS_OUTCOMES for record in known)
        failures = sum(record.outcome in FAILURE_OUTCOMES for record in known)
        failure_rate = _rate(failures, len(known))
        success_rate = _rate(successes, len(known))
        action = "INSUFFICIENT_DATA"
        if len(known) >= min_samples_for_memory:
            if failure_rate >= 0.60:
                action = "PENALIZE_PROMOTION"
            elif success_rate >= 0.60:
                action = "SUPPORT_PROMOTION"
            else:
                action = "NEUTRAL"
        payload[key] = {
            "total_records": len(items),
            "known_records": len(known),
            "success_count": successes,
            "failure_count": failures,
            "failure_rate": failure_rate,
            "success_rate": success_rate,
            "last_outcome": items[-1].outcome if items else None,
            "memory_action": action,
        }
    return payload


def _classify_outcome(
    *,
    mfe_pips: float | None,
    mae_pips: float | None,
    close_delta_pips: float | None,
    target_pips: float,
    stop_pips: float,
    min_edge_pips: float,
) -> str:
    if mfe_pips is None and mae_pips is None and close_delta_pips is None:
        return "UNKNOWN"

    mfe = max(0.0, float(mfe_pips or 0.0))
    mae = max(0.0, float(mae_pips or 0.0))
    target_hit = mfe >= float(target_pips)
    stop_hit = mae >= float(stop_pips)
    if target_hit and not stop_hit:
        return "TARGET_REACHED"
    if stop_hit and not target_hit:
        return "STOP_RISK"
    if target_hit and stop_hit:
        return "MIXED_VOLATILE"

    edge = mfe - mae
    if edge >= float(min_edge_pips):
        return "FOLLOWED_THROUGH"
    if edge <= -float(min_edge_pips):
        return "FAILED"
    if close_delta_pips is not None:
        close_delta = float(close_delta_pips)
        if close_delta >= float(min_edge_pips):
            return "FOLLOWED_THROUGH"
        if close_delta <= -float(min_edge_pips):
            return "FAILED"
    return "FLAT"


def _event_direction(event: Any) -> str | None:
    for key in (
        "direction",
        "raw_direction",
        "raw_allowed_direction",
        "candidate_direction",
        "watch_direction",
        "validated_direction",
        "final_direction",
    ):
        direction = normalize_direction(_optional_text(_get(event, key)), None)
        if direction in {"BUY", "SELL"}:
            return direction
    return normalize_direction(None, _optional_text(_get(event, "verdict") or _get(event, "source_verdict")))


def _mfe_from_extremes(direction: str, entry: float, future_high: float, future_low: float, pip_size: float) -> float:
    if direction == "SELL":
        return max(0.0, (entry - future_low) / pip_size)
    return max(0.0, (future_high - entry) / pip_size)


def _mae_from_extremes(direction: str, entry: float, future_high: float, future_low: float, pip_size: float) -> float:
    if direction == "SELL":
        return max(0.0, (future_high - entry) / pip_size)
    return max(0.0, (entry - future_low) / pip_size)


def _close_delta(direction: str, entry: float, future_close: float, pip_size: float) -> float:
    if direction == "SELL":
        return (entry - future_close) / pip_size
    return (future_close - entry) / pip_size


def _get(event: Any, key: str) -> Any:
    if isinstance(event, Mapping):
        if key in event:
            return event.get(key)
        payload = event.get("payload")
        if isinstance(payload, Mapping):
            return payload.get(key)
        return None
    value = getattr(event, key, None)
    if value is not None:
        return value
    payload = getattr(event, "payload", None)
    if isinstance(payload, Mapping):
        return payload.get(key)
    return None


def _sort_records(records: list[OutcomeRecord]) -> list[OutcomeRecord]:
    return sorted(records, key=lambda item: item.timestamp_utc or "")


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
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


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _round_or_none(value: float | None, places: int) -> float | None:
    return round(float(value), places) if value is not None else None


def _rate(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(float(count) / float(total), 4)


__all__ = [
    "FAILURE_OUTCOMES",
    "KNOWN_OUTCOMES",
    "OutcomeRecord",
    "SUCCESS_OUTCOMES",
    "label_outcome",
    "outcome_memory_for",
    "summarize_outcome_memory",
]
