"""Tests for accounts/capital_deployment.py — readiness, usable capital, eligibility."""

from __future__ import annotations

import pytest

from accounts.capital_deployment import (
    build_readiness,
    compute_eligibility_flags,
    compute_lock_reasons,
    compute_readiness_score,
    compute_usable_capital,
)

# ── Readiness Score ────────────────────────────────────────────


class TestReadinessScore:
    def test_perfect_score(self):
        """Fully healthy account should score close to 1.0."""
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
            news_lock=False,
            account_locked=False,
        )
        assert score == 1.0

    def test_locked_account_returns_zero(self):
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
            account_locked=True,
        )
        assert score == 0.0

    def test_circuit_breaker_returns_zero(self):
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=True,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
        )
        assert score == 0.0

    def test_daily_dd_reduces_score(self):
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=4.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
        )
        # Daily headroom = 20%, so daily_score = 0.2 * 0.4 = 0.08
        # total = 1.0 * 0.3 = 0.3, slot = 1.0 * 0.2 = 0.2, compliance = 0.1
        # total = 0.08 + 0.3 + 0.2 + 0.1 = 0.68
        assert 0.6 < score < 0.75

    def test_full_slots_reduces_score(self):
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=5,
            max_concurrent_trades=5,
        )
        # slot_score = 0 → lose 20% weight
        assert 0.75 < score < 0.85

    def test_news_lock_penalty(self):
        with_lock = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
            news_lock=True,
        )
        without_lock = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
            news_lock=False,
        )
        assert with_lock < without_lock

    @pytest.mark.parametrize(
        "daily_dd, total_dd, expected_min, expected_max",
        [
            (0.0, 0.0, 0.9, 1.01),
            (2.5, 5.0, 0.4, 0.7),
            (5.0, 10.0, 0.0, 0.15),
        ],
    )
    def test_readiness_ranges(self, daily_dd, total_dd, expected_min, expected_max):
        score = compute_readiness_score(
            compliance_mode=True,
            circuit_breaker=False,
            daily_dd_percent=daily_dd,
            max_daily_dd_percent=5.0,
            total_dd_percent=total_dd,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
        )
        assert expected_min <= score <= expected_max


# ── Usable Capital ────────────────────────────────────────────


class TestUsableCapital:
    def test_full_headroom(self):
        result = compute_usable_capital(
            equity=100_000.0,
            balance=100_000.0,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_risk_percent=0.0,
        )
        # min headroom = 5% → 100k * 5/100 = 5000
        assert result == 5_000.0

    def test_partial_dd(self):
        result = compute_usable_capital(
            equity=95_000.0,
            balance=100_000.0,
            daily_dd_percent=2.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=3.0,
            max_total_dd_percent=10.0,
            open_risk_percent=1.0,
        )
        # daily headroom = 3%, total headroom = 7%, min = 3%
        # after open risk: 3% - 1% = 2%
        # base = max(95k, 100k) = 100k → 100k * 2% = 2000
        assert result == 2_000.0

    def test_zero_equity_returns_zero(self):
        result = compute_usable_capital(
            equity=0.0,
            balance=0.0,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
        )
        assert result == 0.0

    def test_at_limit_returns_zero(self):
        result = compute_usable_capital(
            equity=90_000.0,
            balance=100_000.0,
            daily_dd_percent=5.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=10.0,
            max_total_dd_percent=10.0,
        )
        assert result == 0.0

    def test_open_risk_deducted(self):
        full = compute_usable_capital(
            equity=100_000.0,
            balance=100_000.0,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_risk_percent=0.0,
        )
        with_risk = compute_usable_capital(
            equity=100_000.0,
            balance=100_000.0,
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_risk_percent=2.0,
        )
        assert with_risk < full
        assert with_risk == 3_000.0  # 5% - 2% = 3% of 100k


# ── Eligibility Flags ────────────────────────────────────────


class TestEligibilityFlags:
    def test_all_clear(self):
        flags = compute_eligibility_flags(
            compliance_mode=True,
            circuit_breaker=False,
            account_locked=False,
            news_lock=False,
            ea_connected=True,
            data_source="EA",
            daily_dd_percent=1.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=2.0,
            max_total_dd_percent=10.0,
            open_trades=1,
            max_concurrent_trades=5,
        )
        assert flags["compliance_ok"] is True
        assert flags["circuit_breaker_ok"] is True
        assert flags["not_locked"] is True
        assert flags["no_news_lock"] is True
        assert flags["daily_dd_ok"] is True
        assert flags["total_dd_ok"] is True
        assert flags["slots_available"] is True
        assert flags["ea_linked"] is True

    def test_manual_not_ea_linked(self):
        flags = compute_eligibility_flags(
            compliance_mode=True,
            circuit_breaker=False,
            account_locked=False,
            news_lock=False,
            ea_connected=False,
            data_source="MANUAL",
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
        )
        assert flags["ea_linked"] is False

    def test_daily_dd_near_limit(self):
        flags = compute_eligibility_flags(
            compliance_mode=True,
            circuit_breaker=False,
            account_locked=False,
            news_lock=False,
            ea_connected=False,
            data_source="MANUAL",
            daily_dd_percent=4.6,  # 92% of 5.0
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=0,
            max_concurrent_trades=5,
        )
        assert flags["daily_dd_ok"] is False

    def test_no_slots(self):
        flags = compute_eligibility_flags(
            compliance_mode=True,
            circuit_breaker=False,
            account_locked=False,
            news_lock=False,
            ea_connected=False,
            data_source="MANUAL",
            daily_dd_percent=0.0,
            max_daily_dd_percent=5.0,
            total_dd_percent=0.0,
            max_total_dd_percent=10.0,
            open_trades=5,
            max_concurrent_trades=5,
        )
        assert flags["slots_available"] is False


# ── Lock Reasons ──────────────────────────────────────────────


class TestLockReasons:
    def test_no_locks_when_all_ok(self):
        flags = {
            "compliance_ok": True,
            "circuit_breaker_ok": True,
            "not_locked": True,
            "no_news_lock": True,
            "daily_dd_ok": True,
            "total_dd_ok": True,
            "slots_available": True,
            "ea_linked": True,
        }
        assert compute_lock_reasons(flags) == []

    def test_collects_multiple_reasons(self):
        flags = {
            "compliance_ok": False,
            "circuit_breaker_ok": False,
            "not_locked": True,
            "no_news_lock": True,
            "daily_dd_ok": True,
            "total_dd_ok": True,
            "slots_available": True,
            "ea_linked": False,
        }
        reasons = compute_lock_reasons(flags)
        assert len(reasons) == 2
        assert "Compliance mode disabled" in reasons
        assert "Circuit breaker OPEN" in reasons

    def test_ea_linked_not_a_lock_reason(self):
        """ea_linked=False is informational, not a lock."""
        flags = {
            "compliance_ok": True,
            "circuit_breaker_ok": True,
            "not_locked": True,
            "no_news_lock": True,
            "daily_dd_ok": True,
            "total_dd_ok": True,
            "slots_available": True,
            "ea_linked": False,
        }
        assert compute_lock_reasons(flags) == []


# ── Build Readiness (integration) ─────────────────────────────


class TestBuildReadiness:
    def test_build_healthy_account(self):
        result = build_readiness(
            "ACC-123",
            {
                "daily_dd_percent": "0.5",
                "total_dd_percent": "1.0",
                "open_risk_percent": "0.3",
                "open_trades": "1",
                "circuit_breaker": "0",
                "news_lock": "0",
                "account_locked": "0",
                "compliance_mode": "1",
                "ea_connected": "0",
                "data_source": "MANUAL",
            },
            equity=100_000.0,
            balance=100_000.0,
            max_daily_dd_percent=5.0,
            max_total_dd_percent=10.0,
            max_concurrent_trades=5,
        )
        assert result.account_id == "ACC-123"
        assert result.readiness_score > 0.8
        assert result.usable_capital > 0
        assert result.eligibility_flags["compliance_ok"] is True
        assert result.lock_reasons == []

    def test_build_locked_account(self):
        result = build_readiness(
            "ACC-456",
            {
                "daily_dd_percent": "4.8",
                "total_dd_percent": "9.5",
                "open_risk_percent": "2.0",
                "open_trades": "5",
                "circuit_breaker": "1",
                "news_lock": "0",
                "account_locked": "0",
                "compliance_mode": "1",
                "ea_connected": "0",
                "data_source": "MANUAL",
            },
            equity=90_000.0,
            balance=100_000.0,
            max_daily_dd_percent=5.0,
            max_total_dd_percent=10.0,
            max_concurrent_trades=5,
        )
        assert result.readiness_score == 0.0
        assert "Circuit breaker OPEN" in result.lock_reasons

    def test_build_with_empty_payload(self):
        """Redis payload missing → defaults to safe values."""
        result = build_readiness(
            "ACC-789",
            {},
            equity=50_000.0,
            balance=50_000.0,
            max_daily_dd_percent=4.0,
            max_total_dd_percent=8.0,
            max_concurrent_trades=3,
        )
        assert result.readiness_score == 1.0
        assert result.usable_capital == 2_000.0  # min(4%, 8%) = 4% of 50k = 2000

    def test_readiness_badge_mapping(self):
        """Readiness score maps to correct badge tiers."""
        high = build_readiness(
            "A",
            {},
            equity=100_000.0,
            balance=100_000.0,
            max_daily_dd_percent=5.0,
            max_total_dd_percent=10.0,
            max_concurrent_trades=5,
        )
        assert high.readiness_score >= 0.8  # READY tier

        low = build_readiness(
            "B",
            {"circuit_breaker": "1"},
            equity=100_000.0,
            balance=100_000.0,
            max_daily_dd_percent=5.0,
            max_total_dd_percent=10.0,
            max_concurrent_trades=5,
        )
        assert low.readiness_score < 0.2  # BLOCKED tier
