"""
Root conftest -- shared fixtures for the entire Wolf-15 test suite.
Fast by default: heavy fixtures are session-scoped or lazy.
"""

import sys
import time
from pathlib import Path

import pytest

# Ensure project root is importable
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ── Timing helper ─────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _enforce_timeout(request):
    """Warn if any single test exceeds 5s (helps catch regressions)."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    if elapsed > 5.0 and "slow" not in [m.name for m in request.node.iter_markers()]:
        import warnings  # noqa: PLC0415

        warnings.warn(
            f"Test {request.node.nodeid} took {elapsed:.1f}s -- consider marking @pytest.mark.slow", stacklevel=2
        )


# ── Sample Layer-12 verdict ───────────────────────────────────────
@pytest.fixture
def sample_l12_verdict():
    return {
        "symbol": "EURUSD",
        "verdict": "EXECUTE",
        "confidence": 0.87,
        "direction": "BUY",
        "entry_price": 1.0850,
        "stop_loss": 1.0800,
        "take_profit_1": 1.0950,
        "risk_percent": 1.0,
        "scores": {
            "wolf": 8.5,
            "tii": 7.2,
            "frpc": 6.8,
        },
        "signal_id": "SIG-20260215-EURUSD-001",
        "timestamp": "2026-02-15T10:30:00Z",
    }


@pytest.fixture
def sample_l12_reject():
    return {
        "symbol": "GBPUSD",
        "verdict": "NO_TRADE",
        "confidence": 0.35,
        "direction": None,
        "entry_price": None,
        "stop_loss": None,
        "take_profit_1": None,
        "risk_percent": 0,
        "scores": {"wolf": 3.1, "tii": 2.5, "frpc": 4.0},
        "signal_id": "SIG-20260215-GBPUSD-002",
        "timestamp": "2026-02-15T10:35:00Z",
    }


# ── Account state fixtures ────────────────────────────────────────
@pytest.fixture
def sample_account_state():
    return {
        "balance": 100_000.0,
        "equity": 99_500.0,
        "margin_used": 2_000.0,
        "open_positions": 2,
        "daily_pnl": -150.0,
        "daily_loss_limit": 5_000.0,
        "max_loss_limit": 10_000.0,
    }


@pytest.fixture
def sample_trade_risk():
    return {
        "symbol": "EURUSD",
        "direction": "BUY",
        "lot_size": 0.5,
        "risk_amount": 500.0,
        "risk_percent": 0.5,
        "stop_loss_pips": 50,
    }


# ── Prop firm profile fixtures ────────────────────────────────────
@pytest.fixture
def ftmo_profile():
    return {
        "name": "FTMO",
        "max_daily_loss_pct": 5.0,
        "max_total_loss_pct": 10.0,
        "max_positions": 10,
        "max_lot_per_trade": 5.0,
        "news_lockout_minutes": 15,
        "weekend_close_required": True,
    }


@pytest.fixture
def mock_db():
    """In-memory list pretending to be a journal/ledger DB."""
    records = []

    class FakeDB:
        async def insert(self, table, record):
            records.append({"table": table, **record})
            return len(records)

        async def query(self, table, filters=None):
            result = [r for r in records if r.get("table") == table]
            if filters:
                for k, v in filters.items():
                    result = [r for r in result if r.get(k) == v]
            return result

        def get_all(self):
            return list(records)

    return FakeDB()
