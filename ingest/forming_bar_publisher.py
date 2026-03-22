"""Dual-zone forming bar publisher — M15 at 500ms, H1 at 1s.

Zone: ingest/ — data pipeline, no analysis side-effects.

Writes forming (in-progress) candle bars to Redis HASH keys so the API
service (HybridCandleAggregator) can display them on the dashboard without
computing any market direction.

Key pattern:  wolf15:candle:forming:{SYM}:{TF}  (HASH, TTL=120s)
Channel:      candle:forming:{SYM}:{TF}          (PubSub)

Feature flag
------------
Set  USE_REDIS_FORMING=false  to disable all Redis writes instantly
(e.g. during a rollback) without redeploying.  Default: true.

Pydantic v2 notes
-----------------
FormingBarSchema uses ``@model_validator(mode="after")`` for the
high ≥ low cross-field check.  Using ``@field_validator("high")``
with ``info.data["low"]`` is unreliable in Pydantic v2 because
field validators run in declaration order — ``low`` may not be
validated yet when ``high`` is checked.
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import orjson
from loguru import logger
from pydantic import BaseModel, field_validator, model_validator

from core.redis_keys import candle_forming, channel_candle_forming
from ingest.candle_builder import CandleBuilder

# ── Feature flag ─────────────────────────────────────────────────────────────
_USE_REDIS_FORMING = os.getenv("USE_REDIS_FORMING", "true").strip().lower() not in ("false", "0", "no")

# ── Constants ─────────────────────────────────────────────────────────────────
KEY_TTL_SEC = 120  # 120s TTL — 120x safety margin over 1s publish interval


# ══════════════════════════════════════════════════════════════════════════════
#  Schema validation
# ══════════════════════════════════════════════════════════════════════════════


class FormingBarSchema(BaseModel):
    """Validate a forming bar payload before writing to Redis.

    All price fields are required; ``stale`` and ``ts_written`` are optional
    (added by the publisher after validation).
    """

    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    ts_open: float
    ts_close: float

    @field_validator("open", "high", "low", "close")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"price must be > 0, got {v}")
        return v

    @model_validator(mode="after")
    def high_gte_low(self) -> FormingBarSchema:
        """Cross-field validation: high must be ≥ low."""
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) must be >= low ({self.low})")
        return self


# ══════════════════════════════════════════════════════════════════════════════
#  Per-timeframe configuration
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class _TFConfig:
    """Configuration for a single timeframe's publish loop."""

    timeframe: str
    interval_sec: float
    builders: dict[str, CandleBuilder] = field(default_factory=dict)
    publish_count: int = 0
    error_count: int = 0
    last_publish_ts: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  FormingBarPublisher
# ══════════════════════════════════════════════════════════════════════════════


class FormingBarPublisher:
    """Publishes forming (in-progress) candle bars to Redis HASH keys.

    Dual-zone:
      • Zone A — M15 forming bars, published every 500ms
      • Zone B — H1 forming bars, published every 1s

    Designed to run as a supervised async task via ``_FormingPubRunner``
    in ``ingest_service.py``.

    Usage::

        pub = FormingBarPublisher(redis)
        pub.register_builder("EURUSD", "M15", m15_builder)
        pub.register_builder("EURUSD", "H1", h1_builder)

        await pub.start()   # launches background tasks
        # …
        await pub.stop()    # cancels tasks and cleans up keys
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._configs: dict[str, _TFConfig] = {
            "M15": _TFConfig(timeframe="M15", interval_sec=0.5),
            "H1": _TFConfig(timeframe="H1", interval_sec=1.0),
        }
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_builder(self, symbol: str, timeframe: str, builder: CandleBuilder) -> None:
        """Register a CandleBuilder for the given symbol and timeframe.

        Must be called before ``start()``.
        """
        tf_upper = timeframe.upper()
        if tf_upper not in self._configs:
            logger.warning(
                "[FormingBarPublisher] Unknown timeframe %s for %s — ignored",
                timeframe,
                symbol,
            )
            return
        self._configs[tf_upper].builders[symbol] = builder

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch background publish loops for each configured timeframe."""
        if not _USE_REDIS_FORMING:
            logger.info("[FormingBarPublisher] USE_REDIS_FORMING=false — skipping start")
            return

        self._running = True
        for tf_cfg in self._configs.values():
            if not tf_cfg.builders:
                logger.debug(
                    "[FormingBarPublisher] No builders registered for %s — skipping",
                    tf_cfg.timeframe,
                )
                continue
            task = asyncio.create_task(
                self._publish_loop(tf_cfg),
                name=f"forming_pub_{tf_cfg.timeframe}",
            )
            self._tasks.append(task)

        logger.info(
            "[FormingBarPublisher] Started %d publish loops",
            len(self._tasks),
        )

    async def stop(self) -> None:
        """Cancel all publish loops and clean up forming keys from Redis."""
        if not self._running:
            return  # idempotent
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

        if _USE_REDIS_FORMING:
            await self._cleanup_keys()

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return publish counts and error counts per timeframe."""
        return {
            "enabled": _USE_REDIS_FORMING,
            "running": self._running,
            "timeframes": {
                tf: {
                    "symbols": list(cfg.builders.keys()),
                    "publish_count": cfg.publish_count,
                    "error_count": cfg.error_count,
                    "last_publish_ts": cfg.last_publish_ts,
                }
                for tf, cfg in self._configs.items()
            },
        }

    # ------------------------------------------------------------------
    # Internal publish loop
    # ------------------------------------------------------------------

    async def _publish_loop(self, tf_cfg: _TFConfig) -> None:
        """Publish all builders for one timeframe at the configured interval."""
        while self._running:
            start = asyncio.get_event_loop().time()
            await self._publish_all(tf_cfg)
            elapsed = asyncio.get_event_loop().time() - start
            sleep_sec = max(0.0, tf_cfg.interval_sec - elapsed)
            await asyncio.sleep(sleep_sec)

    async def _publish_all(self, tf_cfg: _TFConfig) -> None:
        """Publish forming bars for all registered symbols in one timeframe."""
        for symbol, builder in tf_cfg.builders.items():
            partial = builder.current_partial
            if partial is None:
                continue

            # Build and validate payload
            raw_payload: dict[str, Any] = {
                "symbol": partial.symbol,
                "timeframe": partial.timeframe,
                "open": partial.open,
                "high": partial.high,
                "low": partial.low,
                "close": partial.close,
                "volume": partial.volume,
                "tick_count": partial.tick_count,
                "ts_open": partial.open_time.timestamp(),
                "ts_close": partial.close_time.timestamp(),
            }

            try:
                FormingBarSchema(**raw_payload)
            except Exception as exc:
                tf_cfg.error_count += 1
                logger.warning(
                    "[FormingBarPublisher] Schema validation failed %s %s: %s",
                    symbol,
                    tf_cfg.timeframe,
                    exc,
                )
                continue

            # Serialize for Redis (all values must be strings for HSET)
            payload: dict[str, str] = {k: str(v) for k, v in raw_payload.items()}
            payload["ts_written"] = str(time.time())

            key = candle_forming(symbol, tf_cfg.timeframe)
            channel = channel_candle_forming(symbol, tf_cfg.timeframe)

            try:
                pipe = self._redis.pipeline()
                pipe.hset(key, mapping=payload)
                pipe.expire(key, KEY_TTL_SEC)
                pipe.publish(channel, orjson.dumps(raw_payload).decode())
                await pipe.execute()

                tf_cfg.publish_count += 1
                tf_cfg.last_publish_ts = time.time()
            except Exception as exc:
                tf_cfg.error_count += 1
                logger.warning(
                    "[FormingBarPublisher] Redis write failed %s %s: %s",
                    symbol,
                    tf_cfg.timeframe,
                    exc,
                )

    async def _cleanup_keys(self) -> None:
        """Delete all forming keys from Redis on shutdown."""
        for tf_cfg in self._configs.values():
            for symbol in tf_cfg.builders:
                key = candle_forming(symbol, tf_cfg.timeframe)
                with suppress(Exception):
                    await self._redis.delete(key)
