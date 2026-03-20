"""RedisConsumer — subscribes to Redis pub/sub and loads candle history on startup.

Zones: analysis (context ingestion). No execution side-effects.

This module is responsible for:
1) Warmup load: read Redis Lists into LiveContextBus
2) Realtime: subscribe to pub/sub channels and push candle updates into LiveContextBus

It must provide an async `.run()` method because main.py calls it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from typing import Any, cast

import orjson

from context.live_context_bus import LiveContextBus
from core.redis_keys import (
    CANDLE_HASH_PREFIX as CANDLE_HASH_PREFIX_KEY,
)
from core.redis_keys import (
    CANDLE_HASH_SCAN,
    CANDLE_HISTORY_PREFIX,
    CANDLE_HISTORY_SCAN,
)

logger = logging.getLogger(__name__)

# Timeframes fetched during warmup (must align with writers of Redis Lists)
WARMUP_TIMEFRAMES: tuple[str, ...] = ("M15", "H1", "H4", "D1", "W1", "MN")

# Redis List key prefix for stored candle history
CANDLE_HISTORY_KEY_PREFIX = "candle_history"

# Default ordered list of prefixes that hold *List* data (safe for LRANGE warmup).
# NOTE: wolf15:candle:{sym}:{tf} is a Hash (HSET by RedisContextBridge)
#       — handled separately via HGETALL as a single-bar fallback.
#
# Override at runtime via env var (comma-separated, first-wins):
#   CANDLE_HISTORY_KEY_PREFIXES=wolf15:candle_history,candle_history
CANDLE_HISTORY_LIST_PREFIXES: list[str] = [
    CANDLE_HISTORY_PREFIX,  # noqa: F821
    "candle_history",
]


def get_candle_prefixes() -> list[str]:
    """Resolve candle List prefixes at call-time.

    Reading at call-time (not import-time) lets tests override
    ``CANDLE_HISTORY_KEY_PREFIXES`` without reloading the module.
    Falls back to module defaults when the env var is absent, empty, or
    contains only whitespace/commas.
    """
    env_val = os.environ.get("CANDLE_HISTORY_KEY_PREFIXES", "").strip()
    if env_val:
        parsed = [p.strip() for p in env_val.split(",") if p.strip()]
        if parsed:
            return parsed
    return list(CANDLE_HISTORY_LIST_PREFIXES)


# Private alias kept for backward-compat with internal callers
_get_candle_prefixes = get_candle_prefixes

# Hash key prefix for latest single candle (HSET by RedisContextBridge)
CANDLE_HASH_PREFIX: str = CANDLE_HASH_PREFIX_KEY  # noqa: F821


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
        CANDLE_HASH_SCAN,  # wolf15:candle:*  # noqa: F821
    )
    pubsub_channels: tuple[str, ...] = ("candles", "candle_updates", "candle", "tick_updates")


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
        context_bus: LiveContextBus | None = None,  # noqa: F821
        *,
        config: RedisConsumerConfig | None = None,
    ) -> None:
        super().__init__()
        self._symbols = list(symbols)
        self._redis = redis_client
        self._bus = context_bus or LiveContextBus()  # noqa: F821
        self._config = config or RedisConsumerConfig()

        self._stop_event = asyncio.Event()
        self._logged_empty_seed = False

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
        has_seed = await self._has_any_candle_seed()
        if not has_seed:
            if not self._logged_empty_seed:
                logger.warning(
                    "RedisConsumer: warmup skipped — no candle keys in Redis yet " "(waiting for ingest seed)"
                )
                self._logged_empty_seed = True
            else:
                logger.debug("RedisConsumer: warmup still waiting for first Redis candle seed")
            return

        if self._logged_empty_seed:
            logger.info("RedisConsumer: Redis candle seed detected — loading warmup history")
            self._logged_empty_seed = False

        for symbol in self._symbols:
            for timeframe in WARMUP_TIMEFRAMES:
                raw_entries = await self._warmup_candle_history(symbol, timeframe)
                if not raw_entries:
                    if timeframe != "M15":
                        logger.debug(
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

    async def load_candle_history_with_retry(
        self,
        max_retries: int = 10,
        base_delay: float = 3.0,
    ) -> bool:
        """Retry warmup until candle seed appears in Redis.

        Uses exponential backoff (capped at base_delay * 16) to wait for
        the ingest service to seed candle data, preventing the engine from
        starting in a permanently empty state.

        Returns ``True`` if warmup loaded data for at least one symbol, ``False``
        if all retries were exhausted.
        """
        for attempt in range(max_retries):
            await self.load_candle_history()

            for symbol in self._symbols:
                for tf in WARMUP_TIMEFRAMES:
                    candles = self._bus.get_candles(symbol, tf)
                    if candles:
                        logger.info(
                            "Warmup succeeded on attempt %d/%d (%s:%s has %d candles)",
                            attempt + 1,
                            max_retries,
                            symbol,
                            tf,
                            len(candles),
                        )
                        return True

            delay = base_delay * (2 ** min(attempt, 4))
            logger.warning(
                "Warmup attempt %d/%d failed — retrying in %.1fs",
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)

        logger.error(
            "Warmup FAILED after %d attempts — engine starting degraded",
            max_retries,
        )
        return False

    async def _has_any_candle_seed(self) -> bool:
        """Fast probe to avoid O(symbol*timeframe) warmup scans when Redis is empty."""
        patterns = (
            CANDLE_HISTORY_SCAN,  # noqa: F821
            "candle_history:*",
            CANDLE_HASH_SCAN,  # noqa: F821
        )

        for pattern in patterns:
            try:
                cursor, keys = await self._redis.scan(0, match=pattern, count=1)
                if keys:
                    return True
                if cursor and cursor != 0:
                    # Continue scanning only when Redis indicates more keys.
                    next_cursor = cursor
                    while next_cursor:
                        next_cursor, keys = await self._redis.scan(next_cursor, match=pattern, count=50)
                        if keys:
                            return True
            except Exception:
                # If scan is unsupported (e.g. in some tests/mocks), proceed with regular warmup path.
                return True

        return False

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
                logger.warning("warmup_candle_history | lrange failed on %s: %s", key, exc)

        # ── Priority 2: Hash key (single latest candle) ──
        # wolf15:candle:{sym}:{tf} is written via HSET by RedisContextBridge.
        # It only holds the *latest* candle, but 1 bar > 0 bars.
        hash_key = f"{CANDLE_HASH_PREFIX}:{symbol}:{timeframe}"
        try:
            data: dict[str | bytes, str | bytes] = await self._redis.hgetall(hash_key)
            if data:
                # Hash stores {"data": "<json>", "last_seen_ts": "<epoch>"}
                raw_json = data.get("data") or data.get(b"data")
                if raw_json:
                    if isinstance(raw_json, str):
                        raw_json = raw_json.encode("utf-8")
                    # Inject last_seen_ts into candle payload so warmup
                    # data carries freshness metadata (P0-3).
                    last_seen = data.get("last_seen_ts") or data.get(b"last_seen_ts")
                    if last_seen:
                        try:
                            candle_dict = orjson.loads(raw_json)
                            ts_str = last_seen if isinstance(last_seen, str) else last_seen.decode("utf-8")
                            candle_dict["last_seen_ts"] = float(ts_str)
                            raw_json = orjson.dumps(candle_dict)
                        except Exception:
                            pass  # original payload is still valid without enrichment
                    logger.info(
                        "warmup_candle_history | symbol=%s tf=%s source=hash_fallback count=1",
                        symbol,
                        timeframe,
                    )
                    return [raw_json]
        except Exception as exc:
            logger.warning("warmup_candle_history | hgetall failed on %s: %s", hash_key, exc)

        # Missing data is expected during startup races (engine before ingest).
        # Keep this as debug to avoid noisy false alarms in platform logs.
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
        if isinstance(data, bytes | bytearray):
            return bytes(data)
        # Sometimes data can be str (depending on decode_responses)
        if isinstance(data, str):
            return data.encode("utf-8")
        return None

    @staticmethod
    def _extract_channel(message: dict[str, Any]) -> str | None:
        """Extract channel name from redis pubsub message dict."""
        channel = message.get("channel")
        if channel is None:
            return None
        if isinstance(channel, bytes | bytearray):
            with contextlib.suppress(Exception):
                return bytes(channel).decode("utf-8", errors="ignore")
            return None
        if isinstance(channel, str):
            return channel
        return None

    def _handle_candle_dict(self, candle: dict[str, Any]) -> None:
        """Validate and push a candle update into the context bus.

        Also updates feed-timestamp tracking and emits a ``CANDLE_CLOSED``
        event so the analysis loop wakes immediately instead of waiting
        for its 60-second timer fallback.
        """
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

        # Update feed-timestamp so is_feed_stale() works in redis mode.
        self._bus.record_feed_update(symbol.strip())

        # Emit CANDLE_CLOSED so analysis_loop wakes immediately.
        self._emit_candle_closed(symbol.strip(), timeframe.strip())

    def _handle_tick_dict(self, tick: dict[str, Any]) -> None:
        """Refresh feed freshness from tick pub/sub updates.

        In redis mode the ingest service publishes ``tick_updates`` frequently,
        while candles close only on timeframe boundaries (e.g., M15). Recording
        feed updates from ticks prevents false hard-stale/no-producer holds.
        """
        symbol = tick.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return
        self._bus.record_feed_update(symbol.strip())

    def _emit_candle_closed(self, symbol: str, timeframe: str) -> None:
        """Fire CANDLE_CLOSED event on the in-process EventBus.

        Source is ``"ingest"`` because RedisConsumer is the engine-side
        proxy for the ingest service (authority boundary preserved).
        """
        try:
            from core.event_bus import Event, EventType, get_event_bus  # noqa: PLC0415

            bus = get_event_bus()
            event = Event(
                type=EventType.CANDLE_CLOSED,
                source="ingest",
                data={"symbol": symbol, "timeframe": timeframe},
            )
            # EventBus.emit is async; schedule it on the running loop.
            asyncio.ensure_future(bus.emit(event))
        except Exception:
            # Best-effort — don't crash the pub/sub consumer
            logger.debug("RedisConsumer: failed to emit CANDLE_CLOSED for %s", symbol, exc_info=True)

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

                channel = self._extract_channel(message) or ""

                payload = self._extract_payload(message)
                if not payload:
                    continue

                try:
                    decoded = orjson.loads(payload)
                except Exception:
                    logger.debug("RedisConsumer: non-JSON pubsub payload ignored")
                    continue

                if isinstance(decoded, dict):
                    if channel == "tick_updates":
                        self._handle_tick_dict(cast(dict[str, Any], decoded))
                    else:
                        self._handle_candle_dict(cast(dict[str, Any], decoded))
                elif isinstance(decoded, list):
                    # Some publishers might batch payloads.
                    for item in cast(list[Any], decoded):
                        if isinstance(item, dict):
                            typed_item: dict[str, Any] = {str(k): v for k, v in cast(dict[str, Any], item).items()}
                            if channel == "tick_updates":
                                self._handle_tick_dict(typed_item)
                            else:
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
