"""
Forex Factory JSON provider (primary).

Fetches calendar data from the Forex Factory JSON endpoint:
  https://nfs.faireconomy.media/ff_calendar_thisweek.json  (current week)
  https://nfs.faireconomy.media/ff_calendar_nextweek.json  (next week)

Configuration (env / .env):
  FF_JSON_BASE_URL          — override base URL
  FF_JSON_TIMEOUT_SECONDS   — request timeout (default 10)
  FF_JSON_MAX_RETRIES       — max retry attempts (default 3)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from news.exceptions import ProviderParseError, ProviderUnavailableError
from news.models import EconomicEvent, SourceConfidence
from news.normalizers.forexfactory_normalizer import normalize_ff_events
from news.validation.parse_health_tracker import ParseHealthTracker
from news.validation.schema_validator import validate_ff_events

logger = logging.getLogger(__name__)

# Module-level singleton for parse health tracking
_parse_health = ParseHealthTracker(
    window_seconds=3600,
    degraded_threshold=0.10,
    critical_threshold=0.30,
)

_DEFAULT_BASE_URL = "https://nfs.faireconomy.media"
_CURRENT_WEEK_PATH = "/ff_calendar_thisweek.json"
_NEXT_WEEK_PATH = "/ff_calendar_nextweek.json"


class ForexFactoryJsonProvider:
    """Primary FF JSON calendar provider."""

    name: str = "forexfactory_json"
    source_confidence: str = SourceConfidence.HIGH.value

    def __init__(self) -> None:
        self._base_url = os.getenv("FF_JSON_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = float(os.getenv("FF_JSON_TIMEOUT_SECONDS", "10"))
        self._max_retries = int(os.getenv("FF_JSON_MAX_RETRIES", "3"))
        self._parse_health = _parse_health

    async def fetch_day(self, date_str: str) -> list[EconomicEvent]:
        """
        Fetch all events for *date_str* from FF JSON.

        Tries the current-week feed first, then the next-week feed.
        Events are filtered to only those matching *date_str*.
        """
        fetched_at = datetime.now(UTC)

        for path in [_CURRENT_WEEK_PATH, _NEXT_WEEK_PATH]:
            url = self._base_url + path
            try:
                raw_events = await self._fetch_json(url)
                day_events = [e for e in raw_events if e.get("date", "")[:10] == date_str]
                if day_events:
                    # Schema validation before normalization
                    valid_events, invalid_events, _ = validate_ff_events(day_events)
                    for _ in valid_events:
                        self._parse_health.record_success(self.name)
                    for inv in invalid_events:
                        self._parse_health.record_failure(
                            self.name,
                            f"schema_validation_failed: {inv.get('title', 'unknown')}",
                        )
                    if not valid_events:
                        logger.warning(
                            "All %d FF events for %s failed validation",
                            len(day_events),
                            date_str,
                        )
                        continue
                    return normalize_ff_events(valid_events, date_str=date_str, fetched_at=fetched_at)
            except ProviderUnavailableError:
                logger.warning("FF JSON unavailable at %s", url)
                continue
            except ProviderParseError:
                logger.warning("FF JSON parse error at %s", url)
                continue

        # Return empty — caller will try next provider
        return []

    async def _fetch_json(self, url: str) -> list[dict[str, Any]]:
        """Fetch and parse a FF JSON feed URL."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await self._get_with_retry(client, url)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailableError(self.name, f"HTTP {exc.response.status_code} from {url}") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError(self.name, f"Request error: {exc}") from exc

        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderParseError(self.name, f"JSON decode error: {exc}") from exc

        if not isinstance(data, list):
            # Some FF endpoints wrap in a dict
            if isinstance(data, dict):
                data = data.get("data", data.get("events", []))
            if not isinstance(data, list):
                raise ProviderParseError(self.name, f"Expected list, got {type(data)}")

        return data

    async def _get_with_retry(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """Wrapper that applies retry logic via tenacity."""
        attempt = 0
        last_exc: Exception | None = None
        while attempt < self._max_retries:
            try:
                return await client.get(url)
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                attempt += 1
                logger.debug("FF JSON retry %d/%d for %s: %s", attempt, self._max_retries, url, exc)
                import asyncio

                await asyncio.sleep(min(2**attempt, 10))
        raise ProviderUnavailableError(self.name, f"All {self._max_retries} retries exhausted: {last_exc}")
