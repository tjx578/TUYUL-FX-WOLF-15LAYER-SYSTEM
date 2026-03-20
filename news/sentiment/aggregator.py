"""
News sentiment aggregator — contextual scoring across multiple articles.

Computes net sentiment per currency, time-weighted and entity-aware.
Output is advisory-only — consumed by LiveContextBus for confidence
adjustment and position sizing influence. Never overrides L12 verdict.

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from news.sentiment.entity_recognizer import extract_affected_currencies
from news.sentiment.sentiment_engine import SentimentScorer, get_default_scorer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrencySentiment:
    """Aggregated sentiment for a single currency."""

    currency: str
    net_score: float  # -1.0 to +1.0
    label: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0.0 to 1.0 — weighted average of article confidences
    article_count: int
    bullish_count: int
    bearish_count: int
    neutral_count: int


@dataclass(frozen=True)
class MarketSentimentSnapshot:
    """Complete sentiment snapshot across all currencies."""

    by_currency: dict[str, CurrencySentiment]
    overall_score: float  # -1.0 to +1.0
    overall_label: str
    article_count: int
    scored_at: datetime
    method: str  # "finbert", "keyword", "hybrid:finbert", "hybrid:keyword"


class SentimentAggregator:
    """
    Aggregates sentiment across multiple articles per currency.

    Features:
    - Time-weighted: recent articles count more
    - Confidence-weighted: higher-confidence scores count more
    - Currency-attributed: separates sentiment by affected currency
    - Produces a snapshot suitable for LiveContextBus
    """

    def __init__(
        self,
        scorer: SentimentScorer | None = None,
        decay_hours: float = 6.0,
    ) -> None:
        self._scorer = scorer or get_default_scorer()
        self._decay_hours = decay_hours

    def aggregate(
        self,
        articles: list[dict[str, Any]],
        now: datetime | None = None,
    ) -> MarketSentimentSnapshot:
        """
        Score and aggregate sentiment from a list of news articles.

        Parameters
        ----------
        articles : list[dict]
            Articles with at least 'headline' and/or 'summary' fields.
            Optional: 'datetime' (unix), 'currency'.
        now : datetime | None
            Override for current time (for testing).

        Returns
        -------
        MarketSentimentSnapshot
        """
        now = now or datetime.now(UTC)

        # Score all articles
        texts = [f"{a.get('headline', '')} {a.get('summary', '')}".strip() for a in articles]

        if not texts:
            return MarketSentimentSnapshot(
                by_currency={},
                overall_score=0.0,
                overall_label="neutral",
                article_count=0,
                scored_at=now,
                method=self._scorer.name,
            )

        results = self._scorer.score_batch(texts)
        method = results[0].method if results else self._scorer.name

        # Accumulate per-currency weighted scores
        currency_scores: dict[str, list[tuple[float, float]]] = {}  # {ccy: [(score, weight)]}
        currency_labels: dict[str, dict[str, int]] = {}  # {ccy: {label: count}}

        all_weighted: list[tuple[float, float]] = []

        for article, result in zip(articles, results, strict=False):
            # Time decay weight
            article_ts = article.get("datetime", 0)
            if isinstance(article_ts, (int, float)) and article_ts > 0:
                article_dt = datetime.fromtimestamp(article_ts, tz=UTC)
                hours_ago = (now - article_dt).total_seconds() / 3600
                time_weight = max(0.1, 1.0 - (hours_ago / self._decay_hours))
            else:
                time_weight = 0.5  # Unknown time → half weight

            combined_weight = time_weight * max(result.confidence, 0.1)

            # Determine affected currencies
            currencies = extract_affected_currencies(f"{article.get('headline', '')} {article.get('summary', '')}")
            if not currencies and article.get("currency"):
                currencies = [article["currency"].upper()]
            if not currencies:
                currencies = ["GLOBAL"]

            # Accumulate
            for ccy in currencies:
                if ccy not in currency_scores:
                    currency_scores[ccy] = []
                    currency_labels[ccy] = {"bullish": 0, "bearish": 0, "neutral": 0}
                currency_scores[ccy].append((result.score, combined_weight))
                currency_labels[ccy][result.label] = currency_labels[ccy].get(result.label, 0) + 1

            all_weighted.append((result.score, combined_weight))

        # Compute per-currency aggregates
        by_currency: dict[str, CurrencySentiment] = {}
        for ccy, scores in currency_scores.items():
            net = self._weighted_average(scores)
            labels = currency_labels.get(ccy, {})
            total_conf = sum(w for _, w in scores) / len(scores) if scores else 0.0
            by_currency[ccy] = CurrencySentiment(
                currency=ccy,
                net_score=round(net, 4),
                label=self._label_from_score(net),
                confidence=round(min(total_conf, 1.0), 4),
                article_count=len(scores),
                bullish_count=labels.get("bullish", 0),
                bearish_count=labels.get("bearish", 0),
                neutral_count=labels.get("neutral", 0),
            )

        # Overall aggregate
        overall = self._weighted_average(all_weighted)

        return MarketSentimentSnapshot(
            by_currency=by_currency,
            overall_score=round(overall, 4),
            overall_label=self._label_from_score(overall),
            article_count=len(articles),
            scored_at=now,
            method=method,
        )

    def score_for_symbol(
        self,
        snapshot: MarketSentimentSnapshot,
        symbol: str,
    ) -> tuple[float, float]:
        """
        Get net sentiment score and confidence for a trading symbol.

        E.g. EURUSD: considers EUR sentiment (inverse) and USD sentiment.

        Returns
        -------
        tuple[float, float]
            (score, confidence) where score is -1.0 to +1.0
        """
        if len(symbol) < 6:
            return 0.0, 0.0

        base_ccy = symbol[:3].upper()
        quote_ccy = symbol[3:6].upper()

        base_sent = snapshot.by_currency.get(base_ccy)
        quote_sent = snapshot.by_currency.get(quote_ccy)

        if base_sent is None and quote_sent is None:
            return 0.0, 0.0

        # For EURUSD:
        # - Bullish EUR → bullish for pair
        # - Bullish USD → bearish for pair
        base_score = base_sent.net_score if base_sent else 0.0
        quote_score = quote_sent.net_score if quote_sent else 0.0
        base_conf = base_sent.confidence if base_sent else 0.0
        quote_conf = quote_sent.confidence if quote_sent else 0.0

        net_score = base_score - quote_score
        avg_conf = (base_conf + quote_conf) / 2.0 if (base_sent or quote_sent) else 0.0

        return round(max(-1.0, min(1.0, net_score)), 4), round(avg_conf, 4)

    @staticmethod
    def _weighted_average(scores: list[tuple[float, float]]) -> float:
        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return 0.0
        return sum(s * w for s, w in scores) / total_weight

    @staticmethod
    def _label_from_score(score: float) -> str:
        if score > 0.15:
            return "bullish"
        elif score < -0.15:
            return "bearish"
        return "neutral"
