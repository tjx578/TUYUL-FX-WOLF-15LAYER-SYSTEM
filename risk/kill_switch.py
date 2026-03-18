from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from storage.redis_client import redis_client
from state.data_freshness import stale_threshold_seconds

_KILL_SWITCH_KEY = "RISK:KILL_SWITCH:GLOBAL"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KillSwitchState:
    enabled: bool
    reason: str
    updated_at: str


class GlobalKillSwitch:
    """Global execution stop switch (risk/governor authority)."""

    _instance: GlobalKillSwitch | None = None
    _lock = Lock()
    _state: KillSwitchState
    _rw_lock: Lock

    def __new__(cls) -> GlobalKillSwitch:
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._state = KillSwitchState(
                        enabled=False,
                        reason="",
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    cls._instance._rw_lock = Lock()
                    cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        with contextlib.suppress(Exception):
            raw = redis_client.get(_KILL_SWITCH_KEY)
            if not raw:
                return
            payload = json.loads(raw)
            self._state = KillSwitchState(
                enabled=bool(payload.get("enabled", False)),
                reason=str(payload.get("reason", "")),
                updated_at=str(payload.get("updated_at", datetime.now(UTC).isoformat())),
            )

    def _save(self) -> None:
        with contextlib.suppress(Exception):
            redis_client.set(
                _KILL_SWITCH_KEY,
                json.dumps(self.snapshot()),
            )

    def enable(self, reason: str) -> dict[str, str | bool]:
        with self._rw_lock:
            self._state = KillSwitchState(
                enabled=True,
                reason=reason.strip() or "MANUAL_KILL_SWITCH",
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._save()
            return self.snapshot()

    def disable(self, reason: str = "MANUAL_RELEASE") -> dict[str, str | bool]:
        with self._rw_lock:
            self._state = KillSwitchState(
                enabled=False,
                reason=reason.strip() or "MANUAL_RELEASE",
                updated_at=datetime.now(UTC).isoformat(),
            )
            self._save()
            return self.snapshot()

    def is_enabled(self) -> bool:
        return bool(self._state.enabled)

    def evaluate_and_trip(self, *, metrics: dict[str, Any]) -> dict[str, str | bool]:
        """Trip kill switch automatically from risk/feed telemetry.

        Supported metrics keys:
        - daily_dd_percent: float
        - rapid_loss_percent: float
        - feed_stale_seconds: float
        - feed_freshness_state: fresh | stale_preserved | no_producer | no_transport
        """
        daily_dd = float(metrics.get("daily_dd_percent", 0.0) or 0.0)
        rapid_loss = float(metrics.get("rapid_loss_percent", 0.0) or 0.0)
        feed_stale = float(metrics.get("feed_stale_seconds", 0.0) or 0.0)

        daily_threshold = float(os.getenv("KILL_SWITCH_DAILY_DD_PERCENT", "5.0"))
        rapid_threshold = float(os.getenv("KILL_SWITCH_RAPID_LOSS_PERCENT", "2.0"))
        stale_threshold = stale_threshold_seconds()
        feed_freshness_state = str(metrics.get("feed_freshness_state", "")).strip().lower()

        if daily_dd >= daily_threshold:
            return self.enable(f"AUTO_DAILY_DD_BREACH:{daily_dd:.2f}%>= {daily_threshold:.2f}%")
        if rapid_loss >= rapid_threshold:
            return self.enable(f"AUTO_RAPID_LOSS:{rapid_loss:.2f}%>= {rapid_threshold:.2f}%")
        if feed_freshness_state == "no_transport":
            return self.enable("AUTO_FEED_NO_TRANSPORT")
        if feed_freshness_state == "no_producer":
            return self.enable("AUTO_FEED_NO_PRODUCER")
        if feed_stale >= stale_threshold:
            return self.enable(f"AUTO_FEED_STALE:{feed_stale:.1f}s>= {stale_threshold:.1f}s")

        # Auto-recover from feed-stale trips when feed is fresh again.
        # Uses 50% hysteresis to prevent rapid on/off cycling.
        # Only auto-recovers AUTO_FEED_STALE — DD/loss trips require manual release.
        if self.is_enabled() and "AUTO_FEED_STALE" in self._state.reason and feed_stale < stale_threshold * 0.5:
            logger.info(
                "Kill switch auto-recovery: feed fresh at %.1fs (threshold %.1fs)",
                feed_stale,
                stale_threshold,
            )
            return self.disable(f"AUTO_RECOVERY:feed_fresh_at_{feed_stale:.1f}s")

        return self.snapshot()

    def snapshot(self) -> dict[str, str | bool]:
        return {
            "enabled": self._state.enabled,
            "reason": self._state.reason,
            "updated_at": self._state.updated_at,
        }
