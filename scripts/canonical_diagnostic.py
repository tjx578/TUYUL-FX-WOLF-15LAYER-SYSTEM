"""Diagnostic script for canonical_candles / raw_provider_candles data flow state.

Read-only queries against PostgreSQL. Safe to run in production.

Usage (from /app):
    python -m scripts.canonical_diagnostic
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from storage.postgres_client import pg_client

_AS_OF = "2026-07-24T04:00:00Z"

_REQUIRED_SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
    "USDCHF",
    "EURJPY",
    "GBPJPY",
    "AUDJPY",
    "XAUUSD",
    "XAGUSD",
    "XTIUSD",
    "XBRUSD",
    "SPX500",
    "IND",
    "DXY",
    "US10Y",
    "CN50",
    "JP225",
    "ES",
    "NQ",
    "ZB",
    "CL",
    "GC",
    "NG",
    "ZS",
    "ZW",
    "KT",
    "CT",
]

_REQUIRED_TIMEFRAMES = ["D1", "H4", "H1", "M15", "M1"]

_QUERY_VALID_CANONICAL = """
    SELECT symbol, timeframe, COUNT(*)::int as valid_count,
           MAX(close_time) as latest_close
    FROM canonical_candles
    WHERE complete = TRUE
      AND provider_timestamp_semantics <> 'UNSPECIFIED'
      AND close_time <= '2026-07-24T04:00:00Z'
    GROUP BY symbol, timeframe
    ORDER BY symbol, timeframe
"""

_QUERY_STUCK_DATA = """
    SELECT symbol, timeframe,
           SUM(CASE WHEN complete=FALSE THEN 1 ELSE 0 END)::int as incomplete_count,
           SUM(CASE WHEN provider_timestamp_semantics='UNSPECIFIED' THEN 1 ELSE 0 END)::int as unspec_count
    FROM canonical_candles
    WHERE close_time <= '2026-07-24T04:00:00Z'
    GROUP BY symbol, timeframe
    HAVING (SUM(CASE WHEN complete=FALSE THEN 1 ELSE 0 END) > 0
      OR SUM(CASE WHEN provider_timestamp_semantics='UNSPECIFIED' THEN 1 ELSE 0 END) > 0)
    ORDER BY symbol, timeframe
"""

_QUERY_RAW_PROVIDER = """
    SELECT provider, symbol, timeframe, COUNT(*)::int as count,
           MAX(last_observed_at) as last_seen
    FROM raw_provider_candles
    WHERE close_time <= '2026-07-24T04:00:00Z'
    GROUP BY provider, symbol, timeframe
    ORDER BY provider, symbol, timeframe
"""

_QUERY_VALIDATOR_MISSING = """
    WITH required AS (
     SELECT symbol, timeframe
     FROM unnest($1::text[]) AS symbol
     CROSS JOIN unnest($2::text[]) AS timeframe
    ),
    covered AS (
     SELECT symbol, timeframe, COUNT(*)::bigint as count
     FROM canonical_candles
     WHERE complete = TRUE
     AND provider_timestamp_semantics <> 'UNSPECIFIED'
     AND close_time <= $3
     GROUP BY symbol, timeframe
    )
    SELECT required.symbol, required.timeframe,
     COALESCE(covered.count, 0)::int as candle_count,
     COALESCE(covered.count, 0) >= 3 as meets_minimum
    FROM required
    LEFT JOIN covered USING (symbol, timeframe)
    WHERE COALESCE(covered.count, 0) < 3
    ORDER BY required.symbol, required.timeframe
"""


def _section(title: str) -> None:
    print("=" * 80)
    print(title)
    print("=" * 80)


def _subsection(title: str) -> None:
    print("-" * 80)
    print(title)
    print("-" * 80)


def _print_rows(rows: list, limit: int = 5) -> None:
    print(f"Rows returned: {len(rows)}")
    if not rows:
        return
    for row in rows[:limit]:
        print(f"  {dict(row)}")
    if len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more row(s)")


async def run_diagnostics() -> None:
    """Run the canonical candle / raw provider candle diagnostic queries."""
    await pg_client.initialize()

    print(f"Canonical Diagnostic Report - generated at {datetime.utcnow().isoformat()}Z")
    print(f"As-of cutoff: {_AS_OF}")

    _section("QUERY 1: VALID CANONICAL CANDLES")
    q1_rows = await pg_client.fetch(_QUERY_VALID_CANONICAL)
    _print_rows(q1_rows)
    q1_count = len(q1_rows)
    print(f"Summary: {q1_count} symbol/timeframe combination(s) with valid canonical candles")

    _section("QUERY 2: STUCK DATA (incomplete / UNSPECIFIED semantics)")
    q2_rows = await pg_client.fetch(_QUERY_STUCK_DATA)
    _print_rows(q2_rows)
    q2_count = len(q2_rows)
    total_incomplete = sum(int(row["incomplete_count"] or 0) for row in q2_rows)
    total_unspec = sum(int(row["unspec_count"] or 0) for row in q2_rows)
    print(f"Summary: {q2_count} symbol/timeframe combination(s) stuck")
    print(f"  Total incomplete rows: {total_incomplete}")
    print(f"  Total UNSPECIFIED-semantics rows: {total_unspec}")

    _section("QUERY 3: RAW PROVIDER CANDLES")
    q3_rows = await pg_client.fetch(_QUERY_RAW_PROVIDER)
    _print_rows(q3_rows)
    q3_count = len(q3_rows)
    print(f"Summary: {q3_count} provider/symbol/timeframe combination(s) present in raw_provider_candles")

    _section("QUERY 4: MISSING / INSUFFICIENT COVERAGE VALIDATOR")
    q4_rows = await pg_client.fetch(
        _QUERY_VALIDATOR_MISSING,
        _REQUIRED_SYMBOLS,
        _REQUIRED_TIMEFRAMES,
        _AS_OF,
    )
    _print_rows(q4_rows)
    q4_count = len(q4_rows)
    required_combinations = len(_REQUIRED_SYMBOLS) * len(_REQUIRED_TIMEFRAMES)
    missing_pct = (q4_count / required_combinations * 100.0) if required_combinations else 0.0
    print(
        f"Summary: {q4_count}/{required_combinations} required combination(s) missing "
        f"minimum coverage ({missing_pct:.1f}%)"
    )

    _section("DIAGNOSIS")
    if q1_count == 0 and q2_count > 0:
        _subsection("PROBLEM 3: Data stuck in incomplete/UNSPECIFIED")
        print(
            "No valid canonical candles exist, but rows are present in canonical_candles "
            "marked incomplete or with UNSPECIFIED provider_timestamp_semantics. "
            "The pipeline is producing candles but they are never being finalized."
        )
    elif q1_count == 0 and q2_count == 0 and q3_count > 0:
        _subsection("PROBLEM 1: REST quota exhaustion blocking completion")
        print(
            "No valid canonical candles and no stuck rows exist, but raw_provider_candles "
            "has data. Canonical candle derivation is not running/completing, likely due to "
            "REST quota exhaustion or an upstream ingestion failure."
        )
    elif q1_count > 0 and missing_pct > 80.0:
        _subsection("PROBLEM 1/2: REST quota or fallback insufficient")
        print(
            f"Valid canonical candles exist ({q1_count} combination(s)), but {missing_pct:.1f}% "
            "of required symbol/timeframe combinations are missing minimum coverage. "
            "This suggests REST quota exhaustion or an insufficient fallback data source."
        )
    elif q1_count > 0 and missing_pct < 20.0:
        _subsection("ALL COMBINATIONS READY")
        print(
            f"Valid canonical candles exist ({q1_count} combination(s)) and only {missing_pct:.1f}% "
            "of required symbol/timeframe combinations are missing minimum coverage. "
            "Data flow is healthy."
        )
    else:
        _subsection("INCONCLUSIVE")
        print(
            f"q1_count={q1_count} q2_count={q2_count} q3_count={q3_count} "
            f"missing_pct={missing_pct:.1f}% did not match a known diagnostic pattern. "
            "Review the raw query output above."
        )


async def _async_main() -> None:
    try:
        await run_diagnostics()
    finally:
        await pg_client.close()


if __name__ == "__main__":
    asyncio.run(_async_main())
