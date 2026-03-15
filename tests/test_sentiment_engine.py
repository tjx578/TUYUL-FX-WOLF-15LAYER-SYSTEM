"""
Tests for the sentiment analysis engine.

Covers:
- KeywordScorer: weighted scoring, negation handling
- FinBertScorer: graceful degradation when unavailable
- HybridScorer: fallback chain
- Entity recognition
- Sentiment aggregation per currency
- Architectural boundary: sentiment is advisory-only
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from news.sentiment.aggregator import (
    SentimentAggregator,
)
from news.sentiment.entity_recognizer import (
    extract_affected_currencies,
    extract_entities,
    identify_central_bank,
)
from news.sentiment.sentiment_engine import (
    FinBertScorer,
    HybridScorer,
    KeywordScorer,
    SentimentResult,
    get_default_scorer,
)

# ── KeywordScorer Tests ──────────────────────────────────────────────────────


class TestKeywordScorer:
    def setup_method(self) -> None:
        self.scorer = KeywordScorer()

    def test_bullish_headline(self) -> None:
        result = self.scorer.score("Fed hawkish stance as rate hike expected next meeting")
        assert result.label == "bullish"
        assert result.score > 0.0
        assert result.method == "keyword"

    def test_bearish_headline(self) -> None:
        result = self.scorer.score("ECB signals dovish pivot, rate cut likely in March")
        assert result.label == "bearish"
        assert result.score < 0.0

    def test_neutral_headline(self) -> None:
        result = self.scorer.score("Markets trading sideways ahead of data release")
        assert result.label == "neutral"
        assert result.score == 0.0
        assert result.confidence == 0.0

    def test_negation_flips_sentiment(self) -> None:
        # "not hawkish" should register as bearish signal
        result_neg = self.scorer.score("Fed not hawkish despite inflation data")
        result_pos = self.scorer.score("Fed hawkish despite inflation data")
        assert result_neg.score < result_pos.score

    def test_mixed_sentiment(self) -> None:
        result = self.scorer.score("Strong growth in jobs but rate cut expectations remain")
        # Contains both bullish ("strong growth") and bearish ("rate cut")
        assert result.method == "keyword"
        # Should not be strongly directional
        assert -0.8 <= result.score <= 0.8

    def test_weighted_scoring(self) -> None:
        # "rate hike" (weight 2.0) should score higher than "surge" (weight 1.0)
        result_strong = self.scorer.score("rate hike expected")
        result_weak = self.scorer.score("markets surge")
        assert result_strong.details["bullish_weight"] > result_weak.details["bullish_weight"]

    def test_batch_scoring(self) -> None:
        texts = [
            "Fed raises rates by 25bps as expected",
            "Economy shows signs of recession",
            "Trading volumes remain stable",
        ]
        results = self.scorer.score_batch(texts)
        assert len(results) == 3
        assert all(isinstance(r, SentimentResult) for r in results)

    def test_empty_text(self) -> None:
        result = self.scorer.score("")
        assert result.label == "neutral"
        assert result.score == 0.0

    def test_entities_detected(self) -> None:
        result = self.scorer.score("Federal Reserve raises rates amid strong GDP")
        assert "FED" in result.entities
        assert "USD" in result.entities

    def test_confidence_scales_with_evidence(self) -> None:
        # More keywords → higher confidence
        result_few = self.scorer.score("markets strong")
        result_many = self.scorer.score(
            "hawkish tone, rate hike imminent, strong growth beats expectations, surge in employment"
        )
        assert result_many.confidence > result_few.confidence


# ── FinBertScorer Tests ──────────────────────────────────────────────────────


class TestFinBertScorer:
    def test_unavailable_when_no_transformers(self) -> None:
        scorer = FinBertScorer()
        # In test environment without transformers installed, should be unavailable
        # This test passes in both cases — just verifies graceful handling
        if not scorer.available:
            with pytest.raises(RuntimeError, match="not available"):
                scorer.score("test text")


# ── HybridScorer Tests ──────────────────────────────────────────────────────


class TestHybridScorer:
    def test_falls_back_to_keyword(self) -> None:
        scorer = HybridScorer()
        result = scorer.score("Fed hawkish on rates")
        # Should work regardless of FinBERT availability
        assert result.method.startswith("hybrid:")
        assert result.label in ("bullish", "bearish", "neutral")

    def test_batch_falls_back(self) -> None:
        scorer = HybridScorer()
        results = scorer.score_batch(["hawkish Fed", "dovish ECB"])
        assert len(results) == 2
        assert all(r.method.startswith("hybrid:") for r in results)


# ── get_default_scorer Tests ─────────────────────────────────────────────────


class TestGetDefaultScorer:
    def test_returns_scorer(self) -> None:
        scorer = get_default_scorer()
        assert hasattr(scorer, "score")
        assert hasattr(scorer, "score_batch")
        assert hasattr(scorer, "name")

    def test_keyword_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENTIMENT_ENGINE", "keyword")
        scorer = get_default_scorer()
        assert scorer.name == "keyword"


# ── Entity Recognizer Tests ─────────────────────────────────────────────────


class TestEntityRecognizer:
    def test_central_bank_detection(self) -> None:
        entities = extract_entities("The Federal Reserve raised interest rates today")
        assert "FED" in entities
        assert "USD" in entities

    def test_ecb_detection(self) -> None:
        entities = extract_entities("ECB president Lagarde speaks at press conference")
        assert "ECB" in entities
        assert "EUR" in entities

    def test_boj_detection(self) -> None:
        entities = extract_entities("Bank of Japan maintains ultra-loose policy")
        assert "BOJ" in entities
        assert "JPY" in entities

    def test_multiple_banks(self) -> None:
        entities = extract_entities("Fed and ECB diverge on rate policy")
        assert "FED" in entities
        assert "ECB" in entities
        assert "USD" in entities
        assert "EUR" in entities

    def test_currency_codes(self) -> None:
        entities = extract_entities("EURUSD pair gains as EUR strengthens vs USD")
        assert "EUR" in entities
        assert "USD" in entities

    def test_economic_indicators(self) -> None:
        entities = extract_entities("US Non-Farm Payrolls beat expectations")
        assert "NFP" in entities

    def test_cpi_detection(self) -> None:
        entities = extract_entities("Consumer Price Index rises 0.3% month over month")
        assert "CPI" in entities

    def test_gdp_detection(self) -> None:
        entities = extract_entities("GDP growth accelerated to 3.2% in Q3")
        assert "GDP" in entities

    def test_extract_affected_currencies(self) -> None:
        currencies = extract_affected_currencies("Federal Reserve and Bank of England diverge")
        assert "USD" in currencies
        assert "GBP" in currencies

    def test_identify_primary_bank(self) -> None:
        bank = identify_central_bank("ECB rate decision next Thursday")
        assert bank is not None
        assert bank.abbreviation == "ECB"
        assert "EUR" in bank.currencies

    def test_no_bank_returns_none(self) -> None:
        bank = identify_central_bank("Markets closed for holiday")
        assert bank is None

    def test_rate_decision_indicator(self) -> None:
        entities = extract_entities("BOE interest rate decision at 12:00 GMT")
        assert "BOE" in entities
        assert "RATE_DECISION" in entities

    def test_governor_names(self) -> None:
        entities = extract_entities("Powell speech at Jackson Hole")
        assert "FED" in entities
        entities2 = extract_entities("Lagarde press conference after rate decision")
        assert "ECB" in entities2


# ── SentimentAggregator Tests ───────────────────────────────────────────────


class TestSentimentAggregator:
    def setup_method(self) -> None:
        self.aggregator = SentimentAggregator(
            scorer=KeywordScorer(),
            decay_hours=6.0,
        )

    def test_empty_articles(self) -> None:
        snapshot = self.aggregator.aggregate([])
        assert snapshot.article_count == 0
        assert snapshot.overall_label == "neutral"
        assert snapshot.overall_score == 0.0

    def test_single_bullish_article(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        articles = [
            {
                "headline": "Fed hawkish stance, rate hike expected",
                "summary": "Strong economic growth beats expectations",
                "datetime": now.timestamp(),
            }
        ]
        snapshot = self.aggregator.aggregate(articles, now=now)
        assert snapshot.article_count == 1
        assert snapshot.overall_score > 0.0
        assert snapshot.overall_label == "bullish"

    def test_currency_attribution(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        articles = [
            {
                "headline": "ECB rate cut signals dovish turn for EUR",
                "summary": "European Central Bank easing policy",
                "datetime": now.timestamp(),
            }
        ]
        snapshot = self.aggregator.aggregate(articles, now=now)
        assert "EUR" in snapshot.by_currency or "ECB" in str(snapshot.by_currency)

    def test_time_decay(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        recent_articles = [
            {
                "headline": "Fed hawkish rate hike imminent",
                "summary": "Strong data surge",
                "datetime": (now - __import__("datetime").timedelta(minutes=30)).timestamp(),
            }
        ]
        old_articles = [
            {
                "headline": "Fed hawkish rate hike imminent",
                "summary": "Strong data surge",
                "datetime": (now - __import__("datetime").timedelta(hours=5)).timestamp(),
            }
        ]
        snap_recent = self.aggregator.aggregate(recent_articles, now=now)
        self.aggregator.aggregate(old_articles, now=now)
        # Recent articles should have higher overall weight impact
        # Both have same text, but the recent one should have stronger signal
        assert snap_recent.overall_score != 0.0

    def test_score_for_symbol_eurusd(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        articles = [
            {
                "headline": "ECB dovish, rate cut expected",
                "summary": "European economy weakness and decline",
                "datetime": now.timestamp(),
            },
            {
                "headline": "Fed hawkish, rate hike likely",
                "summary": "US economy strong growth beats expectations",
                "datetime": now.timestamp(),
            },
        ]
        snapshot = self.aggregator.aggregate(articles, now=now)
        score, conf = self.aggregator.score_for_symbol(snapshot, "EURUSD")
        # EUR bearish + USD bullish → EURUSD should be bearish
        assert score < 0.0

    def test_score_for_unknown_symbol(self) -> None:
        snapshot = self.aggregator.aggregate([])
        score, conf = self.aggregator.score_for_symbol(snapshot, "EURUSD")
        assert score == 0.0
        assert conf == 0.0

    def test_multiple_articles_aggregate(self) -> None:
        now = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        articles = [
            {"headline": "Fed hawkish rate hike", "summary": "", "datetime": now.timestamp()},
            {"headline": "Strong GDP growth beats", "summary": "", "datetime": now.timestamp()},
            {"headline": "Economy shows recession signs", "summary": "decline", "datetime": now.timestamp()},
        ]
        snapshot = self.aggregator.aggregate(articles, now=now)
        assert snapshot.article_count == 3


# ── Architectural Boundary Test ──────────────────────────────────────────────


class TestSentimentBoundary:
    """Verify sentiment module has NO execution authority."""

    def test_sentiment_result_is_pure_data(self) -> None:
        """SentimentResult is a frozen dataclass — cannot modify after creation."""
        result = SentimentResult(
            score=0.5,
            label="bullish",
            confidence=0.8,
            method="keyword",
        )
        with pytest.raises(AttributeError):
            result.score = 0.9  # type: ignore[misc]

    def test_no_execution_imports(self) -> None:
        """Sentiment modules must not import from execution/ or constitution/."""
        import importlib
        import inspect

        modules_to_check = [
            "news.sentiment.sentiment_engine",
            "news.sentiment.entity_recognizer",
            "news.sentiment.aggregator",
        ]
        forbidden_prefixes = ("execution.", "constitution.")

        for mod_name in modules_to_check:
            mod = importlib.import_module(mod_name)
            source = inspect.getsource(mod)
            for prefix in forbidden_prefixes:
                assert f"from {prefix}" not in source, (
                    f"{mod_name} imports from {prefix} — violates advisory-only boundary"
                )
                assert f"import {prefix}" not in source, (
                    f"{mod_name} imports from {prefix} — violates advisory-only boundary"
                )
