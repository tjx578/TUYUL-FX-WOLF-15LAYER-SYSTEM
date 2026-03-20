"""
Fallback Data Provider — resilience layer for when Finnhub is unavailable.

Provides a pluggable chain of secondary REST candle sources that can
substitute for ``FinnhubCandleFetcher`` during outages. The module
exposes a single async ``fetch()`` that walks the provider chain in
priority order and returns on the first success.

Supported backends (env-key gated; disabled when key is absent):
  1. Twelve Data   — TWELVE_DATA_API_KEY
  2. Alpha Vantage — ALPHA_VANTAGE_API_KEY

All providers normalise candles to the same dict format used by
``FinnhubCandleFetcher.normalize_response()``, so downstream code
(``LiveContextBus.update_candles``) sees no difference.

When all configured providers fail (or none are configured), the provider
attempts a Redis stale-cache read as a last resort. If that also misses the
provider returns an empty list — it never raises — so the caller (and the
circuit breaker in ``ingest_service.py``) can decide how to handle
degregation. This prevents container crashes when all external APIs are
blocked (e.g. 403 Finnhub + 403 ForexFactory).

Cache keys follow the pattern:
    ``WOLF15:CANDLE_CACHE:{symbol}:{timeframe}``

Cache TTL is configurable via the ``WOLF15_CANDLE_CACHE_TTL_DAYS`` env var
(default: 7 days).

Usage::

    from ingest.fallback_provider import FallbackCandleProvider

    provider = FallbackCandleProvider()
    candles = await provider.fetch("EURUSD", "H1", bars=100)
    # Returns [] when all providers fail — never raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx

from core.redis_keys import CANDLE_CACHE_PREFIX

logger = logging.getLogger(__name__)


class FallbackProviderError(Exception):
    """Base exception for fallback provider failures."""


class ProviderResponseError(FallbackProviderError):
    """Raised when an upstream provider returns an invalid payload."""


# Redis cache TTL for persisted candles (default 7 days).
# Parsed defensively: a non-integer or non-positive env var falls back to the default.
def _parse_candle_cache_ttl() -> int:
    try:
        days = int(os.getenv("WOLF15_CANDLE_CACHE_TTL_DAYS", "7"))
        if days > 0:
            return days * 86_400
    except (ValueError, TypeError):
        pass
    logger.warning(
        "[FallbackProvider] Invalid WOLF15_CANDLE_CACHE_TTL_DAYS value '%s'; "
        "falling back to 7-day default",
        os.getenv("WOLF15_CANDLE_CACHE_TTL_DAYS"),
    )
    return 7 * 86_400


_CANDLE_CACHE_TTL_SECONDS: int = _parse_candle_cache_ttl()
_CANDLE_CACHE_KEY_PREFIX = CANDLE_CACHE_PREFIX
_SUPPORTED_INTRADAY_TIME_PARSE_FORMATS: tuple[str, ...] = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
_EXPECTED_CANDLE_KEYS: frozenset[str] = frozenset(
    {
        "symbol",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "timestamp",
        "source",
    }
)


# ══════════════════════════════════════════════════════════
#  Shared helpers
# ══════════════════════════════════════════════════════════

def _parse_provider_timestamp(value: str) -> datetime:
    """Parse provider timestamp strings into UTC datetimes.

    Args:
        value: Provider timestamp string.

    Returns:
        Timezone-aware UTC datetime.

    Raises:
        ValueError: If the timestamp cannot be parsed.
    """
    for fmt in _SUPPORTED_INTRADAY_TIME_PARSE_FORMATS:
        with contextlib.suppress(ValueError):
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_candle(
    *,
    symbol: str,
    timeframe: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    timestamp: datetime,
    source: str,
    volume: float = 0.0,
) -> dict[str, Any]:
    """Return a canonical candle payload matching Finnhub normalisation."""
    ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    ts_utc = ts_utc.astimezone(UTC)
    candle: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": float(open_price),
        "high": float(high_price),
        "low": float(low_price),
        "close": float(close_price),
        "volume": float(volume),
        "timestamp": ts_utc,
        "source": source,
    }
    return candle


def _serialize_candles(candles: list[dict[str, Any]]) -> str:
    """Serialize candles to a strict JSON payload for Redis cache storage."""
    serialized_rows: list[dict[str, Any]] = []
    for candle in candles:
        missing = _EXPECTED_CANDLE_KEYS.difference(candle)
        if missing:
            raise ProviderResponseError(
                f"Cannot serialize candle with missing keys: {sorted(missing)}"
            )

        timestamp = candle["timestamp"]
        if not isinstance(timestamp, datetime):
            raise ProviderResponseError("Cannot serialize candle with non-datetime timestamp")

        ts_utc = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
        ts_utc = ts_utc.astimezone(UTC)

        serialized_rows.append(
            {
                "symbol": str(candle["symbol"]),
                "timeframe": str(candle["timeframe"]),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle["volume"]),
                "timestamp": ts_utc.isoformat(),
                "source": str(candle["source"]),
            }
        )
    return json.dumps(serialized_rows, separators=(",", ":"))


def _aggregate_h4_from_h1(symbol: str, candles: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """Aggregate ordered H1 candles into ordered H4 candles.

    Drops incomplete trailing windows to avoid fabricating partial H4 bars.
    """
    if len(candles) < 4:
        return []

    ordered = sorted(
        candles,
        key=lambda candle: candle["timestamp"] if isinstance(candle["timestamp"], datetime) else datetime.min.replace(tzinfo=UTC),
    )
    aggregated: list[dict[str, Any]] = []
    for idx in range(0, len(ordered) - 3, 4):
        window = ordered[idx : idx + 4]
        if len(window) < 4:
            continue

        first = window[0]
        last = window[-1]
        aggregated.append(
            _normalize_candle(
                symbol=symbol,
                timeframe="H4",
                open_price=float(first["open"]),
                high_price=max(float(item["high"]) for item in window),
                low_price=min(float(item["low"]) for item in window),
                close_price=float(last["close"]),
                volume=sum(float(item.get("volume", 0.0)) for item in window),
                timestamp=last["timestamp"],
                source=source,
            )
        )
    return aggregated


# ══════════════════════════════════════════════════════════
#  Abstract base
# ══════════════════════════════════════════════════════════

class CandleProviderBase(ABC):
    """Interface every candle provider must implement."""

    name: str = "base"

    @abstractmethod
    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        """Return normalised candle dicts or raise on failure."""  


# ══════════════════════════════════════════════════════════
#  Twelve Data provider
# ══════════════════════════════════════════════════════════

class TwelveDataProvider(CandleProviderBase):
    """REST candle provider backed by Twelve Data (https://twelvedata.com)."""

    name = "twelve_data"

    # Twelve Data uses different interval tokens
    _INTERVAL_MAP: dict[str, str] = {
        "H1": "1h",
        "H4": "4h",
        "D1": "1day",
        "W1": "1week",
        "MN": "1month",
    }

    # Twelve Data forex symbols use slash notation
    @staticmethod
    def _convert_symbol(symbol: str) -> str:
        if len(symbol) == 6:
            return f"{symbol[:3]}/{symbol[3:]}"
        return symbol

    def __init__(self) -> None:
        self.api_key: str = os.getenv("TWELVE_DATA_API_KEY", "")
        self.base_url: str = "https://api.twelvedata.com"
        self.timeout: int = 20

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("TWELVE_DATA_API_KEY not configured")

        interval = self._INTERVAL_MAP.get(timeframe)
        if interval is None:
            raise ValueError(f"Unsupported timeframe for TwelveData: {timeframe}")

        td_symbol = self._convert_symbol(symbol)
        params: dict[str, Any] = {
            "symbol": td_symbol,
            "interval": interval,
            "outputsize": bars,
            "apikey": self.api_key,
            "dp": 5,
            "type": "forex",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/time_series", params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") == "error":
            raise RuntimeError(f"TwelveData error: {data.get('message', 'unknown')}")

        values = data.get("values", [])
        if not isinstance(values, list):
            raise ProviderResponseError("TwelveData response missing list 'values'")

        candles: list[dict[str, Any]] = []
        for row in reversed(values):  # API returns newest-first
            if not isinstance(row, dict):
                logger.warning("[TwelveData] Skipping non-dict candle row for %s %s", symbol, timeframe)
                continue
            try:
                ts = _parse_provider_timestamp(str(row["datetime"]))
                candles.append(
                    _normalize_candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        open_price=float(row["open"]),
                        high_price=float(row["high"]),
                        low_price=float(row["low"]),
                        close_price=float(row["close"]),
                        volume=0.0,
                        timestamp=ts,
                        source=self.name,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "[TwelveData] Skipping malformed candle row for %s %s: %s",
                    symbol,
                    timeframe,
                    exc,
                )

        logger.info(
            "[TwelveData] Fetched %d %s bars for %s", len(candles), timeframe, symbol,
        )
        return candles[-bars:] if bars > 0 else []


# ══════════════════════════════════════════════════════════
#  Alpha Vantage provider
# ══════════════════════════════════════════════════════════

class AlphaVantageProvider(CandleProviderBase):
    """REST candle provider backed by Alpha Vantage."""

    name = "alpha_vantage"

    _FUNCTION_MAP: dict[str, str] = {
        "H1": "FX_INTRADAY",
        "D1": "FX_DAILY",
        "W1": "FX_WEEKLY",
        "MN": "FX_MONTHLY",
    }

    _INTERVAL_MAP: dict[str, str] = {
        "H1": "60min",
    }

    def __init__(self) -> None:
        self.api_key: str = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.base_url: str = "https://www.alphavantage.co/query"
        self.timeout: int = 30

    @staticmethod
    def _split_symbol(symbol: str) -> tuple[str, str]:
        if len(symbol) == 6:
            return symbol[:3], symbol[3:]
        raise ValueError(f"Cannot split symbol: {symbol}")

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("ALPHA_VANTAGE_API_KEY not configured")

        effective_timeframe = "H1" if timeframe == "H4" else timeframe
        function = self._FUNCTION_MAP.get(effective_timeframe)
        if function is None:
            raise ValueError(f"Unsupported timeframe for AlphaVantage: {timeframe}")

        from_currency, to_currency = self._split_symbol(symbol)

        params: dict[str, Any] = {
            "function": function,
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "apikey": self.api_key,
            "datatype": "json",
            "outputsize": "full" if bars > 100 else "compact",
        }
        if function == "FX_INTRADAY":
            params["interval"] = self._INTERVAL_MAP[effective_timeframe]

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.base_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if "Error Message" in data or "Note" in data:
            msg = data.get("Error Message") or data.get("Note", "rate-limited")
            raise RuntimeError(f"AlphaVantage error: {msg}")

        ts_key = next((key for key in data if "Time Series" in key), None)
        if ts_key is None:
            raise ProviderResponseError("AlphaVantage response missing Time Series key")

        raw_series = data.get(ts_key)
        if not isinstance(raw_series, dict):
            raise ProviderResponseError("AlphaVantage Time Series payload is not a mapping")

        ordered_items = sorted(raw_series.items())
        if bars > 0 and timeframe != "H4":
            ordered_items = ordered_items[-bars:]

        candles: list[dict[str, Any]] = []
        for ts_str, vals in ordered_items:
            if not isinstance(vals, dict):
                logger.warning("[AlphaVantage] Skipping non-dict candle row for %s %s", symbol, timeframe)
                continue
            try:
                ts = _parse_provider_timestamp(ts_str)
                candles.append(
                    _normalize_candle(
                        symbol=symbol,
                        timeframe=effective_timeframe,
                        open_price=float(vals["1. open"]),
                        high_price=float(vals["2. high"]),
                        low_price=float(vals["3. low"]),
                        close_price=float(vals["4. close"]),
                        volume=0.0,
                        timestamp=ts,
                        source=self.name,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "[AlphaVantage] Skipping malformed candle row for %s %s: %s",
                    symbol,
                    timeframe,
                    exc,
                )

        if timeframe == "H4":
            candles = _aggregate_h4_from_h1(symbol, candles, self.name)
            if bars > 0:
                candles = candles[-bars:]

        logger.info(
            "[AlphaVantage] Fetched %d %s bars for %s", len(candles), timeframe, symbol,
        )
        return candles


# ══════════════════════════════════════════════════════════
#  Fallback chain orchestrator
# ══════════════════════════════════════════════════════════

class FallbackCandleProvider:
    """Walk a priority-ordered list of providers, returning the first success.

    Providers whose API key is missing are silently skipped.

    When all configured providers fail (or none are configured), the provider
    attempts a Redis stale-cache read as a last resort. If that also misses
    it returns an empty list — it never raises — so the circuit breaker in
    ``ingest_service.py`` can handle the degraded state gracefully.

    Successful fetches are written back to Redis with a configurable TTL
    (``WOLF15_CANDLE_CACHE_TTL_DAYS``, default 7 days) so that future runs
    can serve stale data when all live providers are blocked.

    Parameters
    ----------
    max_retries : int
        Per-provider retry count (default 1 = no retry).
    retry_delay : float
        Seconds between retries.
    redis_client : Any | None
        Optional async Redis client for cache read/write. When ``None``,
        cache operations are silently skipped.
    """

    def __init__(
        self,
        *,
        max_retries: int = 1,
        retry_delay: float = 1.0,
        redis_client: Any | None = None,
    ) -> None:
        self._providers: list[CandleProviderBase] = self._build_chain()
        self._max_retries = max(1, max_retries)
        self._retry_delay = max(0.0, retry_delay)
        self._redis: Any | None = redis_client

    @staticmethod
    def _build_chain() -> list[CandleProviderBase]:
        chain: list[CandleProviderBase] = []
        if os.getenv("TWELVE_DATA_API_KEY"):
            chain.append(TwelveDataProvider())
        if os.getenv("ALPHA_VANTAGE_API_KEY"):
            chain.append(AlphaVantageProvider())
        return chain

    @property
    def available_providers(self) -> list[str]:
        """Names of providers that have valid API keys configured."""
        return [provider.name for provider in self._providers]

    @staticmethod
    def _cache_key(symbol: str, timeframe: str) -> str:
        return f"{_CANDLE_CACHE_KEY_PREFIX}:{symbol}:{timeframe}"

    async def _write_cache(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict[str, Any]],
    ) -> None:
        """Write candles to Redis with TTL; silently skip on any error."""
        if self._redis is None or not candles:
            return

        key = self._cache_key(symbol, timeframe)
        try:
            serialized = _serialize_candles(candles)
            await self._redis.set(key, serialized, ex=_CANDLE_CACHE_TTL_SECONDS)
            logger.info(
                "[FallbackCache] Wrote %d bars for %s %s (ttl=%ds)",
                len(candles),
                symbol,
                timeframe,
                _CANDLE_CACHE_TTL_SECONDS,
            )
        except (ProviderResponseError, TypeError, ValueError) as exc:
            logger.warning(
                "[FallbackCache] Serialization failed for %s %s: %s",
                symbol,
                timeframe,
                exc,
            )
        except Exception as exc:
            logger.warning("[FallbackCache] Write failed for %s %s: %s", symbol, timeframe, exc)

    async def _read_cache(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Read candles from Redis cache; return empty list on miss or error.

        Timestamps stored as ISO strings are rehydrated back to ``datetime``
        objects so callers receive the same type as a live
        ``FinnhubCandleFetcher`` response.
        """
        if self._redis is None:
            return []

        key = self._cache_key(symbol, timeframe)
        try:
            raw = await self._redis.get(key)
            if not raw:
                return []

            payload = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            loaded = json.loads(payload)
            if not isinstance(loaded, list):
                raise ProviderResponseError("Cached candle payload is not a list")

            candles: list[dict[str, Any]] = []
            for row in loaded:
                if not isinstance(row, dict):
                    logger.warning("[FallbackCache] Skipping non-dict cached candle for %s %s", symbol, timeframe)
                    continue
                try:
                    candles.append(
                        _normalize_candle(
                            symbol=str(row["symbol"]),
                            timeframe=str(row["timeframe"]),
                            open_price=float(row["open"]),
                            high_price=float(row["high"]),
                            low_price=float(row["low"]),
                            close_price=float(row["close"]),
                            volume=float(row.get("volume", 0.0)),
                            timestamp=_parse_provider_timestamp(str(row["timestamp"])),
                            source=str(row["source"]),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning(
                        "[FallbackCache] Skipping malformed cached candle for %s %s: %s",
                        symbol,
                        timeframe,
                        exc,
                    )

            if candles:
                logger.warning(
                    "[FallbackCache] Serving %d stale bars for %s %s (all live providers failed)",
                    len(candles),
                    symbol,
                    timeframe,
                )
            return candles
        except Exception as exc:
            logger.warning("[FallbackCache] Read failed for %s %s: %s", symbol, timeframe, exc)
            return []

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        """Attempt each provider in order; fall back to Redis cache; return [] on total miss.

        Returns
        -------
        list[dict[str, Any]]
            Normalised candle dicts identical to ``FinnhubCandleFetcher`` output.
            Empty list when no provider and no cache entry succeeded.

        Notes
        -----
        This method never raises. All provider failures are logged as warnings.
        Callers should treat an empty return as a degradation signal.
        """
        if not self._providers:
            logger.warning(
                "[Fallback] No fallback data providers configured "
                "(set TWELVE_DATA_API_KEY or ALPHA_VANTAGE_API_KEY) — "
                "attempting stale cache for %s %s",
                symbol,
                timeframe,
            )
            return await self._read_cache(symbol, timeframe)

        last_error: Exception | None = None
        for provider in self._providers:
            for attempt in range(1, self._max_retries + 1):
                try:
                    candles = await provider.fetch(symbol, timeframe, bars)
                    if candles:
                        logger.info(
                            "[Fallback] %s succeeded for %s %s (%d bars)",
                            provider.name,
                            symbol,
                            timeframe,
                            len(candles),
                        )
                        await self._write_cache(symbol, timeframe, candles)
                        return candles
                except (httpx.HTTPError, RuntimeError, ValueError, ProviderResponseError) as exc:
                    last_error = exc
                    logger.warning(
                        "[Fallback] %s attempt %d/%d failed for %s %s: %s: %s",
                        provider.name,
                        attempt,
                        self._max_retries,
                        symbol,
                        timeframe,
                        exc.__class__.__name__,
                        exc,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_delay)
                except Exception as exc:
                    last_error = exc
                    logger.exception(
                        "[Fallback] Unexpected %s failure for %s %s on attempt %d/%d",
                        provider.name,
                        symbol,
                        attempt,
                        self._max_retries,
                    )
                    break

        logger.warning(
            "[Fallback] All providers exhausted for %s %s (last_error=%s) — "
            "attempting stale cache",
            symbol,
            timeframe,
            last_error,
        )
        cached = await self._read_cache(symbol, timeframe)
        if not cached:
            logger.warning(
                "[Fallback] No stale cache for %s %s — returning empty list",
                symbol,
                timeframe,
            )
        return cached
