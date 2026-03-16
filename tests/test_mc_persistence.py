"""Tests for storage/mc_persistence.py — MC result PostgreSQL persistence."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from analysis.portfolio_monte_carlo import PairSpec, PortfolioMCResult
from storage.mc_persistence import persist_mc_result


def _result(**overrides: Any) -> PortfolioMCResult:
    defaults: dict[str, Any] = dict(
        portfolio_win_rate=0.55,
        portfolio_profit_factor=1.3,
        portfolio_risk_of_ruin=0.05,
        portfolio_max_drawdown=-0.08,
        portfolio_expected_value=100.0,
        diversification_ratio=0.7,
        advisory_flag="PASS",
        simulations=10_000,
        horizon_bars=500,
    )
    defaults.update(overrides)
    return PortfolioMCResult(**defaults)


def _pair(symbol: str) -> PairSpec:
    return PairSpec(symbol=symbol, win_probability=0.55, avg_win=100.0, avg_loss=80.0)


class TestPersistMCResult:
    """persist_mc_result async function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_pg_unavailable(self):
        """When PostgreSQL pool is not initialised, returns None."""
        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = False
            run_id = await persist_mc_result(
                result=_result(),
                pair_specs=[_pair("EURUSD")],
            )
        assert run_id is None

    @pytest.mark.asyncio
    async def test_inserts_row_and_returns_run_id(self):
        """Successful write returns a 16-char hex run_id."""
        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(return_value="INSERT 0 1")

            run_id = await persist_mc_result(
                result=_result(),
                pair_specs=[_pair("EURUSD"), _pair("GBPUSD")],
                is_incremental=False,
            )

        assert run_id is not None
        assert len(run_id) == 16
        mock_pg.execute.assert_awaited_once()

        # Verify args passed to execute
        args = mock_pg.execute.call_args
        positional = args[0]
        # arg[0] = SQL, arg[1]=run_id, arg[2]=pair_count
        assert positional[2] == 2  # pair_count
        assert positional[11] == "PASS"  # advisory_flag
        assert positional[12] is False  # is_incremental
        # pair_symbols is sorted comma-separated
        assert positional[13] == "EURUSD,GBPUSD"

    @pytest.mark.asyncio
    async def test_incremental_flag_passed(self):
        """is_incremental=True is forwarded to the SQL row."""
        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(return_value="INSERT 0 1")

            run_id = await persist_mc_result(
                result=_result(),
                pair_specs=[_pair("EURUSD")],
                is_incremental=True,
            )

        assert run_id is not None
        args = mock_pg.execute.call_args[0]
        assert args[12] is True  # is_incremental

    @pytest.mark.asyncio
    async def test_pair_contributions_serialised(self):
        """pair_contributions dict is JSON-serialised."""
        result = _result(pair_contributions={"EURUSD": 0.6, "GBPUSD": 0.4})

        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(return_value="INSERT 0 1")

            await persist_mc_result(result=result, pair_specs=[_pair("EURUSD")])

        args = mock_pg.execute.call_args[0]
        contributions = json.loads(args[14])
        assert contributions["EURUSD"] == 0.6

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        """Database error is caught and None returned."""
        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(side_effect=RuntimeError("connection lost"))

            run_id = await persist_mc_result(
                result=_result(),
                pair_specs=[_pair("EURUSD")],
            )

        assert run_id is None

    @pytest.mark.asyncio
    async def test_computed_at_forwarded(self):
        """When computed_at is provided, it converts to a proper datetime."""
        import time

        ts = time.time()

        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(return_value="INSERT 0 1")

            await persist_mc_result(
                result=_result(),
                pair_specs=[_pair("EURUSD")],
                computed_at=ts,
            )

        args = mock_pg.execute.call_args[0]
        dt_arg = args[16]  # computed_at
        assert dt_arg.tzinfo is not None  # timezone-aware

    @pytest.mark.asyncio
    async def test_empty_pairs(self):
        """Empty pair list still persists correctly."""
        with patch("storage.mc_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg.execute = AsyncMock(return_value="INSERT 0 1")

            run_id = await persist_mc_result(
                result=_result(advisory_flag="BLOCK"),
                pair_specs=[],
            )

        assert run_id is not None
        args = mock_pg.execute.call_args[0]
        assert args[2] == 0  # pair_count
        assert args[13] == ""  # pair_symbols
