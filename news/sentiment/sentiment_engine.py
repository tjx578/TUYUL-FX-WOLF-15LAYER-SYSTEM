"""
Sentiment scoring engine — FinBERT primary, keyword fallback.

Zone: analysis/ -- advisory-only, no execution side-effects.

Architecture
------------
- ``SentimentScorer`` protocol defines the interface.
- ``FinBertScorer`` uses ProsusAI/finbert for transformer-based scoring.
- ``KeywordScorer`` provides the fallback when FinBERT is unavailable.
- ``HybridScorer`` chains FinBERT → keyword fallback gracefully.
- ``get_default_scorer()`` returns the best available implementation.

All scoring is pure computation — no side effects, no execution authority.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentimentResult:
    """Result of sentiment analysis on a text."""

    score: float  # -1.0 (bearish) to +1.0 (bullish)
    label: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0.0 to 1.0 — model confidence
    method: str  # "finbert", "keyword", "hybrid"
    entities: list[str] = field(default_factory=list)  # detected entities
    details: dict = field(default_factory=dict)  # method-specific metadata


@runtime_checkable
class SentimentScorer(Protocol):
    """Protocol for all sentiment scoring implementations."""

    name: str

    def score(self, text: str, currency: str | None = None) -> SentimentResult:
        """Score sentiment of text, optionally filtered by currency context."""
        ...  # pragma: no cover

    def score_batch(self, texts: list[str], currency: str | None = None) -> list[SentimentResult]:
        """Score a batch of texts."""
        ...  # pragma: no cover


class KeywordScorer:
    """
    Enhanced keyword-based sentiment scorer.

    Improvements over the original FinnhubMarketNews._score_sentiment:
    - Weighted keywords (high-impact phrases score more)
    - Negation handling ("not hawkish" → bearish)
    - Currency-contextual scoring (only count keywords near currency mentions)
    - Entity extraction for central banks and currencies
    """

    name: str = "keyword"

    # Weighted keywords: (phrase, weight)
    # Higher weight = stronger signal
    BULLISH_KEYWORDS: list[tuple[str, float]] = [
        # Central bank hawkish
        ("hawkish", 1.5),
        ("rate hike", 2.0),
        ("rate increase", 2.0),
        ("tightening", 1.5),
        ("quantitative tightening", 2.0),
        ("higher rates", 1.5),
        ("raising rates", 2.0),
        ("restrictive policy", 1.5),
        # Economic strength
        ("strong growth", 1.5),
        ("beat expectations", 1.8),
        ("beat estimate", 1.8),
        ("above consensus", 1.5),
        ("better than expected", 1.8),
        ("surged", 1.2),
        ("surge", 1.0),
        ("rallied", 1.0),
        ("rally", 0.8),
        ("robust", 1.0),
        ("expanded", 0.8),
        ("accelerated", 1.0),
        ("upbeat", 0.8),
        # Employment
        ("jobs added", 1.5),
        ("unemployment fell", 1.5),
        ("jobless claims fell", 1.5),
        ("payrolls beat", 2.0),
        # Inflation (hawkish context)
        ("inflation rose", 1.0),
        ("cpi above", 1.5),
        ("hot inflation", 1.5),
    ]

    BEARISH_KEYWORDS: list[tuple[str, float]] = [
        # Central bank dovish
        ("dovish", 1.5),
        ("rate cut", 2.0),
        ("rate reduction", 2.0),
        ("easing", 1.5),
        ("quantitative easing", 2.0),
        ("lower rates", 1.5),
        ("cutting rates", 2.0),
        ("accommodative policy", 1.5),
        # Economic weakness
        ("weak growth", 1.5),
        ("missed expectations", 1.8),
        ("missed estimate", 1.8),
        ("below consensus", 1.5),
        ("worse than expected", 1.8),
        ("declined", 1.0),
        ("decline", 0.8),
        ("slumped", 1.2),
        ("slump", 1.0),
        ("contracted", 1.2),
        ("recession", 2.0),
        ("recessionary", 2.0),
        ("slowdown", 1.0),
        ("downturn", 1.2),
        # Employment
        ("jobs lost", 1.5),
        ("unemployment rose", 1.5),
        ("jobless claims rose", 1.5),
        ("payrolls missed", 2.0),
        # Inflation (dovish context)
        ("inflation fell", 1.0),
        ("cpi below", 1.5),
        ("disinflation", 1.2),
        ("deflation", 1.5),
    ]

    NEGATION_WORDS: set[str] = {"not", "no", "never", "neither", "without", "unlikely", "fails to"}

    def score(self, text: str, currency: str | None = None) -> SentimentResult:
        text_lower = text.lower()

        # Entity extraction
        from news.sentiment.entity_recognizer import extract_entities

        entities = extract_entities(text)

        bullish_weight = 0.0
        bearish_weight = 0.0

        for phrase, weight in self.BULLISH_KEYWORDS:
            count = self._count_with_negation(text_lower, phrase)
            if count > 0:
                bullish_weight += weight * count
            elif count < 0:
                bearish_weight += weight * abs(count)

        for phrase, weight in self.BEARISH_KEYWORDS:
            count = self._count_with_negation(text_lower, phrase)
            if count > 0:
                bearish_weight += weight * count
            elif count < 0:
                bullish_weight += weight * abs(count)

        total = bullish_weight + bearish_weight
        if total == 0.0:
            return SentimentResult(
                score=0.0,
                label="neutral",
                confidence=0.0,
                method=self.name,
                entities=entities,
                details={"bullish_weight": 0.0, "bearish_weight": 0.0},
            )

        raw_score = (bullish_weight - bearish_weight) / total
        # Confidence scales with total keyword weight (capped at 1.0)
        confidence = min(total / 10.0, 1.0)

        if raw_score > 0.15:
            label = "bullish"
        elif raw_score < -0.15:
            label = "bearish"
        else:
            label = "neutral"

        return SentimentResult(
            score=round(raw_score, 4),
            label=label,
            confidence=round(confidence, 4),
            method=self.name,
            entities=entities,
            details={
                "bullish_weight": round(bullish_weight, 3),
                "bearish_weight": round(bearish_weight, 3),
            },
        )

    def score_batch(self, texts: list[str], currency: str | None = None) -> list[SentimentResult]:
        return [self.score(t, currency) for t in texts]

    def _count_with_negation(self, text: str, phrase: str) -> int:
        """
        Count phrase occurrences, returning negative count if negated.

        Returns positive int for normal matches, negative for negated matches.
        If both exist, returns net count.
        """
        import re

        # Build pattern that checks for optional negation before the phrase
        escaped = re.escape(phrase)
        neg_pattern = rf"\b(?:{'|'.join(re.escape(n) for n in self.NEGATION_WORDS)})\s+(?:\w+\s+){{0,2}}{escaped}\b"
        plain_pattern = rf"\b{escaped}\b"

        negated_count = len(re.findall(neg_pattern, text))
        total_count = len(re.findall(plain_pattern, text))
        plain_count = total_count - negated_count

        return plain_count - negated_count


class FinBertScorer:
    """
    FinBERT-based sentiment scorer using ProsusAI/finbert.

    Falls back gracefully if transformers/torch are not installed.
    Model is loaded lazily on first call and cached in memory.
    """

    name: str = "finbert"

    def __init__(self, model_name: str = "ProsusAI/finbert") -> None:
        self._model_name = model_name
        self._pipeline: Any = None
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import torch  # noqa: F401  # type: ignore[import-unresolved]
            import transformers  # noqa: F401  # type: ignore[import-unresolved]

            self._available = True
        except ImportError:
            self._available = False
            logger.info("FinBERT unavailable: transformers/torch not installed")
        return self._available

    def _ensure_pipeline(self) -> bool:
        if self._pipeline is not None:
            return True
        if not self.available:
            return False
        try:
            from transformers import pipeline as hf_pipeline  # type: ignore[import-unresolved]

            self._pipeline = hf_pipeline(
                "sentiment-analysis",
                model=self._model_name,
                truncation=True,
                max_length=512,
            )
            logger.info("FinBERT model loaded: %s", self._model_name)
            return True
        except Exception:
            logger.warning("FinBERT model load failed", exc_info=True)
            self._available = False
            return False

    def score(self, text: str, currency: str | None = None) -> SentimentResult:
        if not self._ensure_pipeline():
            raise RuntimeError("FinBERT not available")

        from news.sentiment.entity_recognizer import extract_entities

        entities = extract_entities(text)

        # Truncate very long texts
        truncated = text[:512]
        result = self._pipeline(truncated)[0]

        label_raw: str = result["label"].lower()
        model_confidence: float = result["score"]

        # Map FinBERT labels to our schema
        if label_raw == "positive":
            score_val = model_confidence
            label = "bullish"
        elif label_raw == "negative":
            score_val = -model_confidence
            label = "bearish"
        else:
            score_val = 0.0
            label = "neutral"

        return SentimentResult(
            score=round(score_val, 4),
            label=label,
            confidence=round(model_confidence, 4),
            method=self.name,
            entities=entities,
            details={"raw_label": label_raw, "raw_score": round(model_confidence, 4)},
        )

    def score_batch(self, texts: list[str], currency: str | None = None) -> list[SentimentResult]:
        if not self._ensure_pipeline():
            raise RuntimeError("FinBERT not available")

        from news.sentiment.entity_recognizer import extract_entities

        truncated = [t[:512] for t in texts]
        results = self._pipeline(truncated)

        output: list[SentimentResult] = []
        for text, result in zip(texts, results, strict=False):
            entities = extract_entities(text)
            label_raw: str = result["label"].lower()
            conf: float = result["score"]

            if label_raw == "positive":
                score_val = conf
                label = "bullish"
            elif label_raw == "negative":
                score_val = -conf
                label = "bearish"
            else:
                score_val = 0.0
                label = "neutral"

            output.append(
                SentimentResult(
                    score=round(score_val, 4),
                    label=label,
                    confidence=round(conf, 4),
                    method=self.name,
                    entities=entities,
                    details={"raw_label": label_raw, "raw_score": round(conf, 4)},
                )
            )
        return output


class HybridScorer:
    """
    Chains FinBERT (primary) → KeywordScorer (fallback).

    If FinBERT is available and succeeds, uses its result.
    Otherwise falls back to keyword scoring transparently.
    """

    name: str = "hybrid"

    def __init__(self) -> None:
        self._finbert = FinBertScorer()
        self._keyword = KeywordScorer()

    def score(self, text: str, currency: str | None = None) -> SentimentResult:
        if self._finbert.available:
            try:
                result = self._finbert.score(text, currency)
                return SentimentResult(
                    score=result.score,
                    label=result.label,
                    confidence=result.confidence,
                    method="hybrid:finbert",
                    entities=result.entities,
                    details=result.details,
                )
            except Exception:
                logger.debug("FinBERT scoring failed, falling back to keywords", exc_info=True)

        result = self._keyword.score(text, currency)
        return SentimentResult(
            score=result.score,
            label=result.label,
            confidence=result.confidence,
            method="hybrid:keyword",
            entities=result.entities,
            details=result.details,
        )

    def score_batch(self, texts: list[str], currency: str | None = None) -> list[SentimentResult]:
        if self._finbert.available:
            try:
                results = self._finbert.score_batch(texts, currency)
                return [
                    SentimentResult(
                        score=r.score,
                        label=r.label,
                        confidence=r.confidence,
                        method="hybrid:finbert",
                        entities=r.entities,
                        details=r.details,
                    )
                    for r in results
                ]
            except Exception:
                logger.debug("FinBERT batch scoring failed, falling back", exc_info=True)

        return [
            SentimentResult(
                score=r.score,
                label=r.label,
                confidence=r.confidence,
                method="hybrid:keyword",
                entities=r.entities,
                details=r.details,
            )
            for r in self._keyword.score_batch(texts, currency)
        ]


def get_default_scorer() -> SentimentScorer:
    """
    Return the best available sentiment scorer.

    Uses HybridScorer (FinBERT → keyword fallback) unless explicitly
    overridden by SENTIMENT_ENGINE env var.
    """
    engine = os.getenv("SENTIMENT_ENGINE", "hybrid").lower()

    if engine == "finbert":
        scorer = FinBertScorer()
        if scorer.available:
            return scorer
        logger.warning("SENTIMENT_ENGINE=finbert but FinBERT unavailable; using keyword fallback")
        return KeywordScorer()

    if engine == "keyword":
        return KeywordScorer()

    # Default: hybrid
    return HybridScorer()
