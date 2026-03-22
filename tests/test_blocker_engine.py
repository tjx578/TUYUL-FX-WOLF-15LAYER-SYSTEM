from datetime import UTC, datetime, timedelta

from news.blocker_engine import BlockerEngine
from news.datetime_utils import to_iso_utc
from news.models import EconomicEvent, ImpactLevel, SourceConfidence


def _event(dt: datetime) -> EconomicEvent:
    return EconomicEvent(
        canonical_id="cid-high",
        source="test",
        source_confidence=SourceConfidence.HIGH,
        title="NFP",
        currency="USD",
        impact=ImpactLevel.HIGH,
        impact_score=3,
        date=dt.strftime("%Y-%m-%d"),
        time=dt.strftime("%H:%M"),
        datetime_utc=dt,
        affected_pairs=["EURUSD"],
    )


def test_blocker_engine_locks_inside_window() -> None:
    now = datetime(2026, 3, 8, 13, 0, tzinfo=UTC)
    status = BlockerEngine().evaluate([_event(now)], symbol="EURUSD", now=now)

    assert status.is_locked is True
    assert status.locked_by is not None
    assert "HIGH event" in status.lock_reason


def test_blocker_engine_upcoming_horizon() -> None:
    now = datetime(2026, 3, 8, 13, 0, tzinfo=UTC)
    upcoming_dt = now + timedelta(minutes=50)
    status = BlockerEngine(lookahead_minutes=90).evaluate([_event(upcoming_dt)], symbol="EURUSD", now=now)

    assert status.is_locked is False
    assert len(status.upcoming) == 1
    assert to_iso_utc(status.upcoming[0].datetime_utc) is not None
