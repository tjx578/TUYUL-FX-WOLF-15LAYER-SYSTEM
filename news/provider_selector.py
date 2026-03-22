"""
Provider selector.

Builds the ordered provider chain from environment configuration:

  NEWS_PROVIDER=forexfactory  → [FF JSON, FF XML, Finnhub, (FF HTML if enabled)]
  NEWS_PROVIDER=finnhub       → [Finnhub, FF JSON, FF XML, (FF HTML if enabled)]
  NEWS_PROVIDER=off           → []  (no external fetching)

HTML fallback is included ONLY when NEWS_FF_HTML_FALLBACK_ENABLED=true.
"""

from __future__ import annotations

import os

from news.exceptions import NoProvidersConfiguredError
from news.provider_protocol import NewsProvider


def build_provider_chain(
    *,
    news_provider: str | None = None,
    html_fallback_enabled: bool | None = None,
) -> list[NewsProvider]:
    """
    Build and return the ordered provider chain.

    Parameters
    ----------
    news_provider : str | None
        Override for NEWS_PROVIDER env var (useful in tests).
    html_fallback_enabled : bool | None
        Override for NEWS_FF_HTML_FALLBACK_ENABLED env var.

    Returns
    -------
    list[NewsProvider]
        Ordered list of provider instances.  May be empty if provider=off.

    Raises
    ------
    NoProvidersConfiguredError
        If NEWS_PROVIDER=off — callers should handle this gracefully.
    """
    provider_setting = (news_provider or os.getenv("NEWS_PROVIDER", "forexfactory")).lower().strip()

    if provider_setting == "off":
        raise NoProvidersConfiguredError()

    html_enabled = html_fallback_enabled
    if html_enabled is None:
        html_enabled = os.getenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false").lower() == "true"

    # Lazy imports to avoid import cycles and unnecessary dependencies
    from news.providers.finnhub_provider import FinnhubProvider
    from news.providers.forexfactory_json_provider import ForexFactoryJsonProvider
    from news.providers.forexfactory_xml_provider import ForexFactoryXmlProvider

    ff_json = ForexFactoryJsonProvider()
    ff_xml = ForexFactoryXmlProvider()
    finnhub = FinnhubProvider()

    if provider_setting == "forexfactory":
        chain: list[NewsProvider] = [ff_json, ff_xml, finnhub]
    elif provider_setting == "finnhub":
        chain = [finnhub, ff_json, ff_xml]
    else:
        # Unknown provider — default to forexfactory chain
        chain = [ff_json, ff_xml, finnhub]

    if html_enabled:
        from news.providers.forexfactory_html_provider import ForexFactoryHtmlProvider

        chain.append(ForexFactoryHtmlProvider())

    return chain
