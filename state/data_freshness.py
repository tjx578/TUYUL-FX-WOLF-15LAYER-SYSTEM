from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Literal

FeedFreshnessState = Literal[
    "fresh",
    "stale_preserved",
    "no_producer",
    "no_transport",
    "config_error",
]


class FreshnessClass(str, Enum):
    """Approved pipeline-wide freshness classification.

    This is the single canonical set of freshness labels used across
    analysis, governance, dashboard, and execution layers.
    """

    LIVE = "LIVE"
    DEGRADED_BUT_REFRESHING = "DEGRADED_BUT_REFRESHING"
    STALE_PRESERVED = "STALE_PRESERVED"
    NO_PRODUCER = "NO_PRODUCER"
    NO_TRANSPORT = "NO_TRANSPORT"
    CONFIG_ERROR = "CONFIG_ERROR"


# ---------------------------------------------------------------------------
# Centralized threshold constants — single source of truth
# ---------------------------------------------------------------------------


def _env_threshold(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return default


#: Ticks within this age are classified as LIVE (real-time).
FRESHNESS_LIVE_MAX_AGE_SEC: float = _env_threshold("WOLF_FRESHNESS_LIVE_MAX_AGE_SEC", 30.0)

_DEFAULT_STALE_THRESHOLD_SECONDS = 300.0


def stale_threshold_config() -> tuple[float, bool]:
    """Return the unified stale threshold and whether config parsed cleanly."""
    raw = (
        os.getenv("WOLF_STALE_THRESHOLD_SECONDS")
        or os.getenv("STALE_DATA_THRESHOLD_SEC")
        or str(_DEFAULT_STALE_THRESHOLD_SECONDS)
    )
    try:
        return max(0.0, float(str(raw).strip())), True
    except (TypeError, ValueError):
        return _DEFAULT_STALE_THRESHOLD_SECONDS, False


def stale_threshold_seconds() -> float:
    """Single config authority for cross-layer stale checks."""
    return stale_threshold_config()[0]


@dataclass(frozen=True)
class FeedFreshnessSnapshot:
    state: FeedFreshnessState
    staleness_seconds: float
    threshold_seconds: float
    last_seen_ts: float | None = None
    detail: str = ""

    @property
    def is_fresh(self) -> bool:
        return self.state == "fresh"

    @property
    def freshness_class(self) -> FreshnessClass:
        """Map internal state + staleness to the approved FreshnessClass enum."""
        _fixed: dict[FeedFreshnessState, FreshnessClass] = {
            "config_error": FreshnessClass.CONFIG_ERROR,
            "no_transport": FreshnessClass.NO_TRANSPORT,
            "no_producer": FreshnessClass.NO_PRODUCER,
            "stale_preserved": FreshnessClass.STALE_PRESERVED,
        }
        if self.state in _fixed:
            return _fixed[self.state]
        # state == "fresh" — split into LIVE vs DEGRADED_BUT_REFRESHING
        if self.staleness_seconds <= FRESHNESS_LIVE_MAX_AGE_SEC:
            return FreshnessClass.LIVE
        return FreshnessClass.DEGRADED_BUT_REFRESHING


def classify_feed_freshness(
    *,
    transport_ok: bool,
    has_producer_signal: bool,
    staleness_seconds: float | None = None,
    threshold_seconds: float | None = None,
    last_seen_ts: float | None = None,
    now_ts: float | None = None,
    config_ok: bool = True,
) -> FeedFreshnessSnapshot:
    threshold = stale_threshold_seconds() if threshold_seconds is None else max(0.0, threshold_seconds)

    if last_seen_ts is not None:
        if last_seen_ts > 0:
            reference_now = now_ts if now_ts is not None else time.time()
            staleness_seconds = max(0.0, reference_now - last_seen_ts)
            has_producer_signal = True
        else:
            last_seen_ts = None

    resolved_staleness = float("inf") if staleness_seconds is None else max(0.0, staleness_seconds)

    if not config_ok:
        return FeedFreshnessSnapshot(
            state="config_error",
            staleness_seconds=resolved_staleness,
            threshold_seconds=threshold,
            last_seen_ts=last_seen_ts,
            detail="invalid stale threshold configuration",
        )

    if not transport_ok:
        return FeedFreshnessSnapshot(
            state="no_transport",
            staleness_seconds=float("inf"),
            threshold_seconds=threshold,
            last_seen_ts=last_seen_ts,
            detail="feed transport unavailable",
        )

    if not has_producer_signal:
        return FeedFreshnessSnapshot(
            state="no_producer",
            staleness_seconds=float("inf"),
            threshold_seconds=threshold,
            last_seen_ts=last_seen_ts,
            detail="no producer heartbeat/tick",
        )

    if resolved_staleness <= threshold:
        return FeedFreshnessSnapshot(
            state="fresh",
            staleness_seconds=resolved_staleness,
            threshold_seconds=threshold,
            last_seen_ts=last_seen_ts,
            detail="within freshness threshold",
        )

    return FeedFreshnessSnapshot(
        state="stale_preserved",
        staleness_seconds=resolved_staleness,
        threshold_seconds=threshold,
        last_seen_ts=last_seen_ts,
        detail="stale but preserved cache exists",
    )
