"""
Custom exceptions for the news/calendar subsystem.
"""

from __future__ import annotations


class NewsSubsystemError(Exception):
    """Base class for all news subsystem errors."""


class ProviderUnavailableError(NewsSubsystemError):
    """Raised when a provider cannot be reached or returns an error response."""

    def __init__(self, provider: str, detail: str = "") -> None:
        self.provider = provider
        super().__init__(f"Provider '{provider}' unavailable: {detail}")


class ProviderParseError(NewsSubsystemError):
    """Raised when a provider response cannot be parsed."""

    def __init__(self, provider: str, detail: str = "") -> None:
        self.provider = provider
        super().__init__(f"Provider '{provider}' parse error: {detail}")


class InvalidEventDateError(NewsSubsystemError):
    """Raised when a date/time field from a provider cannot be parsed."""

    def __init__(self, raw_value: str, detail: str = "") -> None:
        self.raw_value = raw_value
        super().__init__(f"Cannot parse event datetime '{raw_value}': {detail}")


class InvalidTimestampError(NewsSubsystemError):
    """Raised when a Unix timestamp or ISO string is malformed."""

    def __init__(self, raw_value: str | int | float, detail: str = "") -> None:
        self.raw_value = raw_value
        super().__init__(f"Cannot parse timestamp '{raw_value}': {detail}")


class RepositoryError(NewsSubsystemError):
    """Raised for Redis or Postgres persistence failures."""


class NewsNormalizationError(NewsSubsystemError):
    """Raised when a raw provider event cannot be normalized safely."""


class HtmlFallbackDisabledError(NewsSubsystemError):
    """Raised when HTML fallback is requested but not enabled via config."""

    def __init__(self) -> None:
        super().__init__(
            "HTML fallback is disabled. "
            "Set NEWS_FF_HTML_FALLBACK_ENABLED=true to enable."
        )


class NoProvidersConfiguredError(NewsSubsystemError):
    """Raised when NEWS_PROVIDER=off or no provider chain is configured."""

    def __init__(self) -> None:
        super().__init__(
            "No news providers configured. "
            "Set NEWS_PROVIDER=forexfactory or NEWS_PROVIDER=finnhub."
        )
