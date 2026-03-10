"""
Fallback Data Provider — resilience layer for when Finnhub is unavailable.

Provides a pluggable chain of secondary REST candle sources that can
substitute for ``FinnhubCandleFetcher`` during outages.  The module
exposes a single async ``fetch()`` that walks the provider chain in
priority order and returns on the first success.

Supported backends (env-key gated; disabled when key is absent):
  1. Twelve Data   — TWELVE_DATA_API_KEY
  2. Alpha Vantage — ALPHA_VANTAGE_API_KEY

All providers normalise candles to the same dict format used by
``FinnhubCandleFetcher.normalize_response()``, so downstream code
(``LiveContextBus.update_candles``) sees no difference.

Usage::

    from ingest.fallback_provider import FallbackCandleProvider

    provider = FallbackCandleProvider()
    candles = await provider.fetch("EURUSD", "H1", bars=100)
"""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


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
        candles: list[dict[str, Any]] = []
        for v in reversed(values):  # API returns newest-first
            ts = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC,
            )
            candles.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "open": float(v["open"]),
                "high": float(v["high"]),
                "low": float(v["low"]),
                "close": float(v["close"]),
                "volume": 0,  # TwelveData forex volume unavailable
                "timestamp": ts,
                "source": "twelve_data",
            })

        logger.info(
            "[TwelveData] Fetched %d %s bars for %s", len(candles), timeframe, symbol,
        )
        return candles


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
        "H4": "60min",  # requires aggregation like Finnhub
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

        function = self._FUNCTION_MAP.get(timeframe)
        if function is None:
            raise ValueError(f"Unsupported timeframe for AlphaVantage: {timeframe}")

        from_currency, to_currency = self._split_symbol(symbol)

        params: dict[str, Any] = {
            "function": function,
            "from_symbol": from_currency,
            "to_symbol": to_currency,
            "apikey": self.api_key,
            "datatype": "json",
        }
        if function == "FX_INTRADAY":
            params["interval"] = self._INTERVAL_MAP.get(timeframe, "60min")
            params["outputsize"] = "full" if bars > 100 else "compact"
        else:
            params["outputsize"] = "full" if bars > 100 else "compact"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(self.base_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if "Error Message" in data or "Note" in data:
            msg = data.get("Error Message") or data.get("Note", "rate-limited")
            raise RuntimeError(f"AlphaVantage error: {msg}")

        # Find the time-series key (varies by function)
        ts_key = next((k for k in data if "Time Series" in k), None)
        if ts_key is None:
            raise RuntimeError("AlphaVantage response missing Time Series key")

        raw_series: dict[str, Any] = data[ts_key]

        candles: list[dict[str, Any]] = []
        for ts_str, vals in sorted(raw_series.items()):
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=UTC,
                )
            except ValueError:
                ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(
                    tzinfo=UTC,
                )

            candles.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "open": float(vals.get("1. open", 0)),
                "high": float(vals.get("2. high", 0)),
                "low": float(vals.get("3. low", 0)),
                "close": float(vals.get("4. close", 0)),
                "volume": 0,
                "timestamp": ts,
                "source": "alpha_vantage",
            })
            if len(candles) >= bars:
                break

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

    Parameters
    ----------
    max_retries : int
        Per-provider retry count (default 1 = no retry).
    retry_delay : float
        Seconds between retries.
    """

    def __init__(
        self,
        *,
        max_retries: int = 1,
        retry_delay: float = 1.0,
    ) -> None:
        self._providers: list[CandleProviderBase] = self._build_chain()
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    # ── Build chain from environment ────────────────────────────
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
        return [p.name for p in self._providers]

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        """Attempt each provider in order; raise if all fail.

        Returns
        -------
        list[dict[str, Any]]
            Normalised candle dicts identical to ``FinnhubCandleFetcher`` output.

        Raises
        ------
        RuntimeError
            If no provider succeeded (or none configured).
        """
        if not self._providers:
            raise RuntimeError(
                "No fallback data providers configured. "
                "Set TWELVE_DATA_API_KEY or ALPHA_VANTAGE_API_KEY."
            )

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
                        return candles
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning(
                        "[Fallback] %s attempt %d/%d failed for %s %s: %s",
                        provider.name,
                        attempt,
                        self._max_retries,
                        symbol,
                        timeframe,
                        exc,
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._retry_delay)

        raise RuntimeError(
            f"All fallback providers exhausted for {symbol} {timeframe}: {last_error}"
        )
