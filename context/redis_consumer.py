"""RedisConsumer — subscribes to Redis pub/sub and loads candle history on startup.

Zones: analysis (context ingestion). No execution side-effects.

This module is responsible for:
1) Warmup load: read Redis Lists into LiveContextBus
2) Realtime: subscribe to pub/sub channels and push candle updates into LiveContextBus

It must provide an async `.run()` method because main.py calls it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, cast

import orjson

from context.live_context_bus import LiveContextBus

logger = logging.getLogger(__name__)

# Timeframes fetched during warmup (must align with writers of Redis Lists)
WARMUP_TIMEFRAMES: tuple[str, ...] = ("M15", "H1", "H4", "D1", "W1")

# Redis List key prefix for stored candle history
CANDLE_HISTORY_KEY_PREFIX = "candle_history"

# Default ordered list of prefixes that hold *List* data (safe for LRANGE warmup).
# NOTE: wolf15:candle:{sym}:{tf} is a Hash (HSET by RedisContextBridge)
#       — handled separately via HGETALL as a single-bar fallback.
#
# Override at runtime via env var (comma-separated, first-wins):
#   CANDLE_HISTORY_KEY_PREFIXES=wolf15:candle_history,candle_history
CANDLE_HISTORY_LIST_PREFIXES: list[str] = [
    "wolf15:candle_history",
    "candle_history",
]


def _get_candle_prefixes() -> list[str]:
    """Resolve candle List prefixes at call-time.

    Reading at call-time (not import-time) lets tests override
    ``CANDLE_HISTORY_KEY_PREFIXES`` without reloading the module.
    """
    env_val = os.environ.get("CANDLE_HISTORY_KEY_PREFIXES", "").strip()
    if env_val:
        return [p.strip() for p in env_val.split(",") if p.strip()]
    return list(CANDLE_HISTORY_LIST_PREFIXES)

# Hash key prefix for latest single candle (HSET by RedisContextBridge)
CANDLE_HASH_PREFIX: str = "wolf15:candle"

@dataclass(frozen=True)
class RedisConsumerConfig:
    """Runtime config for RedisConsumer.

    pubsub_patterns:
        Redis pattern subscriptions. We use psubscribe to allow per-symbol channels.
        If your publisher uses exact channels only, include them here and we will also
        subscribe via `subscribe()` as a fallback.
    """

    pubsub_patterns: tuple[str, ...] = (
        "candles:*",
        "candle:*",
        "candle_updates:*",
        "wolf15:candle:*",  # ← add this
    )
    pubsub_channels: tuple[str, ...] = ("candles", "candle_updates", "candle")


class RedisConsumer:
    """Consumes candle data from Redis (pub/sub + list history).

    On startup, call :meth:`load_candle_history` to populate
    :class:`LiveContextBus` from Redis Lists before subscribing to pub/sub.

    Expected candle message payload:
        JSON dict with at least:
            - symbol: str
            - timeframe: str
        Other fields are passed through.
    """

    def __init__(
        self,
        symbols: list[str],
        redis_client: Any,
        context_bus: LiveContextBus | None = None,
        *,
        config: RedisConsumerConfig | None = None,
    ) -> None:
        super().__init__()
        self._symbols = list(symbols)
        self._redis = redis_client
        self._bus = context_bus or LiveContextBus()
        self._config = config or RedisConsumerConfig()

        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Request the consumer to stop gracefully."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Startup warmup
    # ------------------------------------------------------------------

    async def load_candle_history(self) -> None:
        """Load candle history from Redis Lists into LiveContextBus.

        Tries every prefix in CANDLE_HISTORY_KEY_PREFIXES in order and uses the
        first one that returns data for each symbol × timeframe combination.
        Per-key errors are caught and logged.

        Calling this method more than once replaces (not appends) the stored candles.
        """
        for symbol in self._symbols:
            for timeframe in WARMUP_TIMEFRAMES:
                raw_entries = await self._warmup_candle_history(symbol, timeframe)
                if not raw_entries:
                    logger.info(
                        "RedisConsumer: no data for %s:%s (tried all prefixes)",
                        symbol,
                        timeframe,
                    )
                    continue

                # Derive a display key from the first successful prefix for logging
                key_display = f"<prefix>:{symbol}:{timeframe}"
                candles: list[dict[str, Any]] = []
                for raw in raw_entries:
                    try:
                        candle: Any = orjson.loads(raw)
                        if isinstance(candle, dict):
                            candles.append(cast(dict[str, Any], candle))
                        else:
                            logger.warning(
                                "RedisConsumer: non-dict candle in key %s — skipped",
                                key_display,
                            )
                    except Exception:
                        logger.warning(
                            "RedisConsumer: skipping malformed candle bytes in key %s",
                            key_display,
                        )

                self._bus.set_candle_history(symbol, timeframe, candles)
                logger.info(
                    "RedisConsumer: warmup loaded %d candles for %s:%s",
                    len(candles),
                    symbol,
                    timeframe,
                )

    async def _warmup_candle_history(self, symbol: str, timeframe: str) -> list[bytes]:
        """
        Load candle history from Redis, trying multiple sources.

        Priority:
          1. List keys (wolf15:candle_history, candle_history) — correct type for LRANGE
          2. Hash key (wolf15:candle) — single latest candle via HGETALL fallback

        Each call is wrapped in try/except so a WRONGTYPE error on one key
        does not prevent the remaining fallbacks from being tried.
        """
        # ── Priority 1: List keys (safe for LRANGE) ──
        for prefix in _get_candle_prefixes():
            key = f"{prefix}:{symbol}:{timeframe}"
            try:
                raw_entries: list[bytes] = await self._redis.lrange(key, 0, -1)
                if raw_entries:
                    logger.info(
                        "warmup_candle_history | symbol=%s tf=%s prefix_used=%s count=%d",
                        symbol,
                        timeframe,
                        prefix,
                        len(raw_entries),
                    )
                    return raw_entries
            except Exception as exc:
                # WRONGTYPE or connection error — log and try next prefix
                logger.warning(
                    "warmup_candle_history | lrange failed on %s: %s", key, exc
                )

        # ── Priority 2: Hash key (single latest candle) ──
        # wolf15:candle:{sym}:{tf} is written via HSET by RedisContextBridge.
        # It only holds the *latest* candle, but 1 bar > 0 bars.
        hash_key = f"{CANDLE_HASH_PREFIX}:{symbol}:{timeframe}"
        try:
            data: dict[str | bytes, str | bytes] = await self._redis.hgetall(hash_key)
            if data:
                # Hash stores {"data": "<json>"} — extract the JSON payload
                raw_json = data.get("data") or data.get(b"data")
                if raw_json:
                    if isinstance(raw_json, str):
                        raw_json = raw_json.encode("utf-8")
                    logger.info(
                        "warmup_candle_history | symbol=%s tf=%s source=hash_fallback count=1",
                        symbol,
                        timeframe,
                    )
                    return [raw_json]
        except Exception as exc:
            logger.warning(
                "warmup_candle_history | hgetall failed on %s: %s", hash_key, exc
            )

        logger.warning(
            "warmup_candle_history | symbol=%s tf=%s no_data_found "
            "tried list_prefixes=%s hash_key=%s",
            symbol,
            timeframe,
            _get_candle_prefixes(),
            hash_key,
        )
        return []

    # ------------------------------------------------------------------
    # Pub/Sub realtime consumption
    # ------------------------------------------------------------------

    async def _subscribe(self, pubsub: Any) -> None:
        """Subscribe to configured patterns/channels.

        Uses psubscribe for patterns and subscribe for plain channels (best effort).
        """
        # Pattern subscriptions (psubscribe)
        try:
            if self._config.pubsub_patterns:
                await pubsub.psubscribe(*self._config.pubsub_patterns)
                logger.info(
                    "RedisConsumer: psubscribed patterns=%s",
                    list(self._config.pubsub_patterns),
                )
        except Exception:
            logger.exception("RedisConsumer: psubscribe failed")

        # Plain channel subscriptions (subscribe)
        try:
            if self._config.pubsub_channels:
                await pubsub.subscribe(*self._config.pubsub_channels)
                logger.info(
                    "RedisConsumer: subscribed channels=%s",
                    list(self._config.pubsub_channels),
                )
        except Exception:
            logger.exception("RedisConsumer: subscribe failed")

    @staticmethod
    def _extract_payload(message: dict[str, Any]) -> bytes | None:
        """Extract message payload from redis-py pubsub message dict."""
        # redis-py typically yields:
        # {'type': 'message'|'pmessage', 'pattern': b'..'(optional), 'channel': b'..', 'data': b'...'}
        data = message.get("data")
        if data is None:
            return None
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        # Sometimes data can be str (depending on decode_responses)
        if isinstance(data, str):
            return data.encode("utf-8")
        return None

    def _handle_candle_dict(self, candle: dict[str, Any]) -> None:
        """Validate and push a candle update into the context bus."""
        symbol = candle.get("symbol")
        timeframe = candle.get("timeframe")

        if not isinstance(symbol, str) or not symbol.strip():
            return
        if not isinstance(timeframe, str) or not timeframe.strip():
            return

        # Ensure canonical symbol/timeframe in the candle dict
        candle["symbol"] = symbol.strip()
        candle["timeframe"] = timeframe.strip()

        # Push as live candle update (push_candle expects a single candle dict)
        self._bus.push_candle(candle)

    async def _consume_pubsub(self) -> None:
        """Consume pub/sub messages forever (until stop_event)."""
        pubsub = self._redis.pubsub()
        try:
            await self._subscribe(pubsub)

            # Main loop
            while not self._stop_event.is_set():
                try:
                    message: dict[str, Any] | None = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                except TypeError:
                    # Some redis clients use sync-style get_message without await.
                    message = pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                if not message:
                    await asyncio.sleep(0.05)
                    continue

                payload = self._extract_payload(message)
                if not payload:
                    continue

                try:
                    decoded = orjson.loads(payload)
                except Exception:
                    logger.debug("RedisConsumer: non-JSON pubsub payload ignored")
                    continue

                if isinstance(decoded, dict):
                    self._handle_candle_dict(cast(dict[str, Any], decoded))
                elif isinstance(decoded, list):
                    # Some publishers might batch candles
                    for item in cast(list[Any], decoded):
                        if isinstance(item, dict):
                            typed_item: dict[str, Any] = {str(k): v for k, v in cast(dict[str, Any], item).items()}
                            self._handle_candle_dict(typed_item)

        finally:
            try:
                await pubsub.close()
            except Exception:
                # don't crash shutdown
                logger.debug("RedisConsumer: pubsub close failed", exc_info=True)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entrypoint expected by main.py.

        Steps:
        1) Warmup: load candle history from Redis Lists
        2) Realtime: start pubsub consumer (best-effort)
        3) Block forever until stop requested (or task cancelled)
        """
        logger.info("RedisConsumer: starting (symbols=%d)", len(self._symbols))

        # Warmup is critical for pipeline readiness
        await self.load_candle_history()

        # Realtime consumer is best-effort; do not crash if pubsub fails
        try:
            await self._consume_pubsub()
        except asyncio.CancelledError:
            logger.info("RedisConsumer: cancelled")
            raise
        except Exception:
            logger.exception("RedisConsumer: pubsub loop crashed; continuing idle")
            # Idle loop to keep task alive (mirrors main.py behavior)
            while not self._stop_event.is_set():
                await asyncio.sleep(1.0)
