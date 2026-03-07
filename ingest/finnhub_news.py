"""
Finnhub Economic Calendar Ingestion

Fetches upcoming economic events via Finnhub REST API.
NO TRADING DECISION.

Endpoint: GET /calendar/economic?from=YYYY-MM-DD&to=YYYY-MM-DD&token=KEY
"""

from __future__ import annotations

import asyncio
import os

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]

from loguru import logger

from config_loader import load_finnhub
from context.live_context_bus import LiveContextBus


class FinnhubNewsError(Exception):
    """Raised when Finnhub economic calendar fetch fails."""


class FinnhubNews:
    """
    Economic calendar & news ingestion via Finnhub REST API.

    Responsibilities:
      1. Poll /calendar/economic at configured interval
      2. Filter by impact level (high/medium/low)
      3. Normalize -> push to LiveContextBus
      4. Retry with exponential backoff on transient errors

    NO TRADING DECISION.
    """

    _MAX_RETRY_WAIT_SEC: int = 120

    def __init__(self) -> None:
        self._config = load_finnhub()
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415
        self._key_manager = finnhub_keys
        self._api_key: str = self._key_manager.current_key()
        self._base_url: str = self._config["rest"].get("base_url", "https://finnhub.io/api/v1")
        self._timeout: int = self._config["rest"].get("timeout_sec", 20)
        self._retries: int = self._config["rest"].get("retries", 3)
        self._backoff_factor: float = self._config["rest"].get("backoff_factor", 1.5)
        self._poll_interval: int = self._config["news"].get("poll_interval_sec", 300)
        self._impact_levels: dict[str, bool] = self._config["news"].get(
            "impact_levels", {"high": True, "medium": True, "low": False}
        )
        self._context_bus = LiveContextBus()

        if not self._api_key:
            logger.error("FINNHUB_API_KEY not set - economic calendar will fail")

    async def fetch_calendar(self) -> list[dict[str, Any]]:
        """
        Fetch economic calendar events for next 7 days.

        Returns:
            Filtered list of economic events matching configured
            impact levels.

        Raises:
            FinnhubNewsError: After exhausting retries.
        """
        today = datetime.now(UTC).date()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=7)).isoformat()

        url = f"{self._base_url}/calendar/economic"
        params: dict[str, str] = {
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }

        last_exc: Exception | None = None
        wait: float = 1.0

        for attempt in range(1, self._retries + 1):
            # Refresh key from manager (may have rotated).
            self._api_key = self._key_manager.current_key()
            params["token"] = self._api_key
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()

                self._key_manager.report_success(self._api_key)
                raw_events: list[dict[str, Any]] = data.get("economicCalendar", [])

                filtered = self._filter_by_impact(raw_events)
                logger.info(
                    f"Finnhub calendar: {len(raw_events)} total, "
                    f"{len(filtered)} after impact filter"
                )
                return filtered

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                self._key_manager.report_failure(self._api_key, exc.response.status_code)
                if exc.response.status_code == 429:
                    logger.warning(
                        f"Finnhub rate limited (attempt {attempt}/"
                        f"{self._retries}), waiting {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    wait *= self._backoff_factor
                elif exc.response.status_code == 403:
                    logger.error(
                        f"Finnhub HTTP 403 Forbidden - check API key permissions "
                        f"and endpoint URL: {url}"
                    )
                    raise FinnhubNewsError(f"HTTP 403 Forbidden: {url}") from exc
                else:
                    logger.error(f"Finnhub HTTP {exc.response.status_code}: {exc.response.text}")
                    raise FinnhubNewsError(f"HTTP {exc.response.status_code}") from exc

            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
                logger.warning(
                    f"Finnhub connection error (attempt {attempt}/{self._retries}): {exc}"
                )
                await asyncio.sleep(wait)
                wait = min(
                    wait * self._backoff_factor,
                    self._MAX_RETRY_WAIT_SEC,
                )

        raise FinnhubNewsError(f"Failed after {self._retries} retries: {last_exc}")

    def _filter_by_impact(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Filter events by impact level per config.

        Finnhub impact field: "high", "medium", "low"
        (or numeric 1=low, 2=medium, 3=high depending on API version)
        """
        allowed: set[str] = set()
        impact_map: dict[int, str] = {1: "low", 2: "medium", 3: "high"}

        for level, enabled in self._impact_levels.items():
            if enabled:
                allowed.add(level.lower())

        filtered: list[dict[str, Any]] = []
        for event in events:
            raw_impact = event.get("impact", "")

            # Handle both string and numeric impact
            if isinstance(raw_impact, int):
                impact = impact_map.get(raw_impact, "low")
            else:
                impact = str(raw_impact).lower()

            if impact in allowed:
                filtered.append(self._normalize_event(event, impact))

        return filtered

    @staticmethod
    def _normalize_event(event: dict[str, Any], impact: str) -> dict[str, Any]:
        """Normalize Finnhub economic event to internal format."""
        return {
            "event": event.get("event", ""),
            "country": event.get("country", ""),
            "impact": impact,
            "actual": event.get("actual"),
            "previous": event.get("prev"),
            "estimate": event.get("estimate"),
            "datetime": event.get("time", ""),
            "unit": event.get("unit", ""),
            "source": "finnhub",
        }

    async def run(self) -> None:
        """Main polling loop."""
        if not self._config["news"]["enabled"]:
            logger.warning("Finnhub news ingestion disabled in config")
            return

        logger.info(f"Finnhub news poller started (interval={self._poll_interval}s)")

        while True:
            try:
                events = await self.fetch_calendar()
                self._context_bus.update_news({"events": events, "source": "finnhub"})
                logger.info(f"Economic calendar updated: {len(events)} events")

            except FinnhubNewsError as exc:
                logger.error(f"Finnhub news fetch failed: {exc}")

            except Exception as exc:
                logger.error(f"Unexpected error in news poller: {exc}")

            await asyncio.sleep(self._poll_interval)
