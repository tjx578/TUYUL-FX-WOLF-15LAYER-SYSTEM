from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

FeedFreshnessState = Literal["fresh", "stale_preserved", "no_producer", "no_transport"]

_DEFAULT_STALE_THRESHOLD_SECONDS = 300.0


def stale_threshold_seconds() -> float:
    """Single config authority for cross-layer stale checks."""
    raw = (
        os.getenv("WOLF_STALE_THRESHOLD_SECONDS")
        or os.getenv("STALE_DATA_THRESHOLD_SEC")
        or str(_DEFAULT_STALE_THRESHOLD_SECONDS)
    )
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return _DEFAULT_STALE_THRESHOLD_SECONDS


@dataclass(frozen=True)
class FeedFreshnessSnapshot:
    state: FeedFreshnessState
    staleness_seconds: float
    threshold_seconds: float
    detail: str = ""

    @property
    def is_fresh(self) -> bool:
        return self.state == "fresh"


def classify_feed_freshness(
    *,
    transport_ok: bool,
    has_producer_signal: bool,
    staleness_seconds: float,
    threshold_seconds: float | None = None,
) -> FeedFreshnessSnapshot:
    threshold = stale_threshold_seconds() if threshold_seconds is None else max(0.0, threshold_seconds)

    if not transport_ok:
        return FeedFreshnessSnapshot(
            state="no_transport",
            staleness_seconds=float("inf"),
            threshold_seconds=threshold,
            detail="feed transport unavailable",
        )

    if not has_producer_signal:
        return FeedFreshnessSnapshot(
            state="no_producer",
            staleness_seconds=float("inf"),
            threshold_seconds=threshold,
            detail="no producer heartbeat/tick",
        )

    if staleness_seconds <= threshold:
        return FeedFreshnessSnapshot(
            state="fresh",
            staleness_seconds=max(0.0, staleness_seconds),
            threshold_seconds=threshold,
            detail="within freshness threshold",
        )

    return FeedFreshnessSnapshot(
        state="stale_preserved",
        staleness_seconds=max(0.0, staleness_seconds),
        threshold_seconds=threshold,
        detail="stale but preserved cache exists",
    )
