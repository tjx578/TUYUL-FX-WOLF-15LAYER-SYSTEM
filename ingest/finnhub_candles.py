"""
Finnhub REST candle fetcher for historical data warmup.

Fetches H1, D1, W1 from Finnhub /forex/candle API.
H4 is aggregated from H1 bars (4:1).
M15 is normally built from ticks, but REST fallback is available
for cold-start recovery via ``FinnhubCandleFetcher.cold_start_m15()``.
"""

import asyncio
import os

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from loguru import logger

from config_loader import CONFIG, load_finnhub
from context.live_context_bus import LiveContextBus


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

    def _convert_symbol(self, symbol: str) -> str:
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
        now = datetime.now(timezone.utc)

        # Calculate time delta with 25% buffer
        buffer_multiplier = 1.25

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

    def _normalize_response(self, data: dict[str, Any], symbol: str, timeframe: str) -> list[dict[str, Any]]:
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

        candles = []
        for i in range(length):
            # Convert Unix timestamp to datetime
            timestamp = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)

            candle = {
                "symbol": symbol,
                "timeframe": timeframe,
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
                "timestamp": timestamp,
                "source": "rest_api",
            }
            candles.append(candle)

        return candles

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
                "M15 REST fallback activated for %s — normally built from WS ticks",
                symbol,
            )

        # H4 is aggregated from H1
        if timeframe == "H4":
            h1_bars = bars * 4  # Need 4× H1 bars to make H4 bars
            h1_candles = await self.fetch(symbol, "H1", h1_bars)
            return self._aggregate_h4(h1_candles)

        if timeframe not in self.RESOLUTION_MAP:
            raise FinnhubCandleError(f"Unsupported timeframe: {timeframe}")

        finnhub_symbol = self._convert_symbol(symbol)
        resolution = self.RESOLUTION_MAP[timeframe]
        from_ts = self._calculate_from_ts(bars, timeframe)
        to_ts = int(datetime.now(timezone.utc).timestamp())

        url = f"{self.base_url}/forex/candle"
        params = {
            "symbol": finnhub_symbol,
            "resolution": resolution,
            "from": from_ts,
            "to": to_ts,
            "token": self._key_manager.current_key() or self.api_key,
        }
        self.api_key = params["token"]  # keep in sync

        async with self.semaphore:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    logger.debug(f"Fetching {symbol} {timeframe}: {bars} bars from Finnhub")
                    response = await client.get(url, params=params)

                    if response.status_code == 403:
                        self._key_manager.report_failure(self.api_key, 403)
                        raise FinnhubCandlePremiumError(
                            f"Premium access required for {symbol} {timeframe}"
                        )

                    if response.status_code == 429:
                        self._key_manager.report_failure(self.api_key, 429)
                        # Refresh key (may have rotated)
                        self.api_key = self._key_manager.current_key()
                        # Rate limited - exponential backoff
                        wait_time = float(response.headers.get("Retry-After", 2))
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        # Retry once with (possibly new) key
                        params["token"] = self.api_key
                        response = await client.get(url, params=params)

                    response.raise_for_status()
                    data = response.json()

                    self._key_manager.report_success(self.api_key)
                    candles = self._normalize_response(data, symbol, timeframe)
                    logger.info(f"Fetched {len(candles)} {timeframe} bars for {symbol}")

                    # Delay to respect rate limits
                    await asyncio.sleep(self.request_delay)

                    return candles

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    raise FinnhubCandlePremiumError(str(exc)) from exc
                raise FinnhubCandleError(f"HTTP error fetching {symbol} {timeframe}: {exc}") from exc
            except Exception as exc:
                raise FinnhubCandleError(f"Error fetching {symbol} {timeframe}: {exc}") from exc

    def _aggregate_h4(self, h1_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Aggregate H1 bars into H4 bars (4:1).

        H4 alignment: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC.
        H1 timestamps represent the END of the period.

        Args:
            h1_candles: List of H1 candles

        Returns:
            List of H4 candles
        """
        if not h1_candles:
            return []

        h4_candles = []
        current_group: list[dict[str, Any]] = []

        for h1 in h1_candles:
            timestamp = h1["timestamp"]
            if isinstance(timestamp, datetime):
                ts = timestamp
            else:
                ts = datetime.fromtimestamp(timestamp, tz=timezone.utc)

            # Determine H4 period start for this H1 bar
            # H1 timestamp is the END of the period (e.g., 01:00 means 00:00-01:00)
            # So the H1 bar start time is timestamp - 1 hour
            h1_start_hour = ts.hour - 1
            if h1_start_hour < 0:
                h1_start_hour = 23

            # H4 periods: 00-04, 04-08, 08-12, 12-16, 16-20, 20-00
            h4_period_start_hour = (h1_start_hour // 4) * 4

            # Create H4 period start timestamp
            h4_period_start = ts.replace(hour=h4_period_start_hour, minute=0, second=0, microsecond=0)
            if h1_start_hour < ts.hour - 1:  # Wrapped around midnight
                h4_period_start = h4_period_start - timedelta(days=1)

            # Check if this H1 belongs to current group
            if current_group:
                first_ts = current_group[0]["timestamp"]
                if isinstance(first_ts, datetime):
                    first_dt = first_ts
                else:
                    first_dt = datetime.fromtimestamp(first_ts, tz=timezone.utc)

                first_h1_start_hour = first_dt.hour - 1
                if first_h1_start_hour < 0:
                    first_h1_start_hour = 23

                first_h4_period_start_hour = (first_h1_start_hour // 4) * 4
                first_h4_period_start = first_dt.replace(
                    hour=first_h4_period_start_hour,
                    minute=0,
                    second=0,
                    microsecond=0
                )
                if first_h1_start_hour < first_dt.hour - 1:
                    first_h4_period_start = first_h4_period_start - timedelta(days=1)

                if h4_period_start != first_h4_period_start:
                    # Complete the previous H4 candle
                    h4_candles.append(self._build_h4_candle(current_group))
                    current_group = []

            current_group.append(h1)

        # Don't forget the last group
        if current_group:
            h4_candles.append(self._build_h4_candle(current_group))

        logger.debug(f"Aggregated {len(h1_candles)} H1 bars into {len(h4_candles)} H4 bars")
        return h4_candles

    def _build_h4_candle(self, h1_group: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Build a single H4 candle from a group of H1 candles.

        Args:
            h1_group: List of H1 candles (up to 4)

        Returns:
            H4 candle dict
        """
        first = h1_group[0]
        last = h1_group[-1]

        # Aggregate OHLCV
        opens = [c["open"] for c in h1_group]
        highs = [c["high"] for c in h1_group]
        lows = [c["low"] for c in h1_group]
        closes = [c["close"] for c in h1_group]
        volumes = [c["volume"] for c in h1_group]

        # H4 timestamp is the close time of the last H1 in the group
        timestamp = last["timestamp"]
        if not isinstance(timestamp, datetime):
            timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)

        return {
            "symbol": first["symbol"],
            "timeframe": "H4",
            "open": opens[0],
            "high": max(highs),
            "low": min(lows),
            "close": closes[-1],
            "volume": sum(volumes),
            "timestamp": timestamp,
            "source": "h1_aggregated",
        }

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

        # Get enabled symbols from config
        enabled_symbols = CONFIG["pairs"].get("symbols", [])
        if not enabled_symbols:
            logger.warning("No enabled symbols found for warmup")
            return {}

        warmup_bars = self.warmup_config.get("bars", 100)

        # Ensure required timeframes are always present for analysis.
        REQUIRED_TIMEFRAMES = ["H1", "H4", "D1", "W1", "MN"]

        configured_tfs = self.warmup_config.get("timeframes")
        if not configured_tfs:
            timeframes = REQUIRED_TIMEFRAMES
        else:
            # Preserve required order, then append any additional configured TFs (exclude M15)
            timeframes = list(REQUIRED_TIMEFRAMES)
            for tf in configured_tfs:
                if tf not in timeframes and tf != "M15":
                    timeframes.append(tf)

        logger.info(
            f"Starting warmup for {len(enabled_symbols)} symbols, "
            f"{len(timeframes)} timeframes, {warmup_bars} bars each"
        )

        results: dict[str, dict[str, list[dict[str, Any]]]] = {}

        # Create tasks for all symbol/timeframe combinations
        tasks = [
            self._warmup_symbol_tf(symbol, tf, warmup_bars, results)
            for symbol in enabled_symbols
            for tf in timeframes
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(f"Warmup complete: {len(results)} symbols warmed up")
        return results

    async def _warmup_symbol_tf(
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
                logger.warning(f"No candles fetched for {symbol} {timeframe}")
                return

            # Seed LiveContextBus
            for candle in candles:
                self.context_bus.update_candle(candle)

            # Store in results
            if symbol not in results:
                results[symbol] = {}
            results[symbol][timeframe] = candles

            logger.debug(
                f"Warmup {symbol} {timeframe}: {len(candles)} bars seeded to LiveContextBus"
            )

        except FinnhubCandlePremiumError:
            logger.error(f"Premium access required for {symbol} {timeframe}")
        except FinnhubCandleError as exc:
            logger.error(f"Error warming up {symbol} {timeframe}: {exc}")
        except Exception as exc:
            logger.exception(f"Unexpected error warming up {symbol} {timeframe}: {exc}")

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
                    logger.warning("M15 cold-start: no bars returned for %s", symbol)
            except FinnhubCandlePremiumError:
                logger.error("M15 cold-start: premium required for %s", symbol)
            except FinnhubCandleError as exc:
                logger.error("M15 cold-start error for %s: %s", symbol, exc)

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
                logger.warning("  %s → PREMIUM (403)", symbol)
            except FinnhubCandleError:
                results[symbol] = "error"
                logger.warning("  %s → ERROR (non-403 failure)", symbol)

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
