"""
System health monitor -- required before going live.
Monitors all subsystems and can auto-pause trading if critical issues detected.
"""

from __future__ import annotations

import contextlib
import logging
import time

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger("tuyul.health")


class SubsystemStatus(Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"


@dataclass
class SubsystemHealth:
    name: str
    status: SubsystemStatus
    last_heartbeat: float
    message: str = ""
    metrics: dict = field(default_factory=dict)

    @property
    def seconds_since_heartbeat(self) -> float:
        return time.time() - self.last_heartbeat


@dataclass
class SystemHealth:
    subsystems: dict[str, SubsystemHealth] = field(default_factory=dict)
    trading_allowed: bool = True
    pause_reason: str | None = None

    @property
    def overall_status(self) -> SubsystemStatus:
        if not self.subsystems:
            return SubsystemStatus.OFFLINE
        statuses = [s.status for s in self.subsystems.values()]
        if SubsystemStatus.CRITICAL in statuses:
            return SubsystemStatus.CRITICAL
        if SubsystemStatus.OFFLINE in statuses:
            return SubsystemStatus.CRITICAL
        if SubsystemStatus.DEGRADED in statuses:
            return SubsystemStatus.DEGRADED
        return SubsystemStatus.HEALTHY

    @property
    def is_live_ready(self) -> bool:
        """All subsystems must be healthy for live trading."""
        return (
            self.trading_allowed
            and self.overall_status in (SubsystemStatus.HEALTHY, SubsystemStatus.DEGRADED)
            and all(s.seconds_since_heartbeat < 30 for s in self.subsystems.values())
        )


class HealthMonitor:
    """
    Central health monitor. All subsystems report heartbeats.
    Auto-pauses trading if critical subsystems fail.
    """

    CRITICAL_SUBSYSTEMS = {"data_feed", "execution", "risk_guard"}
    HEARTBEAT_TIMEOUT = 30.0  # seconds

    def __init__(self):
        self._health = SystemHealth()
        self._on_pause_callbacks: list[Callable[[str], None]] = []

    def register_subsystem(self, name: str) -> None:
        self._health.subsystems[name] = SubsystemHealth(
            name=name,
            status=SubsystemStatus.OFFLINE,
            last_heartbeat=0.0,
            message="Not yet started",
        )

    def heartbeat(
        self,
        name: str,
        status: SubsystemStatus = SubsystemStatus.HEALTHY,
        message: str = "",
        metrics: dict | None = None,
    ) -> None:
        if name not in self._health.subsystems:
            self.register_subsystem(name)

        self._health.subsystems[name] = SubsystemHealth(
            name=name,
            status=status,
            last_heartbeat=time.time(),
            message=message,
            metrics=metrics or {},
        )

        # Check if we need to auto-pause
        self._evaluate_trading_status()

    def on_pause(self, callback: Callable[[str], None]) -> None:
        self._on_pause_callbacks.append(callback)

    def get_health(self) -> SystemHealth:
        # Check for stale heartbeats
        for sub in self._health.subsystems.values():
            if sub.seconds_since_heartbeat > self.HEARTBEAT_TIMEOUT:
                sub.status = SubsystemStatus.OFFLINE
                sub.message = f"No heartbeat for {sub.seconds_since_heartbeat:.0f}s"

        self._evaluate_trading_status()
        return self._health

    def _evaluate_trading_status(self) -> None:
        for name in self.CRITICAL_SUBSYSTEMS:
            sub = self._health.subsystems.get(name)
            if sub is None:
                continue
            if sub.status in (SubsystemStatus.CRITICAL, SubsystemStatus.OFFLINE):
                if self._health.trading_allowed:
                    reason = f"Critical subsystem '{name}' is {sub.status.value}: {sub.message}"
                    self._health.trading_allowed = False
                    self._health.pause_reason = reason
                    logger.critical(f"AUTO-PAUSE: {reason}")
                    for cb in self._on_pause_callbacks:
                        with contextlib.suppress(Exception):
                            cb(reason)
                return

        # All critical systems OK -- allow trading
        if not self._health.trading_allowed:
            logger.info("All critical subsystems recovered -- trading re-enabled")
            self._health.trading_allowed = True
            self._health.pause_reason = None
