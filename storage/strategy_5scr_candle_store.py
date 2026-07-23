"""PostgreSQL read adapter for authoritative Strategy 5S-CR candles."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contracts.canonical_candle import CanonicalCandle, as_utc
from storage.postgres_client import PostgresClient, pg_client

_REQUIRED_COLUMNS = frozenset(
    {
        "symbol",
        "timeframe",
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "tick_count",
        "complete",
        "selected_provider",
        "provider_timestamp_semantics",
    }
)


@dataclass(frozen=True)
class ClosedCandleSchemaStatus:
    missing_columns: tuple[str, ...]
    closed_asof_index_present: bool

    @property
    def ready(self) -> bool:
        return not self.missing_columns and self.closed_asof_index_present


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


class PostgresClosedCandleStore:
    """Read immutable, explicitly complete candles at an as-of cutoff."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    async def schema_status(self) -> ClosedCandleSchemaStatus:
        if not self._pg.is_available:
            return ClosedCandleSchemaStatus(
                missing_columns=tuple(sorted(_REQUIRED_COLUMNS)),
                closed_asof_index_present=False,
            )
        column_rows = await self._pg.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'canonical_candles'
            """
        )
        index_rows = await self._pg.fetch(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'canonical_candles'
              AND indexname = 'ix_canonical_candles_closed_asof'
            """
        )
        present = {str(_row_value(row, "column_name") or "") for row in column_rows}
        indexes = {str(_row_value(row, "indexname") or "") for row in index_rows}
        return ClosedCandleSchemaStatus(
            missing_columns=tuple(sorted(_REQUIRED_COLUMNS - present)),
            closed_asof_index_present="ix_canonical_candles_closed_asof" in indexes,
        )

    async def load_closed_candles(
        self,
        *,
        symbol: str,
        timeframe: str,
        as_of_utc: datetime,
        limit: int,
    ) -> Sequence[CanonicalCandle]:
        cutoff = as_utc(as_of_utc, "as_of_utc")
        if not self._pg.is_available:
            return ()
        rows = await self._pg.fetch(
            """
            SELECT symbol, timeframe, open_time, close_time,
                   open, high, low, close, volume, tick_count,
                   complete, selected_provider AS provider,
                   provider_timestamp_semantics
            FROM canonical_candles
            WHERE symbol = $1
              AND timeframe = $2
              AND complete = TRUE
              AND provider_timestamp_semantics <> 'UNSPECIFIED'
              AND close_time <= $3
            ORDER BY close_time DESC
            LIMIT $4
            """,
            symbol.upper(),
            timeframe.upper(),
            cutoff,
            max(1, int(limit)),
        )
        candles = [
            CanonicalCandle.model_validate(
                {
                    "symbol": str(_row_value(row, "symbol")).upper(),
                    "timeframe": str(_row_value(row, "timeframe")).upper(),
                    "open_time": _row_value(row, "open_time"),
                    "close_time": _row_value(row, "close_time"),
                    "open": float(_row_value(row, "open")),
                    "high": float(_row_value(row, "high")),
                    "low": float(_row_value(row, "low")),
                    "close": float(_row_value(row, "close")),
                    "volume": float(_row_value(row, "volume", 0.0) or 0.0),
                    "tick_count": int(_row_value(row, "tick_count", 0) or 0),
                    "complete": _row_value(row, "complete") is True,
                    "provider": str(_row_value(row, "provider") or "unknown"),
                    "provider_timestamp_semantics": str(
                        _row_value(row, "provider_timestamp_semantics") or "UNSPECIFIED"
                    ).upper(),
                }
            )
            for row in rows
        ]
        candles.sort(key=lambda candle: candle.open_time)
        return tuple(candles)


__all__ = ["ClosedCandleSchemaStatus", "PostgresClosedCandleStore"]
