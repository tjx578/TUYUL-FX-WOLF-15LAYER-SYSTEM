"""Validate authoritative Strategy 5S-CR candle coverage for all enabled pairs."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, TypedDict

from config_loader import get_enabled_symbols
from storage.postgres_client import pg_client

_MINIMUM_BARS = {
    "D1": 3,
    "H4": 4,
    "H1": 2,
    "M15": 3,
    "M1": 3,
}


class CoverageRow(TypedDict):
    symbol: str
    timeframe: str
    candle_count: int
    minimum_required: int
    latest_close_time: str | None


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


async def validate_coverage(
    *,
    symbols: Sequence[str],
    as_of_utc: datetime,
) -> dict[str, Any]:
    normalized = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()}))
    timeframes = tuple(_MINIMUM_BARS)
    rows = await pg_client.fetch(
        """
        WITH requested(symbol, timeframe) AS (
            SELECT symbol, timeframe
            FROM unnest($1::text[]) AS symbol
            CROSS JOIN unnest($2::text[]) AS timeframe
        ),
        coverage AS (
            SELECT symbol, timeframe, count(*)::bigint AS candle_count,
                   max(close_time) AS latest_close_time
            FROM canonical_candles
            WHERE symbol = ANY($1::text[])
              AND timeframe = ANY($2::text[])
              AND complete = TRUE
              AND provider_timestamp_semantics <> 'UNSPECIFIED'
              AND close_time <= $3
            GROUP BY symbol, timeframe
        )
        SELECT requested.symbol, requested.timeframe,
               coalesce(coverage.candle_count, 0) AS candle_count,
               coverage.latest_close_time
        FROM requested
        LEFT JOIN coverage USING (symbol, timeframe)
        ORDER BY requested.symbol, requested.timeframe
        """,
        list(normalized),
        list(timeframes),
        as_of_utc,
    )
    future_rows = await pg_client.fetch(
        """
        SELECT symbol, timeframe, count(*)::bigint AS candle_count
        FROM canonical_candles
        WHERE symbol = ANY($1::text[])
          AND timeframe = ANY($2::text[])
          AND complete = TRUE
          AND close_time > $3
        GROUP BY symbol, timeframe
        ORDER BY symbol, timeframe
        """,
        list(normalized),
        list(timeframes),
        as_of_utc,
    )
    coverage_rows: list[CoverageRow] = [
        {
            "symbol": str(_value(row, "symbol")),
            "timeframe": str(_value(row, "timeframe")),
            "candle_count": int(_value(row, "candle_count", 0) or 0),
            "minimum_required": _MINIMUM_BARS[str(_value(row, "timeframe"))],
            "latest_close_time": (
                _value(row, "latest_close_time").isoformat() if _value(row, "latest_close_time") is not None else None
            ),
        }
        for row in rows
    ]
    missing = [row for row in coverage_rows if row["candle_count"] < row["minimum_required"]]
    future = [
        {
            "symbol": str(_value(row, "symbol")),
            "timeframe": str(_value(row, "timeframe")),
            "candle_count": int(_value(row, "candle_count", 0) or 0),
        }
        for row in future_rows
    ]
    return {
        "event": "strategy_5scr_canonical_candle_coverage",
        "as_of_utc": as_of_utc.isoformat(),
        "symbols": len(normalized),
        "expected_symbols": 30,
        "timeframes": list(timeframes),
        "required_combinations": len(normalized) * len(timeframes),
        "ready_combinations": len(coverage_rows) - len(missing),
        "missing_or_insufficient": missing,
        "future_complete_candles": future,
        "future_candle_leakage_detected": bool(future),
        "ready": len(normalized) == 30 and not missing and not future,
        "coverage": coverage_rows,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of-utc", type=_parse_utc, default=datetime.now(UTC))
    parser.add_argument("--symbols", nargs="*", default=None)
    return parser


async def _async_main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    await pg_client.initialize()
    if not pg_client.is_available:
        raise RuntimeError("DATABASE_URL is required for canonical candle coverage validation")
    try:
        result = await validate_coverage(
            symbols=args.symbols or get_enabled_symbols(),
            as_of_utc=args.as_of_utc,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ready"] else 2
    finally:
        await pg_client.close()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
