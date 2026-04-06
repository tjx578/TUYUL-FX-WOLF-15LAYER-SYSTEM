"""Tests for the account state Redis bridge in risk_router.

Validates that _publish_account_state_to_redis writes the correct
JSON payload to the ACCOUNT_STATE Redis key so the orchestrator's
compliance guard sees the expected fields.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from accounts.account_repository import AccountRiskState
from core.redis_keys import ACCOUNT_STATE
from risk.risk_router import _publish_account_state_to_redis


def _make_state(**overrides: Any) -> AccountRiskState:
    defaults: dict[str, Any] = dict(
        account_id="acct_1",
        prop_firm_code="FTMO",
        balance=10000.0,
        equity=9800.0,
        base_risk_percent=1.0,
        max_daily_loss_percent=5.0,
        max_total_loss_percent=10.0,
        daily_loss_used_percent=2.5,
        total_loss_used_percent=4.0,
        compliance_mode=True,
        account_locked=False,
        system_state="NORMAL",
        circuit_breaker_open=False,
        max_concurrent_trades=5,
        open_trades_count=2,
        news_lock=False,
        correlation_bucket="GREEN",
    )
    defaults.update(overrides)
    return AccountRiskState(**defaults)


class TestPublishAccountStateToRedis:
    """Ensure bridge publishes all fields compliance_guard reads."""

    @patch("risk.risk_router.redis_client")
    def test_publishes_all_compliance_fields(self, mock_redis):
        state = _make_state()
        _publish_account_state_to_redis(state)

        mock_redis.set.assert_called_once()
        key, raw = mock_redis.set.call_args[0]
        assert key == ACCOUNT_STATE

        payload = json.loads(raw)
        assert payload["balance"] == 10000.0
        assert payload["equity"] == 9800.0
        assert payload["compliance_mode"] is True
        assert payload["account_locked"] is False
        assert payload["system_state"] == "NORMAL"
        assert payload["circuit_breaker"] is False
        assert payload["daily_dd_percent"] == 2.5
        assert payload["max_daily_dd_percent"] == 5.0
        assert payload["total_dd_percent"] == 4.0
        assert payload["max_total_dd_percent"] == 10.0
        assert payload["max_concurrent_trades"] == 5
        assert payload["open_trades"] == 2
        assert payload["news_lock_active"] is False
        assert payload["correlation_breached"] is False
        assert payload["account_id"] == "acct_1"
        assert payload["prop_firm_code"] == "FTMO"
        assert "updated_at" in payload

    @patch("risk.risk_router.redis_client")
    def test_correlation_red_sets_breached(self, mock_redis):
        state = _make_state(correlation_bucket="RED")
        _publish_account_state_to_redis(state)

        raw = mock_redis.set.call_args[0][1]
        payload = json.loads(raw)
        assert payload["correlation_breached"] is True

    @patch("risk.risk_router.redis_client")
    def test_news_lock_propagates(self, mock_redis):
        state = _make_state(news_lock=True)
        _publish_account_state_to_redis(state)

        raw = mock_redis.set.call_args[0][1]
        payload = json.loads(raw)
        assert payload["news_lock_active"] is True

    @patch("risk.risk_router.redis_client")
    def test_redis_failure_does_not_raise(self, mock_redis):
        mock_redis.set.side_effect = ConnectionError("Redis down")
        state = _make_state()
        # Should not propagate
        _publish_account_state_to_redis(state)

    @patch("risk.risk_router.redis_client")
    def test_payload_parseable_by_compliance_guard(self, mock_redis):
        """End-to-end: bridge output is consumable by compliance_guard."""
        from services.orchestrator.compliance_guard import evaluate_compliance

        state = _make_state()
        _publish_account_state_to_redis(state)

        raw = mock_redis.set.call_args[0][1]
        account_state = json.loads(raw)
        trade_risk = {"risk_percent": 1.0}

        result = evaluate_compliance(account_state, trade_risk)
        assert result.allowed is True
        assert result.code == "OK" or result.severity == "info"
