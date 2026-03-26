"""Unit tests for CalendarNewsIngestor."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

import ingest.calendar_news as calendar_news_module
from news.models import EconomicEvent, ImpactLevel

CalendarNewsIngestor = calendar_news_module.CalendarNewsIngestor


@pytest.fixture
def sample_event() -> EconomicEvent:
    return EconomicEvent(
        event_id="evt-1",
        canonical_id="canon-1",
        source="forexfactory_json",
        title="US CPI",
        currency="USD",
        country="US",
        impact=ImpactLevel.HIGH,
        impact_score=3,
        datetime_utc=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        affected_pairs=["EURUSD", "GBPUSD"],
        actual="3.4%",
        forecast="3.2%",
        previous="3.1%",
    )


@pytest.mark.asyncio
async def test_fetch_window_events_deduplicates_by_canonical_id(sample_event: EconomicEvent) -> None:
    duplicate = EconomicEvent(
        event_id="evt-2",
        canonical_id="canon-1",
        source="forexfactory_xml",
        title="US CPI (dup)",
    )

    fake_service = MagicMock()
    fake_service.get_day_events = AsyncMock(side_effect=[[sample_event], [duplicate]])

    def _news_service_factory(repo: object) -> MagicMock:
        _ = repo
        return fake_service

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(calendar_news_module, "NewsService", _news_service_factory)
        ingestor = CalendarNewsIngestor(redis_client=MagicMock())
        merged = await ingestor._fetch_window_events()

        assert len(merged) == 1
        assert merged[0].canonical_id == "canon-1"
        assert merged[0].source == "forexfactory_xml"


@pytest.mark.asyncio
async def test_run_publishes_payload_to_live_context_bus(sample_event: EconomicEvent) -> None:
    context_bus = MagicMock()
    fake_service = MagicMock()

    def _news_service_factory(repo: object) -> MagicMock:
        _ = repo
        return fake_service

    def _context_bus_factory() -> MagicMock:
        return context_bus

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(calendar_news_module, "NewsService", _news_service_factory)
        monkeypatch.setattr(calendar_news_module, "LiveContextBus", _context_bus_factory)
        monkeypatch.setenv("NEWS_POLL_INTERVAL_SEC", "3600")

        ingestor = CalendarNewsIngestor(redis_client=MagicMock())
        fake_service.get_day_events = AsyncMock(side_effect=[[sample_event], []])

        async def _stop_soon() -> None:
            await asyncio.sleep(0.01)
            await ingestor.stop()

        stopper = asyncio.create_task(_stop_soon())
        await asyncio.wait_for(ingestor.run(), timeout=2.0)
        await stopper

    context_bus.update_news.assert_called_once()
    payload = context_bus.update_news.call_args.args[0]

    assert payload["source"] == "news_provider_chain"
    assert payload["provider"] == "forexfactory"
    assert payload["count"] == 1
    assert payload["events"][0]["event"] == "US CPI"
    assert payload["events"][0]["impact"] == "high"
    assert payload["events"][0]["source"] == "forexfactory_json"
