"""
P1-6: Execution Reconciliation Tests
======================================
Tests restart reconciliation, broker truth resolution, UNRESOLVED marking,
and prevention of blind duplicate semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from execution.execution_intent import (
    ExecutionIntentRecord,
    ExecutionIntentRepository,
    ExecutionLifecycleState,
)
from execution.reconciliation import ExecutionReconciler, ReconciliationResult


async def _noop_coro(*args, **kwargs):
    return None


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(monkeypatch):
    r = ExecutionIntentRepository()
    monkeypatch.setattr(r, "_cache_set", lambda *a, **kw: None)
    monkeypatch.setattr(r, "_cache_get", lambda *a, **kw: None)
    monkeypatch.setattr(r, "_pg_insert", lambda *a, **kw: _noop_coro())
    monkeypatch.setattr(r, "_pg_update", lambda *a, **kw: _noop_coro())
    monkeypatch.setattr(r, "_pg_fetch", lambda *a, **kw: _noop_coro())
    monkeypatch.setattr(r, "_pg_fetch_by_idem", lambda *a, **kw: _noop_coro())
    return r


@pytest.fixture
def reconciler(repo):
    return ExecutionReconciler(repo=repo, pending_timeout_sec=120)


def _make_intent(
    eid: str,
    state: ExecutionLifecycleState = ExecutionLifecycleState.INTENT_CREATED,
    age_sec: int = 0,
) -> ExecutionIntentRecord:
    """Helper: create an intent record with controlled created_at timestamp."""
    created = datetime.now(UTC) - timedelta(seconds=age_sec)
    return ExecutionIntentRecord(
        execution_intent_id=eid,
        idempotency_key=f"idem_{eid}",
        take_id=f"take_{eid}",
        signal_id=f"SIG-{eid}",
        firewall_id=f"fw_{eid}",
        account_id="ACC-001",
        symbol="EURUSD",
        direction="BUY",
        state=state,
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
    )


# ── ReconciliationResult ─────────────────────────────────────────────────


class TestReconciliationResult:
    def test_to_dict(self):
        r = ReconciliationResult("ei_001", "ORDER_PLACED", "UNRESOLVED", "timeout", "300s timeout")
        d = r.to_dict()
        assert d["execution_intent_id"] == "ei_001"
        assert d["previous_state"] == "ORDER_PLACED"
        assert d["resolved_state"] == "UNRESOLVED"
        assert d["resolution_source"] == "timeout"

    def test_is_dataclass_with_slots(self):
        import dataclasses

        assert dataclasses.is_dataclass(ReconciliationResult)
        assert hasattr(ReconciliationResult, "__slots__")
        assert "execution_intent_id" in ReconciliationResult.__slots__
        r = ReconciliationResult("ei", "A", "B", "C", "D")
        assert not hasattr(r, "__dict__")

    def test_auto_eq(self):
        a = ReconciliationResult("ei", "A", "B", "C", "D")
        b = ReconciliationResult("ei", "A", "B", "C", "D")
        assert a == b
        c = ReconciliationResult("ei", "A", "B", "C", "other")
        assert a != c

    def test_auto_repr(self):
        r = ReconciliationResult("ei_001", "A", "B", "C", "D")
        text = repr(r)
        assert "ReconciliationResult" in text
        assert "ei_001" in text

    def test_positional_args_preserved(self):
        """Existing callers pass all 5 args positionally."""
        r = ReconciliationResult("ei", "prev", "resolved", "src", "reason")
        assert r.execution_intent_id == "ei"
        assert r.previous_state == "prev"
        assert r.resolved_state == "resolved"
        assert r.resolution_source == "src"
        assert r.reason == "reason"


# ── Restart Reconciliation ────────────────────────────────────────────────


class TestReconcileOnRestart:
    async def test_marks_timed_out_as_unresolved(self, repo, reconciler):
        """Intent pending for >timeout should be marked UNRESOLVED."""
        intent = _make_intent("ei_timeout", ExecutionLifecycleState.ORDER_PLACED, age_sec=300)
        await repo.create(intent)
        # Manually set state in memory
        repo._memory["ei_timeout"]["state"] = ExecutionLifecycleState.ORDER_PLACED.value

        results = await reconciler.reconcile_on_restart()
        assert len(results) >= 1
        match = [r for r in results if r.execution_intent_id == "ei_timeout"]
        assert len(match) == 1
        assert match[0].resolved_state == "UNRESOLVED"

    async def test_fresh_intents_not_reconciled(self, repo, reconciler):
        """Intent within timeout window should NOT be marked UNRESOLVED."""
        intent = _make_intent("ei_fresh", ExecutionLifecycleState.ORDER_PLACED, age_sec=10)
        await repo.create(intent)
        repo._memory["ei_fresh"]["state"] = ExecutionLifecycleState.ORDER_PLACED.value

        results = await reconciler.reconcile_on_restart()
        match = [r for r in results if r.execution_intent_id == "ei_fresh"]
        assert len(match) == 0

    async def test_scans_multiple_ambiguous_states(self, repo, reconciler):
        """Should scan ORDER_PLACED, ACKNOWLEDGED, PARTIALLY_FILLED."""
        for i, state in enumerate(
            [
                ExecutionLifecycleState.ORDER_PLACED,
                ExecutionLifecycleState.ACKNOWLEDGED,
                ExecutionLifecycleState.PARTIALLY_FILLED,
            ]
        ):
            intent = _make_intent(f"ei_amb_{i}", state, age_sec=300)
            await repo.create(intent)
            repo._memory[f"ei_amb_{i}"]["state"] = state.value

        results = await reconciler.reconcile_on_restart()
        assert len(results) == 3

    async def test_ignores_terminal_states(self, repo, reconciler):
        """Terminal states (FILLED, REJECTED, etc.) should not be reconciled."""
        for state in (
            ExecutionLifecycleState.FILLED,
            ExecutionLifecycleState.REJECTED,
            ExecutionLifecycleState.CANCELLED,
            ExecutionLifecycleState.EXPIRED,
        ):
            intent = _make_intent(f"ei_term_{state.value}", state, age_sec=500)
            await repo.create(intent)
            repo._memory[f"ei_term_{state.value}"]["state"] = state.value

        results = await reconciler.reconcile_on_restart()
        assert len(results) == 0


# ── Broker Truth Resolution ──────────────────────────────────────────────


class TestBrokerTruthReconciliation:
    async def test_broker_fill_resolves_to_filled(self, repo, reconciler):
        intent = _make_intent("ei_broker_fill", ExecutionLifecycleState.ACKNOWLEDGED, age_sec=60)
        await repo.create(intent)
        repo._memory["ei_broker_fill"]["state"] = ExecutionLifecycleState.ACKNOWLEDGED.value

        broker_truth = {
            "status": "FILLED",
            "fill_price": 1.0855,
            "fill_time": "2026-01-01T10:00:00Z",
            "slippage": 0.0005,
            "lot_size": 0.1,
            "order_id": "BRK-12345",
        }
        result = await reconciler.reconcile_single("ei_broker_fill", broker_truth)
        assert result is not None
        assert result.resolved_state == "FILLED"
        assert result.resolution_source == "broker"

        # Verify the intent was actually updated
        updated = await repo.get("ei_broker_fill")
        assert updated.state == ExecutionLifecycleState.FILLED
        assert updated.fill_price == 1.0855

    async def test_broker_cancelled_resolves_to_cancelled(self, repo, reconciler):
        intent = _make_intent("ei_broker_cancel", ExecutionLifecycleState.ACKNOWLEDGED, age_sec=60)
        await repo.create(intent)
        repo._memory["ei_broker_cancel"]["state"] = ExecutionLifecycleState.ACKNOWLEDGED.value

        result = await reconciler.reconcile_single("ei_broker_cancel", {"status": "CANCELLED"})
        assert result is not None
        assert result.resolved_state == "CANCELLED"

    async def test_broker_rejected_resolves_to_rejected(self, repo, reconciler):
        intent = _make_intent("ei_broker_rej", ExecutionLifecycleState.ACKNOWLEDGED, age_sec=60)
        await repo.create(intent)
        repo._memory["ei_broker_rej"]["state"] = ExecutionLifecycleState.ACKNOWLEDGED.value

        result = await reconciler.reconcile_single(
            "ei_broker_rej",
            {"status": "REJECTED", "rejection_code": "INSUFFICIENT_MARGIN"},
        )
        assert result is not None
        assert result.resolved_state == "REJECTED"

    async def test_broker_expired_resolves_to_expired(self, repo, reconciler):
        intent = _make_intent("ei_broker_exp", ExecutionLifecycleState.ACKNOWLEDGED, age_sec=60)
        await repo.create(intent)
        repo._memory["ei_broker_exp"]["state"] = ExecutionLifecycleState.ACKNOWLEDGED.value

        result = await reconciler.reconcile_single("ei_broker_exp", {"status": "EXPIRED"})
        assert result is not None
        assert result.resolved_state == "EXPIRED"

    async def test_missing_intent_returns_none(self, reconciler):
        result = await reconciler.reconcile_single("nonexistent", {"status": "FILLED"})
        assert result is None


# ── Configuration ─────────────────────────────────────────────────────────


class TestReconcilerConfig:
    def test_minimum_timeout_enforced(self):
        """Timeout must be at least 60s even if lower value provided."""
        rec = ExecutionReconciler(pending_timeout_sec=10)
        assert rec._pending_timeout_sec == 60

    def test_custom_timeout(self):
        rec = ExecutionReconciler(pending_timeout_sec=600)
        assert rec._pending_timeout_sec == 600
