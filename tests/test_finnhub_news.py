"""
Unit tests for FinnhubNews economic calendar ingestion.
"""

from unittest.mock import MagicMock, patch

import pytest

from ingest.finnhub_news import FinnhubNews


@pytest.fixture
def news_instance() -> FinnhubNews:
    with (
        patch("ingest.finnhub_news.load_finnhub") as mock_cfg,
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
            "news": {
                "enabled": True,
                "poll_interval_sec": 10,
                "impact_levels": {
                    "high": True,
                    "medium": True,
                    "low": False,
                },
            },
        }
        instance = FinnhubNews()
        instance._context_bus = MagicMock()
        return instance


class TestImpactFilter:
    """Test economic event filtering by impact."""

    def test_filter_high_impact_only(self, news_instance: FinnhubNews) -> None:
        news_instance._impact_levels = {
            "high": True,
            "medium": False,
            "low": False,
        }
        events = [
            {"event": "NFP", "impact": "high", "country": "US"},
            {"event": "PMI", "impact": "medium", "country": "EU"},
            {"event": "Minor", "impact": "low", "country": "UK"},
        ]
        filtered = news_instance._filter_by_impact(events)
        assert len(filtered) == 1
        assert filtered[0]["event"] == "NFP"

    def test_filter_numeric_impact(self, news_instance: FinnhubNews) -> None:
        events = [
            {"event": "FOMC", "impact": 3, "country": "US"},
            {"event": "GDP", "impact": 2, "country": "EU"},
            {"event": "Minor", "impact": 1, "country": "JP"},
        ]
        filtered = news_instance._filter_by_impact(events)
        assert len(filtered) == 2  # high + medium

    def test_normalize_event_structure(self, news_instance: FinnhubNews) -> None:
        event = {
            "event": "NFP",
            "country": "US",
            "impact": "high",
            "actual": "263K",
            "prev": "225K",
            "estimate": "250K",
            "time": "2026-02-10T13:30:00",
            "unit": "",
        }
        result = FinnhubNews._normalize_event(event, "high")
        assert result["source"] == "finnhub"
        assert result["previous"] == "225K"
        assert result["datetime"] == "2026-02-10T13:30:00"
