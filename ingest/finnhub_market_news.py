"""
Finnhub Market News Ingestion

Fetches forex market news articles via Finnhub REST API.
NO TRADING DECISION.

Endpoint: GET /news?category=forex&token=KEY
"""

from __future__ import annotations

import asyncio
import os

from datetime import UTC, datetime
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]

from loguru import logger

from config_loader import load_finnhub
from context.live_context_bus import LiveContextBus


class MarketNewsError(Exception):
    """Raised when Finnhub market news fetch fails."""


class FinnhubMarketNews:
    """
    Market news ingestion via Finnhub REST API.

    Responsibilities:
      1. Poll /news?category=forex at configured interval
      2. Track minId for deduplication (fetch only new articles)
      3. Normalize articles to internal format
      4. Score sentiment using keyword matching
      5. Push to LiveContextBus
      6. Retry with exponential backoff on transient errors

    NO TRADING DECISION.
    """

    _MAX_RETRY_WAIT_SEC: int = 120

    def __init__(self) -> None:
        self._config = load_finnhub()
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415
        self._key_manager = finnhub_keys
        self._api_key: str = self._key_manager.current_key()
        self._base_url: str = self._config["rest"].get("base_url", "https://finnhub.io/api/v1")
        self._timeout: int = self._config["rest"].get("timeout_sec", 20)
        self._retries: int = self._config["rest"].get("retries", 3)
        self._backoff_factor: float = self._config["rest"].get("backoff_factor", 1.5)

        market_cfg = self._config.get("market_news", {})
        self._poll_interval: int = market_cfg.get("poll_interval_sec", 600)
        self._category: str = market_cfg.get("category", "forex")
        self._max_articles: int = market_cfg.get("max_articles", 50)

        # Normalize sentiment keywords to lowercase once during initialization
        raw_keywords = market_cfg.get(
            "sentiment_keywords",
            {
                "bullish": ["hawkish", "rate hike", "strong", "beat", "surge"],
                "bearish": ["dovish", "rate cut", "weak", "miss", "decline"],
            }
        )
        self._sentiment_keywords: dict[str, list[str]] = {
            "bullish": [k.lower() for k in raw_keywords.get("bullish", [])],
            "bearish": [k.lower() for k in raw_keywords.get("bearish", [])],
        }

        self._context_bus = LiveContextBus()
        self._last_id: int = 0  # Track highest article ID for deduplication

        if not self._api_key:
            logger.error("FINNHUB_API_KEY not set - market news will fail")

    async def fetch_news(self) -> list[dict[str, Any]]:
        """
        Fetch market news articles.

        Returns:
            List of normalized articles with sentiment scores.

        Raises:
            MarketNewsError: After exhausting retries.
        """
        url = f"{self._base_url}/news"
        params: dict[str, str | int] = {
            "category": self._category,
            "token": self._api_key,
        }

        # Add minId for deduplication if we've fetched before
        if self._last_id > 0:
            params["minId"] = self._last_id

        last_exc: Exception | None = None
        wait: float = 1.0

        for attempt in range(1, self._retries + 1):
            # Refresh key from manager (may have rotated).
            self._api_key = self._key_manager.current_key()
            params["token"] = self._api_key
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()

                self._key_manager.report_success(self._api_key)
                articles: list[dict[str, Any]] = data if isinstance(data, list) else []

                # Limit number of articles
                articles = articles[:self._max_articles]

                # Normalize and score sentiment
                normalized = [self._normalize_article(article) for article in articles]

                # Update last_id if we got new articles
                if normalized:
                    max_id = max(article["id"] for article in normalized if article["id"])
                    self._last_id = max(max_id, self._last_id)

                logger.info(
                    f"Finnhub market news: {len(normalized)} articles fetched "
                    f"(last_id={self._last_id})"
                )
                return normalized

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                self._key_manager.report_failure(self._api_key, exc.response.status_code)
                if exc.response.status_code == 429:
                    logger.warning(
                        f"Finnhub rate limited (attempt {attempt}/"
                        f"{self._retries}), waiting {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    wait *= self._backoff_factor
                elif exc.response.status_code == 403:
                    logger.error(
                        f"Finnhub HTTP 403 Forbidden - check API key permissions "
                        f"and endpoint URL: {url}"
                    )
                    raise MarketNewsError(f"HTTP 403 Forbidden: {url}") from exc
                else:
                    logger.error(f"Finnhub HTTP {exc.response.status_code}: {exc.response.text}")
                    raise MarketNewsError(f"HTTP {exc.response.status_code}") from exc

            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                logger.warning(
                    f"Finnhub connection error (attempt {attempt}/{self._retries}): {exc}"
                )
                await asyncio.sleep(wait)
                wait = min(
                    wait * self._backoff_factor,
                    self._MAX_RETRY_WAIT_SEC,
                )

        raise MarketNewsError(f"Failed after {self._retries} retries: {last_exc}")

    def _normalize_article(self, article: dict[str, Any]) -> dict[str, Any]:
        """
        Normalize Finnhub market news article to internal format.

        Args:
            article: Raw article from Finnhub API

        Returns:
            Normalized article with sentiment score
        """
        # Extract text for sentiment scoring
        headline = article.get("headline", "")
        summary = article.get("summary", "")
        text = f"{headline} {summary}"

        # Score sentiment
        sentiment_score, sentiment_label = self._score_sentiment(text)

        # Convert timestamp to ISO format
        timestamp = article.get("datetime", 0)
        datetime_iso = datetime.fromtimestamp(timestamp, tz=UTC).isoformat() if timestamp else ""

        return {
            "id": article.get("id", 0),
            "headline": headline,
            "summary": summary,
            "source": article.get("source", ""),
            "url": article.get("url", ""),
            "category": article.get("category", self._category),
            "image": article.get("image", ""),
            "datetime": timestamp,
            "datetime_iso": datetime_iso,
            "sentiment": sentiment_label,
            "sentiment_score": sentiment_score,
            "provider": "finnhub",
        }

    def _score_sentiment(self, text: str) -> tuple[float, str]:
        """
        Score sentiment using keyword matching.

        Args:
            text: Combined headline + summary text

        Returns:
            Tuple of (score, label) where:
            - score ranges from -1.0 (bearish) to 1.0 (bullish)
            - label is "bullish", "bearish", or "neutral"
        """
        text_lower = text.lower()

        bullish_count = sum(
            1 for keyword in self._sentiment_keywords["bullish"]
            if keyword in text_lower
        )
        bearish_count = sum(
            1 for keyword in self._sentiment_keywords["bearish"]
            if keyword in text_lower
        )

        # Normalize score between -1.0 and 1.0
        total = bullish_count + bearish_count
        if total == 0:
            score = 0.0
        else:
            score = (bullish_count - bearish_count) / total

        # Classify label
        if score > 0.2:
            label = "bullish"
        elif score < -0.2:
            label = "bearish"
        else:
            label = "neutral"

        return score, label

    async def run(self) -> None:
        """Main polling loop."""
        market_cfg = self._config.get("market_news", {})
        if not market_cfg.get("enabled", False):
            logger.warning("Finnhub market news ingestion disabled in config")
            return

        logger.info(
            f"Finnhub market news poller started (interval={self._poll_interval}s, "
            f"category={self._category})"
        )

        while True:
            try:
                articles = await self.fetch_news()
                payload = {
                    "articles": articles,
                    "source": "finnhub_market_news",
                    "category": self._category,
                    "count": len(articles),
                    "last_id": self._last_id,
                }
                self._context_bus.update_news(payload)
                logger.info(f"Market news updated: {len(articles)} articles")

            except MarketNewsError as exc:
                logger.error(f"Finnhub market news fetch failed: {exc}")

            except Exception as exc:
                logger.error(f"Unexpected error in market news poller: {exc}")

            await asyncio.sleep(self._poll_interval)
