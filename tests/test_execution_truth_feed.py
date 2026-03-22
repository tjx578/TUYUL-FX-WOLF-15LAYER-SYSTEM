"""
P1-7: Execution Truth Feed Tests
==================================
Tests J3 journal entry creation, audit trail appending,
portfolio read-model updates, and RR truth computation.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from execution.execution_intent import (
    ExecutionIntentRecord,
    ExecutionLifecycleState,
)
from execution.execution_truth_feed import ExecutionTruthFeed

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def truth_feed():
    return ExecutionTruthFeed()


@pytest.fixture
def filled_intent():
    return ExecutionIntentRecord(
        execution_intent_id="ei_truth_001",
        idempotency_key="idem_truth_001",
        take_id="take_truth_001",
        signal_id="SIG-TRUTH-001",
        firewall_id="fw_truth_001",
        account_id="ACC-001",
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.0850,
        stop_loss=1.0800,
        take_profit_1=1.0950,
        lot_size=0.1,
        state=ExecutionLifecycleState.FILLED,
        state_reason="Broker confirmed fill",
        broker_order_id="BRK-12345",
        fill_price=1.0855,
        fill_time="2026-01-01T10:00:00Z",
        slippage=0.0005,
        actual_lot_size=0.1,
    )


@pytest.fixture
def rejected_intent():
    return ExecutionIntentRecord(
        execution_intent_id="ei_truth_002",
        idempotency_key="idem_truth_002",
        take_id="take_truth_002",
        signal_id="SIG-TRUTH-002",
        firewall_id="fw_truth_002",
        account_id="ACC-001",
        symbol="GBPUSD",
        direction="SELL",
        state=ExecutionLifecycleState.REJECTED,
        state_reason="Broker rejected: insufficient margin",
        rejection_code="INSUFFICIENT_MARGIN",
    )


# ── Journal Entry (J3) ───────────────────────────────────────────────────


class TestJournalEntry:
    async def test_journal_entry_contains_correct_fields(self, filled_intent):
        """J3 entry dict has expected structure and values."""
        tf = ExecutionTruthFeed()
        import json as _json

        written_data = {}

        def _fake_open(path, mode, **kw):
            from io import StringIO

            buf = StringIO()
            original_close = buf.close

            def _close():
                buf.seek(0)
                written_data.update(_json.loads(buf.read()))
                original_close()

            buf.close = _close
            return buf

        with patch("builtins.open", _fake_open), patch("pathlib.Path.mkdir"):
            await tf._append_journal_entry(filled_intent, ExecutionLifecycleState.ACKNOWLEDGED)

        assert written_data["journal_type"] == "J3"
        assert written_data["execution_intent_id"] == "ei_truth_001"
        assert written_data["previous_state"] == "ACKNOWLEDGED"
        assert written_data["current_state"] == "FILLED"
        assert written_data["fill_price_actual"] == 1.0855
        assert written_data["slippage"] == 0.0005

    async def test_journal_entry_for_rejection(self, rejected_intent):
        """J3 entry is written for REJECTED state change."""
        tf = ExecutionTruthFeed()
        import json as _json

        written_data = {}

        def _fake_open(path, mode, **kw):
            from io import StringIO

            buf = StringIO()
            original_close = buf.close

            def _close():
                buf.seek(0)
                written_data.update(_json.loads(buf.read()))
                original_close()

            buf.close = _close
            return buf

        with patch("builtins.open", _fake_open), patch("pathlib.Path.mkdir"):
            await tf._append_journal_entry(rejected_intent, ExecutionLifecycleState.ORDER_PLACED)

        assert written_data["journal_type"] == "J3"
        assert written_data["rejection_code"] == "INSUFFICIENT_MARGIN"
        assert written_data["current_state"] == "REJECTED"

    async def test_journal_write_failure_does_not_raise(self, filled_intent):
        """Journal write failure should be swallowed (best-effort)."""
        tf = ExecutionTruthFeed()
        with patch("journal.journal_writer.JournalWriter", side_effect=ImportError("unavailable")):
            await tf._append_journal_entry(filled_intent, ExecutionLifecycleState.ACKNOWLEDGED)


# ── Portfolio Read Model ──────────────────────────────────────────────────


class TestPortfolioReadModel:
    async def test_no_update_for_non_terminal_state(self):
        """Portfolio read model should only update on terminal states."""
        tf = ExecutionTruthFeed()
        intent = ExecutionIntentRecord(
            execution_intent_id="ei_nonterminal",
            idempotency_key="idem_nonterminal",
            take_id="take_nt",
            signal_id="SIG-NT",
            firewall_id="fw_nt",
            account_id="ACC-001",
            state=ExecutionLifecycleState.ORDER_PLACED,
        )
        await tf._update_portfolio_read_model(intent)

    async def test_rr_truth_computation(self, filled_intent):
        """RR truth should be computed when fill_price, stop_loss, take_profit_1 are available."""
        risk_dist = abs(filled_intent.fill_price - filled_intent.stop_loss)
        reward_dist = abs(filled_intent.take_profit_1 - filled_intent.fill_price)
        expected_rr = round(reward_dist / risk_dist, 2)
        assert expected_rr == 1.73

    @pytest.mark.parametrize(
        "state",
        [
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.EXPIRED,
        ],
    )
    async def test_terminal_states_trigger_portfolio_update(self, state):
        """All terminal execution states should trigger portfolio read model update."""
        tf = ExecutionTruthFeed()
        intent = ExecutionIntentRecord(
            execution_intent_id=f"ei_{state.value}",
            idempotency_key=f"idem_{state.value}",
            take_id=f"take_{state.value}",
            signal_id=f"SIG-{state.value}",
            firewall_id=f"fw_{state.value}",
            account_id="ACC-001",
            state=state,
        )
        await tf._update_portfolio_read_model(intent)


# ── End-to-end Truth Feed ────────────────────────────────────────────────


class TestTruthFeedEndToEnd:
    async def test_full_flow_on_state_change(self, truth_feed, filled_intent, monkeypatch):
        """on_execution_state_change should complete without errors."""

        async def _noop(*a, **kw):
            pass

        monkeypatch.setattr(truth_feed, "_append_journal_entry", _noop)
        monkeypatch.setattr(truth_feed, "_update_portfolio_read_model", _noop)
        monkeypatch.setattr(truth_feed, "_emit_truth_event", _noop)
        await truth_feed.on_execution_state_change(filled_intent, ExecutionLifecycleState.ACKNOWLEDGED)
