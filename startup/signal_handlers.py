"""OS signal handling and graceful shutdown coordination.

Zone: startup/ — process lifecycle, no execution side-effects.
"""

from __future__ import annotations

import asyncio
import signal
import types

from loguru import logger

__all__ = ["install_signal_handlers", "create_shutdown_event"]


def create_shutdown_event() -> asyncio.Event:
    """Create the global shutdown event used across all engine tasks."""
    return asyncio.Event()


def install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    """Install SIGINT/SIGTERM handlers that set the shutdown event."""

    def _handler(signum: int, frame: types.FrameType | None) -> None:
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)
