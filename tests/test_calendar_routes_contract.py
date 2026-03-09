from datetime import UTC, datetime

from fastapi.routing import APIRoute

from news.blocker_engine import BlockerEngine
from news.models import BlockerStatus, CalendarDaySnapshot, EconomicEvent, ImpactLevel, SourceConfidence
from news.pair_mapper import affected_pairs_for_currency
from news.routes.calendar_routes import router


def test_calendar_router_contract_paths() -> None:
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}
    assert "/api/v1/calendar" in paths
    assert "/api/v1/calendar/upcoming" in paths
    assert "/api/v1/calendar/blocker" in paths


def test_calendar_day_snapshot_contract() -> None:
    now = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    ev = EconomicEvent(
        canonical_id="cid-1",
        source="test",
        source_confidence=SourceConfidence.HIGH,
        title="CPI",
        currency="USD",
        impact=ImpactLevel.HIGH,
        impact_score=3,
        date="2026-03-08",
        time="12:00",
        datetime_utc=now,
        affected_pairs=affected_pairs_for_currency("USD"),
    )
    snap = CalendarDaySnapshot(date="2026-03-08", events=[ev], fetched_at=now)
    data = snap.to_dict()

    assert data["date"] == "2026-03-08"
    assert data["total"] == 1
    assert data["events"][0]["canonical_id"] == "cid-1"


def test_blocker_status_contract() -> None:
    now = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    ev = EconomicEvent(
        canonical_id="cid-2",
        source="test",
        source_confidence=SourceConfidence.HIGH,
        title="NFP",
        currency="USD",
        impact=ImpactLevel.HIGH,
        impact_score=3,
        date="2026-03-08",
        time="12:00",
        datetime_utc=now,
        affected_pairs=["EURUSD"],
    )

    status = BlockerEngine().evaluate([ev], symbol="EURUSD", now=now)
    payload = BlockerStatus(
        is_locked=status.is_locked,
        locked_by=status.locked_by,
        lock_reason=status.lock_reason,
        upcoming=status.upcoming,
        checked_at=status.checked_at,
    ).to_dict()

    assert "is_locked" in payload
    assert "upcoming" in payload
