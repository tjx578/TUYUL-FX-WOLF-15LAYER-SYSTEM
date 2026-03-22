from __future__ import annotations

from collections.abc import Sequence

import pytest

from news.exceptions import NoProvidersConfiguredError
from news.provider_selector import build_provider_chain


def _names(chain: Sequence[object]) -> list[str]:
    return [getattr(p, "name", "") for p in chain]


def test_provider_selector_forexfactory_default_chain() -> None:
    chain = build_provider_chain(news_provider="forexfactory", html_fallback_enabled=False)
    assert _names(chain)[:3] == ["forexfactory_json", "forexfactory_xml", "finnhub"]


def test_provider_selector_finnhub_chain() -> None:
    chain = build_provider_chain(news_provider="finnhub", html_fallback_enabled=False)
    assert _names(chain)[:3] == ["finnhub", "forexfactory_json", "forexfactory_xml"]


def test_provider_selector_html_flag_appends_fallback() -> None:
    chain = build_provider_chain(news_provider="forexfactory", html_fallback_enabled=True)
    assert _names(chain)[-1] == "forexfactory_html"


def test_provider_selector_off_raises() -> None:
    with pytest.raises(NoProvidersConfiguredError):
        build_provider_chain(news_provider="off", html_fallback_enabled=False)
