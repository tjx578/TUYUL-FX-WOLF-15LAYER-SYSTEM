"""Backfill canonical H1 from M15 and H4 from H1 without partial windows."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from config_loader import get_enabled_symbols
from ingest.candle_builder import Candle
from ingest.canonical_rollup import aggregate_contiguous_candles
from storage.candle_persistence import (
    drain_candle_persistence,
    enqueue_candle,
)
from storage.postgres_client import pg_client


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


def _row_to_candle(row: Any) -> Candle:
    return Candle(
        symbol=str(_value(row, "symbol")).upper(),
        timeframe=str(_value(row, "timeframe")).upper(),
        open_time=_value(row, "open_time"),
        close_time=_value(row, "close_time"),
        open=float(_value(row, "open")),
        high=float(_value(row, "high")),
        low=float(_value(row, "low")),
        close=float(_value(row, "close")),
        volume=float(_value(row, "volume", 0.0) or 0.0),
        tick_count=int(_value(row, "tick_count", 0) or 0),
        complete=_value(row, "complete") is True,
        provider=str(_value(row, "selected_provider") or "unknown"),
        provider_timestamp_semantics=str(_value(row, "provider_timestamp_semantics") or "UNSPECIFIED").upper(),
        provider_timestamp=_value(row, "open_time"),
        provider_feed=str(_value(row, "selected_feed") or "canonical"),
    )


async def _load_candles(
    *,
    symbols: Sequence[str],
    timeframe: str,
    from_utc: datetime,
    to_utc: datetime,
) -> list[Candle]:
    rows = await pg_client.fetch(
        """
        SELECT symbol, timeframe, open_time, close_time,
               open, high, low, close, volume, tick_count, complete,
               selected_provider, selected_feed, provider_timestamp_semantics
        FROM canonical_candles
        WHERE symbol = ANY($1::text[])
          AND timeframe = $2
          AND complete = TRUE
          AND provider_timestamp_semantics <> 'UNSPECIFIED'
          AND open_time >= $3
          AND close_time <= $4
        ORDER BY symbol, open_time
        """,
        list(symbols),
        timeframe,
        from_utc,
        to_utc,
    )
    return [_row_to_candle(row) for row in rows]


async def run_backfill(
    *,
    symbols: Sequence[str],
    from_utc: datetime,
    to_utc: datetime,
    dry_run: bool,
) -> dict[str, Any]:
    await pg_client.initialize()
    if not pg_client.is_available:
        raise RuntimeError("DATABASE_URL is required for canonical H1/H4 backfill")

    normalized_symbols = tuple(sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()}))
    m15 = await _load_candles(
        symbols=normalized_symbols,
        timeframe="M15",
        from_utc=from_utc,
        to_utc=to_utc,
    )
    h1_rollups = aggregate_contiguous_candles(
        m15,
        source_timeframe="M15",
        target_timeframe="H1",
    )
    h1_written = 0
    h4_written = 0
    if not dry_run:
        for candle in h1_rollups:
            enqueue_candle(candle)
        h1_written = await drain_candle_persistence()
        h1_source = await _load_candles(
            symbols=normalized_symbols,
            timeframe="H1",
            from_utc=from_utc,
            to_utc=to_utc,
        )
    else:
        existing_h1 = await _load_candles(
            symbols=normalized_symbols,
            timeframe="H1",
            from_utc=from_utc,
            to_utc=to_utc,
        )
        by_window = {(item.symbol, item.open_time): item for item in existing_h1}
        by_window.update({(item.symbol, item.open_time): item for item in h1_rollups})
        h1_source = list(by_window.values())

    h4_rollups = aggregate_contiguous_candles(
        h1_source,
        source_timeframe="H1",
        target_timeframe="H4",
    )
    if not dry_run:
        for candle in h4_rollups:
            enqueue_candle(candle)
        h4_written = await drain_candle_persistence()

    return {
        "event": "strategy_5scr_canonical_h1_h4_backfill",
        "dry_run": dry_run,
        "symbols": len(normalized_symbols),
        "from_utc": from_utc.isoformat(),
        "to_utc": to_utc.isoformat(),
        "source_m15": len(m15),
        "candidate_h1": len(h1_rollups),
        "written_h1": h1_written,
        "source_h1": len(h1_source),
        "candidate_h4": len(h4_rollups),
        "written_h4": h4_written,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-utc", required=True, type=_parse_utc)
    parser.add_argument("--to-utc", required=True, type=_parse_utc)
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


async def _async_main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.to_utc <= args.from_utc:
        raise SystemExit("--to-utc must be after --from-utc")
    try:
        result = await run_backfill(
            symbols=args.symbols or get_enabled_symbols(),
            from_utc=args.from_utc,
            to_utc=args.to_utc,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    finally:
        await pg_client.close()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
