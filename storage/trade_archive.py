"""
Trade Archive — persisted closed-trade P&L retrieval for Monte Carlo / L7.

Provides `get_closed_returns(symbol, lookback)` which returns a list of
historical P&L floats for the given symbol (most-recent-first, capped at
`lookback`).

Data sources (tried in order):
  1. Redis  — TradeLedger cache / `wolf15:TRADE:*` keys  (fast, same-session)
  2. PostgreSQL — `trade_history` table                   (durable, cross-session)
  3. In-memory TradeLedger singleton fallback              (last resort)

All reads are **read-only** — this module never mutates trade state.
Authority boundary: this is a *storage* reader; it does NOT make decisions.
"""

from __future__ import annotations

import json
import logging
import os

from typing import Any

logger = logging.getLogger("tuyul.trade_archive")

# ---------------------------------------------------------------------------
# Default Redis key prefix (matches TradeLedger convention)
# ---------------------------------------------------------------------------
_REDIS_PREFIX: str = os.getenv("REDIS_PREFIX", "wolf15")


# ═══════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════

def get_closed_returns(
    symbol: str | None = None,
    lookback: int = 200,
) -> list[float]:
    """Return up to *lookback* most-recent closed-trade P&L values.

    Args:
        symbol:   Filter by trading pair (e.g. ``"EURUSD"``).
                  ``None`` → all symbols.
        lookback: Maximum number of returns to retrieve (default 200).

    Returns:
        List of P&L floats, most-recent first.  Empty list if no data found.
    """
    # 1️⃣ Try Redis (primary — fast, in-session)
    returns = _from_redis(symbol, lookback)
    if returns:
        logger.debug(
            "[TradeArchive] Loaded %d returns from Redis (symbol=%s)",
            len(returns),
            symbol,
        )
        return returns

    # 2️⃣ Try PostgreSQL (durable — cross-session)
    returns = _from_postgres(symbol, lookback)
    if returns:
        logger.debug(
            "[TradeArchive] Loaded %d returns from PostgreSQL (symbol=%s)",
            len(returns),
            symbol,
        )
        return returns

    # 3️⃣ Fallback: in-memory TradeLedger singleton
    returns = _from_ledger_cache(symbol, lookback)
    if returns:
        logger.debug(
            "[TradeArchive] Loaded %d returns from TradeLedger cache (symbol=%s)",
            len(returns),
            symbol,
        )
        return returns

    logger.info(
        "[TradeArchive] No closed trade returns found (symbol=%s). "
        "MC engine will use fallback mode.",
        symbol,
    )
    return []


def get_win_loss_counts(
    symbol: str | None = None,
    lookback: int = 200,
) -> tuple[int, int]:
    """Derive prior win/loss counts from closed-trade returns.

    Useful for Bayesian prior state in L7.

    Returns:
        (wins, losses) tuple.
    """
    returns = get_closed_returns(symbol, lookback)
    wins = sum(1 for r in returns if r > 0)
    losses = sum(1 for r in returns if r <= 0)
    return wins, losses


# ═══════════════════════════════════════════════════════════════════════════
#  REDIS SOURCE
# ═══════════════════════════════════════════════════════════════════════════

def _from_redis(symbol: str | None, lookback: int) -> list[float]:
    """Scan Redis for CLOSED trades and extract P&L values."""
    try:
        from storage.redis_client import RedisClient  # noqa: PLC0415

        redis = RedisClient()
        client = redis.client

        closed_trades: list[dict[str, Any]] = []
        cursor = 0

        while True:
            cursor, keys = client.scan(  # type: ignore[misc]
                cursor=cursor,
                match=f"{_REDIS_PREFIX}:TRADE:*",
                count=100,
            )
            for key in keys:
                raw = redis.get(key)
                if not raw:
                    continue
                try:
                    trade = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if trade.get("status") != "CLOSED":
                    continue
                if trade.get("pnl") is None:
                    continue
                if symbol and trade.get("pair", "").upper() != symbol.upper():
                    continue

                closed_trades.append(trade)

            if cursor == 0:
                break

        if not closed_trades:
            return []

        # Sort by updated_at descending (most recent first)
        closed_trades.sort(
            key=lambda t: t.get("updated_at", t.get("closed_at", "")),
            reverse=True,
        )

        return [float(t["pnl"]) for t in closed_trades[:lookback]]

    except Exception as exc:
        logger.warning("[TradeArchive] Redis read failed: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  POSTGRESQL SOURCE
# ═══════════════════════════════════════════════════════════════════════════

def _from_postgres(symbol: str | None, lookback: int) -> list[float]:
    """Query trade_history table for closed-trade P&L values.

    Uses synchronous wrapper around asyncpg since the pipeline is sync.
    """
    try:
        import asyncio  # noqa: PLC0415

        from storage.postgres_client import PostgresClient  # noqa: PLC0415

        pg = PostgresClient()
        if not pg.is_available:
            return []

        async def _query() -> list[float]:
            if symbol:
                rows = await pg.fetch(
                    """
                    SELECT pnl FROM trade_history
                    WHERE status = 'CLOSED' AND pnl IS NOT NULL
                      AND UPPER(pair) = UPPER($1)
                    ORDER BY closed_at DESC NULLS LAST
                    LIMIT $2
                    """,
                    symbol,
                    lookback,
                )
            else:
                rows = await pg.fetch(
                    """
                    SELECT pnl FROM trade_history
                    WHERE status = 'CLOSED' AND pnl IS NOT NULL
                    ORDER BY closed_at DESC NULLS LAST
                    LIMIT $1
                    """,
                    lookback,
                )
            return [float(row["pnl"]) for row in rows]

        # Run in existing event loop or create a temporary one
        try:
            asyncio.get_running_loop()
            # We're inside an async context — can't block.  Skip Postgres.
            logger.debug("[TradeArchive] Async loop running; skipping sync PG query")
            return []
        except RuntimeError:
            return asyncio.run(_query())

    except Exception as exc:
        logger.warning("[TradeArchive] PostgreSQL read failed: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════════════
#  IN-MEMORY TRADE-LEDGER FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

def _from_ledger_cache(symbol: str | None, lookback: int) -> list[float]:
    """Read from the in-memory TradeLedger singleton (last resort)."""
    try:
        from journal.trade_ledger import TradeLedger  # noqa: PLC0415

        ledger = TradeLedger()
        all_trades = list(ledger._cache.values())

        closed = [
            t for t in all_trades
            if str(t.status) == "CLOSED"
            and t.pnl is not None
            and (not symbol or t.pair.upper() == symbol.upper())
        ]

        # Sort by updated_at descending
        closed.sort(key=lambda t: t.updated_at, reverse=True)

        return [float(t.pnl) for t in closed[:lookback] if t.pnl is not None]

    except Exception as exc:
        logger.warning("[TradeArchive] Ledger cache read failed: %s", exc)
        return []
