"""
DEPRECATED — This file is a design blueprint only.

The runtime tick processing path is:
  ingest/dependencies.py :: _build_tick_handler()
    → LiveContextBus.update_tick()
    → RedisContextBridge.write_tick()

This module is preserved for reference. Do NOT import in production code.
See: docs/REDIS_DEPLOYMENT.md for the authoritative data flow.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "analysis.tick_stream is a deprecated blueprint. "
    "Runtime tick handling lives in ingest.dependencies._build_tick_handler(). "
    "Do not import this module in production.",
    DeprecationWarning,
    stacklevel=2,
)


# ── Original blueprint (preserved for reference, non-functional) ──

# from analysis.candle_builder import process_tick_for_candle, update_vwap
# from infrastructure.stream_consumer import ConsumerConfig, StreamBinding, StreamConsumer
#
# async def publish_tick(symbol: str, tick_data: dict):
#     """Blueprint: tick ingestion via Redis Streams."""
#     ...
#
# candle_consumer = StreamConsumer(...)
# vwap_consumer = StreamConsumer(...)
