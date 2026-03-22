"""
Calendar routes — full endpoint test coverage.

Covers:
  GET  /api/v1/calendar           (day events, filtering, imminent flag)
  GET  /api/v1/calendar/upcoming  (lookahead window)
  GET  /api/v1/calendar/blocker   (blocker status + manual override)
  GET  /api/v1/calendar/health    (source health)
  POST /api/v1/calendar/news-lock/enable   (manual lock)
  POST /api/v1/calendar/news-lock/disable  (manual unlock)
  GET  /api/v1/calendar/news-lock/status   (lock query)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from news.models import BlockerStatus, EconomicEvent, ImpactLevel
from news.routes import calendar_routes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    title: str = "NFP",
    currency: str = "USD",
    impact: ImpactLevel = ImpactLevel.HIGH,
    dt_utc: datetime | None = None,
    is_timeless: bool = False,
) -> EconomicEvent:
    return EconomicEvent(
        title=title,
        currency=currency,
        impact=impact,
        impact_score=3 if impact == ImpactLevel.HIGH else 1,
        date=(dt_utc or datetime.now(UTC)).strftime("%Y-%m-%d"),
        time=(dt_utc or datetime.now(UTC)).strftime("%H:%M") if not is_timeless else "",
        datetime_utc=dt_utc,
        is_timeless=is_timeless,
    )


class _FakeService:
    """In-memory service stub; call-args are captured for assertions."""

    def __init__(
        self,
        day_events: list[EconomicEvent] | None = None,
        upcoming: list[EconomicEvent] | None = None,
        blocker: BlockerStatus | None = None,
        health: dict[str, Any] | None = None,
    ):
        super().__init__()
        self.day_events = day_events or []
        self.upcoming_events_list = upcoming or []
        self.blocker = blocker or BlockerStatus(is_locked=False, checked_at=datetime.now(UTC))
        self.health = health or {"forexfactory_json": {"healthy": True}}
        # capture args
        self.last_day_events_date: str | None = None
        self.last_upcoming_args: dict[str, Any] = {}
        self.last_blocker_symbol: str | None = None

    async def get_day_events(self, date_str: str) -> list[EconomicEvent]:
        self.last_day_events_date = date_str
        return self.day_events

    async def get_upcoming_events(
        self,
        lookahead_hours: int = 4,
        min_impact: str = "HIGH",
        *,
        now: datetime | None = None,
    ) -> list[EconomicEvent]:
        self.last_upcoming_args = {
            "lookahead_hours": lookahead_hours,
            "min_impact": min_impact,
            "now": now,
        }
        return self.upcoming_events_list

    async def get_blocker_status(self, symbol: str | None = None) -> BlockerStatus:
        self.last_blocker_symbol = symbol
        return self.blocker

    async def get_source_health(self) -> dict[str, Any]:
        return self.health


class _FakeRedis:
    """Minimal async-Redis stand-in with get/set/delete."""

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_service() -> _FakeService:
    return _FakeService()


@pytest.fixture()
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


def _patch_deps(monkeypatch: pytest.MonkeyPatch, service: _FakeService, redis: _FakeRedis) -> None:
    """Wire FakeService + FakeRedis into the calendar_routes module."""

    async def _svc():
        return service

    async def _redis():
        return redis

    monkeypatch.setattr(calendar_routes, "_get_news_service", _svc)
    monkeypatch.setattr(calendar_routes, "get_async_redis", _redis)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis) -> TestClient:
    _patch_deps(monkeypatch, fake_service, fake_redis)
    app = FastAPI()
    app.include_router(calendar_routes.router)
    return TestClient(app)


# ===================================================================
# GET /health
# ===================================================================


class TestHealth:
    def test_health_returns_sources_and_checked_at(self, client: TestClient) -> None:
        resp = client.get("/api/v1/calendar/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "sources" in body
        assert "checked_at" in body
        assert body["sources"]["forexfactory_json"]["healthy"] is True


# ===================================================================
# GET /blocker
# ===================================================================


class TestBlocker:
    def test_blocker_unlocked(self, client: TestClient) -> None:
        resp = client.get("/api/v1/calendar/blocker")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_locked"] is False
        assert "upcoming" in body

    def test_blocker_locked_by_event(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        now = datetime.now(UTC)
        ev = _make_event("FOMC", "USD", ImpactLevel.HIGH, now + timedelta(minutes=10))
        svc = _FakeService(
            blocker=BlockerStatus(
                is_locked=True,
                locked_by=ev,
                lock_reason="FOMC in 10 min",
                upcoming=[ev],
                checked_at=now,
            )
        )
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar/blocker").json()
        assert body["is_locked"] is True
        assert body["locked_by"]["title"] == "FOMC"
        assert body["upcoming_count"] == 1

    def test_blocker_manual_override(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> None:
        """Manual Redis lock overrides an unlocked service status."""
        fake_redis.store["NEWS_LOCK:STATE"] = json.dumps({"locked": True, "reason": "Manual pre-NFP"})
        _patch_deps(monkeypatch, fake_service, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar/blocker").json()
        assert body["is_locked"] is True
        assert "Manual lock" in body["lock_reason"]

    def test_blocker_forwards_symbol(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        svc = _FakeService()
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        c.get("/api/v1/calendar/blocker?symbol=EURUSD")
        assert svc.last_blocker_symbol == "EURUSD"


# ===================================================================
# GET /  (day calendar)
# ===================================================================


class TestGetCalendar:
    def test_empty_day(self, client: TestClient) -> None:
        body = client.get("/api/v1/calendar").json()
        assert body["total"] == 0
        assert body["events"] == []
        assert "news_lock" in body

    def test_events_returned_with_enrichment(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        now = datetime.now(UTC)
        ev = _make_event("NFP", "USD", ImpactLevel.HIGH, now + timedelta(minutes=30))
        svc = _FakeService(day_events=[ev])
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar").json()
        assert body["total"] == 1
        assert body["high_impact_count"] == 1
        event = body["events"][0]
        assert event["title"] == "NFP"
        assert event["minutes_away"] is not None
        # HIGH + within 60 min → imminent
        assert event["is_imminent"] is True

    def test_filter_by_impact(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        now = datetime.now(UTC)
        high = _make_event("NFP", "USD", ImpactLevel.HIGH, now + timedelta(hours=1))
        low = _make_event("Redbook", "USD", ImpactLevel.LOW, now + timedelta(hours=2))
        svc = _FakeService(day_events=[high, low])
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar?impact=HIGH").json()
        assert body["total"] == 1
        assert body["events"][0]["title"] == "NFP"

    def test_filter_by_currency(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        now = datetime.now(UTC)
        usd = _make_event("NFP", "USD", ImpactLevel.HIGH, now)
        eur = _make_event("ECB Rate", "EUR", ImpactLevel.HIGH, now)
        svc = _FakeService(day_events=[usd, eur])
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar?currency=EUR").json()
        assert body["total"] == 1
        assert body["events"][0]["currency"] == "EUR"

    def test_explicit_date_forwarded(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        svc = _FakeService()
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        c.get("/api/v1/calendar?date=2026-01-15")
        assert svc.last_day_events_date == "2026-01-15"

    def test_timeless_event_imminent_false(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        ev = _make_event("Bank Holiday", "USD", ImpactLevel.HOLIDAY, is_timeless=True)
        svc = _FakeService(day_events=[ev])
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar").json()
        event = body["events"][0]
        assert event["minutes_away"] is None
        assert event["is_imminent"] is False

    def test_news_lock_reflected(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        fake_redis.store["NEWS_LOCK:STATE"] = json.dumps({"locked": True, "reason": "pre-CPI"})
        svc = _FakeService()
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar").json()
        assert body["news_lock"]["active"] is True
        assert body["news_lock"]["reason"] == "pre-CPI"


# ===================================================================
# GET /upcoming
# ===================================================================


class TestUpcoming:
    def test_empty_upcoming(self, client: TestClient) -> None:
        body = client.get("/api/v1/calendar/upcoming").json()
        assert body["count"] == 0
        assert body["has_high_impact"] is False
        assert body["hours_ahead"] == 4

    def test_upcoming_with_events(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        now = datetime.now(UTC)
        ev = _make_event("CPI", "USD", ImpactLevel.HIGH, now + timedelta(hours=2))
        svc = _FakeService(upcoming=[ev])
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        body = c.get("/api/v1/calendar/upcoming?hours=6").json()
        assert body["count"] == 1
        assert body["has_high_impact"] is True
        assert body["events"][0]["title"] == "CPI"
        assert body["events"][0]["minutes_away"] is not None

    def test_upcoming_passes_impact_filter(self, monkeypatch: pytest.MonkeyPatch, fake_redis: _FakeRedis) -> None:
        svc = _FakeService()
        _patch_deps(monkeypatch, svc, fake_redis)
        app = FastAPI()
        app.include_router(calendar_routes.router)
        c = TestClient(app)

        c.get("/api/v1/calendar/upcoming?impact=MEDIUM")
        assert svc.last_upcoming_args["min_impact"] == "MEDIUM"


# ===================================================================
# POST /news-lock/enable, /news-lock/disable, GET /news-lock/status
# ===================================================================


class TestNewsLock:
    """Manual news-lock lifecycle (enable → status → disable → status)."""

    def _make_client(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> TestClient:
        _patch_deps(monkeypatch, fake_service, fake_redis)
        from api.middleware.auth import verify_token
        from api.middleware.governance import enforce_write_policy

        app = FastAPI()
        app.include_router(calendar_routes.router)
        # Override FastAPI Depends() for auth/governance
        app.dependency_overrides[verify_token] = lambda: None
        app.dependency_overrides[enforce_write_policy] = lambda: None
        return TestClient(app)

    def test_enable_lock(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> None:
        c = self._make_client(monkeypatch, fake_service, fake_redis)
        resp = c.post(
            "/api/v1/calendar/news-lock/enable",
            json={"reason": "Pre-NFP", "duration_minutes": 30},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["news_lock"] is True
        assert body["reason"] == "Pre-NFP"
        # Verify Redis was written
        assert "NEWS_LOCK:STATE" in fake_redis.store

    def test_disable_lock(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> None:
        c = self._make_client(monkeypatch, fake_service, fake_redis)
        # enable first
        c.post("/api/v1/calendar/news-lock/enable", json={})
        assert "NEWS_LOCK:STATE" in fake_redis.store
        # disable
        resp = c.post("/api/v1/calendar/news-lock/disable")
        assert resp.status_code == 200
        body = resp.json()
        assert body["news_lock"] is False
        assert "NEWS_LOCK:STATE" not in fake_redis.store

    def test_status_reflects_lock(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> None:
        c = self._make_client(monkeypatch, fake_service, fake_redis)
        # initially unlocked
        body = c.get("/api/v1/calendar/news-lock/status").json()
        assert body["news_lock"] is False

        # enable
        c.post("/api/v1/calendar/news-lock/enable", json={"reason": "CPI"})
        body = c.get("/api/v1/calendar/news-lock/status").json()
        assert body["news_lock"] is True
        assert body["reason"] == "CPI"

    def test_full_lifecycle(
        self, monkeypatch: pytest.MonkeyPatch, fake_service: _FakeService, fake_redis: _FakeRedis
    ) -> None:
        c = self._make_client(monkeypatch, fake_service, fake_redis)
        # enable
        c.post("/api/v1/calendar/news-lock/enable", json={"reason": "FOMC"})
        assert c.get("/api/v1/calendar/news-lock/status").json()["news_lock"] is True
        # disable
        c.post("/api/v1/calendar/news-lock/disable")
        assert c.get("/api/v1/calendar/news-lock/status").json()["news_lock"] is False
