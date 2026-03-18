"""
System State Machine for lifecycle management.

Tracks system readiness and per-symbol data completeness.
Thread-safe singleton pattern.
"""

from __future__ import annotations

import os

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import TYPE_CHECKING

from loguru import logger

from config_loader import load_finnhub

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis


class SystemState(Enum):
    """System lifecycle states."""

    INITIALIZING = "INITIALIZING"
    WARMING_UP = "WARMING_UP"
    READY = "READY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


class SymbolStatus(Enum):
    """Per-symbol data status."""

    COMPLETE = "COMPLETE"
    INCOMPLETE_DATA = "INCOMPLETE_DATA"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"


@dataclass
class WarmupStatus:
    """Per-symbol warmup status."""

    symbol: str
    W1_bars: int = 0
    D1_bars: int = 0
    H4_bars: int = 0
    H1_bars: int = 0
    M15_bars: int = 0
    status: SymbolStatus = SymbolStatus.INCOMPLETE_DATA


class SystemStateManager:
    """
    Thread-safe singleton for system state management.

    Manages system lifecycle and per-symbol data completeness.
    """

    _instance: SystemStateManager | None = None
    _lock = Lock()

    # Valid state transitions
    _VALID_TRANSITIONS: dict[SystemState, set[SystemState]] = {
        SystemState.INITIALIZING: {SystemState.WARMING_UP, SystemState.ERROR},
        SystemState.WARMING_UP: {
            SystemState.READY,
            SystemState.DEGRADED,
            SystemState.ERROR,
        },
        # Allow re-entering warmup from READY/DEGRADED/ERROR during runtime retries.
        SystemState.READY: {
            SystemState.WARMING_UP,
            SystemState.DEGRADED,
            SystemState.ERROR,
        },
        SystemState.DEGRADED: {
            SystemState.WARMING_UP,
            SystemState.READY,
            SystemState.ERROR,
        },
        SystemState.ERROR: {
            SystemState.INITIALIZING,
            SystemState.WARMING_UP,
        },  # Allow restart
    }

    def __new__(cls) -> SystemStateManager:
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize state manager."""
        self._state = SystemState.INITIALIZING
        self._warmup_report: dict[str, WarmupStatus] = {}
        self._rw_lock = Lock()

        # Load config
        self.config = load_finnhub()
        self.warmup_config = self.config.get("candles", {}).get("warmup", {})
        self.min_bars = self.warmup_config.get(
            "min_bars",
            {
                "W1": 20,
                "D1": 50,
                "H4": 10,
                "H1": 50,
            },
        )

        # Redis support for multi-container
        self._mode = os.getenv("CONTEXT_MODE", "local").lower()
        self._redis: AsyncRedis | None = None

        logger.info("SystemStateManager initialized")

    def set_state(self, new_state: SystemState) -> None:
        """
        Set system state with transition validation.

        Args:
            new_state: New system state

        Raises:
            ValueError: If transition is invalid
        """
        with self._rw_lock:
            current = self._state

            if current == new_state:
                logger.debug(
                    "Ignoring no-op system state transition: {} -> {}",
                    current.value,
                    new_state.value,
                )
                return

            # Validate transition
            valid_next = self._VALID_TRANSITIONS.get(current, set())
            if new_state not in valid_next:
                raise ValueError(
                    f"Invalid state transition: {current.value} -> {new_state.value}"
                )

            self._state = new_state
            logger.info(f"System state: {current.value} -> {new_state.value}")

        # Publish to Redis if in redis mode
        self._publish_state(new_state)

    def reset(self) -> None:
        """Reset state manager to INITIALIZING for clean retry attempts."""
        with self._rw_lock:
            self._state = SystemState.INITIALIZING
            self._warmup_report = {}
        logger.warning("System state manager reset to INITIALIZING")

    def get_state(self) -> SystemState:
        """Get current system state."""
        with self._rw_lock:
            return self._state

    def is_ready(self) -> bool:
        """Check if system is ready for trading."""
        with self._rw_lock:
            return self._state == SystemState.READY

    def is_tradeable(self, symbol: str) -> bool:
        """
        Check if a symbol is tradeable.

        Args:
            symbol: Trading symbol

        Returns:
            True if symbol has complete data and system is ready
        """
        with self._rw_lock:
            if self._state not in (SystemState.READY, SystemState.DEGRADED):
                return False

            status = self._warmup_report.get(symbol)
            if not status:
                return False

            return status.status == SymbolStatus.COMPLETE

    def validate_warmup(self, results: dict[str, dict[str, list[dict]]]) -> None:
        """
        Validate warmup results and update symbol statuses.

        Args:
            results: Dict of symbol -> timeframe -> candles
        """
        with self._rw_lock:
            complete_count = 0
            incomplete_count = 0

            for symbol, tf_candles in results.items():
                status = WarmupStatus(symbol=symbol)

                # Count bars per timeframe
                for tf, candles in tf_candles.items():
                    bar_count = len(candles)

                    if tf == "W1":
                        status.W1_bars = bar_count
                    elif tf == "D1":
                        status.D1_bars = bar_count
                    elif tf == "H4":
                        status.H4_bars = bar_count
                    elif tf == "H1":
                        status.H1_bars = bar_count
                    elif tf == "M15":
                        status.M15_bars = bar_count

                # Check if symbol meets minimum requirements
                if (
                    status.W1_bars >= self.min_bars.get("W1", 20)
                    and status.D1_bars >= self.min_bars.get("D1", 50)
                    and status.H4_bars >= self.min_bars.get("H4", 10)
                    and status.H1_bars >= self.min_bars.get("H1", 50)
                ):
                    status.status = SymbolStatus.COMPLETE
                    complete_count += 1
                    logger.debug(
                        f"{symbol} warmup COMPLETE: "
                        f"W1={status.W1_bars}, D1={status.D1_bars}, "
                        f"H4={status.H4_bars}, H1={status.H1_bars}"
                    )
                else:
                    status.status = SymbolStatus.INCOMPLETE_DATA
                    incomplete_count += 1
                    logger.warning(
                        f"{symbol} warmup INCOMPLETE: "
                        f"W1={status.W1_bars}/{self.min_bars.get('W1', 20)}, "
                        f"D1={status.D1_bars}/{self.min_bars.get('D1', 50)}, "
                        f"H4={status.H4_bars}/{self.min_bars.get('H4', 10)}, "
                        f"H1={status.H1_bars}/{self.min_bars.get('H1', 50)}"
                    )

                self._warmup_report[symbol] = status

            # Set system state based on results
            if incomplete_count == 0:
                logger.info(f"Warmup validation: {complete_count} symbols COMPLETE")
            else:
                logger.warning(
                    f"Warmup validation: {complete_count} COMPLETE, "
                    f"{incomplete_count} INCOMPLETE"
                )

    def get_warmup_report(self) -> dict[str, WarmupStatus]:
        """Get warmup report for all symbols."""
        with self._rw_lock:
            return dict(self._warmup_report)

    def mark_symbol_degraded(self, symbol: str, reason: str) -> None:
        """
        Mark a symbol as degraded.

        Args:
            symbol: Trading symbol
            reason: Degradation reason
        """
        with self._rw_lock:
            if symbol in self._warmup_report:
                self._warmup_report[symbol].status = SymbolStatus.DEGRADED
                logger.warning(f"{symbol} marked as DEGRADED: {reason}")

                # Check if any symbols are still COMPLETE
                has_complete = any(
                    s.status == SymbolStatus.COMPLETE
                    for s in self._warmup_report.values()
                )

                if not has_complete and self._state == SystemState.READY:
                    # All symbols degraded - transition to DEGRADED state
                    self._state = SystemState.DEGRADED
                    logger.warning("All symbols degraded - system state: DEGRADED")
                    self._publish_state(SystemState.DEGRADED)

    def mark_symbol_recovered(self, symbol: str) -> None:
        """
        Mark a symbol as recovered from degraded state.

        Args:
            symbol: Trading symbol
        """
        with self._rw_lock:
            if symbol in self._warmup_report:
                status = self._warmup_report[symbol]

                # Re-validate bar counts
                if (
                    status.W1_bars >= self.min_bars.get("W1", 20)
                    and status.D1_bars >= self.min_bars.get("D1", 50)
                    and status.H4_bars >= self.min_bars.get("H4", 10)
                    and status.H1_bars >= self.min_bars.get("H1", 50)
                ):
                    status.status = SymbolStatus.COMPLETE
                    logger.info(f"{symbol} recovered to COMPLETE")

                    # Check if we can transition back to READY
                    if self._state == SystemState.DEGRADED:
                        has_incomplete = any(
                            s.status != SymbolStatus.COMPLETE
                            for s in self._warmup_report.values()
                        )

                        if not has_incomplete:
                            self._state = SystemState.READY
                            logger.info("All symbols recovered - system state: READY")
                            self._publish_state(SystemState.READY)

    def _publish_state(self, state: SystemState) -> None:
        """
        Publish state change to Redis (if in redis mode).

        Note: This is currently a stub. Full Redis integration
        will be implemented when multi-container state sync is needed.

        Args:
            state: New system state
        """
        if self._mode == "redis" and self._redis:
            # TODO: Implement async Redis publish
            # await self._redis.publish("system:state", state.value)
            logger.debug(f"Redis state sync: system:state={state.value}")
