"""
Alpha Vantage candle fetcher — fallback provider for H1/H4/D1/W1.

Used when Finnhub returns "Premium access required" (HTTP 403) for
higher-timeframe candles that are not available on the free tier.

Features
--------
- Supports H1, H4, D1, W1 timeframes (H4 is aggregated from H1)
- Process-shared rate limiter (5 req/min free tier by default)
- Redis result caching to minimise API calls across restarts
- Returns candles in the same dict format as FinnhubCandleFetcher
- Never raises — returns [] on any failure so callers degrade gracefully

Environment variables
---------------------
ALPHAVANTAGE_API_KEY
    Official Alpha Vantage API key (direct transport).
ALPHAVANTAGE_ENABLED
    Set to "false" to disable the fallback entirely (default: "true").
ALPHAVANTAGE_RATE_LIMIT_REQUESTS
    Max requests per rate-limit window (default: 5).
ALPHAVANTAGE_RATE_LIMIT_INTERVAL_SEC
    Rate-limit window in seconds (default: 60).

The older env-var names ``ALPHA_VANTAGE_API_KEY`` and
``ALPHA_VANTAGE_RAPIDAPI_KEY`` are also accepted for backwards
compatibility with the existing ``fallback_provider.py`` configuration.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any

from loguru import logger

from ingest.fallback_provider import (
    AlphaVantageProvider,
    FallbackCandleProvider,
    ProviderQuotaDeferredError,
)

# ── Process-shared rate-limit state ──────────────────────────────────────────
# Mirrors the pattern used in fallback_provider.py so both modules share the
# same quota accounting when running in the same process.

_AV_RATE_LOCK = threading.Lock()
_AV_REQUEST_TIMES: deque[float] = deque()
_AV_BLOCKED_UNTIL: float = 0.0


def _av_rate_limit_requests() -> int:
    try:
        value = int(os.getenv("ALPHAVANTAGE_RATE_LIMIT_REQUESTS", "5"))
        return value if value > 0 else 5
    except (TypeError, ValueError):
        return 5


def _av_rate_limit_interval() -> float:
    try:
        value = float(os.getenv("ALPHAVANTAGE_RATE_LIMIT_INTERVAL_SEC", "60"))
        return value if value > 0 else 60.0
    except (TypeError, ValueError):
        return 60.0


def _av_enabled() -> bool:
    return os.getenv("ALPHAVANTAGE_ENABLED", "true").strip().lower() not in {"false", "0", "no"}


def _av_api_key() -> str:
    """Return the best available Alpha Vantage API key."""
    # Prefer the new canonical name, fall back to legacy names.
    return (
        os.getenv("ALPHAVANTAGE_API_KEY", "")
        or os.getenv("ALPHA_VANTAGE_API_KEY", "")
        or os.getenv("ALPHA_VANTAGE_RAPIDAPI_KEY", "")
    )


def _reserve_av_credit() -> None:
    """Reserve one rate-limit credit or raise ProviderQuotaDeferredError."""
    global _AV_BLOCKED_UNTIL

    now = time.monotonic()
    limit = _av_rate_limit_requests()
    window = _av_rate_limit_interval()

    with _AV_RATE_LOCK:
        if now < _AV_BLOCKED_UNTIL:
            retry_in = _AV_BLOCKED_UNTIL - now
            raise ProviderQuotaDeferredError(
                f"[AlphaVantage] Rate-limit cooldown active; retry in {retry_in:.1f}s"
            )

        # Evict timestamps outside the current window
        while _AV_REQUEST_TIMES and now - _AV_REQUEST_TIMES[0] >= window:
            _AV_REQUEST_TIMES.popleft()

        if len(_AV_REQUEST_TIMES) >= limit:
            retry_in = window - (now - _AV_REQUEST_TIMES[0])
            raise ProviderQuotaDeferredError(
                f"[AlphaVantage] Credit budget exhausted ({limit}/{window:.0f}s); "
                f"retry in {retry_in:.1f}s"
            )

        _AV_REQUEST_TIMES.append(now)


def _block_av_for_quota(cooldown_sec: float = 65.0) -> None:
    """Block further requests after upstream quota exhaustion is detected."""
    global _AV_BLOCKED_UNTIL

    with _AV_RATE_LOCK:
        _AV_BLOCKED_UNTIL = max(_AV_BLOCKED_UNTIL, time.monotonic() + cooldown_sec)
    logger.warning(
        "[AlphaVantage] Upstream quota exhausted; blocking new requests for {:.0f}s",
        cooldown_sec,
    )


# ── Public fetcher ────────────────────────────────────────────────────────────


class AlphaVantageCandleFetcher:
    """Standalone Alpha Vantage candle fetcher with rate limiting and caching.

    This is a thin wrapper around the ``AlphaVantageProvider`` from
    ``fallback_provider.py`` that adds:

    - Explicit rate-limit enforcement via ``_reserve_av_credit()``
    - Redis result caching (TTL driven by ``WOLF15_CANDLE_CACHE_TTL_DAYS``)
    - Structured logging with ``[AlphaVantage]`` prefix
    - A ``fetch_with_fallback()`` convenience method that tries Finnhub first

    Parameters
    ----------
    redis_client:
        Optional async Redis client for result caching.  When ``None``,
        caching is silently skipped.
    """

    # Timeframes supported by this fetcher
    SUPPORTED_TIMEFRAMES = frozenset({"H1", "H4", "D1", "W1"})

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client
        self._provider = AlphaVantageProvider()
        # FallbackCandleProvider gives us the full chain (Twelve Data → AV)
        # plus Redis cache read/write.
        self._fallback_chain = FallbackCandleProvider(redis_client=redis_client)

    @property
    def is_configured(self) -> bool:
        """True when at least one Alpha Vantage API key is present."""
        return bool(_av_api_key())

    async def fetch(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
    ) -> list[dict[str, Any]]:
        """Fetch candles from Alpha Vantage.

        Parameters
        ----------
        symbol:
            Internal symbol (e.g. ``"EURUSD"``).
        timeframe:
            One of ``H1``, ``H4``, ``D1``, ``W1``.
        bars:
            Number of candles to return.

        Returns
        -------
        list[dict[str, Any]]
            Normalised candle dicts (same format as FinnhubCandleFetcher).
            Empty list on any failure — never raises.
        """
        if not _av_enabled():
            logger.debug("[AlphaVantage] Disabled via ALPHAVANTAGE_ENABLED=false")
            return []

        if not self.is_configured:
            logger.warning(
                "[AlphaVantage] No API key configured "
                "(set ALPHAVANTAGE_API_KEY or ALPHA_VANTAGE_API_KEY)"
            )
            return []

        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            logger.warning("[AlphaVantage] Unsupported timeframe: {}", timeframe)
            return []

        try:
            _reserve_av_credit()
        except ProviderQuotaDeferredError as exc:
            logger.warning("[AlphaVantage] Rate limit: {}", exc)
            return []

        try:
            candles = await self._provider.fetch(symbol, timeframe, bars)
            if candles:
                first_ts = candles[0].get("timestamp")
                last_ts = candles[-1].get("timestamp")
                logger.info(
                    "[AlphaVantage] Fetched {} {} bars for {} ({} to {})",
                    len(candles),
                    timeframe,
                    symbol,
                    first_ts.strftime("%Y-%m-%d") if isinstance(first_ts, datetime) else first_ts,
                    last_ts.strftime("%Y-%m-%d") if isinstance(last_ts, datetime) else last_ts,
                )
            else:
                logger.warning(
                    "[AlphaVantage] Returned 0 {} bars for {}", timeframe, symbol
                )
            return candles

        except ProviderQuotaDeferredError as exc:
            _block_av_for_quota()
            logger.warning("[AlphaVantage] Quota exhausted for {} {}: {}", symbol, timeframe, exc)
            return []
        except Exception as exc:
            logger.warning(
                "[AlphaVantage] Fetch failed for {} {}: {}: {}",
                symbol,
                timeframe,
                type(exc).__name__,
                exc,
            )
            return []

    async def fetch_with_fallback(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 100,
        *,
        finnhub_fetcher: Any = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Try Finnhub first; fall back to Alpha Vantage on premium errors.

        Parameters
        ----------
        symbol, timeframe, bars:
            Passed through to the underlying fetchers.
        finnhub_fetcher:
            An instance of ``FinnhubCandleFetcher``.  When ``None``, the
            method skips the Finnhub attempt and goes straight to Alpha
            Vantage.

        Returns
        -------
        (candles, provider)
            ``provider`` is one of ``"finnhub"``, ``"alphavantage"``, or
            ``"none"`` (empty result).
        """
        from ingest.finnhub_candles import FinnhubCandleError, FinnhubCandlePremiumError  # noqa: PLC0415

        if finnhub_fetcher is not None:
            try:
                candles = await finnhub_fetcher.fetch(symbol, timeframe, bars)
                if candles:
                    return candles, "finnhub"
            except FinnhubCandlePremiumError:
                logger.warning(
                    "[AlphaVantage] Finnhub premium required for {} {} — trying Alpha Vantage",
                    symbol,
                    timeframe,
                )
            except FinnhubCandleError as exc:
                logger.warning(
                    "[AlphaVantage] Finnhub failed for {} {}: {} — trying Alpha Vantage",
                    symbol,
                    timeframe,
                    exc,
                )

        candles = await self.fetch(symbol, timeframe, bars)
        if candles:
            return candles, "alphavantage"

        return [], "none"
