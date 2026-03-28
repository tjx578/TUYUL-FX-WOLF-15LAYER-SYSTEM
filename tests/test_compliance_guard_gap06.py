"""ARCH-GAP-06: Compliance guard — news lock, session lock, correlation, data freshness.

Tests the 4 new compliance checks added to evaluate_compliance() and the
StateManager._refresh_compliance_signals() wiring that populates them.
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from services.orchestrator.compliance_guard import evaluate_compliance

# ---------------------------------------------------------------------------
# Shared fixture: healthy account state that passes all existing checks
# ---------------------------------------------------------------------------

def _healthy_state(**overrides: object) -> dict:
    base = {
        "balance": 100_000,
        "equity": 99_500,
        "compliance_mode": True,
        "daily_dd_percent": 1.0,
        "max_daily_dd_percent": 5.0,
        "total_dd_percent": 2.0,
        "max_total_dd_percent": 10.0,
        "open_trades": 1,
        "max_concurrent_trades": 5,
    }
    base.update(overrides)
    return base


_TRADE_RISK: dict = {"risk_percent": 1.0}


# ══════════════════════════════════════════════════════════════════════════
# 1. News Lock Check
# ══════════════════════════════════════════════════════════════════════════


class TestNewsLockCheck:
    def test_news_lock_active_blocks(self):
        state = _healthy_state(news_lock_active=True, news_lock_reason="NFP release")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "NEWS_LOCK_ACTIVE"
        assert result.severity == "warning"
        assert result.details["reason"] == "NFP release"

    def test_news_lock_active_string_true(self):
        state = _healthy_state(news_lock_active="true")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "NEWS_LOCK_ACTIVE"

    def test_news_lock_inactive_passes(self):
        state = _healthy_state(news_lock_active=False)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_news_lock_missing_passes(self):
        state = _healthy_state()
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_news_lock_default_reason(self):
        state = _healthy_state(news_lock_active=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.details["reason"] == "high_impact_event"


# ══════════════════════════════════════════════════════════════════════════
# 2. Session Lock Check
# ══════════════════════════════════════════════════════════════════════════


class TestSessionLockCheck:
    def test_session_locked_blocks(self):
        state = _healthy_state(session_locked=True, session_lock_reason="forex_market_closed")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "SESSION_LOCKED"
        assert result.severity == "warning"
        assert result.details["reason"] == "forex_market_closed"

    def test_session_locked_string_true(self):
        state = _healthy_state(session_locked="1")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "SESSION_LOCKED"

    def test_session_not_locked_passes(self):
        state = _healthy_state(session_locked=False)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_session_locked_missing_passes(self):
        state = _healthy_state()
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_session_lock_default_reason(self):
        state = _healthy_state(session_locked=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.details["reason"] == "market_closed"


# ══════════════════════════════════════════════════════════════════════════
# 3. Correlation Exposure Check
# ══════════════════════════════════════════════════════════════════════════


class TestCorrelationBreachCheck:
    def test_correlation_breached_blocks(self):
        state = _healthy_state(
            correlation_breached=True,
            correlation_breach_reason="EURUSD+GBPUSD group at 3.5% exposure",
        )
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "CORRELATION_LIMIT_BREACHED"
        assert result.severity == "warning"
        assert "EURUSD" in result.details["reason"]

    def test_correlation_not_breached_passes(self):
        state = _healthy_state(correlation_breached=False)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_correlation_missing_passes(self):
        state = _healthy_state()
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_correlation_default_reason(self):
        state = _healthy_state(correlation_breached=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.details["reason"] == "group_exposure_exceeded"


# ══════════════════════════════════════════════════════════════════════════
# 4. Data Freshness Check
# ══════════════════════════════════════════════════════════════════════════


class TestDataFreshnessCheck:
    def test_data_stale_blocks(self):
        state = _healthy_state(
            data_stale=True,
            feed_freshness_class="STALE_PRESERVED",
            staleness_seconds=300.0,
        )
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "DATA_STALE"
        assert result.severity == "warning"
        assert result.details["feed_freshness"] == "STALE_PRESERVED"
        assert result.details["staleness_seconds"] == 300.0

    def test_data_stale_no_producer(self):
        state = _healthy_state(data_stale=True, feed_freshness_class="NO_PRODUCER")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "DATA_STALE"
        assert result.details["feed_freshness"] == "NO_PRODUCER"

    def test_data_fresh_passes(self):
        state = _healthy_state(data_stale=False, feed_freshness_class="LIVE")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_data_stale_missing_passes(self):
        state = _healthy_state()
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is True

    def test_data_stale_string_true(self):
        state = _healthy_state(data_stale="yes")
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.allowed is False
        assert result.code == "DATA_STALE"


# ══════════════════════════════════════════════════════════════════════════
# 5. Check Ordering / Priority
# ══════════════════════════════════════════════════════════════════════════


class TestCheckOrdering:
    """Verify critical checks fire before the 4 new environmental checks."""

    def test_circuit_breaker_beats_news_lock(self):
        state = _healthy_state(circuit_breaker=True, news_lock_active=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "CIRCUIT_BREAKER_OPEN"

    def test_account_locked_beats_session_lock(self):
        state = _healthy_state(account_locked=True, session_locked=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "ACCOUNT_LOCKED"

    def test_system_lockdown_beats_data_stale(self):
        state = _healthy_state(system_state="LOCKDOWN", data_stale=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "SYSTEM_LOCKDOWN"

    def test_news_lock_beats_session_lock(self):
        """News lock appears before session lock in the check chain."""
        state = _healthy_state(news_lock_active=True, session_locked=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "NEWS_LOCK_ACTIVE"

    def test_session_lock_beats_correlation(self):
        state = _healthy_state(session_locked=True, correlation_breached=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "SESSION_LOCKED"

    def test_correlation_beats_data_stale(self):
        state = _healthy_state(correlation_breached=True, data_stale=True)
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "CORRELATION_LIMIT_BREACHED"

    def test_all_four_active_news_lock_wins(self):
        state = _healthy_state(
            news_lock_active=True,
            session_locked=True,
            correlation_breached=True,
            data_stale=True,
        )
        result = evaluate_compliance(state, _TRADE_RISK)
        assert result.code == "NEWS_LOCK_ACTIVE"


# ══════════════════════════════════════════════════════════════════════════
# 6. StateManager._refresh_compliance_signals() Wiring
# ══════════════════════════════════════════════════════════════════════════


class _FakeRedis:
    """Minimal sync Redis stub for StateManager tests."""

    def __init__(self, store: dict[str, str] | None = None) -> None:
        self._store: dict[str, str] = store or {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(k) for k in keys]

    def pubsub(self):
        return _FakePubSub()

    def publish(self, channel: str, message: str) -> int:
        return 0

    def pipeline(self):
        return _FakePipeline(self)


class _FakePubSub:
    def subscribe(self, channel: str) -> None:
        pass

    def close(self) -> None:
        pass

    def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.0):
        return None


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list = []

    def publish(self, channel: str, message: str):
        self._ops.append(("publish", channel, message))
        return self

    def set(self, key: str, value: str, ex: int | None = None):
        self._ops.append(("set", key, value))
        return self

    def execute(self):
        for op in self._ops:
            if op[0] == "set":
                self._redis._store[op[1]] = op[2]


class TestStateManagerComplianceSignals:
    @pytest.fixture
    def _import_sm(self):
        from services.orchestrator.state_manager import StateManager
        return StateManager

    def _make_manager(self, StateManager, store: dict[str, str] | None = None):  # noqa: N803
        redis = _FakeRedis(store or {})
        mgr = StateManager(redis_client=redis)
        return mgr

    def test_news_lock_populated_from_redis(self, _import_sm):
        store = {
            "NEWS_LOCK:STATE": json.dumps({"locked": True, "reason": "Pre-NFP lock"}),
        }
        mgr = self._make_manager(_import_sm, store)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["news_lock_active"] is True
        assert mgr._account_state["news_lock_reason"] == "Pre-NFP lock"

    def test_news_lock_absent_means_inactive(self, _import_sm):
        mgr = self._make_manager(_import_sm)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["news_lock_active"] is False

    def test_session_locked_when_market_closed(self, _import_sm):
        mgr = self._make_manager(_import_sm)
        with patch("services.orchestrator.state_manager.is_forex_market_open", return_value=False):
            mgr._refresh_compliance_signals()
        assert mgr._account_state["session_locked"] is True
        assert mgr._account_state["session_lock_reason"] == "forex_market_closed"

    def test_session_open_when_market_open(self, _import_sm):
        mgr = self._make_manager(_import_sm)
        with patch("services.orchestrator.state_manager.is_forex_market_open", return_value=True):
            mgr._refresh_compliance_signals()
        assert mgr._account_state["session_locked"] is False

    def test_data_stale_when_no_heartbeat(self, _import_sm):
        mgr = self._make_manager(_import_sm)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["data_stale"] is True
        assert mgr._account_state["feed_freshness_class"] == "NO_PRODUCER"

    def test_data_fresh_with_recent_heartbeat(self, _import_sm):
        from core.redis_keys import HEARTBEAT_INGEST
        store = {
            HEARTBEAT_INGEST: json.dumps({"producer": "ingest", "ts": time.time()}),
        }
        mgr = self._make_manager(_import_sm, store)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["data_stale"] is False
        assert mgr._account_state["feed_freshness_class"] == "LIVE"

    def test_data_stale_with_old_heartbeat(self, _import_sm):
        from core.redis_keys import HEARTBEAT_INGEST
        store = {
            HEARTBEAT_INGEST: json.dumps({"producer": "ingest", "ts": time.time() - 300}),
        }
        mgr = self._make_manager(_import_sm, store)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["data_stale"] is True
        assert mgr._account_state["feed_freshness_class"] == "STALE_PRESERVED"
        assert mgr._account_state["staleness_seconds"] >= 299.0

    def test_data_stale_with_zero_ts_heartbeat(self, _import_sm):
        from core.redis_keys import HEARTBEAT_INGEST
        store = {
            HEARTBEAT_INGEST: json.dumps({"producer": "ingest", "ts": 0}),
        }
        mgr = self._make_manager(_import_sm, store)
        mgr._refresh_compliance_signals()
        assert mgr._account_state["data_stale"] is True
        assert mgr._account_state["feed_freshness_class"] == "NO_PRODUCER"

    def test_redis_failure_does_not_crash(self, _import_sm):
        """Redis error in compliance signal refresh should be caught gracefully."""
        mgr = self._make_manager(_import_sm)
        # Sabotage the mget to fail on second call (compliance signals)
        original_mget = mgr._redis.mget
        call_count = 0

        def failing_mget(keys):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise ConnectionError("Redis down")
            return original_mget(keys)

        mgr._redis.mget = failing_mget
        # First call: refresh snapshots (succeeds)
        # Second call inside _refresh_compliance_signals (fails gracefully)
        mgr._refresh_snapshots_from_redis()
        # Should not raise — just logs warning


# ══════════════════════════════════════════════════════════════════════════
# 7. End-to-end: StateManager populates → evaluate_compliance blocks
# ══════════════════════════════════════════════════════════════════════════


class TestEndToEndComplianceFlow:
    @pytest.fixture
    def _import_sm(self):
        from services.orchestrator.state_manager import StateManager
        return StateManager

    def test_news_lock_blocks_via_state_manager(self, _import_sm):
        from core.redis_keys import ACCOUNT_STATE, TRADE_RISK
        store = {
            ACCOUNT_STATE: json.dumps({
                "balance": 100_000,
                "equity": 99_500,
                "compliance_mode": True,
            }),
            TRADE_RISK: json.dumps({"risk_percent": 1.0}),
            "NEWS_LOCK:STATE": json.dumps({"locked": True, "reason": "FOMC"}),
        }
        mgr = self._make_manager(_import_sm, store)
        with patch("services.orchestrator.state_manager.is_forex_market_open", return_value=True):
            mgr._refresh_snapshots_from_redis()
        result = evaluate_compliance(mgr._account_state, mgr._trade_risk)
        assert result.allowed is False
        assert result.code == "NEWS_LOCK_ACTIVE"

    def test_market_closed_blocks_via_state_manager(self, _import_sm):
        from core.redis_keys import ACCOUNT_STATE, HEARTBEAT_INGEST, TRADE_RISK
        store = {
            ACCOUNT_STATE: json.dumps({
                "balance": 100_000,
                "equity": 99_500,
                "compliance_mode": True,
            }),
            TRADE_RISK: json.dumps({"risk_percent": 1.0}),
            HEARTBEAT_INGEST: json.dumps({"producer": "ingest", "ts": time.time()}),
        }
        mgr = self._make_manager(_import_sm, store)
        with patch("services.orchestrator.state_manager.is_forex_market_open", return_value=False):
            mgr._refresh_snapshots_from_redis()
        result = evaluate_compliance(mgr._account_state, mgr._trade_risk)
        assert result.allowed is False
        assert result.code == "SESSION_LOCKED"

    def test_all_clear_passes_via_state_manager(self, _import_sm):
        from core.redis_keys import ACCOUNT_STATE, HEARTBEAT_INGEST, TRADE_RISK
        store = {
            ACCOUNT_STATE: json.dumps({
                "balance": 100_000,
                "equity": 99_500,
                "compliance_mode": True,
            }),
            TRADE_RISK: json.dumps({"risk_percent": 1.0}),
            HEARTBEAT_INGEST: json.dumps({"producer": "ingest", "ts": time.time()}),
        }
        mgr = self._make_manager(_import_sm, store)
        with patch("services.orchestrator.state_manager.is_forex_market_open", return_value=True):
            mgr._refresh_snapshots_from_redis()
        result = evaluate_compliance(mgr._account_state, mgr._trade_risk)
        assert result.allowed is True
        assert result.code == "OK"

    def _make_manager(self, StateManager, store: dict[str, str]):  # noqa: N803
        redis = _FakeRedis(store)
        return StateManager(redis_client=redis)
