"""Advisory pip follow-through scoring for SignalThrottle clean blocks.

This module is observability-only. It ranks whether a pressure block still has
room to move; it never grants execution permission and never mutates trade-plan
fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from schemas.direction import normalize_direction

_SCHEMA_VERSION = "1.0-followthrough-observability"
_SOURCE_EVENT = "SignalThrottleFollowthroughScore"
_EXECUTION_IMPACT = False
_KEY_RESISTANCE_POSITIONS = {"MAIN_RESISTANCE", "KEY_RESISTANCE", "RESISTANCE"}
_KEY_SUPPORT_POSITIONS = {"MAIN_SUPPORT", "KEY_SUPPORT", "SUPPORT"}


@dataclass(frozen=True)
class SignalThrottleFollowthroughScore:
    event: str
    schema_version: str
    symbol: str
    direction: str | None
    source_clean_block_id: str | None
    followthrough_score: int
    followthrough_bucket: str
    pressure_quality_bucket: str
    duration_maturity_bucket: str
    duration_maturity_score: float
    pressure_quality_score: float
    room_to_move_score: float
    room_to_resistance_pips: float | None
    room_to_support_pips: float | None
    directional_room_pips: float | None
    pre_move_pips: float | None
    structure_alignment_score: float
    htf_daily_bias: str | None
    htf_h4_structure: str | None
    htf_price_location: str | None
    htf_allowed_playbook: str | None
    htf_blocked_playbook: list[str] | None
    basket_theme_score: float
    microboost_role: str
    microboost_score: float
    gap_health: str
    max_gap_seconds: float
    gap_degradation_penalty: float
    late_move_penalty: float
    components: dict[str, Any]
    positive_evidence: list[str]
    risk_flags: list[str]
    source_event: str = _SOURCE_EVENT
    valid_for_execution: bool = False
    execution_impact: bool = _EXECUTION_IMPACT
    is_final_signal: bool = False
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_signal_throttle_followthrough_scores(
    *,
    clean_watch_candidates: Sequence[Mapping[str, Any]] | None,
    pressure_tiers: Sequence[Mapping[str, Any]] | None = None,
    market_contexts: Mapping[str, Any] | None = None,
    microboost_summary: Mapping[str, Any] | None = None,
    max_symbols: int | None = None,
) -> list[dict[str, Any]]:
    """Build advisory follow-through scores for clean block candidates."""

    tiers = _rows_by_symbol(pressure_tiers)
    contexts = market_contexts or {}
    scores: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in clean_watch_candidates or []:
        if not isinstance(candidate, Mapping):
            continue
        symbol = str(candidate.get("symbol") or "").upper()
        source_id = str(candidate.get("source_clean_block_id") or "").strip()
        dedupe_key = source_id or symbol
        if not symbol or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        score = score_signal_throttle_followthrough(
            candidate=candidate,
            pressure_tier=tiers.get(symbol),
            market_context=_market_context_for_symbol(contexts, symbol),
            microboost=_microboost_for_symbol(microboost_summary, symbol),
        )
        scores.append(score.to_dict())

    scores.sort(
        key=lambda item: (
            int(item.get("followthrough_score") or 0),
            float(item.get("duration_maturity_score") or 0.0),
            float(item.get("pressure_quality_score") or 0.0),
        ),
        reverse=True,
    )
    if max_symbols is not None:
        scores = scores[: max(0, int(max_symbols))]
    return scores


def score_signal_throttle_followthrough(
    *,
    candidate: Mapping[str, Any],
    pressure_tier: Mapping[str, Any] | None = None,
    market_context: Any | None = None,
    microboost: Mapping[str, Any] | None = None,
) -> SignalThrottleFollowthroughScore:
    symbol = str(candidate.get("symbol") or "").upper()
    direction = _direction(candidate, pressure_tier, market_context)
    source_id = _text(candidate.get("source_clean_block_id") or candidate.get("source_pressure_block_id"))
    maturity_score, maturity_bucket = _duration_maturity(candidate, pressure_tier)
    pressure_quality_score, pressure_quality_bucket, pressure_positive = _pressure_quality(candidate)
    gap_health, gap_penalty = _gap_health(candidate)
    room = _room_to_move(symbol=symbol, direction=direction, context=market_context)
    structure_score, structure_positive, structure_risks = _structure_alignment(direction, market_context)
    basket_score, basket_positive, basket_risks = _basket_theme_score(pressure_tier, market_context)
    microboost_role, microboost_score, microboost_positive, microboost_risks, microboost_penalty = _microboost_role(
        microboost,
        direction=direction,
        context=market_context,
    )
    late_penalty, late_risks = _late_move_penalty(direction=direction, context=market_context, room=room)

    score = (
        maturity_score
        + pressure_quality_score
        + room["room_to_move_score"]
        + structure_score
        + basket_score
        + microboost_score
        - gap_penalty
        - late_penalty
        - microboost_penalty
    )
    final_score = max(0, min(100, int(round(score))))
    positive = _dedupe(
        [
            *_maturity_positive(maturity_score, maturity_bucket),
            *pressure_positive,
            *room["positive_evidence"],
            *structure_positive,
            *basket_positive,
            *microboost_positive,
        ]
    )
    risks = _dedupe(
        [
            *room["risk_flags"],
            *structure_risks,
            *basket_risks,
            *microboost_risks,
            *late_risks,
            *([] if gap_penalty <= 0 else [f"GAP_DEGRADED_{gap_health}"]),
        ]
    )
    if direction not in {"BUY", "SELL"}:
        risks.append("DIRECTION_UNRESOLVED")
    components = {
        "duration_maturity_score": round(maturity_score, 2),
        "pressure_quality_score": round(pressure_quality_score, 2),
        "room_to_move_score": round(room["room_to_move_score"], 2),
        "structure_alignment_score": round(structure_score, 2),
        "basket_theme_score": round(basket_score, 2),
        "microboost_score": round(microboost_score, 2),
        "gap_degradation_penalty": round(gap_penalty, 2),
        "late_move_penalty": round(late_penalty, 2),
        "microboost_penalty": round(microboost_penalty, 2),
        "htf_daily_bias": _text(_field(market_context, "htf_daily_bias") or _field(market_context, "d1_phase")) or None,
        "htf_h4_structure": _text(_field(market_context, "htf_h4_structure") or _field(market_context, "h4_phase")) or None,
        "htf_price_location": _text(_field(market_context, "htf_price_location")) or None,
        "htf_allowed_playbook": _text(_field(market_context, "htf_allowed_playbook")) or None,
        "htf_blocked_playbook": _string_list(_field(market_context, "htf_blocked_playbook")) or None,
    }
    return SignalThrottleFollowthroughScore(
        event="signal_throttle_followthrough_score_json",
        schema_version=_SCHEMA_VERSION,
        symbol=symbol or "UNKNOWN",
        direction=direction,
        source_clean_block_id=source_id,
        followthrough_score=final_score,
        followthrough_bucket=_bucket(final_score, risks),
        pressure_quality_bucket=pressure_quality_bucket,
        duration_maturity_bucket=maturity_bucket,
        duration_maturity_score=round(maturity_score, 2),
        pressure_quality_score=round(pressure_quality_score, 2),
        room_to_move_score=round(room["room_to_move_score"], 2),
        room_to_resistance_pips=room["room_to_resistance_pips"],
        room_to_support_pips=room["room_to_support_pips"],
        directional_room_pips=room["directional_room_pips"],
        pre_move_pips=room["pre_move_pips"],
        structure_alignment_score=round(structure_score, 2),
        htf_daily_bias=_text(_field(market_context, "htf_daily_bias") or _field(market_context, "d1_phase")) or None,
        htf_h4_structure=_text(_field(market_context, "htf_h4_structure") or _field(market_context, "h4_phase")) or None,
        htf_price_location=_text(_field(market_context, "htf_price_location")) or None,
        htf_allowed_playbook=_text(_field(market_context, "htf_allowed_playbook")) or None,
        htf_blocked_playbook=_string_list(_field(market_context, "htf_blocked_playbook")) or None,
        basket_theme_score=round(basket_score, 2),
        microboost_role=microboost_role,
        microboost_score=round(microboost_score, 2),
        gap_health=gap_health,
        max_gap_seconds=round(_number(candidate.get("max_gap_seconds")), 3),
        gap_degradation_penalty=round(gap_penalty, 2),
        late_move_penalty=round(late_penalty + microboost_penalty, 2),
        components=components,
        positive_evidence=positive,
        risk_flags=risks,
    )


def followthrough_context_for_symbol(
    scores: Sequence[Mapping[str, Any]] | None,
    symbol: str,
) -> dict[str, Any] | None:
    normalized = str(symbol or "").upper()
    if not normalized:
        return None
    for raw in scores or []:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("symbol") or "").upper() != normalized:
            continue
        return {
            "followthrough_score": _int(raw.get("followthrough_score")),
            "followthrough_bucket": _text(raw.get("followthrough_bucket")),
            "pressure_quality_bucket": _text(raw.get("pressure_quality_bucket")),
            "duration_maturity_bucket": _text(raw.get("duration_maturity_bucket")),
            "microboost_role": _text(raw.get("microboost_role")),
            "htf_daily_bias": _text(raw.get("htf_daily_bias")),
            "htf_h4_structure": _text(raw.get("htf_h4_structure")),
            "htf_price_location": _text(raw.get("htf_price_location")),
            "htf_allowed_playbook": _text(raw.get("htf_allowed_playbook")),
            "htf_blocked_playbook": _string_list(raw.get("htf_blocked_playbook")),
            "room_to_move_score": _number_or_none(raw.get("room_to_move_score")),
            "directional_room_pips": _number_or_none(raw.get("directional_room_pips")),
            "gap_health": _text(raw.get("gap_health")),
            "late_move_penalty": _number_or_none(raw.get("late_move_penalty")),
            "gap_degradation_penalty": _number_or_none(raw.get("gap_degradation_penalty")),
            "risk_flags": _string_list(raw.get("risk_flags")),
            "source_event": _SOURCE_EVENT,
            "valid_for_execution": False,
            "execution_impact": False,
            "is_final_signal": False,
            "advisory_only": True,
        }
    return None


def signal_throttle_followthrough_score_log_payload(
    scores: Sequence[Mapping[str, Any]] | None,
    *,
    max_symbols: int = 8,
) -> dict[str, Any] | None:
    rows = [dict(row) for row in scores or [] if isinstance(row, Mapping)]
    if not rows:
        return None
    rows.sort(key=lambda item: int(item.get("followthrough_score") or 0), reverse=True)
    top = rows[: max(1, int(max_symbols))]
    high = sum(1 for row in rows if int(row.get("followthrough_score") or 0) >= 80)
    context_missing = sum(1 for row in rows if "MARKET_CONTEXT_MISSING" in _string_list(row.get("risk_flags")))
    late_risk = sum(1 for row in rows if _number(row.get("late_move_penalty")) > 0)
    gap_degraded = sum(1 for row in rows if _number(row.get("gap_degradation_penalty")) > 0)
    compact = [_compact_score(row) for row in top]
    return {
        "event": "signal_throttle_followthrough_score_snapshot",
        "schema_version": _SCHEMA_VERSION,
        "source_event": _SOURCE_EVENT,
        "score_count": len(rows),
        "high_followthrough_count": high,
        "context_missing_count": context_missing,
        "late_risk_count": late_risk,
        "gap_degraded_count": gap_degraded,
        "scores": compact,
        "display_line": _display_line(compact, total=len(rows)),
        "valid_for_execution": False,
        "execution_impact": False,
        "is_final_signal": False,
        "advisory_only": True,
    }


def _compact_score(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(row.get("symbol") or "").upper(),
        "direction": row.get("direction"),
        "followthrough_score": row.get("followthrough_score"),
        "followthrough_bucket": row.get("followthrough_bucket"),
        "duration_maturity_bucket": row.get("duration_maturity_bucket"),
        "pressure_quality_bucket": row.get("pressure_quality_bucket"),
        "microboost_role": row.get("microboost_role"),
        "htf_daily_bias": row.get("htf_daily_bias"),
        "htf_h4_structure": row.get("htf_h4_structure"),
        "htf_price_location": row.get("htf_price_location"),
        "directional_room_pips": row.get("directional_room_pips"),
        "gap_health": row.get("gap_health"),
        "late_move_penalty": row.get("late_move_penalty"),
        "risk_flags": _string_list(row.get("risk_flags"))[:5],
    }


def _display_line(rows: Sequence[Mapping[str, Any]], *, total: int) -> str:
    labels = ", ".join(
        f"{row.get('symbol')}:{row.get('direction') or 'WAIT'}:{row.get('followthrough_score')}"
        f":{row.get('followthrough_bucket')}"
        for row in rows
    ) or "-"
    return f"followthrough_scores total={total} top={len(rows)}[{labels}] execution_impact=false"


def _duration_maturity(
    candidate: Mapping[str, Any],
    pressure_tier: Mapping[str, Any] | None,
) -> tuple[float, str]:
    metric = _metric_for_scope(pressure_tier)
    if metric:
        score = _number_or_none(metric.get("timing_maturity_score"))
        bucket = _text(metric.get("timing_maturity_bucket"))
        if score is not None and bucket:
            return min(30.0, score), bucket
    duration = _duration_seconds(candidate)
    if duration >= 1800:
        return 30.0, "MAJOR_30M"
    if duration >= 1200:
        return 29.0, "DOMINANT_20M"
    if duration >= 900:
        return 27.0, "SUSTAINED_CONFIRMED_15M"
    if duration >= 600:
        return 24.0, "SUSTAINED_10M"
    if duration >= 300:
        return 20.0, "TIMING_VALID_5M"
    if duration > 0:
        return min(8.0, duration / 300.0 * 8.0), "SUB_5M_PRESSURE"
    return 0.0, "NO_CLEAN_BLOCK"


def _pressure_quality(candidate: Mapping[str, Any]) -> tuple[float, str, list[str]]:
    ticks = max(_number(candidate.get("effective_ticks")), _number(candidate.get("events")))
    density = _number(candidate.get("effective_density_per_minute") or candidate.get("density_per_minute"))
    gap_health, gap_penalty = _gap_health(candidate)
    tick_score = min(6.0, ticks / 12.0)
    density_score = min(10.0, density * 2.0)
    gap_score = 4.0 if gap_health in {"VERY_HEALTHY", "HEALTHY"} else 2.0 if gap_health == "INTERMITTENT" else 0.0
    score = max(0.0, tick_score + density_score + gap_score - min(4.0, gap_penalty / 5.0))
    evidence = []
    if ticks > 0:
        evidence.append("EFFECTIVE_PRESSURE_TICKS")
    if density > 0:
        evidence.append("PRESSURE_DENSITY_PRESENT")
    if gap_health in {"VERY_HEALTHY", "HEALTHY"}:
        evidence.append("GAP_HEALTHY")
    if gap_health == "BROKEN_SEQUENCE":
        bucket = "BROKEN_SEQUENCE_PRESSURE"
    elif gap_penalty > 0:
        bucket = "GAP_DEGRADED_PRESSURE"
    elif density >= 2.0 and ticks >= 20:
        bucket = "ACTIVE_CLEAN_PRESSURE"
    elif density > 0:
        bucket = "LOW_DENSITY_CLEAN_PRESSURE"
    else:
        bucket = "PRESSURE_QUALITY_UNKNOWN"
    return min(20.0, score), bucket, evidence


def _gap_health(candidate: Mapping[str, Any]) -> tuple[str, float]:
    gap = _number(candidate.get("max_gap_seconds"))
    if gap <= 75.0:
        return "VERY_HEALTHY", 0.0
    if gap <= 300.0:
        return "HEALTHY", 0.0
    if gap <= 900.0:
        return "INTERMITTENT", 6.0
    if gap <= 1800.0:
        return "WEAK", 12.0
    return "BROKEN_SEQUENCE", 20.0


def _room_to_move(*, symbol: str, direction: str | None, context: Any | None) -> dict[str, Any]:
    if context is None:
        return {
            "room_to_move_score": 0.0,
            "room_to_resistance_pips": None,
            "room_to_support_pips": None,
            "directional_room_pips": None,
            "pre_move_pips": None,
            "positive_evidence": [],
            "risk_flags": ["MARKET_CONTEXT_MISSING"],
        }
    price = _first_number(
        _field(context, "price_at_signal_end"),
        _field(context, "price_at_5m_confirm"),
        _field(context, "bid"),
        _field(context, "ask"),
        _field(context, "price_at_signal_start"),
    )
    start_price = _first_number(_field(context, "price_at_signal_start"))
    support = _first_number(_field(context, "key_support"), _field(context, "main_support"))
    resistance = _first_number(_field(context, "key_resistance"), _field(context, "main_resistance"))
    if price is None:
        return {
            "room_to_move_score": 0.0,
            "room_to_resistance_pips": None,
            "room_to_support_pips": None,
            "directional_room_pips": None,
            "pre_move_pips": None,
            "positive_evidence": [],
            "risk_flags": ["REFERENCE_PRICE_MISSING"],
        }
    pip = _pip_size(symbol, context)
    room_to_resistance = None if resistance is None else round((resistance - price) / pip, 2)
    room_to_support = None if support is None else round((price - support) / pip, 2)
    directional_room = room_to_resistance if direction == "BUY" else room_to_support if direction == "SELL" else None
    pre_move = None
    if start_price is not None and direction in {"BUY", "SELL"}:
        raw_pre_move = (price - start_price) / pip if direction == "BUY" else (start_price - price) / pip
        pre_move = round(max(0.0, raw_pre_move), 2)
    score = _room_score(directional_room)
    risks: list[str] = []
    positive: list[str] = []
    if directional_room is None:
        risks.append("DIRECTIONAL_ROOM_MISSING")
    elif directional_room <= 5:
        risks.append("ROOM_TO_MOVE_SMALL")
    elif directional_room >= 20:
        positive.append("OPEN_LANE_ROOM_TO_MOVE")
    if pre_move is not None and directional_room is not None and pre_move >= 25 and directional_room <= 10:
        risks.append("PRE_MOVE_ALREADY_EXTENDED")
    return {
        "room_to_move_score": score,
        "room_to_resistance_pips": room_to_resistance,
        "room_to_support_pips": room_to_support,
        "directional_room_pips": directional_room,
        "pre_move_pips": pre_move,
        "positive_evidence": positive,
        "risk_flags": risks,
    }


def _room_score(room_pips: float | None) -> float:
    if room_pips is None or room_pips <= 0:
        return 0.0
    if room_pips >= 30:
        return 20.0
    if room_pips >= 20:
        return 16.0
    if room_pips >= 12:
        return 12.0
    if room_pips >= 6:
        return 7.0
    return 3.0


def _structure_alignment(direction: str | None, context: Any | None) -> tuple[float, list[str], list[str]]:
    if context is None:
        return 0.0, [], ["MARKET_STRUCTURE_CONTEXT_MISSING"]
    score = 0.0
    positive: list[str] = []
    risks: list[str] = []
    m15 = _text(_field(context, "m15_phase")).upper()
    h1 = _text(_field(context, "h1_phase")).upper()
    h4 = _text(_field(context, "htf_h4_structure") or _field(context, "h4_phase")).upper()
    daily = _text(_field(context, "htf_daily_bias") or _field(context, "d1_phase")).upper()
    htf_location = _text(_field(context, "htf_price_location")).upper()
    blocked_playbook = set(_string_list(_field(context, "htf_blocked_playbook")))
    price_position = _text(_field(context, "price_position")).upper()
    if direction in {"BUY", "SELL"} and _phase_aligned(direction, m15):
        score += 4.0
        positive.append("M15_STRUCTURE_ALIGNED")
    elif m15:
        risks.append("M15_STRUCTURE_CONFLICT")
    if direction in {"BUY", "SELL"} and _phase_aligned(direction, h1):
        score += 5.0
        positive.append("H1_STRUCTURE_ALIGNED")
    elif h1:
        risks.append("H1_STRUCTURE_CONFLICT")
    if direction in {"BUY", "SELL"} and _htf_phase_aligned(direction, h4):
        score += 5.0
        positive.append("H4_STRUCTURE_ALIGNED")
    elif h4 and h4 not in {"RANGE", "NO_STRUCTURE", "UNKNOWN"}:
        risks.append("H4_STRUCTURE_CONFLICT")
    if direction in {"BUY", "SELL"} and _htf_phase_aligned(direction, daily):
        score += 5.0
        positive.append("DAILY_BIAS_ALIGNED")
    elif daily and daily not in {"RANGE", "TRANSITION", "NO_BIAS", "UNKNOWN"}:
        risks.append("DAILY_BIAS_CONFLICT")
    if direction == "BUY":
        if htf_location in {"DISCOUNT", "H4_DEMAND"}:
            score += 3.0
            positive.append("HTF_BUY_LOCATION_SUPPORTED")
        elif htf_location in {"PREMIUM", "H4_SUPPLY"}:
            risks.append("HTF_BUY_AT_PREMIUM_OR_SUPPLY_NO_CHASE")
        if "BUY_LIMIT" in blocked_playbook and "BUY_BREAKOUT_CHASE" in blocked_playbook:
            risks.append("HTF_BUY_PLAYBOOK_BLOCKED")
        elif blocked_playbook:
            positive.append("HTF_BUY_PLAYBOOK_NOT_HARD_BLOCKED")
    elif direction == "SELL":
        if htf_location in {"PREMIUM", "H4_SUPPLY"}:
            score += 3.0
            positive.append("HTF_SELL_LOCATION_SUPPORTED")
        elif htf_location in {"DISCOUNT", "H4_DEMAND"}:
            risks.append("HTF_SELL_AT_DISCOUNT_OR_DEMAND_NO_CHASE")
        if "SELL_LIMIT" in blocked_playbook and "SELL_BREAKOUT_CHASE" in blocked_playbook:
            risks.append("HTF_SELL_PLAYBOOK_BLOCKED")
        elif blocked_playbook:
            positive.append("HTF_SELL_PLAYBOOK_NOT_HARD_BLOCKED")
    if direction == "BUY" and price_position in {"MID_RANGE", *_KEY_SUPPORT_POSITIONS}:
        score += 2.0
        positive.append("BUY_NOT_CHASING_KEY_RESISTANCE")
    elif direction == "SELL" and price_position in {"MID_RANGE", *_KEY_RESISTANCE_POSITIONS}:
        score += 2.0
        positive.append("SELL_NOT_CHASING_KEY_SUPPORT")
    return min(24.0, score), positive, risks


def _basket_theme_score(
    pressure_tier: Mapping[str, Any] | None,
    context: Any | None,
) -> tuple[float, list[str], list[str]]:
    positive: list[str] = []
    risks: list[str] = []
    if _bool(_field(context, "theme_aligned")) is True:
        positive.append("MARKET_CONTEXT_THEME_ALIGNED")
        return 10.0, positive, risks
    metric = _metric_for_scope(pressure_tier)
    if _bool(metric.get("theme_aligned") if metric else None) is True:
        positive.append("PRESSURE_TIER_THEME_ALIGNED")
        return 8.0, positive, risks
    reasons = pressure_tier.get("tier_reasons") if isinstance(pressure_tier, Mapping) else []
    if isinstance(reasons, Sequence) and "THEME_ALIGNED" in reasons:
        positive.append("PRESSURE_TIER_THEME_ALIGNED")
        return 8.0, positive, risks
    if context is not None and _field(context, "theme_aligned") is False:
        risks.append("THEME_ALIGNMENT_CONFLICT")
    return 0.0, positive, risks


def _microboost_role(
    microboost: Mapping[str, Any] | None,
    *,
    direction: str | None,
    context: Any | None,
) -> tuple[str, float, list[str], list[str], float]:
    if not isinstance(microboost, Mapping):
        return "NO_MICROBOOST", 0.0, [], [], 0.0
    micro_direction = normalize_direction(_text(microboost.get("direction") or microboost.get("raw_direction")), None)
    if micro_direction in {"BUY", "SELL"} and direction in {"BUY", "SELL"} and micro_direction != direction:
        return "COUNTER_PRESSURE_WARNING", 0.0, [], ["MICROBOOST_DIRECTION_CONFLICT"], 12.0
    phase_priced = _text(microboost.get("phase_priced")).upper()
    phase_unpriced = _text(microboost.get("phase_unpriced")).upper()
    action = _text(microboost.get("action")).upper()
    if phase_priced in {"EXHAUSTION_AT_RESISTANCE", "EXHAUSTION_AT_SUPPORT"}:
        return "ABSORPTION_WARNING", 0.0, [], ["MICROBOOST_ABSORPTION_WARNING"], 16.0
    if phase_priced == "LATE_DENSE_PRESSURE" or action == "PROTECT_PROFIT":
        return "PROFIT_PROTECTION", 0.0, [], ["MICROBOOST_LATE_PROFIT_PROTECTION"], 12.0
    if phase_priced in {
        "CONFIRMATION_MICROBOOST",
        "CONTINUATION_MICROBOOST",
        "BULLISH_PULLBACK_MICROBOOST",
        "BEARISH_PULLBACK_MICROBOOST",
    }:
        return "CONFIRMATION_OR_ACCELERATION", 10.0, ["MICROBOOST_CONFIRMS_PRESSURE"], [], 0.0
    if phase_unpriced == "IGNITION_MICROBOOST":
        return "IGNITION", 6.0, ["MICROBOOST_IGNITION"], [], 0.0
    if phase_unpriced in {"DENSE_MICROBOOST", "REPEATED_MICROBOOST", "NEAR_TIMING_GATE_MICROBOOST"}:
        if context is None:
            return "UNPRICED_ACCELERATION_REQUIRES_CONTEXT", 4.0, ["MICROBOOST_ACCELERATION_PRESENT"], [], 0.0
        return "ACCELERATION", 8.0, ["MICROBOOST_ACCELERATION_PRESENT"], [], 0.0
    return "MICROBOOST_CONTEXT_PRESENT", 4.0, ["MICROBOOST_CONTEXT_PRESENT"], [], 0.0


def _late_move_penalty(*, direction: str | None, context: Any | None, room: Mapping[str, Any]) -> tuple[float, list[str]]:
    if context is None:
        return 0.0, []
    price_position = _text(_field(context, "price_position")).upper()
    directional_room = _number_or_none(room.get("directional_room_pips"))
    pre_move = _number_or_none(room.get("pre_move_pips"))
    penalty = 0.0
    risks: list[str] = []
    if direction == "BUY" and price_position in _KEY_RESISTANCE_POSITIONS:
        penalty += 16.0
        risks.append("BUY_PRESSURE_AT_KEY_RESISTANCE_NO_CHASE")
    if direction == "SELL" and price_position in _KEY_SUPPORT_POSITIONS:
        penalty += 16.0
        risks.append("SELL_PRESSURE_AT_KEY_SUPPORT_NO_CHASE")
    if pre_move is not None and directional_room is not None and pre_move >= 25 and directional_room <= 10:
        penalty += 10.0
        risks.append("LATE_MOVE_ROOM_EXHAUSTED")
    return min(26.0, penalty), risks


def _bucket(score: int, risks: Sequence[str]) -> str:
    risk_set = set(risks)
    if "MARKET_CONTEXT_MISSING" in risk_set or "REFERENCE_PRICE_MISSING" in risk_set:
        return "CONTEXT_REQUIRED"
    if (
        "BUY_PRESSURE_AT_KEY_RESISTANCE_NO_CHASE" in risk_set
        or "SELL_PRESSURE_AT_KEY_SUPPORT_NO_CHASE" in risk_set
        or "HTF_BUY_AT_PREMIUM_OR_SUPPLY_NO_CHASE" in risk_set
        or "HTF_SELL_AT_DISCOUNT_OR_DEMAND_NO_CHASE" in risk_set
        or "HTF_BUY_PLAYBOOK_BLOCKED" in risk_set
        or "HTF_SELL_PLAYBOOK_BLOCKED" in risk_set
    ):
        return "LATE_OR_ABSORPTION_RISK"
    if "GAP_DEGRADED_BROKEN_SEQUENCE" in risk_set:
        return "GAP_DEGRADED_RADAR"
    if score >= 80:
        return "HIGH_FOLLOWTHROUGH_CANDIDATE"
    if score >= 65:
        return "MEDIUM_FOLLOWTHROUGH_CANDIDATE"
    if score >= 45:
        return "WATCH_ONLY_FOLLOWTHROUGH"
    return "LOW_FOLLOWTHROUGH_RADAR"


def _direction(
    candidate: Mapping[str, Any],
    pressure_tier: Mapping[str, Any] | None,
    context: Any | None,
) -> str | None:
    return normalize_direction(
        _text(
            candidate.get("clean_block_direction")
            or candidate.get("raw_pressure_direction")
            or candidate.get("direction")
            or (pressure_tier or {}).get("direction")
            or _field(context, "raw_allowed_direction")
        ),
        None,
    )


def _maturity_positive(score: float, bucket: str) -> list[str]:
    if score >= 30:
        return ["MAJOR_PRESSURE_DURATION"]
    if score >= 27:
        return ["SUSTAINED_PRESSURE_MATURITY"]
    if score >= 20:
        return ["TIMING_VALID_CLEAN_BLOCK"]
    return []


def _metric_for_scope(pressure_tier: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(pressure_tier, Mapping):
        return {}
    metrics = pressure_tier.get("metrics")
    if not isinstance(metrics, Mapping):
        return {}
    scope = str(pressure_tier.get("tier_scope") or "live").lower()
    if scope.startswith("live"):
        return metrics.get("live") if isinstance(metrics.get("live"), Mapping) else {}
    if scope.startswith("session"):
        return metrics.get("session") if isinstance(metrics.get("session"), Mapping) else {}
    if scope.startswith("archive"):
        return metrics.get("archive") if isinstance(metrics.get("archive"), Mapping) else {}
    return {}


def _microboost_for_symbol(summary: Mapping[str, Any] | None, symbol: str) -> Mapping[str, Any] | None:
    if not isinstance(summary, Mapping):
        return None
    latest = summary.get("latest")
    if isinstance(latest, Mapping) and str(latest.get("symbol") or "").upper() == symbol:
        return latest
    blocks = summary.get("blocks")
    if isinstance(blocks, Sequence):
        matches = [block for block in blocks if isinstance(block, Mapping) and str(block.get("symbol") or "").upper() == symbol]
        if matches:
            return matches[-1]
    return None


def _rows_by_symbol(rows: Sequence[Mapping[str, Any]] | None) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            result[symbol] = row
    return result


def _market_context_for_symbol(contexts: Mapping[str, Any], symbol: str) -> Any | None:
    normalized = str(symbol or "").upper()
    return contexts.get(normalized) or contexts.get(normalized.lower()) or contexts.get(symbol)


def _duration_seconds(candidate: Mapping[str, Any]) -> float:
    if _number(candidate.get("clean_block_duration_seconds")) > 0:
        return _number(candidate.get("clean_block_duration_seconds"))
    if _number(candidate.get("source_clean_block_latest_duration_seconds")) > 0:
        return _number(candidate.get("source_clean_block_latest_duration_seconds"))
    if _number(candidate.get("duration_seconds")) > 0:
        return _number(candidate.get("duration_seconds"))
    return _number(candidate.get("duration_minutes")) * 60.0


def _field(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    if is_dataclass(source):
        return asdict(source).get(name)
    return getattr(source, name, None)


def _phase_aligned(direction: str, phase: str) -> bool:
    phase = str(phase or "").upper()
    if not phase:
        return False
    bullish = ("BULL", "UPTREND", "SUPPORT_HOLD", "PIVOT_RECLAIM", "ACCUMULATION", "BREAKOUT")
    bearish = ("BEAR", "DOWNTREND", "RESISTANCE_REJECTION", "SUPPORT_BREAK", "DISTRIBUTION", "BREAKDOWN")
    return any(token in phase for token in (bullish if direction == "BUY" else bearish))


def _htf_phase_aligned(direction: str, phase: str) -> bool:
    phase = str(phase or "").upper()
    if not phase:
        return False
    if direction == "BUY":
        return any(token in phase for token in ("BULL", "UPTREND", "DEMAND", "DISCOUNT"))
    return any(token in phase for token in ("BEAR", "DOWNTREND", "SUPPLY", "PREMIUM"))


def _pip_size(symbol: str, context: Any | None) -> float:
    raw = _number_or_none(_field(context, "pip_value"))
    if raw and raw > 0:
        return raw
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number(value: Any) -> float:
    number = _number_or_none(value)
    return 0.0 if number is None else number


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    return int(round(_number(value)))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = [
    "SignalThrottleFollowthroughScore",
    "build_signal_throttle_followthrough_scores",
    "followthrough_context_for_symbol",
    "score_signal_throttle_followthrough",
    "signal_throttle_followthrough_score_log_payload",
]
