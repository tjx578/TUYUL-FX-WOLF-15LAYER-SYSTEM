"""
Forex Factory HTML provider (last resort, explicit opt-in only).

This provider scrapes the Forex Factory calendar HTML page.
It is disabled by default and must be explicitly enabled via:
  NEWS_FF_HTML_FALLBACK_ENABLED=true

HTML scraping is fragile and should only be used when all other
providers are unavailable.

Configuration (env / .env):
  FF_HTML_URL                — override full URL (default FF calendar)
  FF_HTML_TIMEOUT_SECONDS    — request timeout (default 15)
  FF_HTML_MAX_RETRIES        — max retry attempts (default 2)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from news.exceptions import (
    HtmlFallbackDisabledError,
    ProviderParseError,
    ProviderUnavailableError,
)
from news.models import EconomicEvent, SourceConfidence
from news.normalizers.forexfactory_normalizer import normalize_ff_events

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://www.forexfactory.com/calendar"


class ForexFactoryHtmlProvider:
    """
    FF HTML scraper — last-resort fallback.

    Instantiating this provider does NOT check the enable flag.
    The ``fetch_day()`` call raises ``HtmlFallbackDisabledError`` at
    runtime if the flag is not set, so the provider selector can
    optionally include it in the chain and let the service layer
    decide whether to call it.
    """

    name: str = "forexfactory_html"
    source_confidence: str = SourceConfidence.LOW.value

    def __init__(self) -> None:
        self._url = os.getenv("FF_HTML_URL", _DEFAULT_URL)
        self._timeout = float(os.getenv("FF_HTML_TIMEOUT_SECONDS", "15"))
        self._max_retries = int(os.getenv("FF_HTML_MAX_RETRIES", "2"))

    async def fetch_day(self, date_str: str) -> list[EconomicEvent]:
        """
        Scrape events for *date_str* from Forex Factory HTML.

        Raises
        ------
        HtmlFallbackDisabledError
            If NEWS_FF_HTML_FALLBACK_ENABLED is not 'true'.
        ProviderUnavailableError
            If the page cannot be fetched.
        ProviderParseError
            If the HTML cannot be parsed.
        """
        if os.getenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false").lower() != "true":
            raise HtmlFallbackDisabledError()

        fetched_at = datetime.now(UTC)

        attempt = 0
        last_exc: Exception | None = None
        resp: httpx.Response | None = None

        headers = {"User-Agent": ("Mozilla/5.0 (compatible; EconomicCalendarBot/1.0)")}

        while attempt < self._max_retries:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                    resp = await client.get(self._url, headers=headers)
                    resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                raise ProviderUnavailableError(self.name, f"HTTP {exc.response.status_code}") from exc
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exc = exc
                attempt += 1
                import asyncio

                await asyncio.sleep(min(2**attempt, 15))
        else:
            raise ProviderUnavailableError(self.name, f"All retries exhausted: {last_exc}")

        if resp is None:
            raise ProviderUnavailableError(self.name, "No response received")

        raw_events = self._parse_html(resp.text, date_str)
        return normalize_ff_events(raw_events, date_str=date_str, fetched_at=fetched_at)

    def _parse_html(self, html: str, date_str: str) -> list[dict[str, Any]]:
        """
        Parse FF calendar HTML into raw event dicts.

        This is a best-effort parser.  FF's HTML structure changes
        occasionally so this may produce partial results.
        """
        try:
            from html.parser import HTMLParser
        except ImportError as exc:
            raise ProviderParseError(self.name, "html.parser unavailable") from exc

        # Prefer BeautifulSoup if available (more robust)
        try:
            from bs4 import BeautifulSoup  # type: ignore[import-untyped]

            return self._parse_with_bs4(html, date_str, BeautifulSoup)
        except ImportError:
            pass

        raise ProviderParseError(
            self.name,
            "BeautifulSoup (beautifulsoup4) is required for HTML parsing. "
            "Install it or disable NEWS_FF_HTML_FALLBACK_ENABLED.",
        )

    @staticmethod
    def _parse_with_bs4(html: str, date_str: str, bs4: Any) -> list[dict[str, Any]]:
        """Parse with BeautifulSoup when available."""
        soup = bs4(html, "html.parser")
        events: list[dict[str, Any]] = []

        for row in soup.select("tr.calendar__row"):
            title_el = row.select_one(".calendar__event-title")
            currency_el = row.select_one(".calendar__currency")
            time_el = row.select_one(".calendar__time")
            impact_el = row.select_one(".calendar__impact span")
            actual_el = row.select_one(".calendar__actual")
            forecast_el = row.select_one(".calendar__forecast")
            previous_el = row.select_one(".calendar__previous")

            title = title_el.get_text(strip=True) if title_el else ""
            currency = currency_el.get_text(strip=True) if currency_el else ""
            time_str = time_el.get_text(strip=True) if time_el else ""
            impact_raw = impact_el.get("class", [""])[0] if impact_el else ""
            actual = actual_el.get_text(strip=True) if actual_el else None
            forecast = forecast_el.get_text(strip=True) if forecast_el else None
            previous = previous_el.get_text(strip=True) if previous_el else None

            # Map impact from CSS class
            impact = "Low"
            if "high" in impact_raw.lower():
                impact = "High"
            elif "medium" in impact_raw.lower():
                impact = "Medium"

            events.append(
                {
                    "title": title,
                    "currency": currency,
                    "date": date_str,
                    "time": time_str,
                    "impact": impact,
                    "actual": actual or None,
                    "forecast": forecast or None,
                    "previous": previous or None,
                }
            )

        return events
