"""
P1-5: Execution Intent Lifecycle Tests
========================================
Tests 9-state execution lifecycle, transition validation, provenance,
repository CRUD, and replay-safety.
"""

from __future__ import annotations

import pytest

from execution.execution_intent import (
    TERMINAL_EXECUTION_STATES,
    VALID_EXECUTION_TRANSITIONS,
    ExecutionIntentRecord,
    ExecutionIntentRepository,
    ExecutionLifecycleState,
    InvalidExecutionTransition,
    validate_execution_transition,
)


async def _noop_coro(*args, **kwargs):
    return None


# ── State Machine ─────────────────────────────────────────────────────────


class TestExecutionLifecycleStateMachine:
    def test_all_states_in_transition_table(self):
        for state in ExecutionLifecycleState:
            assert state in VALID_EXECUTION_TRANSITIONS

    def test_terminal_states_have_no_outgoing(self):
        for state in TERMINAL_EXECUTION_STATES:
            allowed = VALID_EXECUTION_TRANSITIONS[state]
            assert allowed == frozenset(), f"Terminal {state} has outgoing: {allowed}"

    def test_terminal_states_correct(self):
        expected = frozenset(
            {
                ExecutionLifecycleState.REJECTED,
                ExecutionLifecycleState.FILLED,
                ExecutionLifecycleState.CANCELLED,
                ExecutionLifecycleState.EXPIRED,
            }
        )
        assert expected == TERMINAL_EXECUTION_STATES

    def test_unresolved_is_not_terminal(self):
        """UNRESOLVED can be resolved after reconciliation."""
        assert ExecutionLifecycleState.UNRESOLVED not in TERMINAL_EXECUTION_STATES
        allowed = VALID_EXECUTION_TRANSITIONS[ExecutionLifecycleState.UNRESOLVED]
        assert len(allowed) > 0

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (ExecutionLifecycleState.INTENT_CREATED, ExecutionLifecycleState.ORDER_PLACED),
            (ExecutionLifecycleState.INTENT_CREATED, ExecutionLifecycleState.REJECTED),
            (ExecutionLifecycleState.INTENT_CREATED, ExecutionLifecycleState.CANCELLED),
            (ExecutionLifecycleState.ORDER_PLACED, ExecutionLifecycleState.ACKNOWLEDGED),
            (ExecutionLifecycleState.ORDER_PLACED, ExecutionLifecycleState.UNRESOLVED),
            (ExecutionLifecycleState.ACKNOWLEDGED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.ACKNOWLEDGED, ExecutionLifecycleState.PARTIALLY_FILLED),
            (ExecutionLifecycleState.PARTIALLY_FILLED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.PARTIALLY_FILLED, ExecutionLifecycleState.CANCELLED),
            (ExecutionLifecycleState.UNRESOLVED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.UNRESOLVED, ExecutionLifecycleState.REJECTED),
            (ExecutionLifecycleState.UNRESOLVED, ExecutionLifecycleState.CANCELLED),
            (ExecutionLifecycleState.UNRESOLVED, ExecutionLifecycleState.EXPIRED),
        ],
    )
    def test_valid_transitions(self, from_state, to_state):
        validate_execution_transition(from_state, to_state)

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (ExecutionLifecycleState.FILLED, ExecutionLifecycleState.ORDER_PLACED),
            (ExecutionLifecycleState.REJECTED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.CANCELLED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.EXPIRED, ExecutionLifecycleState.INTENT_CREATED),
            (ExecutionLifecycleState.INTENT_CREATED, ExecutionLifecycleState.FILLED),
            (ExecutionLifecycleState.ORDER_PLACED, ExecutionLifecycleState.INTENT_CREATED),
            (ExecutionLifecycleState.ACKNOWLEDGED, ExecutionLifecycleState.INTENT_CREATED),
            (ExecutionLifecycleState.PARTIALLY_FILLED, ExecutionLifecycleState.ACKNOWLEDGED),
        ],
    )
    def test_invalid_transitions_raise(self, from_state, to_state):
        with pytest.raises(InvalidExecutionTransition) as exc_info:
            validate_execution_transition(from_state, to_state)
        assert exc_info.value.from_state == from_state
        assert exc_info.value.to_state == to_state

    def test_no_self_transitions(self):
        for state in ExecutionLifecycleState:
            allowed = VALID_EXECUTION_TRANSITIONS[state]
            assert state not in allowed, f"Self-transition for {state}"


# ── Intent Record Model ──────────────────────────────────────────────────


class TestExecutionIntentRecord:
    def test_default_state_is_intent_created(self):
        rec = ExecutionIntentRecord(
            execution_intent_id="ei_001",
            idempotency_key="idem_001",
            take_id="take_001",
            signal_id="SIG-001",
            firewall_id="fw_001",
            account_id="ACC-001",
        )
        assert rec.state == ExecutionLifecycleState.INTENT_CREATED
        assert rec.broker_order_id is None
        assert rec.fill_price is None
        assert rec.slippage is None

    def test_provenance_chain(self):
        rec = ExecutionIntentRecord(
            execution_intent_id="ei_001",
            idempotency_key="idem_001",
            take_id="take_001",
            signal_id="SIG-001",
            firewall_id="fw_001",
            account_id="ACC-001",
        )
        assert rec.take_id == "take_001"
        assert rec.signal_id == "SIG-001"
        assert rec.firewall_id == "fw_001"

    def test_broker_truth_fields(self):
        rec = ExecutionIntentRecord(
            execution_intent_id="ei_002",
            idempotency_key="idem_002",
            take_id="take_002",
            signal_id="SIG-002",
            firewall_id="fw_002",
            account_id="ACC-002",
            broker_order_id="BRK-12345",
            fill_price=1.0855,
            fill_time="2026-01-01T10:00:00Z",
            slippage=0.0005,
            actual_lot_size=0.09,
            rejection_code=None,
        )
        assert rec.broker_order_id == "BRK-12345"
        assert rec.fill_price == 1.0855
        assert rec.slippage == 0.0005


# ── Repository ────────────────────────────────────────────────────────────


class TestExecutionIntentRepository:
    @pytest.fixture
    def repo(self, monkeypatch):
        r = ExecutionIntentRepository()
        monkeypatch.setattr(r, "_cache_set", lambda *a, **kw: None)
        monkeypatch.setattr(r, "_cache_get", lambda *a, **kw: None)
        monkeypatch.setattr(r, "_pg_insert", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(r, "_pg_update", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(r, "_pg_fetch", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(r, "_pg_fetch_by_idem", lambda *a, **kw: _noop_coro())
        return r

    @pytest.fixture
    def sample_record(self):
        return ExecutionIntentRecord(
            execution_intent_id="ei_test_001",
            idempotency_key="idem_test_001",
            take_id="take_test_001",
            signal_id="SIG-TEST-001",
            firewall_id="fw_test_001",
            account_id="ACC-TEST-001",
            symbol="EURUSD",
            direction="BUY",
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit_1=1.0950,
            lot_size=0.1,
        )

    async def test_create_and_get(self, repo, sample_record):
        created = await repo.create(sample_record)
        assert created.execution_intent_id == "ei_test_001"

        fetched = await repo.get("ei_test_001")
        assert fetched is not None
        assert fetched.execution_intent_id == "ei_test_001"
        assert fetched.take_id == "take_test_001"

    async def test_idempotent_create(self, repo, sample_record):
        r1 = await repo.create(sample_record)
        r2 = await repo.create(sample_record)
        assert r1.execution_intent_id == r2.execution_intent_id

    async def test_get_by_idempotency_key(self, repo, sample_record):
        await repo.create(sample_record)
        found = await repo.get_by_idempotency_key("idem_test_001")
        assert found is not None
        assert found.execution_intent_id == "ei_test_001"

    async def test_get_missing_returns_none(self, repo):
        assert await repo.get("nonexistent") is None

    async def test_transition_intent_created_to_order_placed(self, repo, sample_record):
        await repo.create(sample_record)
        updated = await repo.transition(
            "ei_test_001",
            ExecutionLifecycleState.ORDER_PLACED,
            reason="Sent to broker",
            broker_order_id="BRK-001",
        )
        assert updated.state == ExecutionLifecycleState.ORDER_PLACED
        assert updated.broker_order_id == "BRK-001"

    async def test_transition_to_filled_with_truth(self, repo, sample_record):
        await repo.create(sample_record)
        await repo.transition("ei_test_001", ExecutionLifecycleState.ORDER_PLACED, reason="sent")
        await repo.transition("ei_test_001", ExecutionLifecycleState.ACKNOWLEDGED, reason="acked")
        filled = await repo.transition(
            "ei_test_001",
            ExecutionLifecycleState.FILLED,
            reason="Broker fill confirmed",
            fill_price=1.0852,
            fill_time="2026-01-01T10:00:00Z",
            slippage=0.0002,
            actual_lot_size=0.1,
        )
        assert filled.state == ExecutionLifecycleState.FILLED
        assert filled.fill_price == 1.0852
        assert filled.slippage == 0.0002

    async def test_invalid_transition_raises(self, repo, sample_record):
        await repo.create(sample_record)
        with pytest.raises(InvalidExecutionTransition):
            await repo.transition("ei_test_001", ExecutionLifecycleState.FILLED)

    async def test_replay_safe_terminal(self, repo, sample_record):
        """Terminal → same terminal should be replay-safe (no-op, no error)."""
        await repo.create(sample_record)
        await repo.transition("ei_test_001", ExecutionLifecycleState.REJECTED, reason="broker reject")
        again = await repo.transition("ei_test_001", ExecutionLifecycleState.REJECTED, reason="replay")
        assert again.state == ExecutionLifecycleState.REJECTED

    async def test_transition_missing_raises_key_error(self, repo):
        with pytest.raises(KeyError):
            await repo.transition("nonexistent_id", ExecutionLifecycleState.ORDER_PLACED)

    async def test_list_by_state(self, repo):
        for i in range(3):
            rec = ExecutionIntentRecord(
                execution_intent_id=f"ei_list_{i}",
                idempotency_key=f"idem_list_{i}",
                take_id=f"take_list_{i}",
                signal_id=f"SIG-LIST-{i}",
                firewall_id=f"fw_list_{i}",
                account_id="ACC-LIST",
            )
            await repo.create(rec)
            if i < 2:
                await repo.transition(f"ei_list_{i}", ExecutionLifecycleState.ORDER_PLACED, reason="sent")

        placed = await repo.list_by_state(ExecutionLifecycleState.ORDER_PLACED)
        assert len(placed) == 2
        created = await repo.list_by_state(ExecutionLifecycleState.INTENT_CREATED)
        assert len(created) == 1
