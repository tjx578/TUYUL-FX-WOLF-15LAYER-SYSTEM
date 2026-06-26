"""Advisory regime invalidation for signal-pressure candidates.

This module detects stale or contradicted pressure narratives from data the
caller already has: market context, basket validation, and outcome memory.
It is read-only and does not mutate execution eligibility.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from schemas.direction import normalize_direction

from .outcome_memory import outcome_memory_for

_BUY_OPPOSING_PHASE_TOKENS = (
    "BEARISH",
    "BREAKDOWN",
    "DOWNTREND",
    "LIQUIDATION",
    "LOWER_RANGE",
    "RESISTANCE_REJECTION",
)
_SELL_OPPOSING_PHASE_TOKENS = (
    "BULLISH",
    "BREAKOUT",
    "RECLAIM",
    "SUPPORT_HOLD",
    "UPTREND",
    "UPPER_BREAKOUT",
)


@dataclass(frozen=True)
class RegimeInvalidationResult:
    symbol: str
    direction: str | None
    status: str
    invalidated: bool
    data_ready: bool
    blockers: list[str]
    warnings: list[str]
    action: str
    evidence: dict[str, Any]
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_regime_state(
    *,
    symbol: str,
    direction: str | None,
    market_context: Any | None = None,
    market_context_validation: Mapping[str, Any] | None = None,
    basket_validation: Mapping[str, Any] | None = None,
    outcome_memory_summary: Mapping[str, Any] | None = None,
    min_failure_samples: int = 3,
    max_failure_rate: float = 0.65,
) -> RegimeInvalidationResult:
    normalized_symbol = str(symbol or "").upper()
    normalized_direction = normalize_direction(direction, None)
    if normalized_direction not in {"BUY", "SELL"}:
        return RegimeInvalidationResult(
            symbol=normalized_symbol or "UNKNOWN",
            direction=normalized_direction,
            status="INSUFFICIENT_DATA",
            invalidated=False,
            data_ready=False,
            blockers=["DIRECTION_MISSING"],
            warnings=[],
            action="WAIT_DIRECTION",
            evidence={},
        )

    blockers: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {}

    if market_context is not None:
        m15_phase = _optional_text(_get(market_context, "m15_phase"))
        h1_phase = _optional_text(_get(market_context, "h1_phase"))
        evidence["m15_phase"] = m15_phase
        evidence["h1_phase"] = h1_phase
        if _phase_opposes_direction(m15_phase, normalized_direction):
            blockers.append(f"M15_REGIME_OPPOSES_{normalized_direction}")
        if _phase_opposes_direction(h1_phase, normalized_direction):
            blockers.append(f"H1_REGIME_OPPOSES_{normalized_direction}")
        if _get(market_context, "price_confirmation") is False:
            warnings.append("PRICE_CONFIRMATION_FALSE")
        if normalized_direction == "BUY" and _get(market_context, "breakdown_confirmed") is True:
            blockers.append("BREAKDOWN_CONFIRMED_AGAINST_BUY")
        if normalized_direction == "SELL" and _get(market_context, "reclaim_confirmed") is True:
            blockers.append("RECLAIM_CONFIRMED_AGAINST_SELL")
        basket_blockers = _string_list(_get(market_context, "basket_blockers"))
        if basket_blockers:
            blockers.extend(_prefix_items("BASKET_", basket_blockers))
            evidence["basket_blockers"] = basket_blockers

    validation = dict(market_context_validation or {})
    if validation:
        evidence["market_context_validation"] = {
            "final_direction": validation.get("final_direction"),
            "direction_validated": validation.get("direction_validated"),
            "execution_grade": validation.get("execution_grade"),
            "action": validation.get("action"),
            "reason": validation.get("reason"),
        }
        reason = str(validation.get("reason") or "").upper()
        action = str(validation.get("action") or "").upper()
        final_direction = normalize_direction(_optional_text(validation.get("final_direction")), None)
        if final_direction in {"BUY", "SELL"} and final_direction != normalized_direction:
            blockers.append("VALIDATED_OPPOSITE_DIRECTION")
        if action.startswith("BLOCK") or "BASKET_CONTRADICTION" in reason:
            blockers.append(action or "MARKET_CONTEXT_BLOCKED")

    basket = dict(basket_validation or {})
    if basket:
        basket_blockers = _string_list(basket.get("blockers"))
        evidence["basket_validation"] = {
            "valid": basket.get("valid"),
            "data_ready": basket.get("data_ready"),
            "pair_alignment": basket.get("pair_alignment"),
            "blockers": basket_blockers,
        }
        if basket_blockers:
            blockers.extend(_prefix_items("BASKET_", basket_blockers))

    memory = outcome_memory_for(outcome_memory_summary, normalized_symbol, normalized_direction)
    if memory:
        evidence["outcome_memory"] = memory
        known_records = _coerce_int(memory.get("known_records")) or 0
        failure_rate = _coerce_float(memory.get("failure_rate")) or 0.0
        if known_records >= int(min_failure_samples) and failure_rate >= float(max_failure_rate):
            blockers.append("OUTCOME_MEMORY_FAILURE_CLUSTER")

    blockers = _dedupe(blockers)
    warnings = _dedupe(warnings)
    data_ready = bool(market_context is not None or validation or basket or memory)
    if blockers:
        status = "INVALIDATED"
        action_result = "WAIT_REGIME_REVALIDATION"
    elif warnings:
        status = "CAUTION"
        action_result = "WATCH_FOR_CONFIRMATION"
    elif data_ready:
        status = "VALID"
        action_result = "CONTINUE_ADVISORY_REVIEW"
    else:
        status = "INSUFFICIENT_DATA"
        action_result = "WAIT_CONTEXT"

    return RegimeInvalidationResult(
        symbol=normalized_symbol or "UNKNOWN",
        direction=normalized_direction,
        status=status,
        invalidated=bool(blockers),
        data_ready=data_ready,
        blockers=blockers,
        warnings=warnings,
        action=action_result,
        evidence=evidence,
    )


def _phase_opposes_direction(phase: str | None, direction: str) -> bool:
    normalized = str(phase or "").upper()
    if not normalized:
        return False
    tokens = _BUY_OPPOSING_PHASE_TOKENS if direction == "BUY" else _SELL_OPPOSING_PHASE_TOKENS
    return any(token in normalized for token in tokens)


def _get(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item or "").strip()]


def _prefix_items(prefix: str, items: list[str]) -> list[str]:
    return [item if item.startswith(prefix) else f"{prefix}{item}" for item in items]


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = str(item or "").strip().upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


__all__ = [
    "RegimeInvalidationResult",
    "validate_regime_state",
]
