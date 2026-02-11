"""
Unit tests for FinnhubMarketNews ingestion.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from ingest.finnhub_market_news import FinnhubMarketNews, MarketNewsError


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
        
        assert score == 0.0  # Equal counts cancel out
        assert label == "neutral"

    def test_case_insensitive(self, market_news_instance: FinnhubMarketNews) -> None:
        text1 = "HAWKISH RATE HIKE"
        text2 = "hawkish rate hike"
        
        score1, label1 = market_news_instance._score_sentiment(text1)
        score2, label2 = market_news_instance._score_sentiment(text2)
        
        assert score1 == score2
        assert label1 == label2


class TestFetchNews:
    """Test news fetching with various scenarios."""

    @pytest.mark.asyncio
    async def test_fetch_success(self, market_news_instance: FinnhubMarketNews) -> None:
        mock_response = [
            {
                "id": 100,
                "headline": "Market Update",
                "summary": "Strong economy",
                "source": "Reuters",
                "url": "https://example.com",
                "category": "forex",
                "image": "",
                "datetime": 1707675000,
            },
            {
                "id": 101,
                "headline": "Fed Decision",
                "summary": "Rate hike expected",
                "source": "Bloomberg",
                "url": "https://example.com/2",
                "category": "forex",
                "image": "",
                "datetime": 1707675100,
            },
        ]
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value.status_code = 200
            mock_instance.get.return_value.json.return_value = mock_response
            mock_instance.get.return_value.raise_for_status = MagicMock()
            
            articles = await market_news_instance.fetch_news()
            
            assert len(articles) == 2
            assert articles[0]["id"] == 100
            assert articles[1]["id"] == 101
            assert market_news_instance._last_id == 101

    @pytest.mark.asyncio
    async def test_fetch_with_minid(self, market_news_instance: FinnhubMarketNews) -> None:
        # Set last_id to simulate previous fetch
        market_news_instance._last_id = 50
        
        mock_response = [
            {
                "id": 51,
                "headline": "New Article",
                "summary": "Latest news",
                "source": "Reuters",
                "url": "https://example.com",
                "category": "forex",
                "image": "",
                "datetime": 1707675000,
            }
        ]
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value.status_code = 200
            mock_instance.get.return_value.json.return_value = mock_response
            mock_instance.get.return_value.raise_for_status = MagicMock()
            
            await market_news_instance.fetch_news()
            
            # Verify minId was passed in params
            call_args = mock_instance.get.call_args
            assert call_args[1]["params"]["minId"] == 50
            assert market_news_instance._last_id == 51

    @pytest.mark.asyncio
    async def test_fetch_rate_limit_retry(self, market_news_instance: FinnhubMarketNews) -> None:
        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"
        
        mock_response_success = [
            {
                "id": 200,
                "headline": "Success",
                "summary": "",
                "source": "Reuters",
                "url": "https://example.com",
                "category": "forex",
                "image": "",
                "datetime": 1707675000,
            }
        ]
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            # First call raises 429, second succeeds
            first_call = MagicMock()
            first_call.raise_for_status.side_effect = httpx.HTTPStatusError(
                "429", request=MagicMock(), response=mock_response_429
            )
            
            second_call = MagicMock()
            second_call.raise_for_status = MagicMock()
            second_call.json.return_value = mock_response_success
            
            mock_instance.get.side_effect = [first_call, second_call]
            
            articles = await market_news_instance.fetch_news()
            
            assert len(articles) == 1
            assert articles[0]["id"] == 200

    @pytest.mark.asyncio
    async def test_fetch_403_forbidden(self, market_news_instance: FinnhubMarketNews) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
                "403", request=MagicMock(), response=mock_response
            )
            
            with pytest.raises(MarketNewsError, match="HTTP 403 Forbidden"):
                await market_news_instance.fetch_news()

    @pytest.mark.asyncio
    async def test_fetch_connection_error_exhausted(
        self, market_news_instance: FinnhubMarketNews
    ) -> None:
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.ConnectError("Connection failed")
            
            with pytest.raises(MarketNewsError, match="Failed after 2 retries"):
                await market_news_instance.fetch_news()

    @pytest.mark.asyncio
    async def test_fetch_read_timeout_exhausted(
        self, market_news_instance: FinnhubMarketNews
    ) -> None:
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = MagicMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.ReadTimeout("Read timeout")
            
            with pytest.raises(MarketNewsError, match="Failed after 2 retries"):
                await market_news_instance.fetch_news()


class TestRunLoop:
    """Test the main polling loop."""

    @pytest.mark.asyncio
    async def test_run_disabled(self, market_news_instance: FinnhubMarketNews) -> None:
        # Reconfigure with disabled flag
        with (
            patch("ingest.finnhub_market_news.load_finnhub") as mock_cfg,
            patch.dict("os.environ", {"FINNHUB_API_KEY": "test_key"}),
        ):
            mock_cfg.return_value = {
                "rest": {"base_url": "https://finnhub.io/api/v1"},
                "market_news": {"enabled": False},
            }
            instance = FinnhubMarketNews()
            instance._context_bus = MagicMock()
            
            # run() should return immediately without polling
            import asyncio
            
            try:
                await asyncio.wait_for(instance.run(), timeout=0.1)
            except asyncio.TimeoutError:
                pytest.fail("run() should have returned immediately when disabled")

    @pytest.mark.asyncio
    async def test_run_enabled_single_iteration(
        self, market_news_instance: FinnhubMarketNews
    ) -> None:
        mock_articles = [
            {
                "id": 300,
                "headline": "Test",
                "summary": "",
                "source": "Reuters",
                "url": "https://example.com",
                "category": "forex",
                "image": "",
                "datetime": 1707675000,
            }
        ]
        
        with patch.object(market_news_instance, "fetch_news") as mock_fetch:
            mock_fetch.return_value = [market_news_instance._normalize_article(mock_articles[0])]
            
            # Run one iteration and cancel
            import asyncio
            
            task = asyncio.create_task(market_news_instance.run())
            await asyncio.sleep(0.1)  # Let it start
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            # Should have called fetch_news at least once
            assert mock_fetch.call_count >= 1
            assert market_news_instance._context_bus.update_news.call_count >= 1
