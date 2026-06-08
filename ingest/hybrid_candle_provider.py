"""Hybrid REST candle repair provider.

Finnhub is the primary REST repair provider.  Substitute providers are used
only as backups when Finnhub fails, is rate-limited, or returns no usable live
data.  The order can still be overridden with
``WOLF_REPAIR_SUBSTITUTE_FIRST_SYMBOLS`` for emergency provider isolation.

Repair calls deliberately use live provider calls only so an old Redis cache is
not rewritten as fresh data.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from ingest.fallback_provider import FallbackCandleProvider
from ingest.finnhub_candles import FinnhubCandleFetcher

_DEFAULT_SUBSTITUTE_FIRST_SYMBOLS = frozenset()
_REPAIR_SUBSTITUTE_FIRST_ENV = "WOLF_REPAIR_SUBSTITUTE_FIRST_SYMBOLS"


def _coerce_symbol_set(symbols: Iterable[str] | str | None) -> set[str]:
    """Normalize a symbol list, supporting ``*`` for all and ``none`` for off."""
    if symbols is None:
        return set(_DEFAULT_SUBSTITUTE_FIRST_SYMBOLS)

    raw_items = symbols.split(",") if isinstance(symbols, str) else symbols

    normalized = {str(item).strip().upper() for item in raw_items if str(item).strip()}
    if normalized & {"", "NONE", "FALSE", "0", "OFF", "DISABLED"}:
        return set()
    if "*" in normalized or "ALL" in normalized:
        return {"*"}
    return normalized


def _load_substitute_first_symbols_from_env() -> set[str]:
    return _coerce_symbol_set(os.getenv(_REPAIR_SUBSTITUTE_FIRST_ENV))


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

    - Default: Finnhub first for all symbols, substitute providers only as
      backup.
    - Override: set ``WOLF_REPAIR_SUBSTITUTE_FIRST_SYMBOLS`` to a comma-separated
      symbol list or ``*``/``ALL`` for every symbol when an emergency needs a
      substitute-first repair path.
    """

    def __init__(
        self,
        *,
        finnhub_fetcher: Any | None = None,
        fallback_provider: FallbackCandleProvider | None = None,
        redis_client: Any | None = None,
        substitute_first_symbols: Iterable[str] | str | None = None,
        commodity_first_symbols: Iterable[str] | str | None = None,
    ) -> None:
        self._finnhub = finnhub_fetcher or FinnhubCandleFetcher()
        self._fallback = fallback_provider or FallbackCandleProvider(redis_client=redis_client)
        # ``commodity_first_symbols`` is kept as a compatibility alias for older
        # callers/tests, but the runtime concept is now substitute-first repair.
        configured_symbols = (
            substitute_first_symbols
            if substitute_first_symbols is not None
            else commodity_first_symbols
            if commodity_first_symbols is not None
            else _load_substitute_first_symbols_from_env()
        )
        self._substitute_first_symbols = _coerce_symbol_set(configured_symbols)

    def prefers_substitute_first(self, symbol: str) -> bool:
        normalized = str(symbol or "").strip().upper()
        return "*" in self._substitute_first_symbols or normalized in self._substitute_first_symbols

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
            first = await self._fetch_substitute(symbol, timeframe, bars, reason="substitute_first")
            if first.ok:
                return first
            second = await self._fetch_finnhub(symbol, timeframe, bars, reason="finnhub_fallback")
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
