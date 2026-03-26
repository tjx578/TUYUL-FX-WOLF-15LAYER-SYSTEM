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
import time
from dataclasses import dataclass
from typing import Any, cast

import orjson

from context.live_context_bus import LiveContextBus
from core.redis_consumer_fix import get_bars_fixed, sanitize_redis_keys
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

# Redis key types that are incompatible with LRANGE.
# If a candle_history key has one of these types it was written by the wrong
# code path (e.g., HSET instead of RPUSH) and lrange would raise WRONGTYPE.
_INCOMPATIBLE_REDIS_TYPES: frozenset[str] = frozenset({"hash", "string", "set", "zset", "stream"})

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
        self._warmup_max_concurrency = self._read_int_env("REDIS_WARMUP_MAX_CONCURRENCY", default=8)
        self._warmup_semaphore = asyncio.Semaphore(self._warmup_max_concurrency)
        self._warmup_error_log_interval_sec = self._read_float_env("REDIS_WARMUP_ERROR_LOG_INTERVAL_SEC", default=60.0)
        self._warmup_error_log_state: dict[str, float] = {}
        logger.info(
            "RedisConsumer startup config | warmup_max_concurrency=%d warmup_error_log_interval_sec=%.1f",
            self._warmup_max_concurrency,
            self._warmup_error_log_interval_sec,
        )

    @staticmethod
    def _read_int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if raw is None:
            return default
        with contextlib.suppress(ValueError, TypeError):
            return max(1, int(raw))
        return default

    @staticmethod
    def _read_float_env(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        with contextlib.suppress(ValueError, TypeError):
            return max(1.0, float(raw))
        return default

    def _should_log_warmup_error(self, error_key: str) -> bool:
        now_ts = time.time()
        last_ts = self._warmup_error_log_state.get(error_key, 0.0)
        if (now_ts - last_ts) >= self._warmup_error_log_interval_sec:
            self._warmup_error_log_state[error_key] = now_ts
            return True
        return False

    async def _warmup_candle_history_limited(self, symbol: str, timeframe: str) -> list[bytes]:
        async with self._warmup_semaphore:
            return await self._warmup_candle_history(symbol, timeframe)

    def stop(self) -> None:
        """Request the consumer to stop gracefully."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Type-aware bar reader (delegates to core.redis_consumer_fix)
    # ------------------------------------------------------------------

    async def get_bars(self, symbol: str, timeframe: str, required: int = 5) -> list[dict[str, Any]]:
        """Return recent candle bars, checking key TYPE before access."""
        return await get_bars_fixed(self._redis, symbol, timeframe, required)

    # ------------------------------------------------------------------
    # Startup warmup
    # ------------------------------------------------------------------

    async def load_candle_history(self) -> None:
        """Load candle history from Redis Lists into LiveContextBus.

        Tries every prefix in CANDLE_HISTORY_KEY_PREFIXES in order and uses the
        first one that returns data for each symbol × timeframe combination.
        Per-key errors are caught and logged.

        All symbol × timeframe pairs are fetched concurrently via
        ``asyncio.gather``, reducing startup latency from O(S × T) sequential
        round trips to O(1) parallel round trips.

        Calling this method more than once replaces (not appends) the stored candles.
        """
        has_seed = await self._has_any_candle_seed()
        if not has_seed:
            if not self._logged_empty_seed:
                logger.warning("RedisConsumer: warmup skipped — no candle keys in Redis yet (waiting for ingest seed)")
                self._logged_empty_seed = True
            else:
                logger.debug("RedisConsumer: warmup still waiting for first Redis candle seed")
            return

        if self._logged_empty_seed:
            logger.info("RedisConsumer: Redis candle seed detected — loading warmup history")
            self._logged_empty_seed = False

        # ── Fetch all symbol × timeframe pairs concurrently ──────────────────
        # Sequential nested loops made S × T round trips; gather reduces that
        # to a single parallel batch (_warmup_candle_history handles its own
        # exceptions and always returns a list, never raises).
        pairs = [(symbol, timeframe) for symbol in self._symbols for timeframe in WARMUP_TIMEFRAMES]
        all_raw: list[list[bytes]] = await asyncio.gather(
            *[self._warmup_candle_history_limited(sym, tf) for sym, tf in pairs]
        )

        for (symbol, timeframe), raw_entries in zip(pairs, all_raw, strict=True):
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
        Load candle history from Redis, using only LIST keys for lrange.
        Fallback to HASH key for single latest candle if no history exists.
        """
        # --- Strategy 1: LIST keys via LRANGE (correct type) ---
        for prefix in _get_candle_prefixes():
            key = f"{prefix}:{symbol}:{timeframe}"
            try:
                # Check key type before issuing lrange to avoid WRONGTYPE errors.
                # wolf15:candle:{sym}:{tf} is a HASH written by RedisContextBridge;
                # blindly calling lrange on it triggers WRONGTYPE → silent 0-bar warmup.
                # Only skip when we receive a concrete wrong-type response from Redis;
                # an unrecognised response (e.g., test mock) falls through to lrange.
                raw_type: bytes | str = await self._redis.type(key)
                key_type = (
                    raw_type.decode().lower() if isinstance(raw_type, bytes | bytearray) else str(raw_type).lower()
                )
                if key_type == "none":
                    continue  # key does not exist, try next prefix
                if key_type in _INCOMPATIBLE_REDIS_TYPES:
                    logger.warning(
                        "warmup_candle_history | %s is '%s' (expected list) — skipping; run sanitize_redis_keys to clean",
                        key,
                        key_type,
                    )
                    continue
                raw = await self._redis.lrange(key, 0, -1)
                if raw:
                    logger.info(
                        "warmup_candle_history | symbol=%s tf=%s prefix_used=%s count=%d",
                        symbol,
                        timeframe,
                        prefix,
                        len(raw),
                    )
                    return raw
            except Exception as exc:
                err_text = str(exc).lower()
                if "too many connections" in err_text:
                    err_key = "warmup:lrange:too_many_connections"
                else:
                    err_key = f"warmup:lrange:{type(exc).__name__}"
                if self._should_log_warmup_error(err_key):
                    logger.warning("warmup_candle_history | lrange failed on %s: %s", key, exc)
                else:
                    logger.debug("warmup_candle_history | lrange failed on %s: %s", key, exc)
                continue

        # --- Strategy 2: HASH key via HGETALL (single latest candle) ---
        # The HASH stores the full candle JSON in the "data" field (written by
        # RedisContextBridge.write_candle / context/redis_context_bridge.py).
        hash_key = f"wolf15:candle:{symbol}:{timeframe}"
        try:
            data = await self._redis.hgetall(hash_key)
            if data:
                # Decode bytes keys/values
                decoded: dict[str, str] = {}
                for k, v in data.items():
                    k_str = k.decode() if isinstance(k, bytes) else str(k)
                    v_str = v.decode() if isinstance(v, bytes) else str(v)
                    decoded[k_str] = v_str

                # Primary: parse the "data" field as JSON (RedisContextBridge format)
                if "data" in decoded:
                    try:
                        candle = orjson.loads(decoded["data"])
                        if isinstance(candle, dict):
                            logger.info(
                                "warmup_candle_history | symbol=%s tf=%s fallback: 1 bar from HASH %s (data field)",
                                symbol,
                                timeframe,
                                hash_key,
                            )
                            return [orjson.dumps(candle)]
                    except Exception as data_exc:
                        logger.warning(
                            "warmup_candle_history | HASH %s 'data' field invalid JSON: %s",
                            hash_key,
                            data_exc,
                        )

                # Secondary: treat all hash fields as a flat key-value candle dict
                bar: dict[str, Any] = {}
                for k_str, v_str in decoded.items():
                    try:
                        bar[k_str] = float(v_str)
                    except (ValueError, TypeError):
                        bar[k_str] = v_str
                if bar:
                    logger.info(
                        "warmup_candle_history | symbol=%s tf=%s fallback: 1 bar from HASH %s",
                        symbol,
                        timeframe,
                        hash_key,
                    )
                    return [orjson.dumps(bar)]
        except Exception as exc:
            err_text = str(exc).lower()
            if "too many connections" in err_text:
                err_key = "warmup:hgetall:too_many_connections"
            else:
                err_key = f"warmup:hgetall:{type(exc).__name__}"
            if self._should_log_warmup_error(err_key):
                logger.warning("warmup_candle_history | hgetall failed on %s: %s", hash_key, exc)
            else:
                logger.debug("warmup_candle_history | hgetall failed on %s: %s", hash_key, exc)

        logger.debug(
            "warmup_candle_history | symbol=%s tf=%s: no candle data found in Redis",
            symbol,
            timeframe,
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
        0) Sanitise: delete keys with wrong Redis type (defence-in-depth)
        1) Warmup: load candle history from Redis Lists
        2) Realtime: start pubsub consumer (best-effort)
        3) Block forever until stop requested (or task cancelled)
        """
        logger.info("RedisConsumer: starting (symbols=%d)", len(self._symbols))

        # Sanitise keys BEFORE warmup so LRANGE never hits a HASH
        try:
            await sanitize_redis_keys(self._redis)
        except Exception as exc:
            logger.warning("RedisConsumer: key sanitise failed (non-fatal): %s", exc)

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
