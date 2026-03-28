"""
P1-9: Compliance Auto-Mode & Guard Tests
==========================================
Tests auto-trading state machine, pause/resume, enforcement,
event emission, idempotency, and compliance guard rules.
"""

from __future__ import annotations

import pytest

from core.redis_keys import COMPLIANCE_AUTO_MODE_STATE
from services.orchestrator.compliance_auto_mode import (
    AutoModeTransition,
    AutoTradingState,
    ComplianceAutoMode,
    ComplianceAutoModePaused,
)
from services.orchestrator.compliance_guard import (
    ComplianceResult,
    evaluate_compliance,
)

# ── Auto-Mode State Machine ──────────────────────────────────────────────


class TestAutoTradingStateMachine:
    @pytest.fixture
    def auto_mode(self):
        return ComplianceAutoMode()

    def test_initial_state_is_enabled(self, auto_mode):
        assert auto_mode.state == AutoTradingState.ENABLED
        assert auto_mode.is_enabled is True
        assert auto_mode.is_paused is False

    def test_pause_transitions_to_paused(self, auto_mode):
        transition = auto_mode.pause("DAILY_DD_LIMIT_BREACH", "DD exceeded", "system:compliance")
        assert auto_mode.state == AutoTradingState.PAUSED
        assert auto_mode.is_paused is True
        assert transition.previous_state == AutoTradingState.ENABLED
        assert transition.new_state == AutoTradingState.PAUSED
        assert transition.trigger_code == "DAILY_DD_LIMIT_BREACH"

    def test_resume_transitions_to_enabled(self, auto_mode):
        auto_mode.pause("TEST", "test", "system:compliance")
        transition = auto_mode.resume("Risk cleared", "admin")
        assert auto_mode.state == AutoTradingState.ENABLED
        assert transition.previous_state == AutoTradingState.PAUSED
        assert transition.new_state == AutoTradingState.ENABLED
        assert transition.trigger_code == "OPERATOR_RESUME"
        assert transition.actor == "admin"

    def test_resume_when_enabled_raises(self, auto_mode):
        with pytest.raises(ValueError, match="already enabled"):
            auto_mode.resume("No reason", "admin")

    def test_pause_is_idempotent(self, auto_mode):
        auto_mode.pause("FIRST", "first pause", "system:compliance")
        transition = auto_mode.pause("SECOND", "duplicate pause", "system:compliance")
        assert auto_mode.state == AutoTradingState.PAUSED
        assert "Already paused" in transition.reason

    def test_transition_history_recorded(self, auto_mode):
        auto_mode.pause("TEST_CODE", "testing", "system:compliance")
        auto_mode.resume("reset", "admin")
        history = auto_mode.transition_history
        assert len(history) == 2
        assert history[0].new_state == AutoTradingState.PAUSED
        assert history[1].new_state == AutoTradingState.ENABLED


# ── Enforcement ───────────────────────────────────────────────────────────


class TestAutoModeEnforcement:
    def test_enforce_passes_when_enabled(self):
        mode = ComplianceAutoMode()
        mode.enforce()  # Should not raise

    def test_enforce_raises_when_paused(self):
        mode = ComplianceAutoMode()
        mode.pause("TEST", "test", "system")
        with pytest.raises(ComplianceAutoModePaused):
            mode.enforce()


# ── AutoModeTransition ────────────────────────────────────────────────────


class TestAutoModeTransition:
    def test_to_dict(self):
        t = AutoModeTransition(
            previous_state=AutoTradingState.ENABLED,
            new_state=AutoTradingState.PAUSED,
            trigger_code="CODE",
            reason="test",
            actor="system",
        )
        d = t.to_dict()
        assert d["previous_state"] == "ENABLED"
        assert d["new_state"] == "PAUSED"
        assert d["trigger_code"] == "CODE"
        assert "timestamp" in d

    def test_frozen_dataclass(self):
        t = AutoModeTransition(
            previous_state=AutoTradingState.ENABLED,
            new_state=AutoTradingState.PAUSED,
            trigger_code="CODE",
            reason="test",
            actor="system",
        )
        with pytest.raises(AttributeError):
            t.reason = "changed"  # type: ignore[misc]


# ── Compliance Guard ──────────────────────────────────────────────────────


class TestComplianceGuard:
    def test_missing_account_state(self):
        result = evaluate_compliance({}, {})
        assert result.allowed is False
        assert result.code == "ACCOUNT_STATE_MISSING"

    def test_invalid_balance(self):
        result = evaluate_compliance({"balance": 0, "equity": 0}, {})
        assert result.allowed is False
        assert result.code == "ACCOUNT_VALUE_INVALID"

    def test_compliance_mode_off(self):
        result = evaluate_compliance(
            {"balance": 100_000, "equity": 100_000, "compliance_mode": False},
            {},
        )
        assert result.allowed is False
        assert result.code == "COMPLIANCE_MODE_OFF"

    def test_account_locked(self):
        result = evaluate_compliance(
            {"balance": 100_000, "equity": 100_000, "compliance_mode": True, "account_locked": True},
            {},
        )
        assert result.allowed is False
        assert result.code == "ACCOUNT_LOCKED"

    def test_system_lockdown(self):
        for state in ("LOCKDOWN", "HALTED", "KILL_SWITCH"):
            result = evaluate_compliance(
                {"balance": 100_000, "equity": 100_000, "compliance_mode": True, "system_state": state},
                {},
            )
            assert result.allowed is False
            assert result.code == "SYSTEM_LOCKDOWN"

    def test_circuit_breaker_open(self):
        result = evaluate_compliance(
            {"balance": 100_000, "equity": 100_000, "compliance_mode": True, "circuit_breaker": True},
            {},
        )
        assert result.allowed is False
        assert result.code == "CIRCUIT_BREAKER_OPEN"

    def test_daily_dd_limit_breach(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 100_000,
                "compliance_mode": True,
                "daily_dd_percent": 5.0,
                "max_daily_dd_percent": 5.0,
            },
            {},
        )
        assert result.allowed is False
        assert result.code == "DAILY_DD_LIMIT_BREACH"

    def test_daily_dd_near_limit(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 100_000,
                "compliance_mode": True,
                "daily_dd_percent": 4.6,
                "max_daily_dd_percent": 5.0,
            },
            {},
        )
        assert result.allowed is False
        assert result.code == "DAILY_DD_NEAR_LIMIT"

    def test_total_dd_limit_breach(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 100_000,
                "compliance_mode": True,
                "total_dd_percent": 10.0,
                "max_total_dd_percent": 10.0,
            },
            {},
        )
        assert result.allowed is False
        assert result.code == "TOTAL_DD_LIMIT_BREACH"

    def test_max_open_trades_reached(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 100_000,
                "compliance_mode": True,
                "open_trades": 5,
                "max_concurrent_trades": 5,
            },
            {},
        )
        assert result.allowed is False
        assert result.code == "MAX_OPEN_TRADES_REACHED"

    def test_trade_risk_too_high(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 100_000,
                "compliance_mode": True,
                "max_risk_per_trade_percent": 2.0,
            },
            {"risk_percent": 5.0},
        )
        assert result.allowed is False
        assert result.code == "TRADE_RISK_TOO_HIGH"

    def test_healthy_account_passes(self):
        result = evaluate_compliance(
            {
                "balance": 100_000,
                "equity": 99_500,
                "compliance_mode": True,
                "daily_dd_percent": 1.0,
                "max_daily_dd_percent": 5.0,
                "total_dd_percent": 2.0,
                "max_total_dd_percent": 10.0,
                "open_trades": 2,
                "max_concurrent_trades": 5,
            },
            {"risk_percent": 1.0},
        )
        assert result.allowed is True
        assert result.code == "OK"


# ── State Persistence (SVC-BUG-06) ───────────────────────────────────────


class _FakeRedis:
    """Minimal Redis fake for auto-mode persistence tests."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class _BrokenRedis:
    """Redis that always raises on access."""

    def get(self, key: str) -> str | None:
        raise ConnectionError("Redis unavailable")

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise ConnectionError("Redis unavailable")


class TestAutoModeStatePersistence:
    def test_no_redis_defaults_to_enabled(self):
        mode = ComplianceAutoMode(redis_client=None)
        assert mode.state == AutoTradingState.ENABLED

    def test_fresh_redis_defaults_to_enabled(self):
        redis = _FakeRedis()
        mode = ComplianceAutoMode(redis_client=redis)
        assert mode.state == AutoTradingState.ENABLED

    def test_pause_persists_to_redis(self):
        redis = _FakeRedis()
        mode = ComplianceAutoMode(redis_client=redis)
        mode.pause("DD_BREACH", "daily dd exceeded", "system:compliance")
        assert redis.store[COMPLIANCE_AUTO_MODE_STATE] == "PAUSED"

    def test_resume_persists_to_redis(self):
        redis = _FakeRedis()
        mode = ComplianceAutoMode(redis_client=redis)
        mode.pause("DD_BREACH", "daily dd exceeded", "system:compliance")
        mode.resume("Risk cleared", "admin")
        assert redis.store[COMPLIANCE_AUTO_MODE_STATE] == "ENABLED"

    def test_restart_restores_paused_state(self):
        """Simulate restart: pause, then create new instance with same Redis."""
        redis = _FakeRedis()
        mode1 = ComplianceAutoMode(redis_client=redis)
        mode1.pause("VIOLATION", "compliance violation", "system:compliance")

        # Simulate restart — new instance, same Redis
        mode2 = ComplianceAutoMode(redis_client=redis)
        assert mode2.state == AutoTradingState.PAUSED
        assert mode2.is_paused is True

    def test_restart_after_resume_is_enabled(self):
        """After operator resume + restart, state should be ENABLED."""
        redis = _FakeRedis()
        mode1 = ComplianceAutoMode(redis_client=redis)
        mode1.pause("VIOLATION", "test", "system:compliance")
        mode1.resume("Cleared", "admin")

        mode2 = ComplianceAutoMode(redis_client=redis)
        assert mode2.state == AutoTradingState.ENABLED

    def test_redis_failure_on_init_defaults_to_paused(self):
        """If Redis is unreachable on startup, default to PAUSED for safety."""
        redis = _BrokenRedis()
        mode = ComplianceAutoMode(redis_client=redis)
        assert mode.state == AutoTradingState.PAUSED

    def test_redis_failure_on_persist_does_not_crash(self):
        """Write failure is best-effort — should not raise."""
        redis = _FakeRedis()
        mode = ComplianceAutoMode(redis_client=redis)
        # Break redis after init
        mode._redis = _BrokenRedis()  # noqa: SLF001
        mode.pause("TEST", "test", "system:compliance")
        assert mode.state == AutoTradingState.PAUSED  # state changed in-memory

    def test_compliance_result_fields(self):
        result = ComplianceResult(True, "OK", "info")
        assert result.allowed is True
        assert result.code == "OK"
        assert result.severity == "info"
        assert result.details == {}
