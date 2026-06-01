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
    cluster_id: str
    cluster_stage: str
    cluster_age_seconds: float
    cluster_event_count: int
    cluster_density_per_minute: float
    symbol: str
    direction: str | None
    start_utc: str
    end_utc: str
    duration_seconds: float
    duration_minutes: float
    event_count: int
    density_per_minute: float
    effective_tick_count: int
    suppressed_tick_count: int
    effective_density_per_minute: float
    phase_unpriced: str
    phase_priced: str | None
    strategy_pattern: str | None
    phase_grade: str | None
    execution_side: str | None
    strategy_priority: str | None
    waiting_for: str | None
    requires_confirmation: bool | None
    matched_patterns: list[str] | None
    selected_pattern_id: str | None
    pattern_tier: str | None
    pattern_family: str | None
    pattern_score: int | None
    pattern_match_score: int | None
    execution_readiness_score: int | None
    golden_reference: str | None
    pattern_scope: str | None
    applies_to: str | None
    golden_references: list[str] | None
    pair_specific_calibration: list[str] | None
    pair_role: str | None
    entry_permission: str | None
    management_action: str | None
    hold_policy: str | None
    chase_allowed: bool | None
    block_reason: str | None
    pattern_evidence: list[str] | None
    jpy_alignment_status: str | None
    theme_alignment_status: str | None
    dual_theme_status: str | None
    alignment_missing_reason: str | None
    action: str
    requires_market_context: bool
    late_pressure_candidate: bool
    theme_aligned: bool
    score: int
    score_components: dict[str, int]
    market_context_validation: dict[str, Any] | None
    market_context_snapshot: dict[str, Any] | None
    price_extension_ratio: float | None
    market_bias: str | None
    trend_direction: str | None
    price_position: str | None
    main_support: float | None
    main_resistance: float | None
    range_position: float | None
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
    microboost_lifecycle: dict[str, Any]
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

    qualifying_blocks.sort(
        key=lambda item: (item.score, item.effective_tick_count, item.effective_density_per_minute, item.event_count),
        reverse=True,
    )
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

    context_applied_to_blocks = any(_has_applied_market_context(block) for block in qualifying_blocks)
    summary = MicroboostSummary(
        enabled=True,
        window_minutes=int(window_minutes),
        market_context_applied=context_applied_to_blocks,
        requires_market_context=any(block.requires_market_context for block in qualifying_blocks)
        or not qualifying_blocks,
        count_total=len(qualifying_blocks),
        count_by_phase=dict(count_by_phase),
        count_by_priced_phase=dict(count_by_priced_phase),
        count_by_symbol=dict(count_by_symbol),
        top_symbols=top_symbols,
        timing_gate_5m=timing_gate_5m,
        latest=latest,
        blocks=[block.to_dict() for block in qualifying_blocks[:10]],
        microboost_lifecycle=_microboost_lifecycle(qualifying_blocks),
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
    effective_tick_count = max(event_count, _coerce_int(_get(block, "effective_ticks", event_count)))
    suppressed_tick_count = max(0, _coerce_int(_get(block, "suppressed_ticks", 0)))
    effective_density = round(_coerce_float(_get(block, "effective_density_per_minute", density)), 2)
    if effective_density <= 0.0:
        effective_density = density
    theme_score, theme_aligned = _theme_alignment_score(symbol, direction, theme_scores)
    score_components = _score_components(
        duration_seconds=duration_seconds,
        event_count=effective_tick_count,
        density_per_minute=effective_density,
        recurrence_count=max(1, symbol_block_count),
        theme_alignment_score=theme_score,
        allowed_quorum_bonus=_allowed_quorum_bonus(symbol, direction, allowed_quorum),
    )
    late_candidate = (
        duration_seconds < clean_block_seconds
        and effective_tick_count >= thresholds.late_candidate_min_events
        and effective_density >= thresholds.late_candidate_min_density
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
    start_utc = _iso_utc(_get(block, "start", None))
    end_utc = _iso_utc(_get(block, "end", None))
    phase_priced = priced["phase_priced"]
    action = priced["action"] or _action_for_phase(phase)
    return MicroboostBlockIntel(
        cluster_id=_cluster_id(symbol, start_utc),
        cluster_stage=_cluster_stage(
            phase_unpriced=phase,
            phase_priced=phase_priced,
            action=action,
            duration_seconds=duration_seconds,
            clean_block_seconds=clean_block_seconds,
            requires_market_context=priced["requires_market_context"],
        ),
        cluster_age_seconds=duration_seconds,
        cluster_event_count=event_count,
        cluster_density_per_minute=effective_density,
        symbol=symbol,
        direction=direction,
        start_utc=start_utc,
        end_utc=end_utc,
        duration_seconds=duration_seconds,
        duration_minutes=round(duration_seconds / 60.0, 2),
        event_count=event_count,
        density_per_minute=density,
        effective_tick_count=effective_tick_count,
        suppressed_tick_count=suppressed_tick_count,
        effective_density_per_minute=effective_density,
        phase_unpriced=phase,
        phase_priced=phase_priced,
        strategy_pattern=priced["strategy_pattern"],
        phase_grade=priced["phase_grade"],
        execution_side=priced["execution_side"],
        strategy_priority=priced["strategy_priority"],
        waiting_for=priced["waiting_for"],
        requires_confirmation=priced["requires_confirmation"],
        matched_patterns=priced["matched_patterns"],
        selected_pattern_id=priced["selected_pattern_id"],
        pattern_tier=priced["pattern_tier"],
        pattern_family=priced["pattern_family"],
        pattern_score=priced["pattern_score"],
        pattern_match_score=priced["pattern_match_score"],
        execution_readiness_score=priced["execution_readiness_score"],
        golden_reference=priced["golden_reference"],
        pattern_scope=priced["pattern_scope"],
        applies_to=priced["applies_to"],
        golden_references=priced["golden_references"],
        pair_specific_calibration=priced["pair_specific_calibration"],
        pair_role=priced["pair_role"],
        entry_permission=priced["entry_permission"],
        management_action=priced["management_action"],
        hold_policy=priced["hold_policy"],
        chase_allowed=priced["chase_allowed"],
        block_reason=priced["block_reason"],
        pattern_evidence=priced["pattern_evidence"],
        jpy_alignment_status=priced["jpy_alignment_status"],
        theme_alignment_status=priced["theme_alignment_status"],
        dual_theme_status=priced["dual_theme_status"],
        alignment_missing_reason=priced["alignment_missing_reason"],
        action=action,
        requires_market_context=priced["requires_market_context"],
        late_pressure_candidate=late_candidate,
        theme_aligned=theme_aligned,
        score=score,
        score_components=score_components,
        market_context_validation=priced["market_context_validation"],
        market_context_snapshot=priced["market_context_snapshot"],
        price_extension_ratio=priced["price_extension_ratio"],
        market_bias=priced["market_bias"],
        trend_direction=priced["trend_direction"],
        price_position=priced["price_position"],
        main_support=priced["main_support"],
        main_resistance=priced["main_resistance"],
        range_position=priced["range_position"],
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
    raw_events = _coerce_int(_get(block, "events", 0))
    events = max(raw_events, _coerce_int(_get(block, "effective_ticks", raw_events)))
    density = _coerce_float(_get(block, "effective_density_per_minute", _get(block, "density_per_minute", 0.0)))
    if duration_seconds >= clean_block_seconds:
        return None
    if (
        duration_seconds >= thresholds.strong_min_seconds
        and events >= thresholds.strong_min_events
        and density >= thresholds.min_density_per_minute
    ):
        return "NEAR_TIMING_GATE_MICROBOOST"
    if (
        symbol_block_count > 1
        and events >= thresholds.small_min_events
        and density >= thresholds.min_density_per_minute
    ):
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
    if any(block.phase_priced in {"EXHAUSTION_AT_RESISTANCE", "EXHAUSTION_AT_SUPPORT"} for block in blocks):
        return "NO_NEW_ENTRY_WAIT_REVERSAL_OR_PULLBACK_CONFIRMATION"
    if any(block.phase_priced in {"SUPPORT_BOUNCE_MICROBOOST", "RESISTANCE_REJECTION_MICROBOOST"} for block in blocks):
        return "VALIDATE_STRUCTURE_REACTION"
    if any(block.phase_priced == "LATE_DENSE_PRESSURE" for block in blocks):
        return "PROTECT_PROFIT"
    if any(block.strategy_priority == "WATCH_HIGH_SELL" for block in blocks):
        return "WAIT_SELL_TRIGGER_OR_RETEST"
    if any(block.strategy_priority == "WATCH_HIGH_BUY" for block in blocks):
        return "WAIT_BUY_TRIGGER_OR_RETEST"
    if any(block.phase_priced in {"BULLISH_PULLBACK_MICROBOOST", "BEARISH_PULLBACK_MICROBOOST"} for block in blocks):
        return "WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION"
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
        return _priced_state_payload(
            context=None,
            phase_priced=None,
            action=_action_for_phase(phase_unpriced),
            requires_market_context=True,
            market_context_validation=None,
            price_extension_ratio=None,
            late_risk_penalty=0,
            reason="unpriced_microboost_requires_market_context_before_entry_or_exit",
        )

    price_extension_ratio = _price_extension_ratio(market_context)
    structure_phase = _structure_microboost_phase(
        context=market_context,
        direction=direction,
        late_pressure_candidate=late_pressure_candidate,
        price_extension_ratio=price_extension_ratio,
    )
    inferred_late = (
        structure_phase is None
        and market_context.price_position is None
        and late_pressure_candidate
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

    if structure_phase is not None:
        phase_priced, action, reason, penalty = structure_phase
        return _priced_state_payload(
            context=market_context,
            phase_priced=phase_priced,
            action=action,
            requires_market_context=False,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=penalty,
            reason=reason,
        )

    if validation.requires_market_context:
        return _priced_state_payload(
            context=market_context,
            phase_priced=None,
            action=validation.action,
            requires_market_context=True,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=0,
            reason=validation.reason,
        )

    if validation.action == "PROTECT_PROFIT":
        return _priced_state_payload(
            context=market_context,
            phase_priced="LATE_DENSE_PRESSURE",
            action="PROTECT_PROFIT",
            requires_market_context=False,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=-24,
            reason=validation.reason,
        )

    if validation.direction_validated:
        phase_priced = (
            "CONFIRMATION_MICROBOOST" if phase_unpriced == "IGNITION_MICROBOOST" else "CONTINUATION_MICROBOOST"
        )
        return _priced_state_payload(
            context=market_context,
            phase_priced=phase_priced,
            action="VALIDATE_RETEST_OR_HOLD",
            requires_market_context=False,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=0,
            reason=validation.reason,
        )

    if validation.final_direction == "BLOCK_DIRECTION":
        return _priced_state_payload(
            context=market_context,
            phase_priced="ABSORPTION_WARNING",
            action="BLOCK_NEW_ENTRY",
            requires_market_context=False,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=0,
            reason=validation.reason,
        )

    if _counter_direction_confirmed(market_context, direction):
        return _priced_state_payload(
            context=market_context,
            phase_priced="REVERSAL_WARNING",
            action="BLOCK_NEW_ENTRY",
            requires_market_context=False,
            market_context_validation=validation_payload,
            price_extension_ratio=price_extension_ratio,
            late_risk_penalty=0,
            reason=validation.reason,
        )

    return _priced_state_payload(
        context=market_context,
        phase_priced=None,
        action=validation.action,
        requires_market_context=False,
        market_context_validation=validation_payload,
        price_extension_ratio=price_extension_ratio,
        late_risk_penalty=0,
        reason=validation.reason,
    )


def _structure_microboost_phase(
    *,
    context: MarketContext,
    direction: str | None,
    late_pressure_candidate: bool,
    price_extension_ratio: float | None,
) -> tuple[str, str, str, int] | None:
    position = _normalize_structure_label(context.price_position)
    trend = _normalize_direction(context.trend_direction)
    bias = _normalize_direction(context.market_bias)
    m15_direction = _m15_phase_direction(context.m15_phase)
    h1_direction = _h1_phase_direction(context.h1_phase)
    extended = late_pressure_candidate and (price_extension_ratio or 0.0) >= 0.0015

    if position == "MAIN_RESISTANCE":
        if direction == "BUY":
            return (
                "EXHAUSTION_AT_RESISTANCE" if extended else "RESISTANCE_PRESSURE_WARNING",
                "NO_NEW_BUY_WAIT_SELL_OR_PULLBACK_CONFIRMATION",
                "buy_microboost_at_main_resistance_requires_rejection_or_breakout_confirmation",
                -24 if extended else -12,
            )
        if direction == "SELL":
            return (
                "RESISTANCE_REJECTION_MICROBOOST",
                "SELL_ON_REJECTION_CONFIRMATION",
                "sell_microboost_at_main_resistance_aligns_with_structure_rejection",
                0,
            )

    if position == "MAIN_SUPPORT":
        if direction == "SELL":
            return (
                "EXHAUSTION_AT_SUPPORT" if extended else "SUPPORT_PRESSURE_WARNING",
                "NO_NEW_SELL_WAIT_BUY_OR_BREAKDOWN_CONFIRMATION",
                "sell_microboost_at_main_support_requires_bounce_or_breakdown_confirmation",
                -24 if extended else -12,
            )
        if direction == "BUY":
            return (
                "SUPPORT_BOUNCE_MICROBOOST",
                "BUY_ON_RECLAIM_CONFIRMATION",
                "buy_microboost_at_main_support_aligns_with_structure_bounce",
                0,
            )

    if direction and h1_direction and direction != h1_direction:
        return (
            "MINOR_PULLBACK_MICROBOOST",
            "WAIT_PULLBACK_COMPLETION",
            "microboost_counter_to_h1_phase_treat_as_pullback_until_reclaim",
            -8,
        )

    if direction and direction == trend and m15_direction and direction != m15_direction:
        phase = "BULLISH_PULLBACK_MICROBOOST" if direction == "BUY" else "BEARISH_PULLBACK_MICROBOOST"
        return (
            phase,
            "WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
            "microboost_aligns_with_h1_trend_but_m15_pullback_is_active",
            -4,
        )

    if direction and direction == trend:
        return (
            "TREND_CONTINUATION_MICROBOOST",
            "VALIDATE_RETEST_OR_HOLD",
            "microboost_aligns_with_running_trend_away_from_main_extreme",
            0,
        )

    if direction and trend and direction != trend:
        return (
            "MINOR_PULLBACK_MICROBOOST",
            "WAIT_PULLBACK_COMPLETION",
            "microboost_counter_to_running_trend_treat_as_pullback_until_structure_break",
            -8,
        )

    if direction and bias and direction != bias:
        return (
            "COUNTER_BIAS_MICROBOOST",
            "WAIT_BIAS_OR_STRUCTURE_CONFIRMATION",
            "microboost_counter_to_pair_bias_requires_structure_confirmation",
            -8,
        )

    return None


def _priced_state_payload(
    *,
    context: MarketContext | None,
    phase_priced: str | None,
    action: str,
    requires_market_context: bool,
    market_context_validation: dict[str, Any] | None,
    price_extension_ratio: float | None,
    late_risk_penalty: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "phase_priced": phase_priced,
        "strategy_pattern": None if market_context_validation is None else market_context_validation.get("strategy_pattern"),
        "phase_grade": None if market_context_validation is None else market_context_validation.get("phase_grade"),
        "execution_side": None if market_context_validation is None else market_context_validation.get("execution_side"),
        "strategy_priority": None if market_context_validation is None else market_context_validation.get("priority"),
        "waiting_for": None if market_context_validation is None else market_context_validation.get("waiting_for"),
        "requires_confirmation": (
            None if market_context_validation is None else market_context_validation.get("requires_confirmation")
        ),
        "matched_patterns": None if market_context_validation is None else _string_list(market_context_validation.get("matched_patterns")),
        "selected_pattern_id": None if market_context_validation is None else _optional_str(market_context_validation.get("selected_pattern_id")),
        "pattern_tier": None if market_context_validation is None else _optional_str(market_context_validation.get("pattern_tier")),
        "pattern_family": None if market_context_validation is None else _optional_str(market_context_validation.get("pattern_family")),
        "pattern_score": None if market_context_validation is None else _optional_int(market_context_validation.get("pattern_score")),
        "pattern_match_score": None if market_context_validation is None else _optional_int(market_context_validation.get("pattern_match_score")),
        "execution_readiness_score": None if market_context_validation is None else _optional_int(market_context_validation.get("execution_readiness_score")),
        "golden_reference": None if market_context_validation is None else _optional_str(market_context_validation.get("golden_reference")),
        "pattern_scope": None if market_context_validation is None else _optional_str(market_context_validation.get("pattern_scope")),
        "applies_to": None if market_context_validation is None else _optional_str(market_context_validation.get("applies_to")),
        "golden_references": None if market_context_validation is None else _string_list(market_context_validation.get("golden_references")),
        "pair_specific_calibration": None if market_context_validation is None else _string_list(market_context_validation.get("pair_specific_calibration")),
        "pair_role": None if market_context_validation is None else _optional_str(market_context_validation.get("pair_role")),
        "entry_permission": None if market_context_validation is None else _optional_str(market_context_validation.get("entry_permission")),
        "management_action": None if market_context_validation is None else _optional_str(market_context_validation.get("management_action")),
        "hold_policy": None if market_context_validation is None else _optional_str(market_context_validation.get("hold_policy")),
        "chase_allowed": None if market_context_validation is None else _optional_bool(market_context_validation.get("chase_allowed")),
        "block_reason": None if market_context_validation is None else _optional_str(market_context_validation.get("block_reason")),
        "pattern_evidence": None if market_context_validation is None else _string_list(market_context_validation.get("pattern_evidence")),
        "jpy_alignment_status": None if market_context_validation is None else _optional_str(market_context_validation.get("jpy_alignment_status")),
        "theme_alignment_status": None if market_context_validation is None else _optional_str(market_context_validation.get("theme_alignment_status")),
        "dual_theme_status": None if market_context_validation is None else _optional_str(market_context_validation.get("dual_theme_status")),
        "alignment_missing_reason": None if market_context_validation is None else _optional_str(market_context_validation.get("alignment_missing_reason")),
        "action": action,
        "requires_market_context": requires_market_context,
        "market_context_validation": market_context_validation,
        "market_context_snapshot": _market_context_snapshot(context),
        "price_extension_ratio": price_extension_ratio,
        "late_risk_penalty": late_risk_penalty,
        "market_bias": None if context is None else _normalize_direction(context.market_bias),
        "trend_direction": None if context is None else _normalize_direction(context.trend_direction),
        "price_position": None if context is None else _normalize_structure_label(context.price_position),
        "main_support": None if context is None else context.main_support,
        "main_resistance": None if context is None else context.main_resistance,
        "range_position": None if context is None else context.range_position,
        "reason": reason,
    }


def _market_context_snapshot(context: MarketContext | None) -> dict[str, Any] | None:
    if context is None:
        return None
    return {
        "symbol": context.symbol,
        "raw_allowed_direction": _normalize_direction(context.raw_allowed_direction),
        "bid": context.bid,
        "ask": context.ask,
        "pip_value": context.pip_value,
        "price_at_signal_start": context.price_at_signal_start,
        "price_at_5m_confirm": context.price_at_5m_confirm,
        "price_at_signal_end": context.price_at_signal_end,
        "m15_phase": context.m15_phase,
        "h1_phase": context.h1_phase,
        "h4_phase": context.h4_phase,
        "theme_aligned": context.theme_aligned,
        "theme_alignment": context.theme_alignment,
        "counter_entry_theme_alignment": context.counter_entry_theme_alignment,
        "jpy_alignment_status": context.jpy_alignment_status,
        "jpy_alignment": context.jpy_alignment,
        "dual_theme_status": context.dual_theme_status,
        "spread_normal": context.spread_normal,
        "spread_pips": context.spread_pips,
        "max_allowed_spread_pips": context.max_allowed_spread_pips,
        "market_bias": _normalize_direction(context.market_bias),
        "trend_direction": _normalize_direction(context.trend_direction),
        "price_position": _normalize_structure_label(context.price_position),
        "main_support": context.main_support,
        "main_resistance": context.main_resistance,
        "key_support": context.key_support,
        "key_resistance": context.key_resistance,
        "buy_pullback_low": context.buy_pullback_low,
        "buy_pullback_high": context.buy_pullback_high,
        "breakout_retest_low": context.breakout_retest_low,
        "breakout_retest_high": context.breakout_retest_high,
        "sell_rejection_low": context.sell_rejection_low,
        "sell_rejection_high": context.sell_rejection_high,
        "range_position": context.range_position,
        "is_late_pressure": context.is_late_pressure,
        "resistance_low": context.resistance_low,
        "resistance_high": context.resistance_high,
        "minor_support": context.minor_support,
        "major_support": context.major_support,
        "m15_close": context.m15_close,
        "m15_open": context.m15_open,
        "m15_high": context.m15_high,
        "m15_low": context.m15_low,
        "m15_range_atr_ratio": context.m15_range_atr_ratio,
        "m15_body_atr_ratio": context.m15_body_atr_ratio,
        "m15_close_above_resistance": context.m15_close_above_resistance,
        "m15_breakout_retest_held": context.m15_breakout_retest_held,
        "m15_rejection_from_resistance": context.m15_rejection_from_resistance,
        "m15_close_below_minor_support": context.m15_close_below_minor_support,
        "support_low": context.support_low,
        "support_high": context.support_high,
        "minor_resistance": context.minor_resistance,
        "m15_close_below_support": context.m15_close_below_support,
        "m15_breakdown_retest_held": context.m15_breakdown_retest_held,
        "m15_rejection_from_support": context.m15_rejection_from_support,
        "m15_close_above_minor_resistance": context.m15_close_above_minor_resistance,
        "sl_buffer": context.sl_buffer,
        "sl_tight": context.sl_tight,
        "sl_safe": context.sl_safe,
        "continuation_sl_tight": context.continuation_sl_tight,
        "continuation_sl_safe": context.continuation_sl_safe,
        "tp1_support": context.tp1_support,
        "tp2_support": context.tp2_support,
        "tp3_support": context.tp3_support,
        "tp4_support": context.tp4_support,
        "tp1_resistance": context.tp1_resistance,
        "tp2_resistance": context.tp2_resistance,
        "tp3_resistance": context.tp3_resistance,
        "tp4_resistance": context.tp4_resistance,
        "m15_bar_count": context.m15_bar_count,
        "h1_bar_count": context.h1_bar_count,
        "support_ladder_ready": context.support_ladder_ready,
        "resistance_ladder_ready": context.resistance_ladder_ready,
        "tradeplan_context_ready": context.tradeplan_context_ready,
        "support_ladder_missing_reason": context.support_ladder_missing_reason,
        "resistance_ladder_missing_reason": context.resistance_ladder_missing_reason,
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
        bid=_optional_float(raw.get("bid")),
        ask=_optional_float(raw.get("ask")),
        pip_value=_optional_float(raw.get("pip_value")),
        price_at_signal_start=_optional_float(raw.get("price_at_signal_start")),
        price_at_5m_confirm=_optional_float(raw.get("price_at_5m_confirm")),
        price_at_signal_end=_optional_float(raw.get("price_at_signal_end")),
        m15_phase=_optional_str(raw.get("m15_phase")),
        h1_phase=_optional_str(raw.get("h1_phase")),
        h4_phase=_optional_str(raw.get("h4_phase")),
        theme_aligned=_optional_bool(raw.get("theme_aligned")),
        theme_alignment=_optional_str(raw.get("theme_alignment")),
        counter_entry_theme_alignment=_optional_str(raw.get("counter_entry_theme_alignment")),
        jpy_alignment_status=_optional_str(raw.get("jpy_alignment_status")),
        jpy_alignment=_optional_str(raw.get("jpy_alignment")),
        dual_theme_status=_optional_str(raw.get("dual_theme_status")),
        spread_normal=_optional_bool(raw.get("spread_normal")),
        spread_pips=_optional_float(raw.get("spread_pips")),
        max_allowed_spread_pips=_optional_float(raw.get("max_allowed_spread_pips")),
        market_bias=_optional_str(raw.get("market_bias")),
        trend_direction=_optional_str(raw.get("trend_direction")),
        price_position=_optional_str(raw.get("price_position")),
        main_support=_optional_float(raw.get("main_support")),
        main_resistance=_optional_float(raw.get("main_resistance")),
        key_support=_optional_float(raw.get("key_support")),
        key_resistance=_optional_float(raw.get("key_resistance")),
        buy_pullback_low=_optional_float(raw.get("buy_pullback_low")),
        buy_pullback_high=_optional_float(raw.get("buy_pullback_high")),
        breakout_retest_low=_optional_float(raw.get("breakout_retest_low")),
        breakout_retest_high=_optional_float(raw.get("breakout_retest_high")),
        sell_rejection_low=_optional_float(raw.get("sell_rejection_low")),
        sell_rejection_high=_optional_float(raw.get("sell_rejection_high")),
        range_position=_optional_float(raw.get("range_position")),
        is_late_pressure=bool(raw.get("is_late_pressure", False)),
        resistance_low=_optional_float(raw.get("resistance_low")),
        resistance_high=_optional_float(raw.get("resistance_high")),
        minor_support=_optional_float(raw.get("minor_support")),
        major_support=_optional_float(raw.get("major_support")),
        m15_close=_optional_float(raw.get("m15_close")),
        m15_open=_optional_float(raw.get("m15_open")),
        m15_high=_optional_float(raw.get("m15_high")),
        m15_low=_optional_float(raw.get("m15_low")),
        m15_range_atr_ratio=_optional_float(raw.get("m15_range_atr_ratio")),
        m15_body_atr_ratio=_optional_float(raw.get("m15_body_atr_ratio")),
        m15_close_above_resistance=_optional_bool(raw.get("m15_close_above_resistance")),
        m15_breakout_retest_held=_optional_bool(raw.get("m15_breakout_retest_held")),
        m15_rejection_from_resistance=_optional_bool(raw.get("m15_rejection_from_resistance")),
        m15_close_below_minor_support=_optional_bool(raw.get("m15_close_below_minor_support")),
        support_low=_optional_float(raw.get("support_low")),
        support_high=_optional_float(raw.get("support_high")),
        minor_resistance=_optional_float(raw.get("minor_resistance")),
        m15_close_below_support=_optional_bool(raw.get("m15_close_below_support")),
        m15_breakdown_retest_held=_optional_bool(raw.get("m15_breakdown_retest_held")),
        m15_rejection_from_support=_optional_bool(raw.get("m15_rejection_from_support")),
        m15_close_above_minor_resistance=_optional_bool(raw.get("m15_close_above_minor_resistance")),
        sl_buffer=_optional_float(raw.get("sl_buffer")),
        sl_tight=_optional_float(raw.get("sl_tight")),
        sl_safe=_optional_float(raw.get("sl_safe")),
        continuation_sl_tight=_optional_float(raw.get("continuation_sl_tight")),
        continuation_sl_safe=_optional_float(raw.get("continuation_sl_safe")),
        tp1_support=_optional_float(raw.get("tp1_support")),
        tp2_support=_optional_float(raw.get("tp2_support")),
        tp3_support=_optional_float(raw.get("tp3_support")),
        tp4_support=_optional_float(raw.get("tp4_support")),
        tp1_resistance=_optional_float(raw.get("tp1_resistance")),
        tp2_resistance=_optional_float(raw.get("tp2_resistance")),
        tp3_resistance=_optional_float(raw.get("tp3_resistance")),
        tp4_resistance=_optional_float(raw.get("tp4_resistance")),
        m15_bar_count=_optional_int(raw.get("m15_bar_count")),
        h1_bar_count=_optional_int(raw.get("h1_bar_count")),
        support_ladder_ready=_optional_bool(raw.get("support_ladder_ready")),
        resistance_ladder_ready=_optional_bool(raw.get("resistance_ladder_ready")),
        tradeplan_context_ready=_optional_bool(raw.get("tradeplan_context_ready")),
        support_ladder_missing_reason=_optional_str(raw.get("support_ladder_missing_reason")),
        resistance_ladder_missing_reason=_optional_str(raw.get("resistance_ladder_missing_reason")),
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


def _microboost_lifecycle(blocks: list[MicroboostBlockIntel]) -> dict[str, Any]:
    latest = max(blocks, key=lambda item: item.end_utc) if blocks else None
    raw_rows = sum(max(0, block.event_count) for block in blocks)
    effective_ticks = sum(max(0, block.effective_tick_count) for block in blocks)
    return {
        "cluster_count": len({block.cluster_id for block in blocks}),
        "raw_rows": raw_rows,
        "effective_ticks": effective_ticks,
        "latest_cluster_id": None if latest is None else latest.cluster_id,
        "latest_stage": None if latest is None else latest.cluster_stage,
        "latest_phase_unpriced": None if latest is None else latest.phase_unpriced,
        "latest_phase_priced": None if latest is None else latest.phase_priced,
        "latest_action": None if latest is None else latest.action,
        "dedup_required": raw_rows > len({block.cluster_id for block in blocks}),
        "stages": dict(Counter(block.cluster_stage for block in blocks)),
    }


def _cluster_id(symbol: str, start_utc: str) -> str:
    parsed = _parse_iso_datetime(start_utc)
    if parsed is None:
        return f"{symbol}_UNKNOWN"
    return f"{symbol}_{parsed:%Y%m%dT%H%M%SZ}"


def _cluster_stage(
    *,
    phase_unpriced: str,
    phase_priced: str | None,
    action: str,
    duration_seconds: float,
    clean_block_seconds: int,
    requires_market_context: bool,
) -> str:
    priced = str(phase_priced or "").upper()
    if priced in {"EXHAUSTION_AT_RESISTANCE", "EXHAUSTION_AT_SUPPORT", "LATE_DENSE_PRESSURE"}:
        return "protect_or_no_chase"
    if priced in {"BULLISH_PULLBACK_MICROBOOST", "BEARISH_PULLBACK_MICROBOOST", "MINOR_PULLBACK_MICROBOOST"}:
        return "pullback_validation"
    if priced in {"SUPPORT_BOUNCE_MICROBOOST", "RESISTANCE_REJECTION_MICROBOOST"}:
        return "structure_reaction"
    if str(action or "").upper() == "WAIT_PULLBACK_COMPLETION":
        return "pullback_validation"
    if duration_seconds >= clean_block_seconds * 0.85 or phase_unpriced == "NEAR_TIMING_GATE_MICROBOOST":
        return "near_timing_gate"
    if requires_market_context:
        return "needs_market_context"
    return "growing"


def _has_applied_market_context(block: MicroboostBlockIntel) -> bool:
    snapshot = block.market_context_snapshot
    if not isinstance(snapshot, dict):
        return False
    return (
        snapshot.get("price_at_signal_start") is not None
        and snapshot.get("price_at_5m_confirm") is not None
        and snapshot.get("price_at_signal_end") is not None
        and block.price_position is not None
    )


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _m15_phase_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"PIVOT_RECLAIM", "BULLISH_PULLBACK", "BREAKOUT_RETEST", "SUPPORT_HOLD", "HIGH_BASE_CONTINUATION"}:
        return "BUY"
    if text in {"BREAKDOWN_RETEST", "BEARISH_PULLBACK", "RESISTANCE_REJECTION", "LOWER_HIGH", "SUPPORT_BREAK"}:
        return "SELL"
    return _normalize_direction(text)


def _h1_phase_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BULLISH", "BULLISH_PULLBACK", "UPTREND", "ACCUMULATION_RECLAIM"}:
        return "BUY"
    if text in {"BEARISH", "BEARISH_PULLBACK", "DOWNTREND", "DISTRIBUTION_BREAKDOWN"}:
        return "SELL"
    return _normalize_direction(text)


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


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
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


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    values = [str(item) for item in value if str(item or "").strip()]
    return values or None


def _normalize_direction(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if text in {"BUY", "SELL"}:
        return text
    if text in {"BULL", "BULLISH", "LONG", "UPTREND", "TREND_UP"}:
        return "BUY"
    if text in {"BEAR", "BEARISH", "SHORT", "DOWNTREND", "TREND_DOWN"}:
        return "SELL"
    return None


def _normalize_structure_label(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if not text:
        return None
    if text in {"MAIN_RESISTANCE", "RESISTANCE", "NEAR_RESISTANCE", "UPPER_RANGE"}:
        return "MAIN_RESISTANCE"
    if text in {"MAIN_SUPPORT", "SUPPORT", "NEAR_SUPPORT", "LOWER_RANGE"}:
        return "MAIN_SUPPORT"
    if text in {"MID_RANGE", "VALUE_AREA", "RANGE_MID"}:
        return "MID_RANGE"
    return text


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
