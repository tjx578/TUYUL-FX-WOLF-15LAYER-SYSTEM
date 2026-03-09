from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from news.models import BlockerStatus, EconomicEvent, ImpactLevel, SourceConfidence
from news.routes import calendar_routes


@dataclass
class _FakeRedis:
    initial: dict[str, str] | None = None
    _store: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self._store = dict(self.initial or {})

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._store[key] = value
        return True

    async def delete(self, key: str) -> int:
        existed = key in self._store
        self._store.pop(key, None)
        return 1 if existed else 0


@dataclass
class _FakeNewsService:
    _events: list[EconomicEvent]
    _status: BlockerStatus

    async def get_day_events(self, date_str: str) -> list[EconomicEvent]:
        return self._events

    async def get_upcoming_events(
        self,
        lookahead_hours: int = 4,
        min_impact: str = "HIGH",
        *,
        now: datetime | None = None,
    ) -> list[EconomicEvent]:
        _ = (lookahead_hours, min_impact, now)
        return self._events

    async def get_blocker_status(self, symbol: str | None = None) -> BlockerStatus:
        _ = symbol
        return self._status

    async def get_source_health(self) -> dict[str, Any]:
        return {"forexfactory_json": {"healthy": True}}


def _build_event(title: str = "CPI") -> EconomicEvent:
    now = datetime.now(UTC)
    return EconomicEvent(
        canonical_id="cid-calendar-1",
        source="test",
        source_confidence=SourceConfidence.HIGH,
        title=title,
        currency="USD",
        impact=ImpactLevel.HIGH,
        impact_score=3,
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M"),
        datetime_utc=now + timedelta(minutes=30),
        affected_pairs=["EURUSD"],
    )


def _test_client_with_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    redis: _FakeRedis,
    service: _FakeNewsService,
) -> TestClient:
    async def _mock_get_news_service() -> _FakeNewsService:
        return service

    async def _mock_get_async_redis() -> _FakeRedis:
        return redis

    monkeypatch.setattr(calendar_routes, "_get_news_service", _mock_get_news_service)
    monkeypatch.setattr(calendar_routes, "get_async_redis", _mock_get_async_redis)

    app = FastAPI()
    app.include_router(calendar_routes.router)
    return TestClient(app)


def test_calendar_get_returns_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _build_event()
    service = _FakeNewsService(
        _events=[event],
        _status=BlockerStatus(is_locked=False, checked_at=datetime.now(UTC)),
    )
    client = _test_client_with_mocks(monkeypatch, redis=_FakeRedis(), service=service)

    resp = client.get("/api/v1/calendar")
    assert resp.status_code == 200
    data = resp.json()

    assert data["total"] == 1
    assert data["high_impact_count"] == 1
    assert data["events"][0]["canonical_id"] == "cid-calendar-1"
    assert "minutes_away" in data["events"][0]


def test_calendar_upcoming_returns_has_high_impact(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _build_event("NFP")
    service = _FakeNewsService(
        _events=[event],
        _status=BlockerStatus(is_locked=False, checked_at=datetime.now(UTC)),
    )
    client = _test_client_with_mocks(monkeypatch, redis=_FakeRedis(), service=service)

    resp = client.get("/api/v1/calendar/upcoming?hours=4&impact=HIGH")
    assert resp.status_code == 200
    data = resp.json()

    assert data["count"] == 1
    assert data["has_high_impact"] is True


def test_calendar_blocker_manual_override(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _build_event("Retail Sales")
    unlocked_status = BlockerStatus(
        is_locked=False,
        locked_by=None,
        lock_reason="",
        upcoming=[event],
        checked_at=datetime.now(UTC),
    )
    service = _FakeNewsService(_events=[event], _status=unlocked_status)
    redis = _FakeRedis(
        initial={
            "NEWS_LOCK:STATE": '{"locked": true, "reason": "Operator lock"}'
        }
    )

    client = _test_client_with_mocks(monkeypatch, redis=redis, service=service)

    resp = client.get("/api/v1/calendar/blocker?symbol=EURUSD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["is_locked"] is True
    assert "Manual lock" in data["lock_reason"]


def test_calendar_health_returns_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    event = _build_event("PMI")
    service = _FakeNewsService(
        _events=[event],
        _status=BlockerStatus(is_locked=False, checked_at=datetime.now(UTC)),
    )
    client = _test_client_with_mocks(monkeypatch, redis=_FakeRedis(), service=service)

    resp = client.get("/api/v1/calendar/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert "forexfactory_json" in data["sources"]
