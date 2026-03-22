from datetime import UTC, datetime, timedelta

import pytest

from context.live_context_bus import LiveContextBus
from news.news_engine import NewsEngine


@pytest.fixture(autouse=True)
def reset_context_bus():
    bus = LiveContextBus()
    bus._init()
    return bus


def test_high_impact_event_locks_market(reset_context_bus):
    now = datetime.now(UTC)
    reset_context_bus.update_news({"events": [{"impact": "HIGH", "timestamp": now, "currency": "USD"}]})

    engine = NewsEngine()
    assert engine.is_locked("XAUUSD") is True


def test_out_of_window_event_does_not_lock(reset_context_bus):
    past = datetime.now(UTC) - timedelta(hours=2)
    reset_context_bus.update_news({"events": [{"impact": "HIGH", "timestamp": past, "currency": "USD"}]})

    engine = NewsEngine()
    assert engine.is_locked("EURUSD") is False
