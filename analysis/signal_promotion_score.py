"""Advisory promotion scoring for signal-pressure candidates.

The score explains whether observed pressure is mature enough for deeper
review. It is not an execution gate and does not emit SignalJSON.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from schemas.direction import normalize_direction

from .outcome_memory import outcome_memory_for


@dataclass(frozen=True)
class SignalPromotionScore:
    symbol: str
    direction: str | None
    score: int
    threshold: int
    eligible: bool
    status: str
    blockers: list[str]
    positive_evidence: list[str]
    negative_evidence: list[str]
    components: dict[str, Any]
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_signal_promotion(
    *,
    candidate: Mapping[str, Any] | None = None,
    allowed_quorum: Mapping[str, Any] | None = None,
    microboost_summary: Mapping[str, Any] | None = None,
    market_context_validation: Mapping[str, Any] | None = None,
    pressure_cluster_summary: Mapping[str, Any] | None = None,
    outcome_memory_summary: Mapping[str, Any] | None = None,
    regime_invalidation: Mapping[str, Any] | None = None,
    threshold: int = 70,
) -> SignalPromotionScore:
    symbol, direction = _candidate_identity(candidate, allowed_quorum, microboost_summary)
    if not symbol:
        return SignalPromotionScore(
            symbol="UNKNOWN",
            direction=direction,
            score=0,
            threshold=int(threshold),
            eligible=False,
            status="INSUFFICIENT_DATA",
            blockers=["SYMBOL_MISSING"],
            positive_evidence=[],
            negative_evidence=[],
            components={},
        )

    score = 0.0
    blockers: list[str] = []
    positive: list[str] = []
    negative: list[str] = []
    components: dict[str, Any] = {}

    pressure_points = _pressure_points(candidate)
    score += pressure_points
    components["pressure_points"] = round(pressure_points, 2)
    if pressure_points > 0:
        positive.append("PRESSURE_BLOCK_PRESENT")

    quorum_points = _allowed_quorum_points(allowed_quorum)
    score += quorum_points
    components["allowed_quorum_points"] = round(quorum_points, 2)
    if quorum_points >= 10:
        positive.append("ALLOWED_QUORUM_REACHED")

    microboost_points = _microboost_points(microboost_summary)
    score += microboost_points
    components["microboost_points"] = round(microboost_points, 2)
    if microboost_points > 0:
        positive.append("MICROBOOST_CONTEXT_PRESENT")

    market_points, market_blockers, market_negative = _market_context_points(market_context_validation)
    score += market_points
    components["market_context_points"] = round(market_points, 2)
    blockers.extend(market_blockers)
    negative.extend(market_negative)
    if market_points >= 20:
        positive.append("MARKET_CONTEXT_VALIDATED")

    cluster_points, cluster_negative = _cluster_points(pressure_cluster_summary, symbol, direction)
    score += cluster_points
    components["pressure_cluster_points"] = round(cluster_points, 2)
    negative.extend(cluster_negative)

    outcome_points, outcome_negative, outcome_payload = _outcome_points(outcome_memory_summary, symbol, direction)
    score += outcome_points
    components["outcome_memory_points"] = round(outcome_points, 2)
    if outcome_payload:
        components["outcome_memory"] = outcome_payload
    negative.extend(outcome_negative)
    if outcome_points > 0:
        positive.append("OUTCOME_MEMORY_SUPPORTS_DIRECTION")

    regime_points, regime_blockers, regime_negative = _regime_points(regime_invalidation)
    score += regime_points
    components["regime_points"] = round(regime_points, 2)
    blockers.extend(regime_blockers)
    negative.extend(regime_negative)

    if direction not in {"BUY", "SELL"}:
        blockers.append("DIRECTION_MISSING")
    final_score = max(0, min(100, int(round(score))))
    blockers = _dedupe(blockers)
    positive = _dedupe(positive)
    negative = _dedupe(negative)
    eligible = final_score >= int(threshold) and not blockers
    if blockers:
        status = "BLOCKED"
    elif eligible:
        status = "PROMOTION_CANDIDATE"
    else:
        status = "WATCH_ONLY"

    return SignalPromotionScore(
        symbol=symbol,
        direction=direction,
        score=final_score,
        threshold=int(threshold),
        eligible=eligible,
        status=status,
        blockers=blockers,
        positive_evidence=positive,
        negative_evidence=negative,
        components=components,
    )


def _candidate_identity(
    candidate: Mapping[str, Any] | None,
    allowed_quorum: Mapping[str, Any] | None,
    microboost_summary: Mapping[str, Any] | None,
) -> tuple[str, str | None]:
    for source in (
        candidate,
        allowed_quorum,
        _latest_microboost(microboost_summary),
    ):
        if not isinstance(source, Mapping):
            continue
        symbol = str(source.get("symbol") or "").upper()
        direction = normalize_direction(
            _optional_text(source.get("direction") or source.get("raw_direction") or source.get("final_direction")),
            _optional_text(source.get("verdict") or source.get("source_verdict")),
        )
        if symbol:
            return symbol, direction
    return "", None


def _pressure_points(candidate: Mapping[str, Any] | None) -> float:
    if not isinstance(candidate, Mapping):
        return 0.0
    events = _coerce_float(candidate.get("effective_ticks") or candidate.get("events")) or 0.0
    duration = _coerce_float(candidate.get("duration_minutes")) or 0.0
    density = _coerce_float(candidate.get("effective_density_per_minute") or candidate.get("density_per_minute")) or 0.0
    points = min(24.0, events * 1.2 + duration * 1.5 + min(density, 8.0))
    grade = str(candidate.get("pressure_grade") or "").upper()
    if grade == "A":
        points += 6
    elif grade == "B":
        points += 3
    return min(30.0, points)


def _allowed_quorum_points(allowed_quorum: Mapping[str, Any] | None) -> float:
    if not isinstance(allowed_quorum, Mapping):
        return 0.0
    streak = _coerce_float(allowed_quorum.get("streak") or allowed_quorum.get("count")) or 0.0
    points = min(8.0, streak * 2.0)
    if allowed_quorum.get("quorum_reached") is True:
        points += 8.0
    return min(16.0, points)


def _microboost_points(microboost_summary: Mapping[str, Any] | None) -> float:
    if not isinstance(microboost_summary, Mapping):
        return 0.0
    count = _coerce_float(microboost_summary.get("count_total")) or 0.0
    points = min(8.0, count * 2.0)
    latest = _latest_microboost(microboost_summary)
    if isinstance(latest, Mapping):
        points += 6.0
        if latest.get("direction_validation_status") in {"PASSED", "VALIDATED"}:
            points += 4.0
    return min(18.0, points)


def _market_context_points(validation: Mapping[str, Any] | None) -> tuple[float, list[str], list[str]]:
    if not isinstance(validation, Mapping):
        return -15.0, ["MARKET_CONTEXT_MISSING"], ["MARKET_CONTEXT_MISSING"]
    if validation.get("direction_validated") is True:
        return 25.0, [], []
    action = str(validation.get("action") or "").upper()
    reason = str(validation.get("reason") or "").upper()
    blockers: list[str] = []
    negative: list[str] = []
    if action.startswith("BLOCK") or str(validation.get("execution_grade") or "").upper() == "BLOCKED":
        blockers.append(action or "MARKET_CONTEXT_BLOCKED")
    elif validation.get("requires_market_context") is True:
        blockers.append("MARKET_CONTEXT_REQUIRED")
    else:
        blockers.append("MARKET_CONTEXT_NOT_VALIDATED")
    if "MISSING_MARKET_CONTEXT" in reason:
        negative.append("MARKET_CONTEXT_INCOMPLETE")
    elif reason:
        negative.append(reason)
    return -20.0, blockers, negative


def _cluster_points(summary: Mapping[str, Any] | None, symbol: str, direction: str | None) -> tuple[float, list[str]]:
    if not isinstance(summary, Mapping):
        return 0.0, []
    key = f"{symbol}:{direction or 'NONE'}"
    groups = summary.get("by_symbol_direction")
    if not isinstance(groups, Mapping) or key not in groups:
        return 0.0, []
    item = groups.get(key)
    if not isinstance(item, Mapping):
        return 0.0, []
    cluster_score = _coerce_float(item.get("cluster_pressure_score")) or 0.0
    duplicate_penalty = _coerce_float(item.get("duplicate_penalty")) or 0.0
    points = min(14.0, cluster_score * 0.2) - min(14.0, duplicate_penalty * 14.0)
    negative = ["DUPLICATE_PRESSURE_CLUSTER"] if duplicate_penalty >= 0.50 else []
    return points, negative


def _outcome_points(
    summary: Mapping[str, Any] | None,
    symbol: str,
    direction: str | None,
) -> tuple[float, list[str], dict[str, Any] | None]:
    memory = outcome_memory_for(summary, symbol, direction)
    if not memory:
        return 0.0, [], None
    failure_rate = _coerce_float(memory.get("failure_rate")) or 0.0
    success_rate = _coerce_float(memory.get("success_rate")) or 0.0
    known_records = _coerce_float(memory.get("known_records")) or 0.0
    if known_records < 3:
        return 0.0, ["OUTCOME_MEMORY_INSUFFICIENT"], memory
    if failure_rate >= 0.60:
        return -18.0, ["OUTCOME_MEMORY_FAILURE_CLUSTER"], memory
    if success_rate >= 0.60:
        return 8.0, [], memory
    return 0.0, [], memory


def _regime_points(regime: Mapping[str, Any] | None) -> tuple[float, list[str], list[str]]:
    if not isinstance(regime, Mapping):
        return 0.0, [], []
    if regime.get("invalidated") is True:
        blockers = _string_list(regime.get("blockers")) or ["REGIME_INVALIDATED"]
        return -35.0, blockers, ["REGIME_INVALIDATED"]
    if str(regime.get("status") or "").upper() == "CAUTION":
        return -8.0, [], _string_list(regime.get("warnings")) or ["REGIME_CAUTION"]
    if str(regime.get("status") or "").upper() == "VALID":
        return 6.0, [], []
    return 0.0, [], []


def _latest_microboost(summary: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    latest = summary.get("latest") if isinstance(summary, Mapping) else None
    return latest if isinstance(latest, Mapping) else None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item or "").strip()]


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
    "SignalPromotionScore",
    "score_signal_promotion",
]
