"""# noqa: F821
Layer 14 — Adaptive Learning / Pattern Memory
Zone: Journal ↔ Analysis boundary. Append-only pattern storage.
NO execution side-effects. NO decision authority. NO L12 override.

Analyses historical L13 reflection records to extract:
  - Recurring win/loss patterns by setup type, session, pair
  - Layer accuracy trends (which layers are reliable vs noisy)
  - Psychological pattern correlations
  - Suggested weight adjustments (advisory ONLY — L12 decides whether to adopt)

Output is an immutable insight record. L14 proposes; L12 disposes.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from journal.l13_reflection import (
    L13ReflectionRecord,
    ReflectionVerdict,
)

logger = logging.getLogger(__name__)


class InsightType(StrEnum):
    """Classification of the extracted insight."""

    PAIR_PATTERN = "PAIR_PATTERN"
    SESSION_PATTERN = "SESSION_PATTERN"
    LAYER_ACCURACY = "LAYER_ACCURACY"
    PSYCH_CORRELATION = "PSYCH_CORRELATION"
    STREAK_PATTERN = "STREAK_PATTERN"
    GENERAL = "GENERAL"


class InsightSeverity(StrEnum):
    """How actionable is this insight?"""

    INFORMATIONAL = "INFORMATIONAL"
    ADVISORY = "ADVISORY"  # L12 may want to consider
    STRONG_ADVISORY = "STRONG_ADVISORY"  # high statistical confidence


@dataclass(frozen=True)
class WeightAdjustmentSuggestion:
    """
    Advisory-only suggestion. L14 proposes; L12 decides.
    This NEVER auto-applies — constitutional boundary.
    """

    layer: str
    current_weight: float | None = None
    suggested_weight: float | None = None
    direction: str = ""  # "increase" | "decrease" | "maintain"
    confidence: float = 0.0  # 0–1 statistical confidence
    reasoning: str = ""


@dataclass(frozen=True)
class PatternInsight:
    """Single extracted pattern / insight from historical data."""

    insight_type: InsightType
    severity: InsightSeverity
    title: str
    description: str
    sample_size: int  # how many reflections support this
    win_rate: float | None = None  # 0–1
    statistical_confidence: float = 0.0  # 0–1
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class L14AdaptiveResult:
    """
    Immutable output of L14 analysis. Appended to pattern memory.
    ADVISORY ONLY — L12 decides whether to incorporate.
    """

    analysis_id: str
    period_label: str  # e.g. "2026-W07", "2026-02"
    total_reflections_analysed: int
    overall_win_rate: float  # 0–1
    insights: tuple[PatternInsight, ...]
    weight_suggestions: tuple[WeightAdjustmentSuggestion, ...]
    top_lesson_tags: tuple[str, ...]  # most frequent lesson tags
    timestamp: str
    metadata: dict[str, object] = field(default_factory=lambda: {})


# ---------------------------------------------------------------------------
# Analysis functions — all pure, no side-effects
# ---------------------------------------------------------------------------

_CORRECT_VERDICTS = frozenset(
    {
        ReflectionVerdict.CORRECT_EXECUTE,
        ReflectionVerdict.CORRECT_REJECT,
    }
)


def _compute_overall_win_rate(records: Sequence[L13ReflectionRecord]) -> float:
    """Win rate from reflection verdicts."""
    if not records:
        return 0.0
    wins = sum(1 for r in records if r.reflection_verdict in _CORRECT_VERDICTS)
    return round(wins / len(records), 4)


def _extract_pair_patterns(
    records: Sequence[L13ReflectionRecord],
) -> list[PatternInsight]:
    """Win rate per symbol — flag outliers."""
    insights: list[PatternInsight] = []
    pair_groups: dict[str, list[L13ReflectionRecord]] = {}
    for r in records:
        pair_groups.setdefault(r.symbol, []).append(r)

    for symbol, group in pair_groups.items():
        if len(group) < 3:
            continue  # not enough data
        wins = sum(1 for r in group if r.reflection_verdict in _CORRECT_VERDICTS)
        wr = wins / len(group)
        severity = InsightSeverity.INFORMATIONAL
        if (wr >= 0.75 and len(group) >= 5) or (wr <= 0.30 and len(group) >= 5):
            severity = InsightSeverity.STRONG_ADVISORY

        insights.append(
            PatternInsight(
                insight_type=InsightType.PAIR_PATTERN,
                severity=severity,
                title=f"{symbol} win rate: {wr:.0%}",
                description=f"{symbol}: {wins}/{len(group)} correct decisions over analysis period.",
                sample_size=len(group),
                win_rate=round(wr, 4),
                statistical_confidence=min(1.0, len(group) / 20.0),
            )
        )
    return insights


def _extract_layer_accuracy(
    records: Sequence[L13ReflectionRecord],
) -> list[PatternInsight]:
    """Which layers are consistently contributing positively or negatively?"""
    insights: list[PatternInsight] = []
    layer_stats: dict[str, dict[str, int]] = {}

    for r in records:
        for contrib in r.layer_contributions:
            if contrib.layer not in layer_stats:
                layer_stats[contrib.layer] = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
            key = contrib.accuracy_contribution
            if key in layer_stats[contrib.layer]:
                layer_stats[contrib.layer][key] += 1

    for layer, stats in layer_stats.items():
        total = stats["POSITIVE"] + stats["NEGATIVE"] + stats["NEUTRAL"]
        if total < 3:
            continue
        positive_rate = stats["POSITIVE"] / total
        negative_rate = stats["NEGATIVE"] / total

        if positive_rate >= 0.70:
            severity = InsightSeverity.ADVISORY
            title = f"{layer}: consistently accurate ({positive_rate:.0%} positive)"
        elif negative_rate >= 0.50:
            severity = InsightSeverity.STRONG_ADVISORY
            title = f"{layer}: frequently inaccurate ({negative_rate:.0%} negative)"
        else:
            severity = InsightSeverity.INFORMATIONAL
            title = f"{layer}: mixed accuracy"

        insights.append(
            PatternInsight(
                insight_type=InsightType.LAYER_ACCURACY,
                severity=severity,
                title=title,
                description=(
                    f"{layer} — positive: {stats['POSITIVE']}, "
                    f"negative: {stats['NEGATIVE']}, neutral: {stats['NEUTRAL']}"
                ),
                sample_size=total,
                win_rate=round(positive_rate, 4),
                statistical_confidence=min(1.0, total / 15.0),
            )
        )
    return insights


def _extract_top_lesson_tags(
    records: Sequence[L13ReflectionRecord],
    top_n: int = 5,
) -> list[str]:
    """Most frequent lesson tags across all reflections."""
    counter: Counter[str] = Counter()
    for r in records:
        counter.update(r.lesson_tags)
    return [tag for tag, _ in counter.most_common(top_n)]


def _generate_weight_suggestions(
    records: Sequence[L13ReflectionRecord],
) -> list[WeightAdjustmentSuggestion]:
    """
    Advisory weight adjustments based on layer accuracy patterns.
    These are PROPOSALS ONLY — L14 never auto-applies.
    """
    suggestions: list[WeightAdjustmentSuggestion] = []
    layer_pos: dict[str, int] = {}
    layer_neg: dict[str, int] = {}
    layer_total: dict[str, int] = {}

    for r in records:
        for contrib in r.layer_contributions:
            layer_total[contrib.layer] = layer_total.get(contrib.layer, 0) + 1
            if contrib.accuracy_contribution == "POSITIVE":
                layer_pos[contrib.layer] = layer_pos.get(contrib.layer, 0) + 1
            elif contrib.accuracy_contribution == "NEGATIVE":
                layer_neg[contrib.layer] = layer_neg.get(contrib.layer, 0) + 1

    for layer, total in layer_total.items():
        if total < 5:
            continue
        pos_rate = layer_pos.get(layer, 0) / total
        neg_rate = layer_neg.get(layer, 0) / total

        if pos_rate >= 0.75:
            suggestions.append(
                WeightAdjustmentSuggestion(
                    layer=layer,
                    direction="increase",
                    confidence=round(min(1.0, total / 20.0), 2),
                    reasoning=f"{pos_rate:.0%} positive accuracy over {total} samples",
                )
            )
        elif neg_rate >= 0.50:
            suggestions.append(
                WeightAdjustmentSuggestion(
                    layer=layer,
                    direction="decrease",
                    confidence=round(min(1.0, total / 20.0), 2),
                    reasoning=f"{neg_rate:.0%} negative accuracy over {total} samples",
                )
            )
        else:
            suggestions.append(
                WeightAdjustmentSuggestion(
                    layer=layer,
                    direction="maintain",
                    confidence=round(min(1.0, total / 20.0), 2),
                    reasoning=f"Mixed results: {pos_rate:.0%} positive, {neg_rate:.0%} negative",
                )
            )

    return suggestions


def analyze_patterns(
    records: Sequence[L13ReflectionRecord],
    analysis_id: str,
    period_label: str,
    metadata: dict[str, object] | None = None,
) -> L14AdaptiveResult:
    """
    Main entry point for Layer-14 adaptive learning.

    Analyses a batch of L13 reflection records to extract patterns.
    Output is ADVISORY ONLY — appended to pattern memory.
    L12 decides whether to incorporate any suggestions.

    Parameters
    ----------
    records : Sequence[L13ReflectionRecord]
        Historical reflection records to analyse.
    analysis_id : str
        Unique identifier for this analysis run.
    period_label : str
        Human-readable period label (e.g. "2026-W07").
    metadata : dict, optional
        Additional context.

    Returns
    -------
    L14AdaptiveResult
        Immutable analysis result with insights and suggestions.
    """
    overall_wr = _compute_overall_win_rate(records)
    pair_insights = _extract_pair_patterns(records)
    layer_insights = _extract_layer_accuracy(records)
    top_tags = _extract_top_lesson_tags(records)
    weight_suggestions = _generate_weight_suggestions(records)

    all_insights = pair_insights + layer_insights

    result = L14AdaptiveResult(
        analysis_id=analysis_id,
        period_label=period_label,
        total_reflections_analysed=len(records),
        overall_win_rate=overall_wr,
        insights=tuple(all_insights),
        weight_suggestions=tuple(weight_suggestions),
        top_lesson_tags=tuple(top_tags),
        timestamp=datetime.now(UTC).isoformat(),
        metadata=metadata or {},
    )

    logger.info(
        "L14 [%s] period=%s | %d reflections | WR=%.2f | %d insights | %d suggestions",
        analysis_id,
        period_label,
        len(records),
        overall_wr,
        len(all_insights),
        len(weight_suggestions),
    )
    return result  # noqa: F821
