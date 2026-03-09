"""
Provider protocol definition.

All concrete providers must implement this protocol so that the
provider selector and service layer can treat them uniformly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from news.models import EconomicEvent


@runtime_checkable
class NewsProvider(Protocol):
    """
    Protocol that all economic calendar providers must satisfy.

    name            : Human-readable identifier used in logs and metrics.
    source_confidence: Reliability tier ('high' | 'medium' | 'low').
    """

    name: str
    source_confidence: str  # 'high' | 'medium' | 'low'

    async def fetch_day(self, date_str: str) -> list[EconomicEvent]:
        """
        Fetch all economic events for a single calendar day.

        Parameters
        ----------
        date_str : str
            ISO date string, e.g. "2026-03-08".

        Returns
        -------
        list[EconomicEvent]
            Normalised canonical events for that day.
            Empty list if the provider has no events for that day.

        Raises
        ------
        ProviderUnavailableError
            If the remote endpoint cannot be reached.
        ProviderParseError
            If the response body cannot be parsed.
        """
        ...  # pragma: no cover
