"""
DEPRECATED — This module is dead code. Do NOT import.

The runtime tick processing path is:
  ingest/dependencies.py :: _build_tick_handler()
    → LiveContextBus.update_tick()
    → RedisContextBridge.write_tick()

See: docs/REDIS_DEPLOYMENT.md for the authoritative data flow.

This file is retained solely as a historical reference.
It will be removed in a future release.
"""

from __future__ import annotations

import os
import warnings

__all__: list[str] = []  # Nothing is public.

_ALLOW_DEPRECATED = os.getenv("ALLOW_DEPRECATED_TICK_STREAM", "").lower() in ("1", "true")

if not _ALLOW_DEPRECATED:
    raise ImportError(
        "analysis.tick_stream is deprecated and must not be imported. "
        "The runtime tick path is ingest.dependencies._build_tick_handler(). "
        "Set ALLOW_DEPRECATED_TICK_STREAM=1 to suppress this guard (tests only)."
    )

warnings.warn(
    "analysis.tick_stream is a deprecated blueprint. "
    "Runtime tick handling lives in ingest.dependencies._build_tick_handler(). "
    "Do not import this module in production.",
    DeprecationWarning,
    stacklevel=2,
)


# ── Original blueprint (preserved for reference, non-functional) ──
#
# from analysis.candle_builder import process_tick_for_candle, update_vwap
# from infrastructure.stream_consumer import ConsumerConfig, StreamBinding, StreamConsumer
#
# async def publish_tick(symbol: str, tick_data: dict):
#     """Blueprint: tick ingestion via Redis Streams."""
#     ...
#
# candle_consumer = StreamConsumer(...)
# vwap_consumer = StreamConsumer(...)
