"""
P1-3: Risk Firewall Tests
===========================
Tests ordered check execution, short-circuit on HARD_FAIL, immutable results,
individual check logic, and event emission for the risk firewall.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from risk.firewall import (
    CheckSeverity,
    FirewallCheckResult,
    FirewallResult,
    FirewallVerdict,
    RiskFirewall,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


async def _noop(*args, **kwargs):
    pass


def _make_mock_redis():
    """Create a mock that looks like RedisClient — all methods return None/0."""
    m = MagicMock()
    m.get.return_value = None
    m.set.return_value = None
    m.client.get.return_value = None
    m.client.set.return_value = None
    return m


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    """Prevent any test in this module from touching a real Redis."""
    mock_redis = _make_mock_redis()
    monkeypatch.setattr("storage.redis_client.redis_client", mock_redis)


class _MockKillSwitch:
    """Fake GlobalKillSwitch that doesn't need Redis."""

    is_active = False

    class state:  # noqa: N801
        reason = ""


@pytest.fixture
def firewall(monkeypatch):
    fw = RiskFirewall()
    monkeypatch.setattr(fw, "_persist", _noop)
    monkeypatch.setattr(fw, "_emit_event", _noop)
    monkeypatch.setattr("risk.kill_switch.GlobalKillSwitch", _MockKillSwitch)
    return fw


@pytest.fixture
def healthy_account():
    """Account state where all checks pass."""
    return {
        "account_id": "ACC-001",
        "balance": 100_000.0,
        "equity": 99_500.0,
        "open_positions": 1,
        "max_concurrent_trades": 5,
        "news_locked": False,
        "daily_loss": 100.0,
        "daily_loss_limit": 5_000.0,
        "pair_cooldowns": {},
        "session_allowed": True,
    }


@pytest.fixture
def valid_signal():
    return {
        "signal_id": "SIG-001",
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 1.0850,
        "stop_loss": 1.0800,
        "take_profit_1": 1.0950,
        "risk_percent": 1.0,
        "lot_size": 0.1,
    }


# ── FirewallResult immutability ───────────────────────────────────────────


class TestFirewallResultImmutability:
    def test_frozen_dataclass(self):
        check = FirewallCheckResult(
            check_name="kill_switch",
            order=1,
            severity=CheckSeverity.PASS,
            code="OK",
            message="test",
        )
        result = FirewallResult(
            firewall_id="fw_test",
            take_id="take_test",
            verdict=FirewallVerdict.APPROVED,
            checks=(check,),
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
        )
        # Frozen dataclass should not allow mutation
        with pytest.raises(AttributeError):
            result.verdict = FirewallVerdict.REJECTED  # type: ignore[misc]

    def test_to_dict_serialization(self):
        check = FirewallCheckResult(
            check_name="kill_switch",
            order=1,
            severity=CheckSeverity.PASS,
            code="OK",
            message="clean",
        )
        result = FirewallResult(
            firewall_id="fw_test",
            take_id="take_test",
            verdict=FirewallVerdict.APPROVED,
            checks=(check,),
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
        )
        d = result.to_dict()
        assert d["firewall_id"] == "fw_test"
        assert d["verdict"] == "APPROVED"
        assert len(d["checks"]) == 1
        assert d["checks"][0]["severity"] == "PASS"
        assert d["short_circuited_at"] is None


# ── Ordered execution and short-circuit ───────────────────────────────────


class TestFirewallOrderedExecution:
    async def test_all_checks_pass_approved(self, firewall, valid_signal, healthy_account):
        """When all checks pass, verdict is APPROVED."""
        result = await firewall.evaluate("take_001", valid_signal, healthy_account)
        assert result.verdict == FirewallVerdict.APPROVED
        assert result.short_circuited_at is None
        assert len(result.checks) == 8
        # All checks should be PASS or SKIP
        for check in result.checks:
            assert check.severity in (CheckSeverity.PASS, CheckSeverity.SKIP)

    async def test_checks_in_strict_order(self, firewall, valid_signal, healthy_account):
        """Checks must appear in order 1-8."""
        result = await firewall.evaluate("take_001", valid_signal, healthy_account)
        orders = [c.order for c in result.checks]
        assert orders == sorted(orders)
        assert orders[0] == 1

    async def test_kill_switch_short_circuits(self, firewall, valid_signal, healthy_account, monkeypatch):
        """Kill switch active should short-circuit at check 1."""

        class FakeKillSwitch:
            is_active = True

            class state:  # noqa: N801
                reason = "Emergency shutdown"

        monkeypatch.setattr(
            "risk.firewall.RiskFirewall._check_kill_switch",
            lambda self, s, a: _make_hard_fail("kill_switch", 1, "KILL_SWITCH_ACTIVE"),
        )

        result = await firewall.evaluate("take_002", valid_signal, healthy_account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "kill_switch"
        assert len(result.checks) == 1  # Remaining checks never ran

    async def test_concurrent_trades_hard_fail(self, firewall, valid_signal):
        """Max concurrent trades hit should cause HARD_FAIL."""
        blocked_account = {
            "account_id": "ACC-001",
            "open_positions": 5,
            "max_concurrent_trades": 5,
            "news_locked": False,
            "daily_loss": 0.0,
            "daily_loss_limit": 5_000.0,
            "pair_cooldowns": {},
            "session_allowed": True,
        }
        result = await firewall.evaluate("take_003", valid_signal, blocked_account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "concurrent_trades"
        # Should stop before checks 5-8
        assert len(result.checks) <= 4

    async def test_news_lock_hard_fail(self, firewall, valid_signal):
        account = {
            "account_id": "ACC-001",
            "open_positions": 0,
            "max_concurrent_trades": 5,
            "news_locked": True,
            "daily_loss": 0.0,
            "daily_loss_limit": 5_000.0,
            "pair_cooldowns": {},
            "session_allowed": True,
        }
        result = await firewall.evaluate("take_004", valid_signal, account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "news_lock"

    async def test_daily_drawdown_hard_fail(self, firewall, valid_signal):
        account = {
            "account_id": "ACC-001",
            "open_positions": 0,
            "max_concurrent_trades": 5,
            "news_locked": False,
            "daily_loss": 5_000.0,
            "daily_loss_limit": 5_000.0,
            "pair_cooldowns": {},
            "session_allowed": True,
        }
        result = await firewall.evaluate("take_005", valid_signal, account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "daily_drawdown"

    async def test_pair_cooldown_hard_fail(self, firewall, valid_signal):
        account = {
            "account_id": "ACC-001",
            "open_positions": 0,
            "max_concurrent_trades": 5,
            "news_locked": False,
            "daily_loss": 0.0,
            "daily_loss_limit": 5_000.0,
            "pair_cooldowns": {"EURUSD": "2026-12-31T23:59:59Z"},
            "session_allowed": True,
        }
        result = await firewall.evaluate("take_006", valid_signal, account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "pair_cooldown"

    async def test_session_window_closed(self, firewall, valid_signal):
        account = {
            "account_id": "ACC-001",
            "open_positions": 0,
            "max_concurrent_trades": 5,
            "news_locked": False,
            "daily_loss": 0.0,
            "daily_loss_limit": 5_000.0,
            "pair_cooldowns": {},
            "session_allowed": False,
        }
        result = await firewall.evaluate("take_007", valid_signal, account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.short_circuited_at == "session_window"

    async def test_firewall_id_is_unique(self, firewall, valid_signal, healthy_account):
        r1 = await firewall.evaluate("take_a", valid_signal, healthy_account)
        r2 = await firewall.evaluate("take_b", valid_signal, healthy_account)
        assert r1.firewall_id != r2.firewall_id

    async def test_check_exception_becomes_hard_fail(self, firewall, valid_signal, healthy_account, monkeypatch):
        """If a check function raises, it becomes HARD_FAIL with CHECK_ERROR code."""

        async def _broken_check(self, signal, account):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "risk.firewall.RiskFirewall._check_kill_switch",
            _broken_check,
        )
        result = await firewall.evaluate("take_err", valid_signal, healthy_account)
        assert result.verdict == FirewallVerdict.REJECTED
        assert result.checks[0].severity == CheckSeverity.HARD_FAIL
        assert result.checks[0].code == "CHECK_ERROR"


# ── Enums ─────────────────────────────────────────────────────────────────


class TestFirewallEnums:
    def test_verdict_values(self):
        assert FirewallVerdict.APPROVED == "APPROVED"
        assert FirewallVerdict.REJECTED == "REJECTED"

    def test_severity_values(self):
        assert CheckSeverity.PASS == "PASS"
        assert CheckSeverity.WARN == "WARN"
        assert CheckSeverity.HARD_FAIL == "HARD_FAIL"
        assert CheckSeverity.SKIP == "SKIP"


# ── Helpers ───────────────────────────────────────────────────────────────


async def _make_hard_fail(name: str, order: int, code: str) -> FirewallCheckResult:
    return FirewallCheckResult(
        check_name=name,
        order=order,
        severity=CheckSeverity.HARD_FAIL,
        code=code,
        message=f"Hard fail: {code}",
    )
