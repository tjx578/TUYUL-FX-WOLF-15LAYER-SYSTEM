"""Resolve raw-pressure versus counter-candidate direction conflicts.

This is an advisory/canary layer for cases like raw BUY pressure at resistance
being reinterpreted too quickly as SELL counter-watch. It never authorizes
execution; it only decides whether the counter scenario is allowed to remain a
watch candidate.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from schemas.direction import normalize_direction

from .basket_direction_validator import validate_basket_direction


@dataclass(frozen=True)
class DirectionConflictResolution:
    symbol: str
    raw_direction: str | None
    candidate_direction: str | None
    direction_conflict: bool
    counter_direction_allowed: bool
    raw_direction_status: str
    candidate_direction_status: str
    counter_direction_block_reason: str | None
    action: str
    evidence: dict[str, Any]
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_direction_conflict(
    *,
    symbol: str,
    raw_direction: str | None,
    candidate_direction: str | None,
    market_context: Any | None = None,
    basket_validation: Mapping[str, Any] | None = None,
    currency_scores: Mapping[str, float] | None = None,
    min_pair_alignment: float = 0.15,
) -> DirectionConflictResolution:
    normalized_symbol = str(symbol or "").upper()
    raw = normalize_direction(raw_direction, None)
    candidate = normalize_direction(candidate_direction, None)
    conflict = raw in {"BUY", "SELL"} and candidate in {"BUY", "SELL"} and raw != candidate
    if not conflict:
        return DirectionConflictResolution(
            symbol=normalized_symbol or "UNKNOWN",
            raw_direction=raw,
            candidate_direction=candidate,
            direction_conflict=False,
            counter_direction_allowed=True,
            raw_direction_status="NO_DIRECTION_CONFLICT",
            candidate_direction_status="NO_DIRECTION_CONFLICT",
            counter_direction_block_reason=None,
            action="NO_CONFLICT",
            evidence={},
        )

    scores = _currency_scores(currency_scores, basket_validation, market_context)
    pair_alignment = _pair_alignment(symbol=normalized_symbol, scores=scores, market_context=market_context)
    raw_status = _direction_status(
        normalized_symbol,
        raw,
        scores=scores,
        pair_alignment=pair_alignment,
        basket_validation=basket_validation,
        min_pair_alignment=min_pair_alignment,
    )
    candidate_status = _direction_status(
        normalized_symbol,
        candidate,
        scores=scores,
        pair_alignment=pair_alignment,
        basket_validation=None,
        min_pair_alignment=min_pair_alignment,
    )
    reversal_confirmed = _counter_reversal_confirmed(candidate, market_context)
    block_reason: str | None = None
    allowed = True
    action = "ALLOW_COUNTER_WATCH"

    if reversal_confirmed:
        action = "ALLOW_COUNTER_WATCH_CONFIRMED_REVERSAL"
    elif raw_status == "SUPPORTS_DIRECTION" and candidate_status != "SUPPORTS_DIRECTION":
        allowed = False
        block_reason = "BASKET_SUPPORTS_RAW_DIRECTION"
        action = "WAIT_RAW_CONTINUATION_RETEST"
    elif raw_status == "SUPPORTS_DIRECTION":
        allowed = False
        block_reason = "RAW_DIRECTION_STILL_SUPPORTED"
        action = "WAIT_RAW_CONTINUATION_RETEST"
    elif candidate_status == "NEUTRAL_LOW_DIFFERENTIAL":
        action = "ALLOW_COUNTER_WATCH_LOW_PRIORITY"
    elif candidate_status == "SUPPORTS_DIRECTION":
        action = "ALLOW_COUNTER_WATCH_BASKET_SUPPORTED"

    return DirectionConflictResolution(
        symbol=normalized_symbol or "UNKNOWN",
        raw_direction=raw,
        candidate_direction=candidate,
        direction_conflict=True,
        counter_direction_allowed=allowed,
        raw_direction_status=_role_status(raw_status, "RAW"),
        candidate_direction_status=_role_status(candidate_status, "COUNTER"),
        counter_direction_block_reason=block_reason,
        action=action,
        evidence={
            "pair_alignment": pair_alignment,
            "currency_scores": dict(scores),
            "reversal_confirmed": reversal_confirmed,
            "min_pair_alignment": float(min_pair_alignment),
        },
    )


def _direction_status(
    symbol: str,
    direction: str | None,
    *,
    scores: Mapping[str, float],
    pair_alignment: float | None,
    basket_validation: Mapping[str, Any] | None,
    min_pair_alignment: float,
) -> str:
    if direction not in {"BUY", "SELL"}:
        return "DIRECTION_MISSING"
    if scores:
        result = validate_basket_direction(
            symbol,
            direction,
            currency_scores=scores,
            min_pair_alignment=min_pair_alignment,
        )
        if result.directional_status == "SUPPORTS_DIRECTION":
            return "SUPPORTS_DIRECTION"
        if result.directional_status == "NEUTRAL_LOW_DIFFERENTIAL":
            return "NEUTRAL_LOW_DIFFERENTIAL"
        return "REJECTS_DIRECTION"

    if basket_validation:
        validation_direction = normalize_direction(basket_validation.get("direction"), None)
        if validation_direction == direction and basket_validation.get("valid") is True:
            return "SUPPORTS_DIRECTION"
        blockers = basket_validation.get("blockers")
        if validation_direction == direction and isinstance(blockers, list) and blockers:
            return "REJECTS_DIRECTION"

    if pair_alignment is None:
        return "DATA_UNAVAILABLE"
    if abs(pair_alignment) < min_pair_alignment:
        return "NEUTRAL_LOW_DIFFERENTIAL"
    if (direction == "BUY" and pair_alignment > 0) or (direction == "SELL" and pair_alignment < 0):
        return "SUPPORTS_DIRECTION"
    return "REJECTS_DIRECTION"


def _role_status(status: str, role: str) -> str:
    if status == "SUPPORTS_DIRECTION":
        return f"SUPPORTS_{role}_DIRECTION"
    if status == "REJECTS_DIRECTION":
        return f"REJECTS_{role}_DIRECTION"
    return status


def _currency_scores(
    explicit: Mapping[str, float] | None,
    basket_validation: Mapping[str, Any] | None,
    market_context: Any | None,
) -> dict[str, float]:
    for source in (
        explicit,
        _mapping_get(basket_validation, "currency_scores"),
        _mapping_get(_mapping_get(basket_validation, "evidence"), "currency_scores"),
        _get(market_context, "currency_scores"),
        _mapping_get(_get(market_context, "basket_validation"), "currency_scores"),
        _mapping_get(_mapping_get(_get(market_context, "basket_validation"), "evidence"), "currency_scores"),
    ):
        if not isinstance(source, Mapping):
            continue
        scores: dict[str, float] = {}
        for key, value in source.items():
            try:
                scores[str(key).upper()] = float(value)
            except (TypeError, ValueError):
                continue
        if scores:
            return scores
    return {}


def _pair_alignment(
    *,
    symbol: str,
    scores: Mapping[str, float],
    market_context: Any | None,
) -> float | None:
    explicit = _optional_float(_get(market_context, "pair_direction_alignment"))
    if explicit is not None:
        return explicit
    if len(symbol) != 6:
        return None
    base, quote = symbol[:3], symbol[3:]
    if base in scores and quote in scores:
        return round(float(scores[base]) - float(scores[quote]), 4)
    return None


def _counter_reversal_confirmed(candidate_direction: str | None, market_context: Any | None) -> bool:
    if candidate_direction == "SELL":
        return any(
            _optional_bool(_get(market_context, name)) is True
            for name in (
                "m15_rejection_from_resistance",
                "m15_close_below_minor_support",
                "m15_close_below_support",
                "breakdown_confirmed",
            )
        )
    if candidate_direction == "BUY":
        return any(
            _optional_bool(_get(market_context, name)) is True
            for name in (
                "m15_rejection_from_support",
                "m15_close_above_minor_resistance",
                "m15_close_above_resistance",
                "reclaim_confirmed",
            )
        )
    return False


def _get(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        if key in source:
            return source.get(key)
        snapshot = source.get("market_context_snapshot")
        if isinstance(snapshot, Mapping) and key in snapshot:
            return snapshot.get(key)
        return None
    return getattr(source, key, None)


def _mapping_get(source: Any, key: str) -> Any:
    return source.get(key) if isinstance(source, Mapping) else None


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


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DirectionConflictResolution",
    "resolve_direction_conflict",
]
