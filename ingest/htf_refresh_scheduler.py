"""
Higher-Timeframe (D1/W1) periodic refresh scheduler.

D1 and W1 candles are seeded once at startup but never refreshed.
This scheduler fetches fresh D1 & W1 bars periodically so the
data-quality gate in the engine does not flag them as stale.

Follows the same pattern as H1RefreshScheduler.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import orjson
from loguru import logger

from config_loader import get_enabled_symbols, load_finnhub
from context.live_context_bus import LiveContextBus
from context.system_state import SystemStateManager
from core.redis_keys import candle_history, channel_candle, latest_candle
from ingest.finnhub_candles import FinnhubCandleFetcher
from storage.candle_persistence import enqueue_candle_dict


class HTFRefreshScheduler:
    """
    Periodic D1/W1 refresh scheduler.

    Runs every *interval_sec* (default 4 h) to:
    - Fetch latest D1 bars for all enabled symbols.
    - Fetch latest W1 bars for all enabled symbols.
    - RPUSH + PUBLISH to Redis so the engine container picks up the
      update via RedisConsumer pub/sub.
    """

    def __init__(self, redis_client: Any = None) -> None:
        config = load_finnhub()
        refresh_cfg = config.get("candles", {}).get("refresh", {})

        self.interval_sec: int = refresh_cfg.get("htf_interval_sec", 14400)  # 4 hours
        self.d1_bars: int = refresh_cfg.get("d1_bars", 10)
        self.w1_bars: int = refresh_cfg.get("w1_bars", 8)

        self.fetcher = FinnhubCandleFetcher()
        self.context_bus = LiveContextBus()
        self.system_state = SystemStateManager()
        self._redis = redis_client
        self._redis_maxlen = 300

        self.semaphore = asyncio.Semaphore(3)

        logger.info(
            "HTFRefreshScheduler initialized: interval={}s, d1_bars={}, w1_bars={}",
            self.interval_sec,
            self.d1_bars,
            self.w1_bars,
        )

    async def run(self) -> None:
        """Main refresh loop."""
        logger.info("HTFRefreshScheduler started")

        while not self.system_state.is_ready():
            logger.debug("HTFRefresh waiting for system ready…")
            await asyncio.sleep(10)

        while True:
            try:
                await asyncio.sleep(self.interval_sec)
                await self.refresh_all_symbols()
            except asyncio.CancelledError:
                logger.info("HTFRefreshScheduler cancelled")
                raise
            except Exception as exc:
                logger.exception("HTF refresh error: {}", exc)

    async def force_refresh_now(self) -> None:
        """Trigger an immediate D1/W1 refresh (e.g. after WS reconnect).

        Called from outside the regular loop to shorten the recovery window
        when HTF candles are stale due to a WS disconnect/reconnect cycle.
        """
        logger.info("HTFRefreshScheduler: force refresh triggered (WS reconnect)")
        try:
            await self.refresh_all_symbols()
        except Exception as exc:
            logger.error("HTFRefreshScheduler: force refresh failed: {}", exc)

    async def refresh_all_symbols(self) -> None:
        """Refresh D1/W1 for every enabled symbol."""
        symbols = get_enabled_symbols()
        if not symbols:
            logger.warning("No enabled symbols for HTF refresh")
            return

        logger.info("Starting D1/W1 refresh for {} symbols", len(symbols))

        tasks = [self._refresh_symbol(sym) for sym in symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("D1/W1 refresh complete")

    async def _refresh_symbol(self, symbol: str) -> None:
        async with self.semaphore:
            try:
                # ── D1 ──
                d1 = await self.fetcher.fetch(symbol, "D1", self.d1_bars)
                if d1:
                    for c in d1:
                        self.context_bus.update_candle(c)
                    await self._push_candles_to_redis(d1)
                else:
                    logger.warning("No D1 bars fetched for {} during HTF refresh", symbol)

                # ── W1 ──
                w1 = await self.fetcher.fetch(symbol, "W1", self.w1_bars)
                if w1:
                    for c in w1:
                        self.context_bus.update_candle(c)
                    await self._push_candles_to_redis(w1)
                else:
                    logger.warning("No W1 bars fetched for {} during HTF refresh", symbol)

                logger.debug("HTF refreshed {}: D1={}, W1={}", symbol, len(d1 or []), len(w1 or []))
            except Exception as exc:
                logger.error("HTF refresh error for {}: {}", symbol, exc)

    @staticmethod
    def _parse_candle_timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        if isinstance(value, int | float):
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            try:
                return datetime.fromtimestamp(timestamp, tz=UTC)
            except (OverflowError, OSError, ValueError):
                return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                try:
                    return HTFRefreshScheduler._parse_candle_timestamp(float(raw))
                except ValueError:
                    return None
            dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        return None

    @classmethod
    def _latest_candle_dt(cls, candles: list[dict[str, Any]]) -> datetime | None:
        latest: datetime | None = None
        for candle in candles:
            for key in ("timestamp", "open_time", "close_time", "time", "datetime"):
                parsed = cls._parse_candle_timestamp(candle.get(key))
                if parsed is not None:
                    if latest is None or parsed > latest:
                        latest = parsed
                    break
        return latest

    @classmethod
    def _candle_timestamp(cls, candle: dict[str, Any]) -> datetime | None:
        for key in ("timestamp", "open_time", "close_time", "time", "datetime"):
            parsed = cls._parse_candle_timestamp(candle.get(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _decode_candle_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, bytes | bytearray):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            return None
        try:
            payload = orjson.loads(raw)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _merge_candle_history(
        cls,
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
        cap: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, int]:
        merged_by_ts: dict[datetime, dict[str, Any]] = {}
        incoming_ts: set[datetime] = set()

        for candle in existing:
            candle_ts = cls._candle_timestamp(candle)
            if candle_ts is None:
                continue
            merged_by_ts[candle_ts] = candle

        for candle in incoming:
            candle_ts = cls._candle_timestamp(candle)
            if candle_ts is None:
                continue
            incoming_ts.add(candle_ts)
            merged_by_ts[candle_ts] = candle

        merged = [merged_by_ts[candle_ts] for candle_ts in sorted(merged_by_ts)]
        retained = merged[-cap:] if cap > 0 else merged
        latest = retained[-1] if retained else None

        retained_ts = {
            candle_ts
            for candle in retained
            if (candle_ts := cls._candle_timestamp(candle)) is not None
        }
        written_count = sum(1 for candle_ts in incoming_ts if candle_ts in retained_ts)
        dedup_skipped = max(0, len(incoming) - written_count)

        return retained, latest, written_count, dedup_skipped

    async def _read_redis_history_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        if not self._redis:
            return []

        try:
            raw_history = await self._redis.lrange(candle_history(symbol, timeframe), 0, -1)
        except Exception:
            return []

        candles: list[dict[str, Any]] = []
        for item in raw_history:
            candle = self._decode_candle_payload(item)
            if candle is not None:
                candles.append(candle)
        return candles

    async def _read_redis_candle_state(self, symbol: str, timeframe: str) -> dict[str, Any]:
        if not self._redis:
            return {}

        latest_key = latest_candle(symbol, timeframe)
        history_key = candle_history(symbol, timeframe)

        state: dict[str, Any] = {
            "redis_latest_key": latest_key,
            "redis_history_key": history_key,
            "redis_latest_ts": None,
            "redis_last_seen_ts": None,
            "history_len": None,
            "redis_latest_candle": None,
        }

        try:
            latest_map = await self._redis.hgetall(latest_key)
            if latest_map:
                decoded: dict[str, str] = {}
                for raw_key, raw_value in latest_map.items():
                    key = raw_key.decode() if isinstance(raw_key, bytes | bytearray) else str(raw_key)
                    value = raw_value.decode() if isinstance(raw_value, bytes | bytearray) else str(raw_value)
                    decoded[key] = value

                if "data" in decoded:
                    try:
                        latest_candle_payload = orjson.loads(decoded["data"])
                        if isinstance(latest_candle_payload, dict):
                            state["redis_latest_candle"] = latest_candle_payload
                            latest_dt = self._latest_candle_dt([latest_candle_payload])
                            if latest_dt is not None:
                                state["redis_latest_ts"] = latest_dt.isoformat()
                    except Exception:
                        state["redis_latest_ts"] = None

                last_seen_raw = decoded.get("last_seen_ts")
                if last_seen_raw is not None:
                    try:
                        state["redis_last_seen_ts"] = float(last_seen_raw)
                    except (TypeError, ValueError):
                        state["redis_last_seen_ts"] = None
        except Exception as exc:
            state["read_error"] = f"latest_hash:{type(exc).__name__}:{exc}"
            return state

        try:
            state["history_len"] = int(await self._redis.llen(history_key))
        except Exception as exc:
            state["read_error"] = f"history_len:{type(exc).__name__}:{exc}"

        return state

    @classmethod
    def _build_write_result_telemetry(
        cls,
        *,
        symbol: str,
        timeframe: str,
        candles: list[dict[str, Any]],
        before: dict[str, Any],
        after: dict[str, Any],
        written_count: int | None = None,
        dedup_skipped: int | None = None,
        write_error: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        provider_latest_dt = cls._latest_candle_dt(candles)
        provider_latest_ts = provider_latest_dt.isoformat() if provider_latest_dt is not None else None
        before_dt = cls._parse_candle_timestamp(before.get("redis_latest_ts"))
        after_dt = cls._parse_candle_timestamp(after.get("redis_latest_ts"))

        result = "latest_updated"
        if write_error:
            result = "redis_write_error"
        elif provider_latest_dt is None:
            result = "timestamp_parse_error"
        elif after_dt is None:
            result = "write_not_proven"
        elif provider_latest_dt > (before_dt or datetime.min.replace(tzinfo=UTC)) and after_dt >= provider_latest_dt:
            result = "latest_updated"
        elif before_dt is not None and provider_latest_dt == before_dt and after_dt == before_dt:
            result = "same_latest_dedup_ok"
        elif before_dt is not None and provider_latest_dt < before_dt and after_dt == before_dt:
            result = "provider_older_ignored"
        elif provider_latest_dt > (before_dt or datetime.min.replace(tzinfo=UTC)) and after_dt < provider_latest_dt:
            result = "latest_update_failed"
        else:
            result = "write_not_proven"

        latest_age_seconds_after = None
        if after_dt is not None:
            latest_age_seconds_after = max(0.0, (datetime.now(tz=UTC) - after_dt).total_seconds())

        effective_written_count = 0 if write_error is not None else (written_count if written_count is not None else len(candles))
        effective_dedup_skipped = (
            dedup_skipped
            if dedup_skipped is not None
            else max(0, len(candles) - effective_written_count)
        )
        telemetry = {
            "event": "htf_refresh_write_result",
            "symbol": symbol,
            "timeframe": timeframe,
            "fetched_count": len(candles),
            "written_count": effective_written_count,
            "dedup_skipped": effective_dedup_skipped,
            "provider_latest_ts": provider_latest_ts,
            "redis_latest_ts_before": before.get("redis_latest_ts"),
            "redis_latest_ts_after": after.get("redis_latest_ts"),
            "redis_last_seen_before": before.get("redis_last_seen_ts"),
            "redis_last_seen_after": after.get("redis_last_seen_ts"),
            "history_len_before": before.get("history_len"),
            "history_len_after": after.get("history_len"),
            "latest_age_seconds_after": latest_age_seconds_after,
            "redis_history_key": after.get("redis_history_key") or before.get("redis_history_key"),
            "redis_latest_key": after.get("redis_latest_key") or before.get("redis_latest_key"),
            "result": result,
            "latest_updated": result == "latest_updated",
        }
        if write_error:
            telemetry["write_error"] = write_error
        if "read_error" in before:
            telemetry["read_error_before"] = before["read_error"]
        if "read_error" in after:
            telemetry["read_error_after"] = after["read_error"]
        return result, telemetry

    @staticmethod
    def _telemetry_log_method(result: str) -> str:
        if result in {"redis_write_error", "timestamp_parse_error", "latest_update_failed"}:
            return "error"
        if result == "write_not_proven":
            return "warning"
        return "info"

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH + PUBLISH candle dicts to Redis (best-effort).

        Candles are grouped by key so each unique key receives a single
        RPUSH with all its values and one LTRIM, reducing round trips
        from (rpush + ltrim + publish) × N to
        (rpush + ltrim) × K + publish × N  (K = unique keys ≤ N).
        """
        if not self._redis or not candles:
            return

        # ── Group valid candles by Redis key to batch writes ─────────────────
        # Reduces round trips: 3 × N → 2 × K + N  (K = unique keys, K ≤ N).
        key_batches: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                continue
            key = candle_history(symbol, timeframe)
            candle_json = orjson.dumps(candle).decode("utf-8")
            pub_channel = channel_candle(symbol, timeframe)
            key_batches[key].append((candle_json, pub_channel, candle))

        for key, items in key_batches.items():
            symbol = str(items[0][2].get("symbol", ""))
            timeframe = str(items[0][2].get("timeframe", ""))
            before = await self._read_redis_candle_state(symbol, timeframe) if symbol and timeframe else {}
            try:
                existing_history = await self._read_redis_history_candles(symbol, timeframe)
                if latest_candle_payload := before.get("redis_latest_candle"):
                    existing_history.append(latest_candle_payload)

                incoming_candles = [item[2] for item in items]
                retained, latest_payload, written_count, dedup_skipped = self._merge_candle_history(
                    existing_history,
                    incoming_candles,
                    self._redis_maxlen,
                )

                await self._redis.delete(key)
                if retained:
                    retained_json = [orjson.dumps(candle).decode("utf-8") for candle in retained]
                    await self._redis.rpush(key, *retained_json)
                    await self._redis.ltrim(key, -self._redis_maxlen, -1)

                if latest_payload is not None:
                    await self._redis.hset(
                        latest_candle(symbol, timeframe),
                        mapping={
                            "data": orjson.dumps(latest_payload).decode("utf-8"),
                            "last_seen_ts": str(datetime.now(tz=UTC).timestamp()),
                        },
                    )

                incoming_by_ts: dict[datetime, tuple[str, str, dict[str, Any]]] = {}
                for candle_json, pub_channel, candle in items:
                    candle_ts = self._candle_timestamp(candle)
                    if candle_ts is None:
                        continue
                    incoming_by_ts[candle_ts] = (candle_json, pub_channel, candle)

                for _, (candle_json, pub_channel, candle) in sorted(incoming_by_ts.items()):
                    enqueue_candle_dict(candle)
                    await self._redis.publish(pub_channel, candle_json)
                if symbol and timeframe:
                    after = await self._read_redis_candle_state(symbol, timeframe)
                    result, telemetry = self._build_write_result_telemetry(
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=incoming_candles,
                        before=before,
                        after=after,
                        written_count=written_count,
                        dedup_skipped=dedup_skipped,
                    )
                    getattr(logger, self._telemetry_log_method(result))("HTF write result {}", telemetry)
            except Exception as exc:
                logger.warning("[HTFRefresh] Redis push failed {}: {}", key, exc)
                if symbol and timeframe:
                    result, telemetry = self._build_write_result_telemetry(
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=[item[2] for item in items],
                        before=before,
                        after=before,
                        written_count=0,
                        dedup_skipped=len(items),
                        write_error=f"{type(exc).__name__}:{exc}",
                    )
                    getattr(logger, self._telemetry_log_method(result))("HTF write result {}", telemetry)
