"""
Finnhub REST candle fetcher for historical data warmup.

Fetches H1, D1, W1 from Finnhub /forex/candle API.
H4 is aggregated from H1 bars (4:1).
M15 is normally built from ticks, but REST fallback is available
for cold-start recovery via ``FinnhubCandleFetcher.cold_start_m15()``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from config_loader import CONFIG, get_enabled_symbols, load_finnhub
from context.live_context_bus import LiveContextBus
from contracts.canonical_candle import TIMEFRAME_DELTAS, as_utc
from core.metrics import WARMUP_FAILURES
from ingest.finnhub_rest_budget import (
    FinnhubRestCooldownError,
    finnhub_rest_budget,
)


class FinnhubCandleError(Exception):
    """Base exception for Finnhub candle fetching errors."""


class FinnhubCandlePremiumError(FinnhubCandleError):
    """Raised when premium access is required (HTTP 403)."""


class FinnhubCandleFetcher:
    """
    Fetches historical candles from Finnhub REST API.

    Supports warmup for multiple symbols with rate limiting.
    H4 is aggregated from H1 bars.
    """

    # Resolution mapping: timeframe -> Finnhub resolution
    RESOLUTION_MAP: dict[str, str] = {
        "M15": "15",
        "H1": "60",
        "D1": "D",
        "W1": "W",
        "MN": "M",
    }

    def __init__(self) -> None:
        super().__init__()
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

        self._key_manager = finnhub_keys
        self.api_key = self._key_manager.current_key()
        self.config = load_finnhub()
        self.rest_config = self.config.get("rest", {})
        self.candles_config = self.config.get("candles", {})
        self.warmup_config = self.candles_config.get("warmup", {})
        self.symbols_config = self.config.get("symbols", {})
        self.symbol_prefix = self.symbols_config.get("symbol_prefix", "OANDA")

        self.base_url = self.rest_config.get("base_url", "https://finnhub.io/api/v1")
        self.timeout = self.rest_config.get("timeout_sec", 20)
        self.context_bus = LiveContextBus()

        # Rate limiting
        self.max_concurrent = self.warmup_config.get("max_concurrent", 5)
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        self.request_delay = self.warmup_config.get("request_delay_sec", 0.5)

        # HTTP retry policy (used primarily for HTTP 429)
        self.retries = int(self.rest_config.get("retries", 3))
        self.backoff_factor = float(self.rest_config.get("backoff_factor", 1.5))
        self.max_backoff_sec = float(self.rest_config.get("max_backoff_sec", 30.0))
        self.backoff_jitter_sec = float(self.rest_config.get("backoff_jitter_sec", 0.25))

    async def _wait_for_request_slot(self) -> None:
        """Reserve a process-wide Finnhub REST request slot."""
        key_cooldown = self._key_manager.next_available_in()
        if isinstance(key_cooldown, (int, float)) and key_cooldown > 0:
            finnhub_rest_budget.defer_for(key_cooldown)
        await finnhub_rest_budget.wait_for_slot(self.request_delay)

    @staticmethod
    def _register_rate_limit(retry_after: str | None) -> None:
        """Propagate a provider 429 into the shared process cooldown."""
        parsed = FinnhubCandleFetcher._retry_after_seconds(retry_after)
        # Finnhub's key manager defaults to 65 seconds.  A missing or zero
        # Retry-After must not permit another worker to immediately retry.
        finnhub_rest_budget.defer_for(max(parsed, 65.0))

    async def _fallback_or_raise(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        primary_error: FinnhubCandleError,
    ) -> list[dict[str, Any]]:
        """Try configured REST substitute providers without changing candle consumers."""
        candles = await self.try_fallback(symbol, timeframe, bars)
        if candles:
            logger.warning(
                "[ProviderFailover] Finnhub unavailable for {} {} ({}); using {} fallback candles",
                symbol,
                timeframe,
                primary_error,
                len(candles),
            )
            return candles
        raise primary_error

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        """Parse Retry-After header value into seconds."""
        if not value:
            return 0.0

        value = value.strip()
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def convert_symbol(self, symbol: str) -> str:
        """
        Convert internal symbol to Finnhub format.

        Args:
            symbol: Internal symbol (e.g., EURUSD, XAUUSD)

        Returns:
            Finnhub symbol (e.g., OANDA:EUR_USD, OANDA:XAU_USD)
        """
        # If already prefixed, return as is
        if ":" in symbol:
            return symbol

        # Add underscore for Finnhub format
        # EURUSD -> EUR_USD, XAUUSD -> XAU_USD
        if len(symbol) == 6:
            base = symbol[:3]
            quote = symbol[3:]
            formatted = f"{base}_{quote}"
        else:
            formatted = symbol

        return f"{self.symbol_prefix}:{formatted}"

    @staticmethod
    def _enabled_symbols_from_config(config: dict[str, Any]) -> list[str]:
        """Resolve enabled symbols from either pairs.symbols or pairs.pairs."""
        pairs_cfg = config.get("pairs", {})

        symbols = pairs_cfg.get("symbols", [])
        if isinstance(symbols, list):
            normalized = [str(s) for s in symbols if isinstance(s, str) and s]
            if normalized:
                return normalized

        pairs = pairs_cfg.get("pairs", [])
        if not isinstance(pairs, list):
            return []

        enabled: list[str] = []
        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            symbol = pair.get("symbol")
            if isinstance(symbol, str) and symbol and pair.get("enabled"):
                enabled.append(symbol)
        return enabled

    def _calculate_from_ts(self, bars: int, timeframe: str) -> int:
        """
        Calculate from timestamp for fetching historical bars.

        Adds 25% buffer for weekends/holidays.

        Args:
            bars: Number of bars to fetch
            timeframe: Timeframe (H1, D1, W1, MN)

        Returns:
            Unix timestamp for from parameter
        """
        now = datetime.now(UTC)

        # ── Weekend alignment: snap back to last Friday 21:00 UTC (forex close)
        weekday = now.weekday()  # 0=Mon ... 5=Sat, 6=Sun
        if weekday == 5:  # Saturday → rewind to Friday
            now = now - timedelta(days=1)
        elif weekday == 6:  # Sunday → rewind to Friday
            now = now - timedelta(days=2)

        # 40% buffer accommodates weekends, holidays, and sparse data gaps
        buffer_multiplier = 1.40

        if timeframe == "M15":
            delta = timedelta(minutes=int(bars * 15 * buffer_multiplier))
        elif timeframe == "H1":
            delta = timedelta(hours=int(bars * buffer_multiplier))
        elif timeframe == "D1":
            delta = timedelta(days=int(bars * buffer_multiplier))
        elif timeframe == "W1":
            delta = timedelta(weeks=int(bars * buffer_multiplier))
        elif timeframe == "MN":
            delta = timedelta(days=int(bars * 30 * buffer_multiplier))
        else:
            raise FinnhubCandleError(f"Unsupported timeframe: {timeframe}")

        from_dt = now - delta
        return int(from_dt.timestamp())

    def normalize_response(
        self,
        data: dict[str, Any],
        symbol: str,
        timeframe: str,
        *,
        as_of_utc: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Normalize Finnhub parallel arrays to list of candle dicts.

        Args:
            data: Finnhub API response
            symbol: Trading symbol
            timeframe: Timeframe

        Returns:
            List of candle dicts compatible with LiveContextBus
        """
        if data.get("s") != "ok":
            logger.warning(f"Finnhub returned status: {data.get('s')} for {symbol} {timeframe}")
            return []

        # Extract parallel arrays
        closes = data.get("c", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        opens = data.get("o", [])
        timestamps = data.get("t", [])
        volumes = data.get("v", [])

        if not closes or len(closes) == 0:
            return []

        # Validate all arrays have same length
        length = len(closes)
        if not all(len(arr) == length for arr in [highs, lows, opens, timestamps, volumes]):
            logger.error(f"Mismatched array lengths in Finnhub response for {symbol} {timeframe}")
            return []

        period = TIMEFRAME_DELTAS.get(timeframe)
        if period is None:
            period = timedelta(days=30) if timeframe == "MN" else None
        if period is None:
            raise FinnhubCandleError(f"Unsupported timeframe: {timeframe}")
        cutoff = as_utc(as_of_utc or datetime.now(UTC), "as_of_utc")

        candles: list[dict[str, Any]] = []
        skipped = 0
        for i in range(length):
            # Reject sentinel -1 values from Finnhub no_data / partial responses
            ohlc = [opens[i], highs[i], lows[i], closes[i]]
            if any(v <= 0 for v in ohlc):
                skipped += 1
                continue
            # OHLC sanity: high must be >= low, open, close
            if highs[i] < lows[i] or highs[i] < closes[i] or highs[i] < opens[i]:
                skipped += 1
                continue
            # Reject sentinel timestamps
            if timestamps[i] <= 0:
                skipped += 1
                continue

            # Finnhub REST timestamps are treated as provider period-end
            # timestamps in this adapter.  Both sides of the canonical window
            # are persisted so downstream code never has to guess semantics.
            provider_timestamp = datetime.fromtimestamp(timestamps[i], tz=UTC)
            close_time = provider_timestamp
            open_time = close_time - period

            candle = {
                "symbol": symbol,
                "timeframe": timeframe,
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "timestamp": provider_timestamp,
                "open_time": open_time,
                "close_time": close_time,
                "complete": close_time <= cutoff,
                "provider": "finnhub",
                "provider_timestamp_semantics": "PERIOD_END",
                "source": "rest_api",
            }
            candles.append(candle)

        if skipped:
            logger.warning(
                "[Normalize] %s %s: skipped %d/%d invalid candles (sentinel -1 or OHLC violation)",
                symbol,
                timeframe,
                skipped,
                length,
            )
        return candles

    async def fetch_range(
        self,
        symbol: str,
        timeframe: str,
        from_utc: datetime,
        to_utc: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch an exact historical window without consulting current time.

        This path is intended for replay and as-of evidence snapshots.  It does
        not use a latest-bars fallback because substituting a provider response
        with an unbounded current-time query would invalidate replay isolation.
        """

        start = as_utc(from_utc, "from_utc")
        end = as_utc(to_utc, "to_utc")
        if end <= start:
            raise FinnhubCandleError("to_utc must be after from_utc")
        timeframe = timeframe.upper()

        if timeframe == "H4":
            h1_candles = await self.fetch_range(symbol, "H1", start, end)
            return [
                candle
                for candle in self.aggregate_h4(h1_candles)
                if candle.get("complete") is True
                and candle["open_time"] >= start
                and candle["close_time"] <= end
            ]
        if timeframe not in self.RESOLUTION_MAP:
            raise FinnhubCandleError(f"Unsupported timeframe: {timeframe}")

        finnhub_symbol = self.convert_symbol(symbol)
        resolution = self.RESOLUTION_MAP[timeframe]
        url = f"{self.base_url}/forex/candle"
        active_key = self._key_manager.current_key() or self.api_key
        params = {
            "symbol": finnhub_symbol,
            "resolution": resolution,
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
            "token": active_key,
        }
        self.api_key = active_key

        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    active_key = self._key_manager.current_key() or self.api_key
                    self.api_key = active_key
                    params["token"] = active_key
                    await self._wait_for_request_slot()
                    response = await client.get(url, params=params)
                    if response.status_code == 429:
                        self._key_manager.report_failure(active_key, 429)
                        self._register_rate_limit(response.headers.get("Retry-After"))
                        raise FinnhubCandleError(f"[429] Rate limited for {symbol} {timeframe}")
                    if response.status_code == 403:
                        self._key_manager.report_failure(active_key, 403)
                        raise FinnhubCandlePremiumError(
                            f"Premium access required for {symbol} {timeframe}"
                        )
                    response.raise_for_status()
                    self._key_manager.report_success(active_key)
                    candles = self.normalize_response(
                        response.json(),
                        symbol,
                        timeframe,
                        as_of_utc=end,
                    )
                    return [
                        candle
                        for candle in candles
                        if candle.get("complete") is True
                        and candle["open_time"] >= start
                        and candle["close_time"] <= end
                    ]
            except FinnhubRestCooldownError as exc:
                raise FinnhubCandleError(
                    f"Finnhub cooldown active for {symbol} {timeframe}; "
                    f"retry_in={exc.retry_after_sec:.1f}s"
                ) from exc
            except (FinnhubCandleError, FinnhubCandlePremiumError):
                raise
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                self._key_manager.report_failure(active_key, status_code)
                raise FinnhubCandleError(
                    f"HTTP {status_code} for {symbol} {timeframe}"
                ) from exc
            except Exception as exc:
                raise FinnhubCandleError(
                    f"Error fetching range for {symbol} {timeframe}: {exc}"
                ) from exc

    async def fetch(self, symbol: str, timeframe: str, bars: int = 100) -> list[dict[str, Any]]:
        """
        Fetch historical candles for a symbol and timeframe.

        Args:
            symbol: Trading symbol (internal format)
            timeframe: Timeframe (H1, D1, W1)
            bars: Number of bars to fetch

        Returns:
            List of candle dicts

        Raises:
            FinnhubCandleError: On fetch failure
            FinnhubCandlePremiumError: On HTTP 403
        """
        # M15 is normally built from WS ticks.  REST fetch is allowed
        # only as a cold-start fallback (callers must opt in explicitly or
        # use cold_start_m15()).  A warning is emitted so callers know this
        # path was taken.
        if timeframe == "M15":
            logger.info(
                "M15 REST fallback activated for {} — normally built from WS ticks",
                symbol,
            )

        # H4 is aggregated from H1
        if timeframe == "H4":
            h1_bars = bars * 4  # Need 4× H1 bars to make H4 bars
            h1_candles = await self.fetch(symbol, "H1", h1_bars)
            return self.aggregate_h4(h1_candles)

        if timeframe not in self.RESOLUTION_MAP:
            raise FinnhubCandleError(f"Unsupported timeframe: {timeframe}")

        finnhub_symbol = self.convert_symbol(symbol)
        resolution = self.RESOLUTION_MAP[timeframe]
        from_ts = self._calculate_from_ts(bars, timeframe)
        to_ts = int(datetime.now(UTC).timestamp())

        url = f"{self.base_url}/forex/candle"
        active_key = self._key_manager.current_key() or self.api_key
        params = {
            "symbol": finnhub_symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
            "token": active_key,
        }
        self.api_key = active_key  # keep in sync

        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    active_key = self._key_manager.current_key() or self.api_key
                    self.api_key = active_key
                    params["token"] = active_key

                    await self._wait_for_request_slot()
                    logger.debug(
                        "Fetching {} {}: {} bars from Finnhub (single attempt, no retry)",
                        symbol,
                        timeframe,
                        bars,
                    )
                    response = await client.get(url, params=params)

                    if response.status_code == 429:
                        self._key_manager.report_failure(active_key, 429)
                        self._register_rate_limit(response.headers.get("Retry-After"))
                        raise FinnhubCandleError(
                            f"[429] Rate limited for {symbol} {timeframe} — "
                            "warmup akan skip, WS akan feed data secara live"
                        )

                    if response.status_code == 403:
                        self._key_manager.report_failure(active_key, 403)
                        return await self._fallback_or_raise(
                            symbol,
                            timeframe,
                            bars,
                            FinnhubCandlePremiumError(f"Premium access required for {symbol} {timeframe}"),
                        )

                    response.raise_for_status()
                    data = response.json()

                    self._key_manager.report_success(active_key)
                    candles = self.normalize_response(data, symbol, timeframe)
                    if not candles:
                        fallback = await self.try_fallback(symbol, timeframe, bars)
                        if fallback:
                            logger.warning(
                                "[ProviderFailover] Finnhub returned no candles for {} {}; using {} fallback candles",
                                symbol,
                                timeframe,
                                len(fallback),
                            )
                            return fallback
                    logger.info("Fetched {} {} bars for {}", len(candles), timeframe, symbol)
                    return candles

            except FinnhubRestCooldownError as exc:
                return await self._fallback_or_raise(
                    symbol,
                    timeframe,
                    bars,
                    FinnhubCandleError(
                        f"Finnhub cooldown active for {symbol} {timeframe}; "
                        f"retry_in={exc.retry_after_sec:.1f}s"
                    ),
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                self._key_manager.report_failure(active_key, status_code)
                if status_code == 403:
                    primary_error: FinnhubCandleError = FinnhubCandlePremiumError(
                        f"Premium access required for {symbol} {timeframe}"
                    )
                elif status_code == 429:
                    raise FinnhubCandleError(
                        f"[429] Rate limited for {symbol} {timeframe} — "
                        "warmup akan skip, WS akan feed data secara live"
                    ) from exc
                else:
                    primary_error = FinnhubCandleError(f"HTTP {status_code} for {symbol} {timeframe}")
                return await self._fallback_or_raise(symbol, timeframe, bars, primary_error)
            except (FinnhubCandleError, FinnhubCandlePremiumError):
                raise
            except Exception as exc:
                return await self._fallback_or_raise(
                    symbol,
                    timeframe,
                    bars,
                    FinnhubCandleError(f"Error fetching {symbol} {timeframe}: {exc}"),
                )

    def aggregate_h4(self, h1_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Aggregate H1 bars into H4 bars (4:1).

        H4 alignment: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
        An authoritative H4 candle contains exactly four complete, contiguous
        H1 candles.  Partial or ambiguous groups are retained as diagnostics
        with ``complete=False`` and therefore cannot enter 5S-CR evidence.

        Args:
            h1_candles: List of H1 candles

        Returns:
            List of H4 candles
        """
        if not h1_candles:
            return []

        valid_h1: list[dict[str, Any]] = []
        for raw in h1_candles:
            if not (
                raw.get("close", -1) > 0
                and raw.get("open", -1) > 0
                and raw.get("high", -1) > 0
                and raw.get("low", -1) > 0
                and raw["high"] >= max(raw["low"], raw["open"], raw["close"])
                and raw["low"] <= min(raw["high"], raw["open"], raw["close"])
            ):
                continue
            normalized = self._canonical_h1_for_aggregation(raw)
            if normalized is not None:
                valid_h1.append(normalized)
        dropped = len(h1_candles) - len(valid_h1)
        if dropped:
            logger.warning("aggregate_h4: dropped {}/{} invalid H1 bars before aggregation", dropped, len(h1_candles))
        if not valid_h1:
            return []
        groups: dict[datetime, list[dict[str, Any]]] = {}
        for h1 in sorted(valid_h1, key=lambda item: item["open_time"]):
            open_time = h1["open_time"]
            group_start = open_time.replace(
                hour=(open_time.hour // 4) * 4,
                minute=0,
                second=0,
                microsecond=0,
            )
            groups.setdefault(group_start, []).append(h1)

        h4_candles = [
            self._build_h4_candle(group, group_start=group_start)
            for group_start, group in sorted(groups.items())
        ]

        logger.debug(f"Aggregated {len(valid_h1)} H1 bars into {len(h4_candles)} H4 bars")
        return h4_candles

    @staticmethod
    def _canonical_h1_for_aggregation(candle: dict[str, Any]) -> dict[str, Any] | None:
        def _dt(value: Any) -> datetime | None:
            if isinstance(value, datetime):
                return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return datetime.fromtimestamp(float(value), tz=UTC)
            if isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return None
                return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
            return None

        open_time = _dt(candle.get("open_time"))
        close_time = _dt(candle.get("close_time"))
        provider_timestamp = _dt(candle.get("timestamp"))
        semantics = str(candle.get("provider_timestamp_semantics") or "UNSPECIFIED").upper()
        if open_time is None or close_time is None:
            if provider_timestamp is None:
                return None
            # Historical H1 payloads in this module used period-end timestamps.
            open_time = provider_timestamp - timedelta(hours=1)
            close_time = provider_timestamp
            semantics = "UNSPECIFIED"

        return {
            **candle,
            "open_time": open_time,
            "close_time": close_time,
            "complete": candle.get("complete") is True and semantics != "UNSPECIFIED",
            "provider": str(candle.get("provider") or candle.get("source") or "legacy_unknown"),
            "provider_timestamp_semantics": semantics,
        }

    def _build_h4_candle(
        self,
        h1_group: list[dict[str, Any]],
        *,
        group_start: datetime,
    ) -> dict[str, Any]:
        """
        Build a single H4 candle from a group of H1 candles.

        Args:
            h1_group: List of H1 candles in one aligned UTC H4 bucket.

        Returns:
            H4 candle dict
        """
        ordered = sorted(h1_group, key=lambda item: item["open_time"])
        first = ordered[0]
        expected_opens = [group_start + timedelta(hours=index) for index in range(4)]
        actual_opens = [item["open_time"] for item in ordered]
        authoritative = (
            len(ordered) == 4
            and actual_opens == expected_opens
            and all(
                item.get("complete") is True
                and item["close_time"] == item["open_time"] + timedelta(hours=1)
                for item in ordered
            )
        )

        # Aggregate OHLCV
        opens = [c["open"] for c in ordered]
        highs = [c["high"] for c in ordered]
        lows = [c["low"] for c in ordered]
        closes = [c["close"] for c in ordered]
        volumes = [c.get("volume", 0.0) for c in ordered]
        group_close = group_start + timedelta(hours=4)
        providers = sorted({str(item.get("provider") or "legacy_unknown") for item in ordered})

        return {
            "symbol": first["symbol"],
            "timeframe": "H4",
            "open": opens[0],
            "high": max(highs),
            "low": min(lows),
            "close": closes[-1],
            "volume": sum(volumes),
            "timestamp": group_close,
            "open_time": group_start,
            "close_time": group_close,
            "complete": authoritative,
            "provider": "+".join(providers),
            "provider_timestamp_semantics": "CANONICAL_WINDOW",
            "aggregation_component_count": len(ordered),
            "aggregation_diagnostic": (
                "AUTHORITATIVE_4X_H1" if authoritative else "INCOMPLETE_OR_GAPPED_H1_GROUP"
            ),
            "source": "h1_aggregated",
        }

    def aggregate_d1(self, h1_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate H1 bars into D1 (daily) bars.

        Groups H1 candles by UTC date and builds one D1 candle per group.
        Used as a fallback when the REST API returns no daily data.
        """
        if not h1_candles:
            return []

        valid_h1 = [
            c
            for c in h1_candles
            if c.get("close", -1) > 0
            and c.get("open", -1) > 0
            and c.get("high", -1) > 0
            and c.get("low", -1) > 0
            and c["high"] >= c["low"]
        ]
        if not valid_h1:
            return []

        from collections import defaultdict

        daily_groups: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for h1 in valid_h1:
            ts = h1["timestamp"]
            dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, tz=UTC)
            daily_groups[(dt.year, dt.month, dt.day)].append(h1)

        d1_candles_out: list[dict[str, Any]] = []
        for (_y, _m, _d), group in sorted(daily_groups.items()):
            last_ts = group[-1]["timestamp"]
            if not isinstance(last_ts, datetime):
                last_ts = datetime.fromtimestamp(last_ts, tz=UTC)
            d1_candles_out.append(
                {
                    "symbol": group[0]["symbol"],
                    "timeframe": "D1",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "h1_aggregated",
                }
            )

        logger.debug("Aggregated {} H1 bars into {} D1 bars", len(valid_h1), len(d1_candles_out))
        return d1_candles_out

    def aggregate_w1(self, d1_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate D1 bars into W1 (weekly) bars.

        Groups D1 candles by ISO year+week and builds one W1 candle per group.
        Used as a fallback when the REST API returns no weekly data.
        """
        if not d1_candles:
            return []

        valid_d1 = [
            c
            for c in d1_candles
            if c.get("close", -1) > 0
            and c.get("open", -1) > 0
            and c.get("high", -1) > 0
            and c.get("low", -1) > 0
            and c["high"] >= c["low"]
        ]
        if not valid_d1:
            return []

        from collections import defaultdict

        weekly_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for d1 in valid_d1:
            ts = d1["timestamp"]
            dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, tz=UTC)
            iso_year, iso_week, _ = dt.isocalendar()
            weekly_groups[(iso_year, iso_week)].append(d1)

        w1_candles: list[dict[str, Any]] = []
        for (_y, _w), group in sorted(weekly_groups.items()):
            last_ts = group[-1]["timestamp"]
            if not isinstance(last_ts, datetime):
                last_ts = datetime.fromtimestamp(last_ts, tz=UTC)
            w1_candles.append(
                {
                    "symbol": group[0]["symbol"],
                    "timeframe": "W1",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "d1_aggregated",
                }
            )

        logger.debug("Aggregated {} D1 bars into {} W1 bars", len(valid_d1), len(w1_candles))
        return w1_candles

    def aggregate_mn(self, d1_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate D1 bars into MN (monthly) bars.

        Groups D1 candles by (year, month) and builds one MN candle per group.
        Used as a fallback when the REST API returns no monthly data.
        """
        if not d1_candles:
            return []

        valid_d1 = [
            c
            for c in d1_candles
            if c.get("close", -1) > 0
            and c.get("open", -1) > 0
            and c.get("high", -1) > 0
            and c.get("low", -1) > 0
            and c["high"] >= c["low"]
        ]
        if not valid_d1:
            return []

        # Group by (year, month)
        from collections import defaultdict

        monthly_groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for d1 in valid_d1:
            ts = d1["timestamp"]
            dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, tz=UTC)
            monthly_groups[(dt.year, dt.month)].append(d1)

        mn_candles: list[dict[str, Any]] = []
        for (_year, _month), group in sorted(monthly_groups.items()):
            first = group[0]
            last = group[-1]
            last_ts = last["timestamp"]
            if not isinstance(last_ts, datetime):
                last_ts = datetime.fromtimestamp(last_ts, tz=UTC)

            mn_candles.append(
                {
                    "symbol": first["symbol"],
                    "timeframe": "MN",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "d1_aggregated",
                }
            )

        logger.debug("Aggregated {} D1 bars into {} MN bars", len(valid_d1), len(mn_candles))
        return mn_candles

    async def warmup_all(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """
        Warmup all enabled symbols with historical candles.

        Fetches H1, D1, W1 from REST, aggregates H4.
        Seeds LiveContextBus with candles.

        Returns:
            Dict of symbol -> timeframe -> candles
        """
        if not self.warmup_config.get("enabled", True):
            logger.info("Warmup disabled in config")
            return {}

        # Get enabled symbols from config (supports pairs.symbols and pairs.pairs)
        enabled_symbols = get_enabled_symbols()
        logger.info("[Warmup] enabled symbols count={} symbols={}", len(enabled_symbols), enabled_symbols[:10])
        if not enabled_symbols:
            logger.warning("No enabled symbols found for warmup")
            return {}

        warmup_bars = self.warmup_config.get("bars", 100)

        # Ensure required timeframes are always present for analysis.
        REQUIRED_TIMEFRAMES = ["H1", "H4", "D1", "W1", "MN"]  # noqa: N806

        configured_tfs = self.warmup_config.get("timeframes")
        if not configured_tfs:
            timeframes = REQUIRED_TIMEFRAMES
        else:
            # Preserve required order, then append any additional configured TFs (exclude M15)
            timeframes = list(REQUIRED_TIMEFRAMES)
            for tf in configured_tfs:
                if tf not in timeframes and tf != "M15":
                    timeframes.append(tf)

        # When D1/W1 are synthesized from H1 (Finnhub free-tier returns
        # no_data for "D"/"W" resolutions), the H1 fetch must span enough
        # history.  5 W1 bars ≈ 5 forex weeks ≈ 25 trading days × 24 H1/day
        # = 600 H1, plus ~40 % calendar buffer for weekends ≈ 840.
        h1_synthesis_min = 0
        if "D1" in timeframes or "W1" in timeframes:
            h1_synthesis_min = max(warmup_bars, 840)

        tf_bars: dict[str, int] = {}
        for tf in timeframes:
            tf_bars[tf] = warmup_bars
        if h1_synthesis_min:
            tf_bars["H1"] = max(tf_bars.get("H1", warmup_bars), h1_synthesis_min)

        logger.info(
            f"Starting warmup for {len(enabled_symbols)} symbols, {len(timeframes)} timeframes, "
            f"{warmup_bars} bars each (H1={tf_bars.get('H1', warmup_bars)} for synthesis coverage)"
        )

        results: dict[str, dict[str, list[dict[str, Any]]]] = {}

        # Create tasks for all symbol/timeframe combinations
        tasks = [
            self.warmup_symbol_tf(symbol, tf, tf_bars.get(tf) or warmup_bars, results)
            for symbol in enabled_symbols
            for tf in timeframes
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        # ── D1 fallback: synthesize from H1 when REST returned no daily data ──
        for symbol in enabled_symbols:
            sym_data = results.get(symbol, {})
            if not sym_data.get("D1") and sym_data.get("H1"):
                synthesized = self.aggregate_d1(sym_data["H1"])
                if synthesized:
                    results.setdefault(symbol, {})["D1"] = synthesized
                    for candle in synthesized:
                        self.context_bus.update_candle(candle)
                    logger.info(
                        "[Warmup] {} D1: synthesized {} bars from H1 (REST returned no daily data)",
                        symbol,
                        len(synthesized),
                    )

        # ── W1 fallback: synthesize from D1 when REST returned no weekly data ──
        for symbol in enabled_symbols:
            sym_data = results.get(symbol, {})
            if not sym_data.get("W1") and sym_data.get("D1"):
                synthesized = self.aggregate_w1(sym_data["D1"])
                if synthesized:
                    results.setdefault(symbol, {})["W1"] = synthesized
                    for candle in synthesized:
                        self.context_bus.update_candle(candle)
                    logger.info(
                        "[Warmup] {} W1: synthesized {} bars from D1 (REST returned no weekly data)",
                        symbol,
                        len(synthesized),
                    )

        # ── MN fallback: synthesize from D1 when REST returned no monthly data ──
        for symbol in enabled_symbols:
            sym_data = results.get(symbol, {})
            if not sym_data.get("MN") and sym_data.get("D1"):
                synthesized = self.aggregate_mn(sym_data["D1"])
                if synthesized:
                    results.setdefault(symbol, {})["MN"] = synthesized
                    for candle in synthesized:
                        self.context_bus.update_candle(candle)
                    logger.info(
                        "[Warmup] {} MN: synthesized {} bars from D1 (REST returned no monthly data)",
                        symbol,
                        len(synthesized),
                    )

        logger.info(f"Warmup complete: {len(results)} symbols warmed up")
        return results

    async def warmup_symbol_tf(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        results: dict[str, dict[str, list[dict[str, Any]]]],
    ) -> None:
        """
        Warmup a single symbol/timeframe combination.

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            bars: Number of bars to fetch
            results: Shared results dict
        """
        try:
            candles = await self.fetch(symbol, timeframe, bars)

            if not candles:
                WARMUP_FAILURES.labels(symbol=symbol, tf=timeframe, reason="empty").inc()
                logger.warning(f"No candles fetched for {symbol} {timeframe}")
                return

            # Seed LiveContextBus
            for candle in candles:
                self.context_bus.update_candle(candle)

            # Store in results
            if symbol not in results:
                results[symbol] = {}
            results[symbol][timeframe] = candles

            logger.debug(f"Warmup {symbol} {timeframe}: {len(candles)} bars seeded to LiveContextBus")

        except FinnhubCandlePremiumError:
            WARMUP_FAILURES.labels(symbol=symbol, tf=timeframe, reason="premium_blocked").inc()
            logger.warning(f"Premium access required for {symbol} {timeframe} — trying fallback providers")
            candles = await self.try_fallback(symbol, timeframe, bars)
            if candles:
                for candle in candles:
                    self.context_bus.update_candle(candle)
                if symbol not in results:
                    results[symbol] = {}
                results[symbol][timeframe] = candles
                logger.info(f"Fallback warmup {symbol} {timeframe}: {len(candles)} bars via fallback provider")
            else:
                logger.error(f"No fallback data for {symbol} {timeframe} (premium-blocked, no fallback providers)")
        except FinnhubCandleError as exc:
            WARMUP_FAILURES.labels(symbol=symbol, tf=timeframe, reason="api_error").inc()
            logger.error(f"Error warming up {symbol} {timeframe}: {exc}")
        except Exception as exc:
            WARMUP_FAILURES.labels(symbol=symbol, tf=timeframe, reason="unexpected").inc()
            logger.exception(f"Unexpected error warming up {symbol} {timeframe}: {exc}")

    # ------------------------------------------------------------------
    # Fallback provider for premium-blocked symbols
    # ------------------------------------------------------------------

    async def try_fallback(self, symbol: str, timeframe: str, bars: int) -> list[dict[str, Any]]:
        """Attempt to fetch candles via the fallback provider chain.

        Returns an empty list if no fallback providers are configured or
        all providers fail.
        """
        try:
            from ingest.fallback_provider import FallbackCandleProvider  # noqa: PLC0415

            provider = FallbackCandleProvider()
            if not provider.available_providers:
                return []
            return await provider.fetch(symbol, timeframe, bars)
        except Exception as exc:
            logger.warning(f"Fallback provider failed for {symbol} {timeframe}: {exc}")
            return []

    # ------------------------------------------------------------------
    # M15 cold-start recovery
    # ------------------------------------------------------------------

    async def cold_start_m15(
        self,
        symbols: list[str] | None = None,
        bars: int = 100,
    ) -> dict[str, int]:
        """
        Fetch M15 candles from REST for all (or given) symbols.

        This is a recovery path for when the WebSocket has been disconnected
        long enough that in-memory M15 candle history is stale or empty.

        Args:
            symbols: Symbols to recover (default: all enabled in config).
            bars:    Number of M15 bars to fetch per symbol.

        Returns:
            Dict mapping symbol → number of M15 bars seeded.
        """
        if symbols is None:
            symbols = CONFIG["pairs"].get("symbols", [])

        if not symbols:
            logger.warning("cold_start_m15: no symbols to recover")
            return {}

        logger.info(
            "M15 cold-start recovery: fetching %d bars for %d symbols",
            bars,
            len(symbols),
        )

        seeded: dict[str, int] = {}

        for symbol in symbols:
            try:
                candles = await self.fetch(symbol, "M15", bars)
                if candles:
                    for candle in candles:
                        self.context_bus.update_candle(candle)
                    seeded[symbol] = len(candles)
                    logger.info(
                        "M15 cold-start: seeded %d bars for %s",
                        len(candles),
                        symbol,
                    )
                else:
                    logger.warning("M15 cold-start: no bars returned for {}", symbol)
            except FinnhubCandlePremiumError:
                logger.error("M15 cold-start: premium required for {}", symbol)
            except FinnhubCandleError as exc:
                logger.error("M15 cold-start error for {}: {}", symbol, exc)

        logger.info(
            "M15 cold-start complete: %d/%d symbols recovered",
            len(seeded),
            len(symbols),
        )
        return seeded

    # ------------------------------------------------------------------
    # Premium pair probe
    # ------------------------------------------------------------------

    async def probe_premium_pairs(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "H1",
    ) -> dict[str, str]:
        """
        Probe each symbol to classify it as ``free`` or ``premium``.

        Sends a minimal 1-bar fetch for each symbol and catches 403.

        Args:
            symbols:   Symbols to probe (default: all enabled).
            timeframe: Timeframe to test (default ``H1``).

        Returns:
            Dict mapping ``symbol`` → ``"free"`` | ``"premium"`` | ``"error"``.
            The result is also logged at INFO level for startup diagnostics.
        """
        if symbols is None:
            symbols = CONFIG["pairs"].get("symbols", [])

        if not symbols:
            logger.warning("probe_premium_pairs: no symbols to check")
            return {}

        logger.info(
            "Probing %d symbols for Finnhub premium requirements (%s) …",
            len(symbols),
            timeframe,
        )

        results: dict[str, str] = {}

        for symbol in symbols:
            try:
                candles = await self.fetch(symbol, timeframe, 1)
                results[symbol] = "free" if candles else "free"
            except FinnhubCandlePremiumError:
                results[symbol] = "premium"
                logger.warning("  {} → PREMIUM (403)", symbol)
            except FinnhubCandleError:
                results[symbol] = "error"
                logger.warning("  {} → ERROR (non-403 failure)", symbol)

        free_count = sum(1 for v in results.values() if v == "free")
        premium_count = sum(1 for v in results.values() if v == "premium")
        error_count = sum(1 for v in results.values() if v == "error")

        logger.info(
            "Premium probe complete: %d free, %d premium, %d errors",
            free_count,
            premium_count,
            error_count,
        )

        # Log sorted summary for easy reference
        if premium_count > 0:
            premium_symbols = sorted(k for k, v in results.items() if v == "premium")
            logger.warning(
                "Pairs requiring Finnhub premium: %s",
                premium_symbols,
            )

        return results
