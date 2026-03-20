from __future__ import annotations

from collections.abc import Sequence

import pytest

from news.exceptions import NoProvidersConfiguredError
from news.provider_protocol import NewsProvider
from news.provider_selector import build_provider_chain


def _provider_names(chain: Sequence[NewsProvider]) -> list[str]:
    return [p.name for p in chain]


def test_provider_selector_forexfactory_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_PROVIDER", "forexfactory")
    monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false")

    names = _provider_names(build_provider_chain())

    assert names == ["forexfactory_json", "forexfactory_xml", "finnhub"]


def test_provider_selector_finnhub_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_PROVIDER", "finnhub")
    monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false")

    names = _provider_names(build_provider_chain())

    assert names == ["finnhub", "forexfactory_json", "forexfactory_xml"]


def test_provider_selector_off_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_PROVIDER", "off")
    monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "false")

    with pytest.raises(NoProvidersConfiguredError):
        build_provider_chain()


def test_provider_selector_html_opt_in_appends_html(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_PROVIDER", "forexfactory")
    monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "true")

    names = _provider_names(build_provider_chain())

    assert names[:3] == ["forexfactory_json", "forexfactory_xml", "finnhub"]
    assert names[-1] == "forexfactory_html"


def test_provider_selector_html_opt_in_with_finnhub_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEWS_PROVIDER", "finnhub")
    monkeypatch.setenv("NEWS_FF_HTML_FALLBACK_ENABLED", "true")

    names = _provider_names(build_provider_chain())

    assert names[:3] == ["finnhub", "forexfactory_json", "forexfactory_xml"]
    assert names[-1] == "forexfactory_html"
