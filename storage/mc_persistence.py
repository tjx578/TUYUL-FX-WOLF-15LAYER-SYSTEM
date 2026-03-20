"""Async Monte Carlo result persistence to PostgreSQL.

Writes each MC result (full or incremental) to the ``mc_results`` table
for historical trending and audit. Uses the shared PostgresClient singleton.

Zone: storage/ — no analysis or execution side-effects.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from loguru import logger

from storage.postgres_client import pg_client

if TYPE_CHECKING:
    from analysis.portfolio_monte_carlo import PairSpec, PortfolioMCResult

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO mc_results (
    run_id, pair_count, simulations, horizon_bars,
    portfolio_win_rate, portfolio_profit_factor,
    portfolio_risk_of_ruin, portfolio_max_drawdown,
    portfolio_expected_value, diversification_ratio,
    advisory_flag, is_incremental,
    pair_symbols, pair_contributions, correlation_matrix,
    computed_at
) VALUES (
    $1, $2, $3, $4,
    $5, $6,
    $7, $8,
    $9, $10,
    $11, $12,
    $13, $14, $15,
    $16
)
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def persist_mc_result(
    result: PortfolioMCResult,
    pair_specs: list[PairSpec],
    is_incremental: bool = False,
    computed_at: float | None = None,
) -> str | None:
    """Persist a single MC result row to PostgreSQL.

    Parameters
    ----------
    result : PortfolioMCResult
        The Monte Carlo simulation result.
    pair_specs : list[PairSpec]
        The portfolio pairs used in this run.
    is_incremental : bool
        Whether this was an incremental (delta) run.
    computed_at : float, optional
        Unix timestamp of computation. Defaults to now.

    Returns
    -------
    str | None
        The ``run_id`` on success, ``None`` if persistence is unavailable.
    """
    if not pg_client.is_available:
        return None

    run_id = uuid.uuid4().hex[:16]
    ts = datetime.fromtimestamp(computed_at, tz=UTC) if computed_at else datetime.now(tz=UTC)

    pair_symbols = ",".join(sorted(p.symbol for p in pair_specs))
    pair_contributions = json.dumps(result.pair_contributions) if result.pair_contributions else None
    correlation_matrix = json.dumps(result.correlation_matrix_used) if result.correlation_matrix_used else None

    try:
        await pg_client.execute(
            _INSERT_SQL,
            run_id,
            len(pair_specs),
            result.simulations,
            result.horizon_bars,
            result.portfolio_win_rate,
            result.portfolio_profit_factor,
            result.portfolio_risk_of_ruin,
            result.portfolio_max_drawdown,
            result.portfolio_expected_value,
            result.diversification_ratio,
            result.advisory_flag,
            is_incremental,
            pair_symbols,
            pair_contributions,
            correlation_matrix,
            ts,
        )
        logger.debug(
            "mc_persist: stored run_id=%s pairs=%d advisory=%s incremental=%s",
            run_id,
            len(pair_specs),
            result.advisory_flag,
            is_incremental,
        )
        return run_id
    except Exception:
        logger.exception("mc_persist: failed to write MC result")
        return None
