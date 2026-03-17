"""Raw tick normalization helpers for ingest service."""

from datetime import UTC, datetime
from typing import Any


def normalize_tick(symbol: str, bid: float, ask: float, volume: float | None = None) -> dict[str, Any]:
    ts = datetime.now(UTC).isoformat()
    return {
        "symbol": symbol,
        "bid": float(bid),
        "ask": float(ask),
        "mid": round((float(bid) + float(ask)) / 2.0, 6),
        "volume": float(volume or 0.0),
        "timestamp": ts,
    }
