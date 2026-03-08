"""
Forex Factory XML provider (fallback).

Fetches calendar data from the Forex Factory RSS/XML feed.
Used as the second fallback when the JSON endpoint is unavailable.

Configuration (env / .env):
  FF_XML_BASE_URL           — override base URL
  FF_XML_TIMEOUT_SECONDS    — request timeout (default 10)
  FF_XML_MAX_RETRIES        — max retry attempts (default 3)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from news.exceptions import ProviderParseError, ProviderUnavailableError
from news.models import EconomicEvent, SourceConfidence
from news.normalizers.forexfactory_normalizer import normalize_ff_events

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://www.forexfactory.com"
_XML_PATH = "/ffcal_week_this.xml"


class ForexFactoryXmlProvider:
    """FF XML / RSS feed fallback provider."""

    name: str = "forexfactory_xml"
    source_confidence: str = SourceConfidence.HIGH.value

    def __init__(self) -> None:
        self._base_url = os.getenv("FF_XML_BASE_URL", _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = float(os.getenv("FF_XML_TIMEOUT_SECONDS", "10"))
        self._max_retries = int(os.getenv("FF_XML_MAX_RETRIES", "3"))

    async def fetch_day(self, date_str: str) -> list[EconomicEvent]:
        """Fetch events for *date_str* from the FF XML feed."""
        fetched_at = datetime.now(UTC)
        url = self._base_url + _XML_PATH

        attempt = 0
        last_exc: Exception | None = None

        while attempt < self._max_retries:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                raise ProviderUnavailableError(
                    self.name, f"HTTP {exc.response.status_code}"
                ) from exc
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                attempt += 1
                logger.debug("FF XML retry %d/%d: %s", attempt, self._max_retries, exc)
                import asyncio
                await asyncio.sleep(min(2 ** attempt, 10))
        else:
            raise ProviderUnavailableError(
                self.name, f"All {self._max_retries} retries exhausted: {last_exc}"
            )

        raw_events = self._parse_xml(resp.text)
        day_events = [e for e in raw_events if e.get("date", "")[:10] == date_str]
        return normalize_ff_events(day_events, date_str=date_str, fetched_at=fetched_at)

    def _parse_xml(self, xml_text: str) -> list[dict[str, Any]]:
        """Parse FF XML feed into a list of raw event dicts."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise ProviderParseError(self.name, f"XML parse error: {exc}") from exc

        events: list[dict[str, Any]] = []
        for item in root.iter("event"):
            # FF XML schema: <title>, <country>, <date>, <time>, <impact>, etc.
            def get_text(tag: str) -> str:
                el = item.find(tag)
                return el.text.strip() if el is not None and el.text else ""

            events.append({
                "title": get_text("title"),
                "currency": get_text("country"),  # FF XML uses <country> for currency
                "date": get_text("date"),
                "time": get_text("time"),
                "impact": get_text("impact"),
                "actual": get_text("actual") or None,
                "forecast": get_text("forecast") or None,
                "previous": get_text("previous") or None,
                "url": get_text("url") or None,
            })

        return events
