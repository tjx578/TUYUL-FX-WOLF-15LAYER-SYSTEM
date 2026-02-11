"""
Unit tests for FinnhubMarketNews ingestion.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingest.finnhub_market_news import FinnhubMarketNews


@pytest.fixture
def market_news_instance() -> FinnhubMarketNews:
    with (
        patch("ingest.finnhub_market_news.load_finnhub") as mock_cfg,
        patch.dict(
            "os.environ",
            {"FINNHUB_API_KEY": "test_key"},
        ),
    ):
        mock_cfg.return_value = {
            "rest": {
                "base_url": "https://finnhub.io/api/v1",
                "timeout_sec": 5,
                "retries": 2,
                "backoff_factor": 1.0,
            },
            "market_news": {
                "enabled": True,
                "endpoint": "/news",
                "category": "forex",
                "poll_interval_sec": 10,
                "max_articles": 50,
                "sentiment_keywords": {
                    "bullish": ["hawkish", "rate hike", "strong", "beat", "surge"],
                    "bearish": ["dovish", "rate cut", "weak", "miss", "decline"],
                },
            },
        }
        instance = FinnhubMarketNews()
        instance._context_bus = MagicMock()
        return instance


class TestArticleNormalization:
    """Test article normalization."""

    def test_normalize_article_complete(self, market_news_instance: FinnhubMarketNews) -> None:
        article = {
            "id": 123456,
            "headline": "USD/EUR Surges on Hawkish Fed Comments",
            "summary": "The dollar rallied after strong inflation data beat expectations.",
            "source": "Reuters",
            "url": "https://example.com/article",
            "category": "forex",
            "image": "https://example.com/image.jpg",
            "datetime": 1707675000,
        }
        result = market_news_instance._normalize_article(article)

        assert result["id"] == 123456
        assert result["headline"] == "USD/EUR Surges on Hawkish Fed Comments"
        assert result["source"] == "Reuters"
        assert result["provider"] == "finnhub"
        assert result["sentiment"] in ["bullish", "bearish", "neutral"]
        assert -1.0 <= result["sentiment_score"] <= 1.0
        assert result["datetime_iso"] != ""

    def test_normalize_article_minimal(self, market_news_instance: FinnhubMarketNews) -> None:
        article = {}
        result = market_news_instance._normalize_article(article)

        assert result["id"] == 0
        assert result["headline"] == ""
        assert result["provider"] == "finnhub"
        assert result["sentiment"] == "neutral"


class TestSentimentScoring:
    """Test sentiment scoring logic."""

    def test_bullish_sentiment(self, market_news_instance: FinnhubMarketNews) -> None:
        text = "The Fed announced a hawkish rate hike, the economy is strong"
        score, label = market_news_instance._score_sentiment(text)

        assert score > 0.2
        assert label == "bullish"

    def test_bearish_sentiment(self, market_news_instance: FinnhubMarketNews) -> None:
        text = "Dovish central bank cuts rates as economy shows weakness and decline"
        score, label = market_news_instance._score_sentiment(text)

        assert score < -0.2
        assert label == "bearish"

    def test_neutral_sentiment(self, market_news_instance: FinnhubMarketNews) -> None:
        text = "The market moved sideways today with no clear direction"
        score, label = market_news_instance._score_sentiment(text)

        assert -0.2 <= score <= 0.2
        assert label == "neutral"

    def test_mixed_sentiment(self, market_news_instance: FinnhubMarketNews) -> None:
        # Equal bullish and bearish keywords should result in neutral
        text = "Strong data beat estimates but dovish rate cut announced"
        score, label = market_news_instance._score_sentiment(text)

        assert abs(score) < 0.01  # Nearly zero with small tolerance
        assert label == "neutral"

    def test_case_insensitive(self, market_news_instance: FinnhubMarketNews) -> None:
        text1 = "HAWKISH RATE HIKE"
        text2 = "hawkish rate hike"

        score1, label1 = market_news_instance._score_sentiment(text1)
        score2, label2 = market_news_instance._score_sentiment(text2)

        assert score1 == score2
        assert label1 == label2


class TestLastIdTracking:
    """Test minId deduplication logic."""

    def test_initial_last_id_is_zero(self, market_news_instance: FinnhubMarketNews) -> None:
        assert market_news_instance._last_id == 0

    def test_last_id_updates_after_normalization(
        self, market_news_instance: FinnhubMarketNews
    ) -> None:
        # Simulate processing articles
        articles = [
            {"id": 100, "headline": "Test 1", "summary": "", "datetime": 1707675000},
            {"id": 105, "headline": "Test 2", "summary": "", "datetime": 1707675100},
            {"id": 103, "headline": "Test 3", "summary": "", "datetime": 1707675200},
        ]

        # Normalize articles
        normalized = [market_news_instance._normalize_article(a) for a in articles]

        # Update last_id based on max
        if normalized:
            max_id = max(article["id"] for article in normalized if article["id"])
            market_news_instance._last_id = max_id

        # Should track highest ID
        assert market_news_instance._last_id == 105


class TestConfiguration:
    """Test configuration and initialization."""

    def test_enabled_flag_access(self, market_news_instance: FinnhubMarketNews) -> None:
        # Verify configuration is loaded correctly
        assert market_news_instance._category == "forex"
        assert market_news_instance._poll_interval == 10
        assert market_news_instance._max_articles == 50

    def test_disabled_config(self) -> None:
        with (
            patch("ingest.finnhub_market_news.load_finnhub") as mock_cfg,
            patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key"}),
        ):
            mock_cfg.return_value = {
                "rest": {"base_url": "https://finnhub.io/api/v1"},
                "market_news": {"enabled": False},
            }
            instance = FinnhubMarketNews()

            # Should still initialize but enabled flag is False
            market_cfg = instance._config.get("market_news", {})
            assert market_cfg.get("enabled", False) is False
