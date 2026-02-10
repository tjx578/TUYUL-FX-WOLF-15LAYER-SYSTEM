"""
Journal Metrics — Read-only metrics computation.

Provides daily, weekly, and accuracy statistics from journal entries.
"""

from typing import Any, Dict

from journal.journal_gpt_bridge import _load_entries, compute_metrics


def get_daily_stats(days: int = 1) -> Dict[str, Any]:
    """
    Get journal metrics for specified number of days.

    Args:
        days: Number of days to analyze (default: 1 for today)

    Returns:
        Dictionary of metrics
    """
    entries = _load_entries(date_range_days=days)
    return compute_metrics(entries)


def get_weekly_stats() -> Dict[str, Any]:
    """
    Get journal metrics for the last 7 days.

    Returns:
        Dictionary of metrics
    """
    return get_daily_stats(days=7)


def get_rejection_accuracy(days: int = 7) -> float:
    """
    Calculate accuracy of rejections (percentage of correct rejections).

    Requires reflective journal entries (J4) to assess whether rejections
    were correct in hindsight.

    Args:
        days: Number of days to analyze

    Returns:
        Rejection accuracy as percentage (0-100)
    """
    entries = _load_entries(date_range_days=days, journal_types=["reflection"])

    if not entries:
        return 0.0

    correct_rejections = 0
    total_rejections = 0

    for entry in entries:
        data = entry.get("data", {})
        outcome = data.get("outcome")
        was_rejection_correct = data.get("was_rejection_correct")

        # Count rejections (SKIPPED outcomes with rejection correctness assessment)
        if outcome == "SKIPPED" and was_rejection_correct is not None:
            total_rejections += 1
            if was_rejection_correct:
                correct_rejections += 1

    if total_rejections == 0:
        return 0.0

    return round(correct_rejections / total_rejections * 100, 1)
