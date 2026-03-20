from __future__ import annotations

from datetime import UTC, datetime, timedelta

from news.source_health import evaluate_source_health, summarize_source_health


def test_evaluate_source_health_healthy() -> None:
  now = datetime(2026, 3, 9, 10, 0, tzinfo=UTC)
  record = {
      "healthy": True,
      "last_checked": (now - timedelta(minutes=2)).isoformat(),
      "last_success": (now - timedelta(minutes=2)).isoformat(),
      "last_error": None,
  }

  result = evaluate_source_health(record, now=now)
  assert result["status"] == "healthy"
  assert result["healthy"] is True


def test_evaluate_source_health_stale() -> None:
  now = datetime(2026, 3, 9, 10, 0, tzinfo=UTC)
  record = {
      "healthy": True,
      "last_checked": (now - timedelta(minutes=90)).isoformat(),
      "last_success": (now - timedelta(minutes=90)).isoformat(),
      "last_error": None,
  }

  result = evaluate_source_health(record, now=now, stale_after_minutes=30)
  assert result["status"] == "stale"
  assert result["healthy"] is False


def test_summarize_source_health_counts() -> None:
  now = datetime(2026, 3, 9, 10, 0, tzinfo=UTC)
  records = {
      "forexfactory_json": {
          "healthy": True,
          "last_checked": (now - timedelta(minutes=2)).isoformat(),
          "last_success": (now - timedelta(minutes=2)).isoformat(),
          "last_error": None,
      },
      "finnhub": {
          "healthy": False,
          "last_checked": (now - timedelta(minutes=1)).isoformat(),
          "last_success": (now - timedelta(hours=1)).isoformat(),
          "last_error": "timeout",
      },
  }

  summary = summarize_source_health(records, now=now)
  assert summary["summary"]["total"] == 2
  assert summary["summary"]["healthy"] == 1
  assert summary["summary"]["down"] == 1
