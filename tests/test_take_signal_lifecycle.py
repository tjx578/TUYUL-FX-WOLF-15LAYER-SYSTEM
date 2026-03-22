"""
P1-1 / P1-2: Take-Signal Lifecycle Tests
==========================================
Tests the state machine, transition rules, terminal states, idempotency,
request/response models, and service layer for take-signal operational bindings.
"""

from __future__ import annotations

import pytest

from execution.take_signal_models import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    InvalidTakeSignalTransition,
    TakeSignalCreateRequest,
    TakeSignalRecord,
    TakeSignalResponse,
    TakeSignalStatus,
    is_terminal,
    validate_transition,
)


async def _noop_coro(*args, **kwargs):
    """Async no-op coroutine used to mock PG methods."""
    return None


# ── State Machine ──────────────────────────────────────────────────────────


class TestTakeSignalStateMachine:
    """Test P1-2 state machine: transitions, terminal states, validation."""

    def test_all_states_present_in_transition_table(self):
        """Every TakeSignalStatus value has an entry in VALID_TRANSITIONS."""
        for state in TakeSignalStatus:
            assert state in VALID_TRANSITIONS, f"Missing transition entry for {state}"

    def test_terminal_states_have_no_outgoing_transitions(self):
        """Terminal states must map to empty frozenset (no outgoing transitions)."""
        for state in TERMINAL_STATES:
            assert VALID_TRANSITIONS[state] == frozenset(), (
                f"Terminal state {state} has outgoing transitions: {VALID_TRANSITIONS[state]}"
            )

    def test_terminal_states_are_correct(self):
        expected = frozenset(
            {
                TakeSignalStatus.FIREWALL_REJECTED,
                TakeSignalStatus.EXECUTED,
                TakeSignalStatus.REJECTED,
                TakeSignalStatus.CANCELLED,
                TakeSignalStatus.EXPIRED,
            }
        )
        assert expected == TERMINAL_STATES

    def test_is_terminal_true_for_terminal_states(self):
        for state in TERMINAL_STATES:
            assert is_terminal(state) is True

    def test_is_terminal_false_for_non_terminal_states(self):
        non_terminal = set(TakeSignalStatus) - TERMINAL_STATES
        for state in non_terminal:
            assert is_terminal(state) is False

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (TakeSignalStatus.PENDING, TakeSignalStatus.FIREWALL_APPROVED),
            (TakeSignalStatus.PENDING, TakeSignalStatus.FIREWALL_REJECTED),
            (TakeSignalStatus.PENDING, TakeSignalStatus.REJECTED),
            (TakeSignalStatus.PENDING, TakeSignalStatus.CANCELLED),
            (TakeSignalStatus.PENDING, TakeSignalStatus.EXPIRED),
            (TakeSignalStatus.FIREWALL_APPROVED, TakeSignalStatus.EXECUTION_SENT),
            (TakeSignalStatus.FIREWALL_APPROVED, TakeSignalStatus.CANCELLED),
            (TakeSignalStatus.FIREWALL_APPROVED, TakeSignalStatus.EXPIRED),
            (TakeSignalStatus.EXECUTION_SENT, TakeSignalStatus.EXECUTED),
            (TakeSignalStatus.EXECUTION_SENT, TakeSignalStatus.REJECTED),
            (TakeSignalStatus.EXECUTION_SENT, TakeSignalStatus.CANCELLED),
            (TakeSignalStatus.EXECUTION_SENT, TakeSignalStatus.EXPIRED),
        ],
    )
    def test_valid_transitions_accepted(self, from_state, to_state):
        """All defined valid transitions should not raise."""
        validate_transition(from_state, to_state)

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (TakeSignalStatus.PENDING, TakeSignalStatus.EXECUTED),
            (TakeSignalStatus.PENDING, TakeSignalStatus.EXECUTION_SENT),
            (TakeSignalStatus.FIREWALL_APPROVED, TakeSignalStatus.FIREWALL_REJECTED),
            (TakeSignalStatus.FIREWALL_APPROVED, TakeSignalStatus.EXECUTED),
            (TakeSignalStatus.FIREWALL_REJECTED, TakeSignalStatus.FIREWALL_APPROVED),
            (TakeSignalStatus.EXECUTED, TakeSignalStatus.PENDING),
            (TakeSignalStatus.CANCELLED, TakeSignalStatus.PENDING),
            (TakeSignalStatus.EXPIRED, TakeSignalStatus.PENDING),
            (TakeSignalStatus.EXECUTION_SENT, TakeSignalStatus.FIREWALL_APPROVED),
        ],
    )
    def test_invalid_transitions_raise(self, from_state, to_state):
        """Forbidden transitions must raise InvalidTakeSignalTransition."""
        with pytest.raises(InvalidTakeSignalTransition) as exc_info:
            validate_transition(from_state, to_state)
        assert exc_info.value.from_state == from_state
        assert exc_info.value.to_state == to_state

    def test_no_self_transitions(self):
        """No state should be allowed to transition to itself."""
        for state in TakeSignalStatus:
            allowed = VALID_TRANSITIONS[state]
            assert state not in allowed, f"Self-transition found for {state}"

    def test_pending_is_initial_state(self):
        """PENDING must be the only non-terminal state reachable from nothing (initial)."""
        record = TakeSignalRecord(
            take_id="test",
            request_id="req-test",
            signal_id="sig-test",
            account_id="acc-test",
            ea_instance_id="ea-test",
            operator="tester",
            reason="testing",
        )
        assert record.status == TakeSignalStatus.PENDING


# ── Pydantic Models ───────────────────────────────────────────────────────


class TestTakeSignalModels:
    """Test P1-1 Pydantic request/response models with validation."""

    def test_create_request_valid(self):
        req = TakeSignalCreateRequest(
            signal_id="SIG-20260215-EURUSD-001",
            account_id="ACC-FTMO-001",
            ea_instance_id="EA-MT5-001",
            operator="admin",
            reason="High-confidence signal",
            request_id="idm-12345678",
        )
        assert req.signal_id == "SIG-20260215-EURUSD-001"
        assert req.strategy_profile_id is None

    def test_create_request_rejects_short_signal_id(self):
        with pytest.raises(Exception):  # noqa: B017
            TakeSignalCreateRequest(
                signal_id="ab",  # too short (min 3)
                account_id="ACC-FTMO-001",
                ea_instance_id="EA-MT5-001",
                operator="admin",
                reason="test",
                request_id="idm-12345678",
            )

    def test_create_request_rejects_short_request_id(self):
        with pytest.raises(Exception):  # noqa: B017
            TakeSignalCreateRequest(
                signal_id="SIG-001",
                account_id="ACC-001",
                ea_instance_id="EA-001",
                operator="admin",
                reason="test",
                request_id="short",  # min_length=8
            )

    def test_create_request_forbids_extra_fields(self):
        with pytest.raises(Exception):  # noqa: B017
            TakeSignalCreateRequest(
                signal_id="SIG-001",
                account_id="ACC-001",
                ea_instance_id="EA-001",
                operator="admin",
                reason="test",
                request_id="idm-12345678",
                extra_field="nope",  # type: ignore[call-arg]
            )

    def test_record_default_status_is_pending(self):
        rec = TakeSignalRecord(
            take_id="take_abc",
            request_id="req-abc",
            signal_id="SIG-001",
            account_id="ACC-001",
            ea_instance_id="EA-001",
            operator="admin",
            reason="test",
        )
        assert rec.status == TakeSignalStatus.PENDING
        assert rec.firewall_result_id is None
        assert rec.execution_intent_id is None

    def test_response_model_serializes(self):
        resp = TakeSignalResponse(
            take_id="take_abc",
            request_id="req-abc",
            signal_id="SIG-001",
            account_id="ACC-001",
            ea_instance_id="EA-001",
            status=TakeSignalStatus.FIREWALL_APPROVED,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:01:00Z",
            firewall_result_id="fw_abc",
        )
        d = resp.model_dump()
        assert d["status"] == "FIREWALL_APPROVED"
        assert d["firewall_result_id"] == "fw_abc"
        assert d["execution_intent_id"] is None


# ── Service Layer ─────────────────────────────────────────────────────────


class TestTakeSignalService:
    """Test P1-1 service: create, idempotency, transitions, cancel."""

    @pytest.fixture
    def service(self, monkeypatch):
        from execution.take_signal_repository import TakeSignalRepository
        from execution.take_signal_service import TakeSignalService

        repo = TakeSignalRepository()
        # Disable Redis and PG calls — use in-memory only
        monkeypatch.setattr(repo, "_redis_set", lambda *a, **kw: None)
        monkeypatch.setattr(repo, "_redis_get", lambda *a, **kw: None)
        monkeypatch.setattr(repo, "_redis_set_idempotency", lambda *a, **kw: None)
        monkeypatch.setattr(repo, "_redis_get_idempotency", lambda *a, **kw: None)
        monkeypatch.setattr(repo, "_pg_insert", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(repo, "_pg_update", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(repo, "_pg_fetch_one", lambda *a, **kw: _noop_coro())
        monkeypatch.setattr(repo, "_pg_fetch_by_request_id", lambda *a, **kw: _noop_coro())
        svc = TakeSignalService(repository=repo)
        # Mock event emission to avoid async Redis
        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._emit_event",
            staticmethod(lambda *a, **kw: _noop_coro()),
        )
        return svc

    @pytest.fixture
    def create_request(self):
        return TakeSignalCreateRequest(
            signal_id="SIG-20260215-EURUSD-001",
            account_id="ACC-FTMO-001",
            ea_instance_id="EA-MT5-001",
            operator="admin",
            reason="High-confidence signal",
            request_id="idm-test-001",
        )

    async def test_create_new_record(self, service, create_request, monkeypatch):
        # Mock signal lookup to return a valid signal
        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "symbol": "EURUSD", "verdict": "EXECUTE"}

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        response, created = await service.create(create_request)
        assert created is True
        assert response.status == TakeSignalStatus.PENDING
        assert response.signal_id == "SIG-20260215-EURUSD-001"
        assert response.account_id == "ACC-FTMO-001"
        assert response.take_id.startswith("take_")

    async def test_idempotent_replay_returns_same_record(self, service, create_request, monkeypatch):
        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "symbol": "EURUSD", "verdict": "EXECUTE"}

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        resp1, created1 = await service.create(create_request)
        resp2, created2 = await service.create(create_request)
        assert created1 is True
        assert created2 is False
        assert resp1.take_id == resp2.take_id

    async def test_idempotency_conflict_raises(self, service, monkeypatch):
        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "symbol": "EURUSD", "verdict": "EXECUTE"}

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        req1 = TakeSignalCreateRequest(
            signal_id="SIG-001",
            account_id="ACC-001",
            ea_instance_id="EA-001",
            operator="admin",
            reason="first",
            request_id="idm-conflict-001",
        )
        await service.create(req1)

        req2 = TakeSignalCreateRequest(
            signal_id="SIG-002",  # different signal!
            account_id="ACC-001",
            ea_instance_id="EA-001",
            operator="admin",
            reason="conflict",
            request_id="idm-conflict-001",  # same request_id
        )
        with pytest.raises(ValueError, match="Idempotency conflict"):
            await service.create(req2)

    async def test_signal_not_found_raises(self, service, create_request, monkeypatch):
        from execution.take_signal_service import SignalNotFoundError

        async def _mock_lookup(self_svc, signal_id):
            return None

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        with pytest.raises(SignalNotFoundError):
            await service.create(create_request)

    async def test_expired_signal_raises(self, service, create_request, monkeypatch):
        from execution.take_signal_service import SignalExpiredError

        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "expires_at": 0}  # expired (epoch=0)

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        with pytest.raises(SignalExpiredError):
            await service.create(create_request)

    async def test_transition_lifecycle(self, service, create_request, monkeypatch):
        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "symbol": "EURUSD", "verdict": "EXECUTE"}

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        resp, _ = await service.create(create_request)
        take_id = resp.take_id

        # PENDING -> FIREWALL_APPROVED
        resp = await service.transition(take_id, TakeSignalStatus.FIREWALL_APPROVED, reason="All checks passed")
        assert resp.status == TakeSignalStatus.FIREWALL_APPROVED

        # FIREWALL_APPROVED -> EXECUTION_SENT
        resp = await service.transition(take_id, TakeSignalStatus.EXECUTION_SENT, reason="Dispatched")
        assert resp.status == TakeSignalStatus.EXECUTION_SENT

        # EXECUTION_SENT -> EXECUTED (terminal)
        resp = await service.transition(take_id, TakeSignalStatus.EXECUTED, reason="Broker confirmed")
        assert resp.status == TakeSignalStatus.EXECUTED

    async def test_cancel_from_pending(self, service, create_request, monkeypatch):
        async def _mock_lookup(self_svc, signal_id):
            return {"signal_id": signal_id, "symbol": "EURUSD", "verdict": "EXECUTE"}

        monkeypatch.setattr(
            "execution.take_signal_service.TakeSignalService._lookup_signal",
            _mock_lookup,
        )

        resp, _ = await service.create(create_request)
        cancelled = await service.cancel(resp.take_id, reason="Operator changed mind")
        assert cancelled.status == TakeSignalStatus.CANCELLED

    async def test_get_returns_none_for_missing(self, service):
        result = await service.get("nonexistent_take_id")
        assert result is None
