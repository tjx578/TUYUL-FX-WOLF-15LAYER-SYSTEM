"""RedisConsumer — subscribes to Redis pub/sub and loads candle history on startup.

Zones: analysis (context ingestion). No execution side-effects.
"""

from __future__ import annotations

import logging
from typing import Any

import orjson

from context.live_context_bus import LiveContextBus

logger = logging.getLogger(__name__)

# Timeframes fetched during warmup
WARMUP_TIMEFRAMES: tuple[str, ...] = ("M15", "H1", "H4", "D1", "W1")

# Redis List key prefix for stored candle history
CANDLE_HISTORY_KEY_PREFIX = "candle_history"


class RedisConsumer:
    """Consumes candle data from Redis (pub/sub + list history).

    On startup, call :meth:`load_candle_history` to populate
    :class:`LiveContextBus` from Redis Lists *before* subscribing to
    pub/sub, so the warmup gate sees a non-zero bar count even if
    pub/sub messages were already sent before this consumer subscribed.
    """

    def __init__(
        self,
        symbols: list[str],
        redis_client: Any,
        context_bus: LiveContextBus | None = None,
    ) -> None:
        super().__init__()
        self._symbols = symbols
        self._redis = redis_client
        self._bus = context_bus or LiveContextBus()

    # ------------------------------------------------------------------
    # Startup warmup
    # ------------------------------------------------------------------

    async def load_candle_history(self) -> None:
        """Load candle history from Redis Lists into LiveContextBus.

        Fetches ``candle_history:{symbol}:{timeframe}`` list keys for
        every symbol × timeframe combination.  Per-key errors are caught
        and logged so that a single failing key does not abort the others.

        Calling this method more than once replaces (not appends) the
        stored candles, ensuring idempotency.
        """
        for symbol in self._symbols:
            for timeframe in WARMUP_TIMEFRAMES:
                key = f"{CANDLE_HISTORY_KEY_PREFIX}:{symbol}:{timeframe}"
                try:
                    raw_entries: list[bytes] = await self._redis.lrange(key, 0, -1)
                except Exception:
                    logger.exception(
                        "RedisConsumer: failed to fetch candle history for %s — skipping",
                        key,
                    )
                    continue

                candles: list[dict[str, Any]] = []
                for raw in raw_entries:
                    try:
                        candles.append(orjson.loads(raw))
                    except Exception:
                        logger.warning(
                            "RedisConsumer: skipping malformed candle bytes in key %s",
                            key,
                        )

                # Replace (not append) so repeated calls stay idempotent
                self._bus.set_candle_history(symbol, timeframe, candles)
                logger.debug(
                    "RedisConsumer: loaded %d candles for %s:%s",
                    len(candles),
                    symbol,
                    timeframe,
                )
