"""Route valid clean SignalThrottle blocks into Watch output or diagnostics.

This module is observability-only. It never produces an executable signal; a
clean block can only become a non-executable SignalWatch payload or an explicit
promotion diagnostic.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta
from numbers import Real
from typing import Any

DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX = "[SignalWatchPromotionDiagnostic]"


@dataclass(frozen=True)
class CleanBlockWatchRoute:
    event: str
    payload: dict[str, Any]
    emit_as_watch: bool
    diagnostic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "payload": dict(self.payload),
            "emit_as_watch": self.emit_as_watch,
            "diagnostic": self.diagnostic,
        }


def route_clean_blocks_to_watch(
    candidates: Iterable[Mapping[str, Any]],
    *,
    market_contexts: Mapping[str, Any] | None = None,
    clean_block_seconds: int = 300,
) -> list[CleanBlockWatchRoute]:
    contexts = market_contexts or {}
    return [
        route_clean_block_to_watch(
            candidate,
            market_context=_market_context_for_symbol(contexts, str(candidate.get("symbol") or "")),
            clean_block_seconds=clean_block_seconds,
        )
        for candidate in candidates
    ]


def route_clean_block_to_watch(
    candidate: Mapping[str, Any],
    *,
    market_context: Any | None = None,
    clean_block_seconds: int = 300,
) -> CleanBlockWatchRoute:
    block = dict(candidate)
    lineage = clean_block_lineage_fields(block, clean_block_seconds=clean_block_seconds)
    symbol = str(block.get("symbol") or "").upper()
    direction = _raw_pressure_direction(block)
    duration = _duration_seconds(block)
    blocked_by: list[str] = []

    if not symbol:
        blocked_by.append("SYMBOL_MISSING")
    if duration is None or duration < clean_block_seconds:
        blocked_by.append("CLEAN_BLOCK_DURATION_BELOW_THRESHOLD")
    if not lineage.get("source_clean_block_id"):
        blocked_by.append("SOURCE_CLEAN_BLOCK_ID_MISSING")
    if direction not in {"BUY", "SELL"}:
        blocked_by.append("CLEAN_BLOCK_DIRECTION_MISSING")

    signal_price = _signal_price(market_context)
    if market_context is None:
        blocked_by.append("MARKET_CONTEXT_MISSING")
    elif signal_price is None:
        blocked_by.append("SIGNAL_PRICE_MISSING")

    if blocked_by:
        return CleanBlockWatchRoute(
            event="signal_watch_promotion_diagnostic",
            payload=_diagnostic_payload(
                block,
                lineage=lineage,
                blocked_by=blocked_by,
                clean_block_seconds=clean_block_seconds,
            ),
            emit_as_watch=False,
            diagnostic=True,
        )

    assert signal_price is not None  # for type checkers; guarded above
    return CleanBlockWatchRoute(
        event="signal_watch_json",
        payload=_watch_payload(
            block,
            lineage=lineage,
            market_context=market_context,
            signal_price=signal_price,
            direction=direction,
        ),
        emit_as_watch=True,
        diagnostic=False,
    )


def clean_block_lineage_fields(
    candidate: Mapping[str, Any],
    *,
    clean_block_seconds: int = 300,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    start = _text(candidate.get("block_start_utc") or candidate.get("start_utc") or candidate.get("start"))
    end = _text(candidate.get("block_end_utc") or candidate.get("end_utc") or candidate.get("end"))
    duration = _duration_seconds(candidate)
    event_count = _int_value(candidate.get("events") or candidate.get("event_count"))
    direction = _raw_pressure_direction(candidate)
    explicit_valid_since = _text(
        candidate.get("source_clean_block_first_valid_end_utc")
        or candidate.get("clean_block_first_valid_end_utc")
        or candidate.get("clean_block_valid_since_utc")
        or candidate.get("valid_since_utc")
    )
    first_valid_end = explicit_valid_since or _first_valid_end_utc(start, clean_block_seconds)
    source_id = _text(candidate.get("source_clean_block_id")) or _stable_clean_block_id(
        symbol,
        start,
        first_valid_end,
    )
    latest_duration = None if duration is None else round(duration, 3)
    return {
        "source_clean_block_id": source_id,
        "source_pressure_block_id": _text(candidate.get("source_pressure_block_id")) or source_id,
        "clean_block_valid": duration is not None and duration >= clean_block_seconds,
        "clean_block_start_utc": start,
        "clean_block_end_utc": end,
        "clean_block_valid_since_utc": first_valid_end,
        "clean_block_duration_seconds": latest_duration,
        "clean_block_event_count": event_count,
        "clean_block_direction": direction if direction in {"BUY", "SELL"} else None,
        "source_clean_block_start_utc": start,
        "source_clean_block_first_valid_end_utc": first_valid_end,
        "source_clean_block_latest_end_utc": end,
        "source_clean_block_latest_duration_seconds": latest_duration,
        "watch_promotion_source": "CLEAN_BLOCK_ROUTER",
    }


def emit_signal_watch_promotion_diagnostic(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = dict(payload)
    data["event"] = "signal_watch_promotion_diagnostic"
    data["valid_for_execution"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    logging.getLogger("signal_json").warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def _watch_payload(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    market_context: Any,
    signal_price: float,
    direction: str,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    side = "BUY" if direction == "BUY" else "SELL"
    start_price = _first_number(_field(market_context, "price_at_signal_start"))
    end_price = _first_number(_field(market_context, "price_at_signal_end"))
    entry_zone = sorted(
        {
            round(start_price if start_price is not None else signal_price, 5),
            round(end_price if end_price is not None else signal_price, 5),
            round(signal_price, 5),
        }
    )
    signal_time = (
        lineage.get("clean_block_end_utc")
        or lineage.get("clean_block_valid_since_utc")
        or candidate.get("valid_since_utc")
    )
    requires_m15_close, requires_m15_close_policy = _requires_m15_close_policy(
        direction=direction,
        market_context=market_context,
    )
    payload = {
        "enabled": True,
        "status": f"CLEAN_BLOCK_{side}_WATCH",
        "signal_family": f"CLEAN_BLOCK_{side}_WATCH",
        "cluster_id": lineage.get("source_clean_block_id"),
        "symbol": symbol,
        "raw_direction": direction,
        "candidate_direction": direction,
        "validated_direction": None,
        "watch_direction": direction,
        "direction_source": candidate.get("direction_source") or "CLEAN_BLOCK_DIRECTION",
        "direction_confidence": candidate.get("direction_confidence") or "CLEAN_BLOCK_CONTEXT",
        "resolved_family": "CLEAN_BLOCK_TO_SIGNAL_WATCH",
        "requires_m15_close": requires_m15_close,
        "requires_m15_close_policy": requires_m15_close_policy,
        "final_direction": "WAIT",
        "direction_status": "CLEAN_BLOCK_WATCH_ONLY",
        "direction_validation_status": "CLEAN_BLOCK_WATCH_PENDING_STRUCTURE",
        "action": "WAIT_PRICE_THEME_STRUCTURE",
        "reason": "clean_block_router_promoted_valid_clean_block_to_signal_watch",
        "signal_valid_time": signal_time,
        "signal_valid_time_utc": signal_time,
        "signal_valid_price": signal_price,
        "entry_reference_price": signal_price,
        "entry_zone": entry_zone or [signal_price],
        "price_position": _field(market_context, "price_position"),
        "m15_phase": _field(market_context, "m15_phase"),
        "h1_phase": _field(market_context, "h1_phase"),
        "phase_unpriced": candidate.get("phase"),
        "phase_priced": None,
        "effective_ticks": candidate.get("effective_ticks"),
        "effective_density": candidate.get("effective_density_per_minute") or candidate.get("density_per_minute"),
        "duration_minutes": candidate.get("duration_minutes"),
        "rr_status": "UNVALIDATED",
        "market_context_applied": True,
        "valid_for_execution": False,
        "requires_market_context": True,
        "confidence_bucket": "CLEAN_BLOCK_WATCH_ONLY",
        "emit_reason": "CLEAN_BLOCK_TO_SIGNAL_WATCH",
        "signal_quality": "WATCH_ONLY",
        "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "source_clean_block_confirmed": True,
        "source_clean_block_valid_since_utc": lineage.get("clean_block_valid_since_utc"),
        "microboost_validation_status": "NOT_REQUIRED_CLEAN_BLOCK_ROUTER",
        "promotion_path": "CLEAN_BLOCK_TO_SIGNAL_WATCH",
        "promotion_trigger": "CLEAN_BLOCK_VALID",
        "signal_valid": False,
        "tradeplan_valid": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "market_structure": {
            "structure_ready": False,
            "structure_source": "CLEAN_BLOCK_ROUTER",
            "structure_bias": f"{side}_WATCH",
            "market_structure_status": "PENDING_PRICE_THEME_STRUCTURE",
            "invalidation_level": None,
            "key_support": _field(market_context, "key_support") or _field(market_context, "main_support"),
            "key_resistance": _field(market_context, "key_resistance") or _field(market_context, "main_resistance"),
            "reason": "clean_block_watch_requires_structure_context_but_execution_not_authorized",
        },
    }
    payload.update(lineage)
    payload["clean_block_valid"] = True
    return payload


def _requires_m15_close_policy(*, direction: str, market_context: Any) -> tuple[bool, str]:
    price_position = _normalized_field(market_context, "price_position")
    m15_phase = _normalized_field(market_context, "m15_phase")
    h1_phase = _normalized_field(market_context, "h1_phase")
    market_bias = _normalized_field(market_context, "market_bias")
    trend_direction = _normalized_field(market_context, "trend_direction")

    if direction not in {"BUY", "SELL"}:
        return False, "NOT_APPLICABLE_DIRECTION_UNRESOLVED"

    if direction == "BUY" and price_position in {"MAIN_RESISTANCE", "KEY_RESISTANCE", "RESISTANCE"}:
        return True, "REQUIRED_KEY_LEVEL_OR_REJECTION_RISK"
    if direction == "SELL" and price_position in {"MAIN_SUPPORT", "KEY_SUPPORT", "SUPPORT"}:
        return True, "REQUIRED_KEY_LEVEL_OR_REJECTION_RISK"

    htf_aligned = any(
        _phase_aligned(direction, phase)
        for phase in (h1_phase, market_bias, trend_direction)
    )
    ltf_aligned = _phase_aligned(direction, m15_phase)
    if htf_aligned and ltf_aligned:
        return False, "OPTIONAL_HTF_ALIGNED_CONTINUATION"
    if htf_aligned and price_position not in {"MAIN_RESISTANCE", "MAIN_SUPPORT", "KEY_RESISTANCE", "KEY_SUPPORT"}:
        return False, "OPTIONAL_HTF_ALIGNED_STRUCTURE"
    return True, "REQUIRED_STRUCTURE_CONFIRMATION"


def _phase_aligned(direction: str, phase: str) -> bool:
    if not phase:
        return False
    bullish_tokens = ("BULL", "UPTREND", "SUPPORT_HOLD", "PIVOT_RECLAIM", "ACCUMULATION")
    bearish_tokens = ("BEAR", "DOWNTREND", "RESISTANCE_REJECTION", "SUPPORT_BREAK", "DISTRIBUTION")
    tokens = bullish_tokens if direction == "BUY" else bearish_tokens
    return any(token in phase for token in tokens)


def _normalized_field(source: Any, name: str) -> str:
    return str(_field(source, name) or "").strip().upper()


def _diagnostic_payload(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    blocked_by: list[str],
    clean_block_seconds: int,
) -> dict[str, Any]:
    payload = {
        "event": "signal_watch_promotion_diagnostic",
        "symbol": str(candidate.get("symbol") or "").upper() or None,
        "clean_block_valid": lineage.get("clean_block_valid"),
        "eligible_for_signal_watch": False,
        "blocked_by": blocked_by,
        "next_required_stage": _next_required_stage(blocked_by),
        "clean_block_threshold_seconds": int(clean_block_seconds),
        "valid_for_execution": False,
        "is_final_signal": False,
        "final_direction": "WAIT",
        "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": "clean_block_watch_promotion_blocked_explicitly",
    }
    payload.update(lineage)
    return payload


def _next_required_stage(blocked_by: list[str]) -> str:
    blocked = set(blocked_by)
    if "MARKET_CONTEXT_MISSING" in blocked or "SIGNAL_PRICE_MISSING" in blocked:
        return "HYDRATE_MARKET_CONTEXT"
    if "CLEAN_BLOCK_DIRECTION_MISSING" in blocked:
        return "RESOLVE_CLEAN_BLOCK_DIRECTION"
    if "SOURCE_CLEAN_BLOCK_ID_MISSING" in blocked:
        return "ATTACH_CLEAN_BLOCK_LINEAGE"
    if "CLEAN_BLOCK_DURATION_BELOW_THRESHOLD" in blocked:
        return "WAIT_CLEAN_BLOCK_THRESHOLD"
    return "REVIEW_WATCH_PROMOTION"


def _market_context_for_symbol(contexts: Mapping[str, Any], symbol: str) -> Any | None:
    normalized = str(symbol or "").upper()
    return contexts.get(normalized) or contexts.get(symbol) or contexts.get(normalized.lower())


def _signal_price(market_context: Any | None) -> float | None:
    if market_context is None:
        return None
    return _first_number(
        _field(market_context, "price_at_signal_end"),
        _field(market_context, "price_at_5m_confirm"),
        _field(market_context, "price_at_signal_start"),
        _field(market_context, "bid"),
        _field(market_context, "ask"),
    )


def _field(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    if is_dataclass(source):
        return asdict(source).get(name)
    return getattr(source, name, None)


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, Real):
            return float(value)
        try:
            text = str(value).strip()
            if text:
                return float(text)
        except (TypeError, ValueError):
            continue
    return None


def _duration_seconds(candidate: Mapping[str, Any]) -> float | None:
    raw = candidate.get("duration_seconds")
    if raw is None and candidate.get("duration_minutes") is not None:
        minutes = _first_number(candidate.get("duration_minutes"))
        return None if minutes is None else minutes * 60.0
    return _first_number(raw)


def _raw_pressure_direction(candidate: Mapping[str, Any]) -> str | None:
    for key in ("raw_pressure_direction", "clean_block_direction", "direction"):
        value = str(candidate.get(key) or "").upper()
        if value in {"BUY", "SELL"}:
            return value
    return None


def _int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _stable_clean_block_id(symbol: str, start: str | None, first_valid_end: str | None) -> str | None:
    if not symbol or not start or not first_valid_end:
        return None
    return f"{symbol}_{_compact_time(start)}_{_compact_time(first_valid_end)}"


def _first_valid_end_utc(start: str | None, clean_block_seconds: int) -> str | None:
    start_dt = _parse_datetime(start)
    if start_dt is None:
        return None
    return (start_dt + timedelta(seconds=int(clean_block_seconds))).astimezone(UTC).isoformat()


def _compact_time(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        text = str(value or "").strip()
        return re.sub(r"[^A-Za-z0-9]+", "", text) or "UNKNOWN"
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


__all__ = [
    "CleanBlockWatchRoute",
    "DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX",
    "clean_block_lineage_fields",
    "emit_signal_watch_promotion_diagnostic",
    "route_clean_block_to_watch",
    "route_clean_blocks_to_watch",
]
