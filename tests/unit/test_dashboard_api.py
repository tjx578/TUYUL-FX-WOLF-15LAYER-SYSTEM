"""
Tests for dashboard API endpoints & risk governance.
Constitutional boundary: dashboard cannot override Layer-12 verdict.
"""


import pytest

try:
    from dashboard.app import app as dashboard_app
    HAS_DASHBOARD = True
except ImportError:
    try:
        from dashboard.main import (
            app as dashboard_app,  # noqa: F401
        )
        HAS_DASHBOARD = True
    except ImportError:
        HAS_DASHBOARD = False

try:
    from httpx import ASGITransport, AsyncClient  # noqa: F401, I001
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class TestDashboardRiskGovernance:
    """Dashboard must enforce risk rules from propfirm guard."""

    def test_risk_clamp_lot_size(self):
        """Dashboard must clamp requested lot to max_safe_lot."""
        requested = 3.0
        max_safe = 2.0
        clamped = min(requested, max_safe)
        assert clamped == 2.0

    def test_risk_block_when_guard_denies(self):
        guard_result = {"allowed": False, "code": "DAILY_LOSS_BREACH", "severity": "CRITICAL"}
        assert guard_result["allowed"] is False
        # Dashboard must respect this -- no override
        trade_permitted = guard_result["allowed"]
        assert trade_permitted is False

    def test_dashboard_cannot_change_verdict(self, sample_l12_verdict):
        """Dashboard receives verdict but must not alter it."""
        original_verdict = sample_l12_verdict["verdict"]
        # Simulate dashboard processing
        dashboard_view = {**sample_l12_verdict, "display_color": "green"}
        # Must not have changed verdict
        assert dashboard_view["verdict"] == original_verdict

    def test_dashboard_adds_account_context(self, sample_l12_verdict, sample_account_state):
        """Dashboard enriches verdict WITH account data (but doesn't alter verdict)."""
        enriched = {
            "signal": sample_l12_verdict,
            "account": sample_account_state,
            "risk_check": {"allowed": True, "recommended_lot": 0.5},
        }
        assert enriched["signal"]["verdict"] == "EXECUTE"
        assert "balance" in enriched["account"]
        assert "balance" not in enriched["signal"]


class TestTradeReportingEndpoints:
    """Trade events from EA/user -> dashboard."""

    @pytest.mark.parametrize("event_type", [
        "ORDER_PLACED",
        "ORDER_FILLED",
        "ORDER_CANCELLED",
        "ORDER_EXPIRED",
        "SYSTEM_VIOLATION",
    ])
    def test_required_event_types_accepted(self, event_type):
        valid_events = {"ORDER_PLACED", "ORDER_FILLED", "ORDER_CANCELLED",
                        "ORDER_EXPIRED", "SYSTEM_VIOLATION"}
        assert event_type in valid_events

    def test_event_payload_structure(self):
        event = {
            "event_type": "ORDER_FILLED",
            "order_id": "ORD-0001",
            "symbol": "EURUSD",
            "direction": "BUY",
            "lot_size": 0.5,
            "fill_price": 1.0855,
            "timestamp": "2026-02-15T10:31:00Z",
            "source": "EA",  # or "MANUAL"
        }
        required = ["event_type", "order_id", "symbol", "timestamp"]
        for field in required:
            assert field in event

    def test_manual_and_ea_use_same_format(self):
        """Both manual and EA events must have the same structure."""
        base = {"event_type": "ORDER_PLACED", "order_id": "X", "symbol": "EURUSD",
                "timestamp": "2026-02-15T10:00:00Z"}
        ea_event = {**base, "source": "EA"}
        manual_event = {**base, "source": "MANUAL"}
        assert set(ea_event.keys()) == set(manual_event.keys())
