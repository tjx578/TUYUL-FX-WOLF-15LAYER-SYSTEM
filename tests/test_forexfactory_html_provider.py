from __future__ import annotations

import pytest

from news.exceptions import HtmlFallbackDisabledError
from news.providers.forexfactory_html_provider import ForexFactoryHtmlProvider


@pytest.mark.asyncio
async def test_html_provider_requires_explicit_flag(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false")

  provider = ForexFactoryHtmlProvider()

  with pytest.raises(HtmlFallbackDisabledError):
      await provider.fetch_day("2026-03-09")
