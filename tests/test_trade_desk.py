"""
Unit + Integration tests for Trade Desk router (api/trades_router.py).

Tests:
  - Trade state partitioning (pending/open/closed/cancelled)
  - Anomaly detection helper
  - Exposure aggregation by pair/account
  - Trade detail endpoint (timeline, anomalies)
"""

from __future__ import annotations

import time
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Import helpers under test ─────────────────────────────────
from api.trades_router import (
    _ACTIVE_STATUSES,
    _build_execution_timeline,
    _compute_exposure,
    _detect_anomalies,
)
from schemas.trade_models import TradeStatus

# ── Fixtures ──────────────────────────────────────────────────


def _make_trade(
    trade_id: str = "T-001",
    status: str = "OPEN",
    pair: str = "EURUSD",
    direction: str = "BUY",
    account_id: str = "ACC-001",
    lot_size: float = 0.10,
    entry_price: float = 1.10000,
    stop_loss: float = 1.09500,
    take_profit: float = 1.11000,
    pnl: float | None = None,
    created_at: str | None = None,
    opened_at: str | None = None,
    closed_at: str | None = None,
    confirmed_at: str | None = None,
    close_reason: str | None = None,
    current_price: float | None = None,
) -> dict:
    return {
        "trade_id": trade_id,
        "status": status,
        "pair": pair,
        "direction": direction,
        "account_id": account_id,
        "lot_size": lot_size,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "pnl": pnl,
        "created_at": created_at,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "confirmed_at": confirmed_at,
        "close_reason": close_reason,
        "current_price": current_price,
    }


# ══════════════════════════════════════════════════════════════
#  Trade State Partitioning
# ══════════════════════════════════════════════════════════════


class TestTradeStatePartitioning:
    """Verify that active statuses filter correctly."""

    def test_active_statuses_include_intended_pending_open(self):
        assert TradeStatus.INTENDED in _ACTIVE_STATUSES
        assert TradeStatus.PENDING in _ACTIVE_STATUSES
        assert TradeStatus.OPEN in _ACTIVE_STATUSES

    def test_active_statuses_exclude_terminal(self):
        assert TradeStatus.CLOSED not in _ACTIVE_STATUSES
        assert TradeStatus.CANCELLED not in _ACTIVE_STATUSES
        assert TradeStatus.SKIPPED not in _ACTIVE_STATUSES

    def test_partition_by_status(self):
        trades = [
            _make_trade(trade_id="T-1", status="INTENDED"),
            _make_trade(trade_id="T-2", status="PENDING"),
            _make_trade(trade_id="T-3", status="OPEN"),
            _make_trade(trade_id="T-4", status="CLOSED"),
            _make_trade(trade_id="T-5", status="CANCELLED"),
        ]

        active = [t for t in trades if t["status"] in _ACTIVE_STATUSES]
        closed = [t for t in trades if t["status"] == TradeStatus.CLOSED]
        cancelled = [t for t in trades if t["status"] in {TradeStatus.CANCELLED, TradeStatus.SKIPPED}]

        assert len(active) == 3
        assert len(closed) == 1
        assert len(cancelled) == 1


# ══════════════════════════════════════════════════════════════
#  Anomaly Detection
# ══════════════════════════════════════════════════════════════


class TestAnomalyDetection:
    """Test _detect_anomalies helper."""

    def test_no_anomalies_for_normal_open_trade(self):
        trade = _make_trade(status="OPEN", current_price=1.10050, entry_price=1.10000)
        anomalies = _detect_anomalies(trade)
        assert anomalies == []

    def test_stale_pending_detected(self):
        # Trade pending for > 5 minutes
        old_ts = time.time() - 600  # 10 minutes ago
        from datetime import datetime

        created = datetime.fromtimestamp(old_ts, tz=UTC).isoformat()

        trade = _make_trade(status="PENDING", created_at=created)
        anomalies = _detect_anomalies(trade)

        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "STALE_PENDING"
        assert anomalies[0]["severity"] == "WARNING"

    def test_stale_pending_not_detected_for_recent(self):
        from datetime import datetime

        recent = datetime.fromtimestamp(time.time() - 60, tz=UTC).isoformat()

        trade = _make_trade(status="PENDING", created_at=recent)
        anomalies = _detect_anomalies(trade)

        stale = [a for a in anomalies if a["type"] == "STALE_PENDING"]
        assert len(stale) == 0

    def test_price_deviation_detected(self):
        trade = _make_trade(
            status="OPEN",
            entry_price=1.10000,
            current_price=1.13500,  # > 2% deviation
        )
        anomalies = _detect_anomalies(trade)

        assert len(anomalies) == 1
        assert anomalies[0]["type"] == "PRICE_DEVIATION"

    def test_price_deviation_not_detected_within_threshold(self):
        trade = _make_trade(
            status="OPEN",
            entry_price=1.10000,
            current_price=1.10100,  # < 2%
        )
        anomalies = _detect_anomalies(trade)

        price_devs = [a for a in anomalies if a["type"] == "PRICE_DEVIATION"]
        assert len(price_devs) == 0

    def test_no_anomaly_for_closed_trade(self):
        trade = _make_trade(status="CLOSED", pnl=50.0)
        anomalies = _detect_anomalies(trade)
        assert anomalies == []


# ══════════════════════════════════════════════════════════════
#  Execution Timeline
# ══════════════════════════════════════════════════════════════


class TestExecutionTimeline:
    """Test _build_execution_timeline helper."""

    def test_full_lifecycle_timeline(self):
        trade = _make_trade(
            created_at="2026-01-15T10:00:00Z",
            confirmed_at="2026-01-15T10:01:00Z",
            opened_at="2026-01-15T10:02:00Z",
            closed_at="2026-01-15T10:30:00Z",
            close_reason="TP_HIT",
            pnl=42.50,
            status="CLOSED",
        )
        timeline = _build_execution_timeline(trade)

        assert len(timeline) == 4
        assert timeline[0]["event"] == "TRADE_CREATED"
        assert timeline[1]["event"] == "TRADE_CONFIRMED"
        assert timeline[2]["event"] == "ORDER_FILLED"
        assert timeline[3]["event"] == "TRADE_CLOSED"
        assert timeline[3]["pnl"] == 42.50
        assert timeline[3]["close_reason"] == "TP_HIT"

    def test_partial_timeline(self):
        trade = _make_trade(created_at="2026-01-15T10:00:00Z", status="INTENDED")
        timeline = _build_execution_timeline(trade)

        assert len(timeline) == 1
        assert timeline[0]["event"] == "TRADE_CREATED"

    def test_empty_timeline(self):
        trade = _make_trade()
        timeline = _build_execution_timeline(trade)
        assert len(timeline) == 0


# ══════════════════════════════════════════════════════════════
#  Exposure Aggregation
# ══════════════════════════════════════════════════════════════


class TestExposureAggregation:
    """Test _compute_exposure helper."""

    def test_single_trade_exposure(self):
        trades = [_make_trade(pair="EURUSD", direction="BUY", lot_size=0.10, account_id="ACC-1")]
        result = _compute_exposure(trades)

        assert result["total_lots"] == pytest.approx(0.10)
        assert result["total_trades"] == 1
        assert len(result["by_pair"]) == 1
        assert result["by_pair"][0]["pair"] == "EURUSD"
        assert result["by_pair"][0]["buy_lots"] == pytest.approx(0.10)
        assert result["by_pair"][0]["sell_lots"] == pytest.approx(0.0)

    def test_multi_pair_exposure(self):
        trades = [
            _make_trade(pair="EURUSD", direction="BUY", lot_size=0.10, account_id="ACC-1"),
            _make_trade(pair="EURUSD", direction="SELL", lot_size=0.05, account_id="ACC-1"),
            _make_trade(pair="GBPUSD", direction="BUY", lot_size=0.20, account_id="ACC-2"),
        ]
        result = _compute_exposure(trades)

        assert result["total_lots"] == pytest.approx(0.35)
        assert result["total_trades"] == 3
        assert len(result["by_pair"]) == 2

        eur = next(p for p in result["by_pair"] if p["pair"] == "EURUSD")
        assert eur["buy_lots"] == pytest.approx(0.10)
        assert eur["sell_lots"] == pytest.approx(0.05)
        assert eur["count"] == 2

    def test_multi_account_exposure(self):
        trades = [
            _make_trade(pair="EURUSD", direction="BUY", lot_size=0.10, account_id="ACC-1"),
            _make_trade(pair="GBPUSD", direction="BUY", lot_size=0.20, account_id="ACC-1"),
            _make_trade(pair="EURUSD", direction="BUY", lot_size=0.15, account_id="ACC-2"),
        ]
        result = _compute_exposure(trades)

        assert len(result["by_account"]) == 2

        acc1 = next(a for a in result["by_account"] if a["account_id"] == "ACC-1")
        assert acc1["total_lots"] == pytest.approx(0.30)
        assert acc1["count"] == 2
        assert set(acc1["pairs"]) == {"EURUSD", "GBPUSD"}

    def test_empty_trades(self):
        result = _compute_exposure([])

        assert result["total_lots"] == 0
        assert result["total_trades"] == 0
        assert result["by_pair"] == []
        assert result["by_account"] == []

    def test_missing_lot_defaults_to_zero(self):
        trade = _make_trade(pair="EURUSD", direction="BUY")
        trade["lot_size"] = None
        trade["lot"] = None
        result = _compute_exposure([trade])

        assert result["total_lots"] == 0
        assert result["total_trades"] == 1


# ══════════════════════════════════════════════════════════════
#  Integration: Endpoint responses
# ══════════════════════════════════════════════════════════════


class TestTradeDeskEndpoint:
    """Test the /trades/desk endpoint with mocked ledger."""

    @pytest.mark.asyncio
    async def test_desk_returns_partitioned_trades(self):
        mock_trades = [
            _make_trade(trade_id="T-1", status="INTENDED"),
            _make_trade(trade_id="T-2", status="OPEN"),
            _make_trade(trade_id="T-3", status="CLOSED", pnl=25.0),
            _make_trade(trade_id="T-4", status="CANCELLED"),
        ]

        with patch("api.trades_router._trade_ledger") as mock_ledger:
            mock_ledger.get_all_trades_async = AsyncMock(return_value=mock_trades)

            from api.trades_router import get_trade_desk

            result = await get_trade_desk()

        assert result["counts"]["pending"] == 1
        assert result["counts"]["open"] == 1
        assert result["counts"]["closed"] == 1
        assert result["counts"]["cancelled"] == 1
        assert result["counts"]["total"] == 4
        assert len(result["trades"]["pending"]) == 1
        assert len(result["trades"]["open"]) == 1

    @pytest.mark.asyncio
    async def test_desk_computes_exposure(self):
        mock_trades = [
            _make_trade(trade_id="T-1", status="OPEN", pair="EURUSD", lot_size=0.10),
            _make_trade(trade_id="T-2", status="OPEN", pair="GBPUSD", lot_size=0.20),
        ]

        with patch("api.trades_router._trade_ledger") as mock_ledger:
            mock_ledger.get_all_trades_async = AsyncMock(return_value=mock_trades)

            from api.trades_router import get_trade_desk

            result = await get_trade_desk()

        assert result["exposure"]["total_lots"] == pytest.approx(0.30)
        assert result["exposure"]["total_trades"] == 2


class TestTradeDetailEndpoint:
    """Test the /trades/{trade_id}/detail endpoint."""

    @pytest.mark.asyncio
    async def test_detail_returns_timeline(self):
        mock_trade = MagicMock()
        mock_trade.model_dump.return_value = _make_trade(
            trade_id="T-99",
            status="CLOSED",
            pair="EURUSD",
            created_at="2026-01-15T10:00:00Z",
            opened_at="2026-01-15T10:02:00Z",
            closed_at="2026-01-15T10:30:00Z",
            close_reason="TP_HIT",
            pnl=50.0,
        )

        with (
            patch("api.trades_router._trade_ledger") as mock_ledger,
            patch("api.trades_router._price_feed") as mock_feed,
        ):
            mock_ledger.get_trade_async = AsyncMock(return_value=mock_trade)
            mock_feed.get_price_async = AsyncMock(return_value=1.10500)

            from api.trades_router import get_trade_detail

            result = await get_trade_detail("T-99")

        assert result["trade"]["trade_id"] == "T-99"
        assert result["trade"]["current_price"] == 1.10500
        assert len(result["timeline"]) == 3  # created, opened, closed

    @pytest.mark.asyncio
    async def test_detail_404_for_missing_trade(self):
        with patch("api.trades_router._trade_ledger") as mock_ledger:
            mock_ledger.get_trade_async = AsyncMock(return_value=None)

            from api.trades_router import get_trade_detail

            with pytest.raises(Exception):  # HTTPException  # noqa: B017
                await get_trade_detail("NONEXISTENT")
