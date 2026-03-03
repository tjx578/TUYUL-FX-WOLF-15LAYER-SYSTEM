"""Finnhub client aliases for ingestion workers."""

from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.finnhub_ws import FinnhubWebSocket

__all__ = ["FinnhubCandleFetcher", "FinnhubWebSocket"]
