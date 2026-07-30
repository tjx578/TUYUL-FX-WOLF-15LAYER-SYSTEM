"""Market-hours tick-feed heartbeat.

Raises a rate-limited alarm event when the live tick feed is silent while the
forex market is open, and announces recovery once ticks resume.  Pure state
machine: the caller supplies the freshest tick timestamp and the market-open
flag, so the module stays deterministic and testable.  Observability-only —
it never blocks anything and emits nothing while disabled (default), while the
market is closed, or during the startup / market-open grace window (so a
Friday-stale tick does not fire a false alarm at the Sunday reopen before the
websocket has reconnected).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_DEFAULT_MAX_SILENCE_SECONDS = 300.0
_DEFAULT_ALERT_INTERVAL_SECONDS = 600.0
_DEFAULT_STARTUP_GRACE_SECONDS = 600.0


@dataclass
class TickFeedHeartbeat:
    enabled: bool = False
    max_silence_seconds: float = _DEFAULT_MAX_SILENCE_SECONDS
    alert_interval_seconds: float = _DEFAULT_ALERT_INTERVAL_SECONDS
    startup_grace_seconds: float = _DEFAULT_STARTUP_GRACE_SECONDS

    _started_at: float | None = field(default=None, repr=False)
    _market_open_since: float | None = field(default=None, repr=False)
    _alarm_started_at: float | None = field(default=None, repr=False)
    _last_alert_at: float | None = field(default=None, repr=False)
    _alert_count: int = field(default=0, repr=False)

    @classmethod
    def from_env(cls) -> TickFeedHeartbeat:
        return cls(
            enabled=os.getenv("TICK_FEED_HEARTBEAT_ENABLED", "false").strip().lower() == "true",
            max_silence_seconds=_env_positive_float(
                "TICK_FEED_HEARTBEAT_MAX_SILENCE_SECONDS", _DEFAULT_MAX_SILENCE_SECONDS
            ),
            alert_interval_seconds=_env_positive_float(
                "TICK_FEED_HEARTBEAT_ALERT_INTERVAL_SECONDS", _DEFAULT_ALERT_INTERVAL_SECONDS
            ),
            startup_grace_seconds=_env_positive_float(
                "TICK_FEED_HEARTBEAT_STARTUP_GRACE_SECONDS", _DEFAULT_STARTUP_GRACE_SECONDS
            ),
        )

    def check(
        self,
        *,
        freshest_tick_epoch: float | None,
        market_open: bool,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Advance the state machine; return an alarm/recovery event or None."""
        if not self.enabled:
            return None
        current = time.time() if now is None else float(now)
        if self._started_at is None:
            self._started_at = current

        if not market_open:
            # Weekend / closed market: silence is expected.  Keep any active
            # alarm latched so the reopen either recovers or re-alerts, but
            # reset the open-transition baseline.
            self._market_open_since = None
            return None
        if self._market_open_since is None:
            self._market_open_since = current

        silence_baseline = max(
            value for value in (freshest_tick_epoch, self._started_at, self._market_open_since) if value is not None
        )
        silence_seconds = max(0.0, current - silence_baseline)
        tick_is_fresh = freshest_tick_epoch is not None and current - freshest_tick_epoch <= self.max_silence_seconds

        if tick_is_fresh:
            if self._alarm_started_at is None:
                return None
            downtime = max(0.0, current - self._alarm_started_at)
            event = self._base_event(
                event="tick_feed_heartbeat_recovered",
                status="TICK_FEED_RECOVERED",
                current=current,
                freshest_tick_epoch=freshest_tick_epoch,
                silence_seconds=0.0,
            )
            event["alarm_downtime_seconds"] = round(downtime, 3)
            event["alerts_raised"] = self._alert_count
            self._alarm_started_at = None
            self._last_alert_at = None
            self._alert_count = 0
            return event

        in_grace = (
            current - self._started_at < self.startup_grace_seconds
            or current - self._market_open_since < self.startup_grace_seconds
        )
        if in_grace and self._alarm_started_at is None:
            return None
        if silence_seconds <= self.max_silence_seconds and self._alarm_started_at is None:
            return None

        if self._alarm_started_at is None:
            self._alarm_started_at = current
        if self._last_alert_at is not None and current - self._last_alert_at < self.alert_interval_seconds:
            return None
        self._last_alert_at = current
        self._alert_count += 1
        event = self._base_event(
            event="tick_feed_heartbeat_alarm",
            status="TICK_FEED_SILENT_MARKET_OPEN",
            current=current,
            freshest_tick_epoch=freshest_tick_epoch,
            silence_seconds=silence_seconds,
        )
        event["alert_number"] = self._alert_count
        event["alarm_started_at_utc"] = _epoch_to_iso(self._alarm_started_at)
        return event

    def _base_event(
        self,
        *,
        event: str,
        status: str,
        current: float,
        freshest_tick_epoch: float | None,
        silence_seconds: float,
    ) -> dict[str, Any]:
        return {
            "event": event,
            "status": status,
            "market_open": True,
            "silence_seconds": round(silence_seconds, 3),
            "max_silence_seconds": self.max_silence_seconds,
            "alert_interval_seconds": self.alert_interval_seconds,
            "freshest_tick_utc": _epoch_to_iso(freshest_tick_epoch),
            "checked_at_utc": _epoch_to_iso(current),
            "valid_for_execution": False,
            "execution_impact": False,
        }


def _env_positive_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0.0 else default


def _epoch_to_iso(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat()
    except (OSError, OverflowError, TypeError, ValueError):
        return None


__all__ = ["TickFeedHeartbeat"]
