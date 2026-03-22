"""
Finnhub economic calendar provider (secondary fallback).

Fetches from Finnhub's REST API:
  GET /calendar/economic?from=YYYY-MM-DD&to=YYYY-MM-DD&token=<key>

Configuration (env / .env):
  FINNHUB_API_KEY            — primary API key (reuses existing key system)
  FINNHUB_BASE_URL           — override base URL
  FINNHUB_TIMEOUT_SECONDS    — request timeout (default 10)
  FINNHUB_MAX_RETRIES        — max retry attempts (default 3)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from news.exceptions import ProviderParseError, ProviderUnavailableError
from news.models import EconomicEvent, SourceConfidence
from news.normalizers.finnhub_normalizer import normalize_finnhub_events

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider:
    """Finnhub economic calendar provider."""

    name: str = "finnhub"
    source_confidence: str = SourceConfidence.MEDIUM.value

    def __init__(self) -> None:
        self._base_url = os.getenv("FINNHUB_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = float(os.getenv("FINNHUB_TIMEOUT_SECONDS", "10"))
        self._max_retries = int(os.getenv("FINNHUB_MAX_RETRIES", "3"))
        self._api_key = self._resolve_api_key()

    @staticmethod
    def _resolve_api_key() -> str | None:
        """
        Resolve the active Finnhub API key.

        Tries the existing key manager first (for automatic rotation),
        then falls back to the raw env var.
        """
        try:
            from ingest.finnhub_key_manager import finnhub_keys

            key = finnhub_keys.current_key()
            if key:
                return key
        except Exception:
            pass
        return os.getenv("FINNHUB_API_KEY") or None

    async def fetch_day(self, date_str: str) -> list[EconomicEvent]:
        """Fetch events for *date_str* from Finnhub."""
        fetched_at = datetime.now(UTC)

        api_key = self._resolve_api_key()
        if not api_key:
            logger.warning("Finnhub API key not configured — skipping provider")
            return []

        url = f"{self._base_url}/calendar/economic"
        params = {"from": date_str, "to": date_str, "token": api_key}

        attempt = 0
        last_exc: Exception | None = None

        while attempt < self._max_retries:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (401, 403):
                    raise ProviderUnavailableError(
                        self.name, f"Auth error HTTP {code} — check FINNHUB_API_KEY"
                    ) from exc
                raise ProviderUnavailableError(self.name, f"HTTP {code}") from exc
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                attempt += 1
                logger.debug("Finnhub retry %d/%d: %s", attempt, self._max_retries, exc)
                import asyncio

                await asyncio.sleep(min(2**attempt, 10))
        else:
            raise ProviderUnavailableError(self.name, f"All {self._max_retries} retries exhausted: {last_exc}")

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderParseError(self.name, f"JSON decode error: {exc}") from exc

        raw_events: list[dict[str, Any]] = []
        if isinstance(data, dict):
            raw_events = data.get("economicCalendar", [])
        elif isinstance(data, list):
            raw_events = data

        return normalize_finnhub_events(raw_events, fetched_at=fetched_at)
