"""Data contracts for cross-symbol ranking and conditional watchlists."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PairRank:
    """One ranked symbol candidate from the universe-level analysis."""

    symbol: str
    rank: int = 0
    bias: str = "NEUTRAL"
    phase: str = "MIXED_OR_UNKNOWN"
    watchlist_status: str = "BLOCKED"
    rank_score: float = 0.0
    theme_score: float = 0.0
    relative_strength_delta: float = 0.0
    cross_confirmation_score: float = 0.0
    entry_quality_score: float = 0.0
    confidence: float = 0.0
    base_currency: str = ""
    quote_currency: str = ""
    short_roc: float = 0.0
    medium_roc: float = 0.0
    data_ready: bool = True
    reasons: list[str] = field(default_factory=list)
    l12_verdict: str | None = None
    execution_allowed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "rank": self.rank,
            "bias": self.bias,
            "phase": self.phase,
            "watchlist_status": self.watchlist_status,
            "rank_score": round(self.rank_score, 4),
            "theme_score": round(self.theme_score, 4),
            "relative_strength_delta": round(self.relative_strength_delta, 4),
            "cross_confirmation_score": round(self.cross_confirmation_score, 4),
            "entry_quality_score": round(self.entry_quality_score, 4),
            "confidence": round(self.confidence, 4),
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "short_roc": round(self.short_roc, 6),
            "medium_roc": round(self.medium_roc, 6),
            "data_ready": self.data_ready,
            "reasons": list(self.reasons),
            "l12_verdict": self.l12_verdict,
            "execution_allowed": self.execution_allowed,
        }


@dataclass
class UniverseRankingResult:
    """Full snapshot emitted by the universe ranking engine."""

    target_symbol: str
    data_ready: bool
    readiness_reasons: list[str]
    currency_scores: dict[str, float] = field(default_factory=dict)
    currency_ranks: list[str] = field(default_factory=list)
    pairs_analyzed: int = 0
    pairs_available: int = 0
    ranked_pairs: list[PairRank] = field(default_factory=list)
    target_rank: PairRank | None = None
    top_n: int = 5
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        target = self.target_rank.to_dict() if self.target_rank is not None else None
        return {
            "target_symbol": self.target_symbol,
            "data_ready": self.data_ready,
            "readiness_reasons": list(self.readiness_reasons),
            "currency_scores": {k: round(v, 4) for k, v in self.currency_scores.items()},
            "currency_ranks": list(self.currency_ranks),
            "pairs_analyzed": self.pairs_analyzed,
            "pairs_available": self.pairs_available,
            "top_n": self.top_n,
            "target_rank": target,
            "top_pairs": [pair.to_dict() for pair in self.ranked_pairs[: self.top_n]],
            "ranked_pairs": [pair.to_dict() for pair in self.ranked_pairs],
            "errors": list(self.errors),
        }


__all__ = ["PairRank", "UniverseRankingResult"]
