"""
Dashboard Journal Routes — Expose journal system to dashboard.

Endpoints:
  GET /api/v1/journal/today       — Today's journal entries
  GET /api/v1/journal/weekly      — Last 7 days
  GET /api/v1/journal/metrics     — Rejection %, protection rate, win rate
"""

from typing import Any

from fastapi import APIRouter

from journal.journal_metrics import get_daily_stats, get_rejection_accuracy, get_weekly_stats

router = APIRouter()


@router.get("/api/v1/journal/today")
async def get_today_journal() -> dict[str, Any]:
    """
    Get today's journal entries and metrics.

    Returns:
        Dictionary with journal metrics for today
    """
    return get_daily_stats(days=1)


@router.get("/api/v1/journal/weekly")
async def get_weekly_journal() -> dict[str, Any]:
    """
    Get last 7 days of journal entries and metrics.

    Returns:
        Dictionary with journal metrics for last 7 days
    """
    return get_weekly_stats()


@router.get("/api/v1/journal/metrics")
async def get_journal_metrics() -> dict[str, Any]:
    """
    Get journal metrics summary.

    Includes:
      - Rejection accuracy %
      - Protection rate
      - Win rate
      - Total decisions

    Returns:
        Dictionary with metric summary
    """
    # Get weekly stats
    weekly = get_weekly_stats()

    # Get rejection accuracy
    rejection_accuracy = get_rejection_accuracy(days=7)

    # Build metrics summary
    metrics = {
        "rejection_accuracy_pct": rejection_accuracy,
        "total_decisions": weekly.get("total_decisions", 0),
        "execute_count": weekly.get("execute_count", 0),
        "hold_count": weekly.get("hold_count", 0),
        "no_trade_count": weekly.get("no_trade_count", 0),
        "win_rate_pct": weekly.get("win_rate", 0.0),
        "protection_rate_pct": weekly.get("protection_rate", 0.0),
        "avg_discipline_score": weekly.get("avg_discipline", 0.0),
    }

    return metrics
