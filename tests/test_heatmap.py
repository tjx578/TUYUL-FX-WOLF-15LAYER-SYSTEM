from __future__ import annotations

from datetime import UTC, datetime

from news.heatmap import build_news_heatmap
from news.models import EconomicEvent, ImpactLevel, SourceConfidence


def _event(hour: int, impact: ImpactLevel) -> EconomicEvent:
  return EconomicEvent(
      canonical_id=f"cid-{hour}-{impact.value}",
      source="test",
      source_confidence=SourceConfidence.HIGH,
      title="Event",
      currency="USD",
      impact=impact,
      impact_score=3,
      date="2026-03-09",
      time=f"{hour:02d}:00",
      datetime_utc=datetime(2026, 3, 9, hour, 0, tzinfo=UTC),
  )


def test_build_news_heatmap_scores_and_counts() -> None:
  events = [
      _event(8, ImpactLevel.HIGH),
      _event(8, ImpactLevel.MEDIUM),
      _event(9, ImpactLevel.LOW),
  ]

  payload = build_news_heatmap(events)
  buckets = payload["buckets"]

  b8 = buckets[8]
  assert b8["high"] == 1
  assert b8["medium"] == 1
  assert b8["score"] == 5

  b9 = buckets[9]
  assert b9["low"] == 1
  assert b9["score"] == 1

  assert payload["max_score"] == 5
