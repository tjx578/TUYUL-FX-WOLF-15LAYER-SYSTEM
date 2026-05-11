"""Production-safe microboost intelligence for SignalThrottle pressure blocks.

The detector only classifies log-derived pressure density.  It does not claim
late pressure, reversal, entry, or exit without market context.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from numbers import Real
from typing import Any

from analysis.market_context_validator import MarketContext, validate_market_context

_CURRENCIES = ("AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "NZD", "USD")
_METAL_BASES = ("XAG", "XAU")


@dataclass(frozen=True)
class MicroboostThresholds:
    small_min_seconds: float = 18.0
    small_max_seconds: float = 60.0
    small_min_events: int = 5
    valid_min_seconds: float = 60.0
    valid_max_seconds: float = 180.0
    valid_min_events: int = 10
    strong_min_seconds: float = 180.0
    strong_min_events: int = 25
    min_density_per_minute: float = 8.0
    late_candidate_min_events: int = 10
    late_candidate_min_density: float = 8.0
    late_extension_min_ratio: float = 0.002


@dataclass(frozen=True)
class MicroboostBlockIntel:
    symbol: str
    direction: str | None
    start_utc: str
    end_utc: str
    duration_seconds: float
    duration_minutes: float
    event_count: int
    density_per_minute: float
    phase_unpriced: str
    phase_priced: str | None
    action: str
    requires_market_context: bool
    late_pressure_candidate: bool
    theme_aligned: bool
    score: int
    score_components: dict[str, int]
    market_context_validation: dict[str, Any] | None
    price_extension_ratio: float | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MicroboostSummary:
    enabled: bool
    window_minutes: int
    market_context_applied: bool
    requires_market_context: bool
    count_total: int
    count_by_phase: dict[str, int]
    count_by_priced_phase: dict[str, int]
    count_by_symbol: dict[str, int]
    top_symbols: list[str]
    timing_gate_5m: bool
    latest: dict[str, Any] | None
    blocks: list[dict[str, Any]]
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_microboost_summary(
    blocks: list[Any],
    *,
    window_minutes: int,
    clean_block_seconds: int = 300,
    theme_scores: list[dict[str, Any]] | None = None,
    allowed_quorum: dict[str, Any] | None = None,
    market_contexts: dict[str, Any] | None = None,
    thresholds: MicroboostThresholds | None = None,
    market_context_applied: bool = False,
) -> dict[str, Any]:
    """Build a microboost report from pressure blocks.

    The output is intentionally unpriced by default: dense pressure may become
    ignition, continuation, or late pressure only after price context is added.
    """
    thresholds = thresholds or MicroboostThresholds()
    market_contexts = market_contexts or {}
    market_context_applied = market_context_applied or bool(market_contexts)
    timing_gate_5m = any(_duration_seconds(block) >= clean_block_seconds for block in blocks)
    recurrence = Counter(str(_get(block, "symbol", "")).upper() for block in blocks if _get(block, "symbol", ""))
    qualifying_blocks: list[MicroboostBlockIntel] = []

    for block in blocks:
        phase = _classify_unpriced_phase(
            block,
            thresholds=thresholds,
            clean_block_seconds=clean_block_seconds,
            symbol_block_count=recurrence.get(str(_get(block, "symbol", "")).upper(), 0),
        )
        if phase is None:
            continue
        qualifying_blocks.append(
            _build_block_intel(
                block,
                phase=phase,
                symbol_block_count=recurrence.get(str(_get(block, "symbol", "")).upper(), 1),
                thresholds=thresholds,
                clean_block_seconds=clean_block_seconds,
                theme_scores=theme_scores or [],
                allowed_quorum=allowed_quorum or {},
                market_context=_market_context_for_symbol(
                    market_contexts,
                    str(_get(block, "symbol", "")).upper(),
                    _normalize_direction(_get(block, "direction", None)),
                ),
            )
        )

    qualifying_blocks.sort(key=lambda item: (item.score, item.event_count, item.density_per_minute), reverse=True)
    count_by_phase = Counter(block.phase_unpriced for block in qualifying_blocks)
    count_by_priced_phase = Counter(block.phase_priced for block in qualifying_blocks if block.phase_priced)
    count_by_symbol = Counter(block.symbol for block in qualifying_blocks)
    latest = max(qualifying_blocks, key=lambda item: item.end_utc).to_dict() if qualifying_blocks else None
    top_symbols = [
        symbol
        for symbol, _ in sorted(
            count_by_symbol.items(),
            key=lambda item: (item[1], _max_symbol_score(qualifying_blocks, item[0]), item[0]),
            reverse=True,
        )[:8]
    ]

    summary = MicroboostSummary(
        enabled=True,
        window_minutes=int(window_minutes),
        market_context_applied=market_context_applied,
        requires_market_context=any(block.requires_market_context for block in qualifying_blocks) or not qualifying_blocks,
        count_total=len(qualifying_blocks),
        count_by_phase=dict(count_by_phase),
        count_by_priced_phase=dict(count_by_priced_phase),
        count_by_symbol=dict(count_by_symbol),
        top_symbols=top_symbols,
        timing_gate_5m=timing_gate_5m,
        latest=latest,
        blocks=[block.to_dict() for block in qualifying_blocks[:10]],
        action=_summary_action(qualifying_blocks, timing_gate_5m),
        reason=_summary_reason(qualifying_blocks),
    )
    return summary.to_dict()


def _build_block_intel(
    block: Any,
    *,
    phase: str,
    symbol_block_count: int,
    thresholds: MicroboostThresholds,
    clean_block_seconds: int,
    theme_scores: list[dict[str, Any]],
    allowed_quorum: dict[str, Any],
    market_context: MarketContext | None,
) -> MicroboostBlockIntel:
    symbol = str(_get(block, "symbol", "")).upper()
    direction = _normalize_direction(_get(block, "direction", None))
    duration_seconds = round(_duration_seconds(block), 3)
    event_count = max(0, _coerce_int(_get(block, "events", 0)))
    density = round(_coerce_float(_get(block, "density_per_minute", 0.0)), 2)
    theme_score, theme_aligned = _theme_alignment_score(symbol, direction, theme_scores)
    score_components = _score_components(
        duration_seconds=duration_seconds,
        event_count=event_count,
        density_per_minute=density,
        recurrence_count=max(1, symbol_block_count),
        theme_alignment_score=theme_score,
        allowed_quorum_bonus=_allowed_quorum_bonus(symbol, direction, allowed_quorum),
    )
    late_candidate = (
        duration_seconds < clean_block_seconds
        and event_count >= thresholds.late_candidate_min_events
        and density >= thresholds.late_candidate_min_density
    )
    priced = _priced_microboost_state(
        market_context=market_context,
        phase_unpriced=phase,
        direction=direction,
        late_pressure_candidate=late_candidate,
        thresholds=thresholds,
    )
    score_components["late_risk_penalty"] = priced["late_risk_penalty"]
    score = max(0, min(100, sum(score_components.values())))
    return MicroboostBlockIntel(
        symbol=symbol,
        direction=direction,
        start_utc=_iso_utc(_get(block, "start", None)),
        end_utc=_iso_utc(_get(block, "end", None)),
        duration_seconds=duration_seconds,
        duration_minutes=round(duration_seconds / 60.0, 2),
        event_count=event_count,
        density_per_minute=density,
        phase_unpriced=phase,
        phase_priced=priced["phase_priced"],
        action=priced["action"] or _action_for_phase(phase),
        requires_market_context=priced["requires_market_context"],
        late_pressure_candidate=late_candidate,
        theme_aligned=theme_aligned,
        score=score,
        score_components=score_components,
        market_context_validation=priced["market_context_validation"],
        price_extension_ratio=priced["price_extension_ratio"],
        reason=priced["reason"],
    )


def _classify_unpriced_phase(
    block: Any,
    *,
    thresholds: MicroboostThresholds,
    clean_block_seconds: int,
    symbol_block_count: int,
) -> str | None:
    duration_seconds = _duration_seconds(block)
    events = _coerce_int(_get(block, "events", 0))
    density = _coerce_float(_get(block, "density_per_minute", 0.0))
    if duration_seconds >= clean_block_seconds:
        return None
    if (
        duration_seconds >= thresholds.strong_min_seconds
        and events >= thresholds.strong_min_events
        and density >= thresholds.min_density_per_minute
    ):
        return "NEAR_TIMING_GATE_MICROBOOST"
    if symbol_block_count > 1 and events >= thresholds.small_min_events and density >= thresholds.min_density_per_minute:
        return "REPEATED_MICROBOOST"
    if (
        thresholds.valid_min_seconds <= duration_seconds < thresholds.valid_max_seconds
        and events >= thresholds.valid_min_events
        and density >= thresholds.min_density_per_minute
    ):
        return "DENSE_MICROBOOST"
    if (
        thresholds.small_min_seconds <= duration_seconds < thresholds.small_max_seconds
        and events >= thresholds.small_min_events
        and density >= thresholds.min_density_per_minute
    ):
        return "IGNITION_MICROBOOST"
    return None


def _score_components(
    *,
    duration_seconds: float,
    event_count: int,
    density_per_minute: float,
    recurrence_count: int,
    theme_alignment_score: int,
    allowed_quorum_bonus: int,
) -> dict[str, int]:
    density_score = min(30, int(round(density_per_minute * 2)))
    event_count_score = min(25, event_count)
    duration_score = min(15, int(round(duration_seconds / 12.0)))
    recurrence_score = min(10, max(0, recurrence_count - 1) * 5)
    return {
        "density_score": density_score,
        "event_count_score": event_count_score,
        "duration_score": duration_score,
        "recurrence_score": recurrence_score,
        "theme_alignment_score": theme_alignment_score,
        "allowed_quorum_bonus": allowed_quorum_bonus,
        "late_risk_penalty": 0,
    }


def _theme_alignment_score(symbol: str, direction: str | None, theme_scores: list[dict[str, Any]]) -> tuple[int, bool]:
    base_quote = _split_symbol(symbol)
    if base_quote is None or direction not in {"BUY", "SELL"}:
        return 0, False
    base, quote = base_quote
    if direction == "BUY":
        supportive = {f"{base}_STRENGTH", f"{quote}_WEAKNESS"}
    else:
        supportive = {f"{base}_WEAKNESS", f"{quote}_STRENGTH"}

    best = 0
    for theme in theme_scores:
        theme_name = str(theme.get("theme", "")).upper()
        if theme_name not in supportive:
            continue
        best = max(best, min(20, _coerce_int(theme.get("score", 0)) // 2))
    return best, best > 0


def _allowed_quorum_bonus(symbol: str, direction: str | None, allowed_quorum: dict[str, Any]) -> int:
    if not allowed_quorum:
        return 0
    quorum_symbol = str(allowed_quorum.get("symbol") or "").upper()
    quorum_direction = _normalize_direction(allowed_quorum.get("direction"))
    if quorum_symbol != symbol or quorum_direction != direction:
        return 0
    if bool(allowed_quorum.get("quorum_reached")):
        return 8
    return 4 if _coerce_int(allowed_quorum.get("streak", 0)) >= 2 else 0


def _summary_action(blocks: list[MicroboostBlockIntel], timing_gate_5m: bool) -> str:
    if any(block.phase_priced == "LATE_DENSE_PRESSURE" for block in blocks):
        return "PROTECT_PROFIT"
    if any(block.phase_priced in {"CONFIRMATION_MICROBOOST", "CONTINUATION_MICROBOOST"} for block in blocks):
        return "VALIDATE_RETEST_OR_HOLD"
    if timing_gate_5m:
        return "FETCH_MARKET_CONTEXT_FOR_TIMING_GATE"
    if any(block.phase_unpriced == "NEAR_TIMING_GATE_MICROBOOST" for block in blocks):
        return "FETCH_MARKET_CONTEXT_FOR_TIMING_GATE"
    if blocks:
        return "PRIORITIZE_MICROBOOST_SYMBOLS_FOR_CONTEXT_VALIDATION"
    return "WAIT_FOR_MICROBOOST"


def _summary_reason(blocks: list[MicroboostBlockIntel]) -> str:
    if not blocks:
        return "no_qualifying_microboost_in_window"
    if any(block.phase_priced for block in blocks):
        return "priced_microboost_context_applied"
    if any(block.late_pressure_candidate for block in blocks):
        return "dense_pressure_seen_but_late_pressure_requires_price_context"
    return "microboost_detected_from_signal_throttle_density"


def _action_for_phase(phase: str) -> str:
    if phase == "IGNITION_MICROBOOST":
        return "WATCH_EARLY_ACCELERATION"
    if phase == "NEAR_TIMING_GATE_MICROBOOST":
        return "FETCH_MARKET_CONTEXT_FOR_TIMING_GATE"
    if phase == "REPEATED_MICROBOOST":
        return "PRIORITIZE_PAIR_FOR_MARKET_CONTEXT"
    return "VALIDATE_PRICE_THEME_STRUCTURE"


def _priced_microboost_state(
    *,
    market_context: MarketContext | None,
    phase_unpriced: str,
    direction: str | None,
    late_pressure_candidate: bool,
    thresholds: MicroboostThresholds,
) -> dict[str, Any]:
    if market_context is None:
        return {
            "phase_priced": None,
            "action": _action_for_phase(phase_unpriced),
            "requires_market_context": True,
            "market_context_validation": None,
            "price_extension_ratio": None,
            "late_risk_penalty": 0,
            "reason": "unpriced_microboost_requires_market_context_before_entry_or_exit",
        }

    price_extension_ratio = _price_extension_ratio(market_context)
    inferred_late = (
        late_pressure_candidate
        and _directional_extension_confirmed(
            market_context,
            direction=direction,
            min_ratio=thresholds.late_extension_min_ratio,
        )
    )
    validation_context = replace(
        market_context,
        is_late_pressure=bool(market_context.is_late_pressure or inferred_late),
    )
    validation = validate_market_context(validation_context)
    validation_payload = validation.to_dict()

    if validation.requires_market_context:
        return {
            "phase_priced": None,
            "action": validation.action,
            "requires_market_context": True,
            "market_context_validation": validation_payload,
            "price_extension_ratio": price_extension_ratio,
            "late_risk_penalty": 0,
            "reason": validation.reason,
        }

    if validation.action == "PROTECT_PROFIT":
        return {
            "phase_priced": "LATE_DENSE_PRESSURE",
            "action": "PROTECT_PROFIT",
            "requires_market_context": False,
            "market_context_validation": validation_payload,
            "price_extension_ratio": price_extension_ratio,
            "late_risk_penalty": -24,
            "reason": validation.reason,
        }

    if validation.direction_validated:
        phase_priced = (
            "CONFIRMATION_MICROBOOST" if phase_unpriced == "IGNITION_MICROBOOST" else "CONTINUATION_MICROBOOST"
        )
        return {
            "phase_priced": phase_priced,
            "action": "VALIDATE_RETEST_OR_HOLD",
            "requires_market_context": False,
            "market_context_validation": validation_payload,
            "price_extension_ratio": price_extension_ratio,
            "late_risk_penalty": 0,
            "reason": validation.reason,
        }

    if validation.final_direction == "BLOCK_DIRECTION":
        return {
            "phase_priced": "ABSORPTION_WARNING",
            "action": "BLOCK_NEW_ENTRY",
            "requires_market_context": False,
            "market_context_validation": validation_payload,
            "price_extension_ratio": price_extension_ratio,
            "late_risk_penalty": 0,
            "reason": validation.reason,
        }

    if _counter_direction_confirmed(market_context, direction):
        return {
            "phase_priced": "REVERSAL_WARNING",
            "action": "BLOCK_NEW_ENTRY",
            "requires_market_context": False,
            "market_context_validation": validation_payload,
            "price_extension_ratio": price_extension_ratio,
            "late_risk_penalty": 0,
            "reason": validation.reason,
        }

    return {
        "phase_priced": None,
        "action": validation.action,
        "requires_market_context": False,
        "market_context_validation": validation_payload,
        "price_extension_ratio": price_extension_ratio,
        "late_risk_penalty": 0,
        "reason": validation.reason,
    }


def _market_context_for_symbol(
    market_contexts: dict[str, Any],
    symbol: str,
    direction: str | None,
) -> MarketContext | None:
    raw = market_contexts.get(symbol) or market_contexts.get(symbol.upper()) or market_contexts.get(symbol.lower())
    if raw is None:
        return None
    if isinstance(raw, MarketContext):
        if raw.raw_allowed_direction:
            return raw
        return replace(raw, raw_allowed_direction=direction)
    if not isinstance(raw, dict):
        return None
    return MarketContext(
        symbol=str(raw.get("symbol") or symbol),
        raw_allowed_direction=str(raw.get("raw_allowed_direction") or direction or ""),
        price_at_signal_start=_optional_float(raw.get("price_at_signal_start")),
        price_at_5m_confirm=_optional_float(raw.get("price_at_5m_confirm")),
        price_at_signal_end=_optional_float(raw.get("price_at_signal_end")),
        m15_phase=_optional_str(raw.get("m15_phase")),
        h1_phase=_optional_str(raw.get("h1_phase")),
        theme_aligned=_optional_bool(raw.get("theme_aligned")),
        spread_normal=_optional_bool(raw.get("spread_normal")),
        is_late_pressure=bool(raw.get("is_late_pressure", False)),
    )


def _directional_extension_confirmed(
    context: MarketContext,
    *,
    direction: str | None,
    min_ratio: float,
) -> bool:
    if direction not in {"BUY", "SELL"}:
        return False
    start = _optional_float(context.price_at_signal_start)
    confirm = _optional_float(context.price_at_5m_confirm)
    end = _optional_float(context.price_at_signal_end)
    if start is None or confirm is None or end is None or start <= 0:
        return False
    ratio = abs(end - start) / start
    if ratio < min_ratio:
        return False
    if direction == "BUY":
        return confirm >= start and end >= confirm
    return confirm <= start and end <= confirm


def _counter_direction_confirmed(context: MarketContext, direction: str | None) -> bool:
    if direction not in {"BUY", "SELL"}:
        return False
    start = _optional_float(context.price_at_signal_start)
    end = _optional_float(context.price_at_signal_end)
    if start is None or end is None:
        return False
    if direction == "BUY":
        return end < start
    return end > start


def _price_extension_ratio(context: MarketContext) -> float | None:
    start = _optional_float(context.price_at_signal_start)
    end = _optional_float(context.price_at_signal_end)
    if start is None or end is None or start <= 0:
        return None
    return round(abs(end - start) / start, 6)


def _max_symbol_score(blocks: list[MicroboostBlockIntel], symbol: str) -> int:
    return max((block.score for block in blocks if block.symbol == symbol), default=0)


def _get(value: Any, key: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _duration_seconds(block: Any) -> float:
    return max(0.0, _coerce_float(_get(block, "duration_seconds", 0.0)))


def _coerce_int(value: Any) -> int:
    if isinstance(value, Real) and not isinstance(value, bool):
        return int(float(value))
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "SELL"}:
        return text
    return None


def _iso_utc(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _split_symbol(symbol: str) -> tuple[str, str] | None:
    if len(symbol) != 6:
        return None
    base = symbol[:3]
    quote = symbol[3:]
    if quote in _CURRENCIES and (base in _CURRENCIES or base in _METAL_BASES):
        return base, quote
    return None
