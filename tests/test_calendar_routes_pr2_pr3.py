from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from news.models import BlockerStatus, EconomicEvent
from news.routes import calendar_routes


class _FakeService:
  async def get_day_events(self, date_str: str) -> list[EconomicEvent]:
      _ = date_str
      return []

  async def get_upcoming_events(self, lookahead_hours: int = 4, min_impact: str = "HIGH", *, now: datetime | None = None) -> list[EconomicEvent]:
      _ = (lookahead_hours, min_impact, now)
      return []

  async def get_blocker_status(self, symbol: str | None = None) -> BlockerStatus:
      _ = symbol
      return BlockerStatus(is_locked=False, checked_at=datetime.now(UTC))

  async def get_source_health(self) -> dict[str, Any]:
      return {"forexfactory_json": {"healthy": True}}


class _FakeRedis:
  async def get(self, key: str) -> None:
      _ = key
      return None


def test_calendar_health_and_blocker_contract(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F821
  async def _mock_service():
      return _FakeService()

  async def _mock_redis():
      return _FakeRedis()

  monkeypatch.setattr(calendar_routes, "_get_news_service", _mock_service)
  monkeypatch.setattr(calendar_routes, "get_async_redis", _mock_redis)

  app = FastAPI()
  app.include_router(calendar_routes.router)
  client = TestClient(app)

  health = client.get("/api/v1/calendar/health")
  assert health.status_code == 200
  payload = health.json()
  assert "sources" in payload
  assert "checked_at" in payload

  blocker = client.get("/api/v1/calendar/blocker")
  assert blocker.status_code == 200
  status = blocker.json()
  assert "is_locked" in status
  assert "upcoming" in status
