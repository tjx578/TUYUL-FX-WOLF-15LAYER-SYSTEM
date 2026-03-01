"""Layer-4 multi-factor scoring utilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

DEFAULT_PASS_THRESHOLD = 55.0


class ScoreGrade(Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


@dataclass(frozen=True)
class ScoringWeights:
    trend_alignment: float = 0.25
    structure_quality: float = 0.20
    momentum: float = 0.15
    volume_confirmation: float = 0.10
    multi_timeframe_confluence: float = 0.15
    key_level_proximity: float = 0.15

    def __post_init__(self) -> None:
        total = (
            self.trend_alignment
            + self.structure_quality
            + self.momentum
            + self.volume_confirmation
            + self.multi_timeframe_confluence
            + self.key_level_proximity
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError("ScoringWeights must sum to 1.0")


@dataclass(frozen=True)
class FactorScores:
    trend_alignment: float
    structure_quality: float
    momentum: float
    volume_confirmation: float
    multi_timeframe_confluence: float
    key_level_proximity: float

    def __post_init__(self) -> None:
        for field_name in (
            "trend_alignment",
            "structure_quality",
            "momentum",
            "volume_confirmation",
            "multi_timeframe_confluence",
            "key_level_proximity",
        ):
            value = getattr(self, field_name)
            if not 0.0 <= value <= 100.0:
                raise ValueError(f"{field_name} must be 0–100")


@dataclass(frozen=True)
class L4Result:
    symbol: str
    composite_score: float
    grade: ScoreGrade
    pass_threshold: bool
    threshold_used: float
    dominant_factor: str
    weakness_factor: str
    metadata: dict[str, Any] | None = None


def compute_composite(
    factors: FactorScores,
    weights: ScoringWeights | None = None,
) -> float:
    w = weights or ScoringWeights()
    score = (
        factors.trend_alignment * w.trend_alignment
        + factors.structure_quality * w.structure_quality
        + factors.momentum * w.momentum
        + factors.volume_confirmation * w.volume_confirmation
        + factors.multi_timeframe_confluence * w.multi_timeframe_confluence
        + factors.key_level_proximity * w.key_level_proximity
    )
    return round(score, 4)


def classify_grade(score_value: float) -> ScoreGrade:
    if score_value >= 90.0:
        return ScoreGrade.A_PLUS
    if score_value >= 80.0:
        return ScoreGrade.A
    if score_value >= 65.0:
        return ScoreGrade.B
    if score_value >= 50.0:
        return ScoreGrade.C
    if score_value >= 35.0:
        return ScoreGrade.D
    return ScoreGrade.F


def score(
    symbol: str,
    factors: FactorScores,
    weights: ScoringWeights | None = None,
    threshold: float = DEFAULT_PASS_THRESHOLD,
    metadata: dict[str, Any] | None = None,
) -> L4Result:
    composite = compute_composite(factors, weights)
    field_values = {
        "trend_alignment": factors.trend_alignment,
        "structure_quality": factors.structure_quality,
        "momentum": factors.momentum,
        "volume_confirmation": factors.volume_confirmation,
        "multi_timeframe_confluence": factors.multi_timeframe_confluence,
        "key_level_proximity": factors.key_level_proximity,
    }
    dominant_factor = max(field_values, key=field_values.get)
    weakness_factor = min(field_values, key=field_values.get)
    return L4Result(
        symbol=symbol,
        composite_score=composite,
        grade=classify_grade(composite),
        pass_threshold=composite >= threshold,
        threshold_used=threshold,
        dominant_factor=dominant_factor,
        weakness_factor=weakness_factor,
        metadata=metadata,
    )
