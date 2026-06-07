"""Hybrid REST candle repair provider.

This keeps Finnhub as the normal forex REST source while allowing commodity
symbols to repair stale H1/HTF candles through configured substitute providers
first.  It deliberately uses live provider calls only for repair so an old Redis
cache is not rewritten as a fresh candle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from ingest.fallback_provider import FallbackCandleProvider
from ingest.finnhub_candles import FinnhubCandleFetcher

_COMMODITY_FIRST_SYMBOLS = frozenset({"XAUUSD", "XAGUSD"})


@dataclass(frozen=True)
class HybridCandleFetchResult:
    """Result metadata for a hybrid candle fetch attempt."""

    candles: list[dict[str, Any]]
    provider: str
    reason: str
    attempts: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.candles)


class HybridCandleProvider:
    """Select a REST candle provider according to symbol risk.

    - XAUUSD/XAGUSD: substitute providers first (Twelve Data, then Alpha
      Vantage), then Finnhub.  This targets the production symptom where gold
      HTF candles went stale while commodity-capable providers were available.
    - Other symbols: Finnhub first, then substitute providers on failure.
    """

    def __init__(
        self,
        *,
        finnhub_fetcher: Any | None = None,
        fallback_provider: FallbackCandleProvider | None = None,
        redis_client: Any | None = None,
        commodity_first_symbols: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._finnhub = finnhub_fetcher or FinnhubCandleFetcher()
        self._fallback = fallback_provider or FallbackCandleProvider(redis_client=redis_client)
        self._commodity_first_symbols = {
            str(symbol).strip().upper() for symbol in (commodity_first_symbols or _COMMODITY_FIRST_SYMBOLS)
        }

    def prefers_substitute_first(self, symbol: str) -> bool:
        return str(symbol or "").strip().upper() in self._commodity_first_symbols

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        *,
        substitute_first: bool | None = None,
    ) -> HybridCandleFetchResult:
        """Fetch candles using the configured hybrid order."""
        prefer_substitute = self.prefers_substitute_first(symbol) if substitute_first is None else substitute_first

        if prefer_substitute:
            first = await self._fetch_substitute(symbol, timeframe, bars, reason="commodity_substitute_first")
            if first.ok:
                return first
            second = await self._fetch_finnhub(symbol, timeframe, bars, reason="commodity_finnhub_fallback")
            if second.ok:
                return second
            return HybridCandleFetchResult(
                candles=[],
                provider="none",
                reason="all_live_providers_failed",
                attempts=first.attempts + second.attempts,
            )

        first = await self._fetch_finnhub(symbol, timeframe, bars, reason="finnhub_primary")
        if first.ok:
            return first
        second = await self._fetch_substitute(symbol, timeframe, bars, reason="finnhub_failed_substitute")
        if second.ok:
            return second
        return HybridCandleFetchResult(
            candles=[],
            provider="none",
            reason="all_live_providers_failed",
            attempts=first.attempts + second.attempts,
        )

    async def _fetch_finnhub(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        *,
        reason: str,
    ) -> HybridCandleFetchResult:
        try:
            candles = await self._finnhub.fetch(symbol, timeframe, bars)
            if candles:
                return HybridCandleFetchResult(
                    candles=candles,
                    provider=self._provider_from_candles(candles, default="finnhub"),
                    reason=reason,
                    attempts=("finnhub",),
                )
        except Exception as exc:
            logger.warning(
                "[HybridCandle] Finnhub fetch failed {} {} bars={}: {}: {}",
                symbol,
                timeframe,
                bars,
                type(exc).__name__,
                exc,
            )
        return HybridCandleFetchResult(candles=[], provider="none", reason=reason, attempts=("finnhub",))

    async def _fetch_substitute(
        self,
        symbol: str,
        timeframe: str,
        bars: int,
        *,
        reason: str,
    ) -> HybridCandleFetchResult:
        try:
            candles = await self._fallback.fetch(symbol, timeframe, bars, allow_stale_cache=False)
            if candles:
                return HybridCandleFetchResult(
                    candles=candles,
                    provider=self._provider_from_candles(candles, default="fallback"),
                    reason=reason,
                    attempts=tuple(self._fallback.available_providers) or ("fallback",),
                )
        except Exception as exc:
            logger.warning(
                "[HybridCandle] Substitute fetch failed {} {} bars={}: {}: {}",
                symbol,
                timeframe,
                bars,
                type(exc).__name__,
                exc,
            )
        return HybridCandleFetchResult(
            candles=[],
            provider="none",
            reason=reason,
            attempts=tuple(self._fallback.available_providers) or ("fallback",),
        )

    @staticmethod
    def _provider_from_candles(candles: list[dict[str, Any]], *, default: str) -> str:
        for candle in reversed(candles):
            source = str(candle.get("source") or "").strip().lower()
            if source:
                if source == "rest_api":
                    return "finnhub"
                return source
        return default
