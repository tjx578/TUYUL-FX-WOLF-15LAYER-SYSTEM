"""
Unit tests for risk/drawdown.py — DrawdownMonitor.

Covers:
- Initialization & Redis persistence
- Peak equity tracking & total drawdown calculation
- Daily/weekly drawdown accumulation from PnL
- Auto-reset (daily midnight UTC, weekly Monday 00:00 UTC)
- Breach detection (daily, weekly, total)
- check_and_raise exception
- Thread-safe snapshot
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Patch dependencies before importing DrawdownMonitor
# so the class never hits real Redis or config files.

_RISK_CONFIG = {
    "drawdown": {
        "max_daily_percent": 0.03,
        "max_weekly_percent": 0.05,
        "max_total_percent": 0.10,
    },
    "redis_keys": {
        "drawdown_daily": "wolf15:risk:drawdown:daily",
        "drawdown_weekly": "wolf15:risk:drawdown:weekly",
        "drawdown_total": "wolf15:risk:drawdown:total",
        "peak_equity": "wolf15:risk:peak_equity",
    },
}


def _make_redis_mock(stored: dict[str, str] | None = None) -> MagicMock:
    """Build a RedisClient mock backed by an in-memory dict."""
    store: dict[str, str] = dict(stored or {})
    mock = MagicMock()
    mock.get = MagicMock(side_effect=lambda k: store.get(k))  # type: ignore[misc]
    mock.set = MagicMock(side_effect=lambda k, v, **_: store.__setitem__(k, v))  # type: ignore[misc]
    mock._store = store  # expose for assertions
    return mock


@pytest.fixture(autouse=True)
def patch_deps() -> Generator[None, None, None]:
    """Patch RedisClient singleton + load_risk for every test."""
    with (
        patch("risk.drawdown.RedisClient", side_effect=lambda: _make_redis_mock()),
        patch("risk.drawdown.load_risk", return_value=_RISK_CONFIG),
    ):
        yield


def _build_monitor(
    initial_balance: float = 100_000.0,
    stored: dict[str, str] | None = None,
    **kwargs: float,
):
    """Construct a DrawdownMonitor with an optional pre-populated Redis store."""
    redis_mock = _make_redis_mock(stored)
    with (
        patch("risk.drawdown.RedisClient", return_value=redis_mock),
        patch("risk.drawdown.load_risk", return_value=_RISK_CONFIG),
    ):
        from risk.drawdown import DrawdownMonitor
        mon = DrawdownMonitor(initial_balance=initial_balance, **kwargs)
    # Expose the mock for verification
    mon._test_redis = redis_mock  # type: ignore[attr-defined]
    return mon


# ──────────────────────────────────────────────────────────────────
#  Initialization
# ──────────────────────────────────────────────────────────────────

class TestDrawdownInit:
    def test_initializes_with_defaults(self) -> None:
        mon = _build_monitor(100_000)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["peak_equity"] == 100_000
        assert snap["daily_dd_amount"] == 0.0
        assert snap["weekly_dd_amount"] == 0.0
        assert snap["total_dd_amount"] == 0.0

    def test_loads_state_from_redis(self) -> None:
        stored = {
            "wolf15:risk:drawdown:daily": "150.0",
            "wolf15:risk:drawdown:weekly": "300.0",
            "wolf15:risk:drawdown:total": "500.0",
            "wolf15:risk:peak_equity": "105000.0",
        }
        mon = _build_monitor(100_000, stored=stored)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["daily_dd_amount"] == 150.0
        assert snap["weekly_dd_amount"] == 300.0
        assert snap["total_dd_amount"] == 500.0
        assert snap["peak_equity"] == 105_000.0

    def test_config_limits_loaded(self) -> None:
        mon = _build_monitor(100_000)
        assert mon.max_daily_percent == 0.03
        assert mon.max_weekly_percent == 0.05
        assert mon.max_total_percent == 0.10

    def test_custom_limits_override_config(self) -> None:
        mon = _build_monitor(
            100_000,
            max_daily_percent=0.02,
            max_weekly_percent=0.04,
            max_total_percent=0.08,
        )
        assert mon.max_daily_percent == 0.02
        assert mon.max_weekly_percent == 0.04
        assert mon.max_total_percent == 0.08


# ──────────────────────────────────────────────────────────────────
#  Peak equity tracking
# ──────────────────────────────────────────────────────────────────

class TestPeakEquity:
    def test_peak_updates_on_higher_equity(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(102_000)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["peak_equity"] == 102_000

    def test_peak_does_not_decrease(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(102_000)
        mon.update(99_000)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["peak_equity"] == 102_000


# ──────────────────────────────────────────────────────────────────
#  Total drawdown (peak − current equity)
# ──────────────────────────────────────────────────────────────────

class TestTotalDrawdown:
    def test_total_drawdown_from_peak(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(100_000)  # peak = 100k
        mon.update(97_000)   # DD = 3k
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["total_dd_amount"] == 3_000

    def test_total_drawdown_percent(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(95_000)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        dd_percent: float = snap["total_dd_percent"]  # type: ignore[index]
        assert abs(dd_percent - 0.05) < 1e-9


# ──────────────────────────────────────────────────────────────────
#  Daily / weekly PnL accumulation
# ──────────────────────────────────────────────────────────────────

class TestPnLAccumulation:
    def test_negative_pnl_adds_to_daily_and_weekly(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_500, pnl=-500)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["daily_dd_amount"] == 500
        assert snap["weekly_dd_amount"] == 500

    def test_positive_pnl_does_not_affect_counters(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(100_500, pnl=500)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["daily_dd_amount"] == 0.0
        assert snap["weekly_dd_amount"] == 0.0

    def test_cumulative_losses(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_700, pnl=-300)
        mon.update(99_400, pnl=-300)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["daily_dd_amount"] == 600
        assert snap["weekly_dd_amount"] == 600


# ──────────────────────────────────────────────────────────────────
#  Auto-reset
# ──────────────────────────────────────────────────────────────────

class TestAutoReset:
    def test_daily_reset_on_date_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_000, pnl=-1_000)
        snap_init: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap_init["daily_dd_amount"] == 1_000

        # Simulate date advancing to tomorrow (without touching protected fields)
        tomorrow = datetime.now(UTC) + timedelta(days=1)
        monkeypatch.setattr("risk.drawdown.now_utc", lambda: tomorrow)

        # Next operation triggers auto-reset
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["daily_dd_amount"] == 0.0

    def test_weekly_reset_on_week_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = _build_monitor(100_000)
        mon.update(98_000, pnl=-2_000)
        snap_init: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap_init["weekly_dd_amount"] == 2_000

        # Simulate week advancing (without touching protected fields)
        future_week = datetime.now(UTC) + timedelta(days=8)
        monkeypatch.setattr("risk.drawdown.now_utc", lambda: future_week)
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["weekly_dd_amount"] == 0.0


# ──────────────────────────────────────────────────────────────────
#  Breach detection
# ──────────────────────────────────────────────────────────────────

class TestBreachDetection:
    def test_no_breach_when_within_limits(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_000, pnl=-1_000)  # 1% daily < 3% max
        assert mon.is_breached() is False

    def test_daily_breach(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(97_000, pnl=-3_000)  # 3% daily == limit → breached
        assert mon.is_breached() is True

    def test_weekly_breach(self) -> None:
        mon = _build_monitor(100_000)
        # Spread losses across "multiple days" by accumulating weekly
        mon.update(99_000, pnl=-1_000)
        mon.update(98_000, pnl=-1_000)
        mon.update(97_000, pnl=-1_000)
        mon.update(96_000, pnl=-1_000)
        mon.update(95_000, pnl=-1_000)  # weekly = 5k = 5% == limit → breached
        assert mon.is_breached() is True

    def test_total_breach_from_peak(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(105_000)  # new peak
        mon.update(94_000)   # total DD = 11k / 105k ≈ 10.5% > 10%
        assert mon.is_breached() is True

    def test_zero_peak_does_not_crash(self) -> None:
        """Edge case: peak_equity is 0 → should not divide-by-zero."""
        mon = _build_monitor(0)
        assert mon.is_breached() is False


# ──────────────────────────────────────────────────────────────────
#  check_and_raise
# ──────────────────────────────────────────────────────────────────

class TestCheckAndRaise:
    def test_raises_when_breached(self) -> None:
        from risk.exceptions import DrawdownLimitExceeded

        mon = _build_monitor(100_000)
        mon.update(96_000, pnl=-4_000)  # 4% > 3% daily
        with pytest.raises(DrawdownLimitExceeded):
            mon.check_and_raise()

    def test_no_raise_when_safe(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_500, pnl=-500)
        mon.check_and_raise()  # should not raise


# ──────────────────────────────────────────────────────────────────
#  Redis persistence
# ──────────────────────────────────────────────────────────────────

class TestRedisPersistence:
    def test_state_persisted_on_update(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(99_000, pnl=-1_000)
        store: dict[str, str] = mon._test_redis._store  # type: ignore[attr-defined]
        assert float(store["wolf15:risk:drawdown:daily"]) == 1_000
        assert float(store["wolf15:risk:peak_equity"]) == 100_000

    def test_peak_equity_persisted_on_new_high(self) -> None:
        mon = _build_monitor(100_000)
        mon.update(105_000)
        store: dict[str, str] = mon._test_redis._store  # type: ignore[attr-defined]
        assert float(store["wolf15:risk:peak_equity"]) == 105_000


# ──────────────────────────────────────────────────────────────────
#  Thread safety sanity check
# ──────────────────────────────────────────────────────────────────

class TestThreadSafety:
    def test_concurrent_updates_do_not_corrupt(self) -> None:
        mon = _build_monitor(100_000)
        errors: list[Exception] = []

        def worker(equity: float, pnl: float | None) -> None:
            try:
                for _ in range(50):
                    mon.update(equity, pnl=pnl)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(99_000, -100)),
            threading.Thread(target=worker, args=(98_500, -200)),
            threading.Thread(target=worker, args=(101_000, None)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent update errors: {errors}"
        snap: dict[str, float] = mon.get_snapshot()  # type: ignore[assignment]
        assert snap["peak_equity"] >= 100_000
        assert snap["daily_dd_amount"] >= 0.0
