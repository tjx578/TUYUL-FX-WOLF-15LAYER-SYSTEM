"""
P1-4: Orchestrator Coordinator Tests
======================================
Tests the orchestrated take-signal → firewall → execution flow.
Verifies the coordinator does NOT mutate verdicts, only routes flow.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from execution.take_signal_models import TakeSignalResponse, TakeSignalStatus
from risk.firewall import CheckSeverity, FirewallCheckResult, FirewallResult, FirewallVerdict
from services.orchestrator.coordinator import OrchestrationResult, OrchestratorCoordinator

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_take_service():
    svc = AsyncMock()
    svc.get = AsyncMock()
    svc.transition = AsyncMock()
    return svc


@pytest.fixture
def mock_firewall():
    fw = AsyncMock()
    return fw


@pytest.fixture
def coordinator(mock_take_service, mock_firewall):
    return OrchestratorCoordinator(
        take_signal_service=mock_take_service,
        risk_firewall=mock_firewall,
    )


@pytest.fixture
def pending_take_response():
    return TakeSignalResponse(
        take_id="take_001",
        request_id="req-001",
        signal_id="SIG-001",
        account_id="ACC-001",
        ea_instance_id="EA-001",
        status=TakeSignalStatus.PENDING,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def approved_firewall_result():
    return FirewallResult(
        firewall_id="fw_001",
        take_id="take_001",
        verdict=FirewallVerdict.APPROVED,
        checks=(
            FirewallCheckResult(
                check_name="kill_switch",
                order=1,
                severity=CheckSeverity.PASS,
                code="OK",
                message="All clear",
            ),
        ),
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:01Z",
    )


@pytest.fixture
def rejected_firewall_result():
    return FirewallResult(
        firewall_id="fw_002",
        take_id="take_001",
        verdict=FirewallVerdict.REJECTED,
        checks=(
            FirewallCheckResult(
                check_name="kill_switch",
                order=1,
                severity=CheckSeverity.HARD_FAIL,
                code="KILL_SWITCH_ACTIVE",
                message="Kill switch active",
            ),
        ),
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:01Z",
        short_circuited_at="kill_switch",
    )


@pytest.fixture
def test_signal():
    return {
        "signal_id": "SIG-001",
        "symbol": "EURUSD",
        "direction": "BUY",
        "entry_price": 1.0850,
        "stop_loss": 1.0800,
        "take_profit_1": 1.0950,
    }


@pytest.fixture
def test_account():
    return {"account_id": "ACC-001", "balance": 100_000.0, "equity": 99_500.0}


# ── Happy path ────────────────────────────────────────────────────────────


class TestOrchestratorHappyPath:
    async def test_approved_flow_dispatches(
        self,
        coordinator,
        mock_take_service,
        mock_firewall,
        pending_take_response,
        approved_firewall_result,
        test_signal,
        test_account,
    ):
        """Full approved flow: PENDING → FIREWALL_APPROVED → EXECUTION_SENT."""
        mock_take_service.get.return_value = pending_take_response
        mock_firewall.evaluate.return_value = approved_firewall_result
        mock_take_service.transition.return_value = pending_take_response

        with patch("infrastructure.stream_publisher.StreamPublisher.publish", new_callable=AsyncMock):
            result = await coordinator.process_take_signal("take_001", test_signal, test_account)

        assert result.verdict == "APPROVED"
        assert result.status == TakeSignalStatus.EXECUTION_SENT.value
        assert result.firewall_id == "fw_001"
        assert result.execution_intent_id is not None

        # Verify transitions were called in order
        calls = mock_take_service.transition.call_args_list
        assert len(calls) == 2
        # First call: FIREWALL_APPROVED
        assert calls[0].args[1] == TakeSignalStatus.FIREWALL_APPROVED
        # Second call: EXECUTION_SENT
        assert calls[1].args[1] == TakeSignalStatus.EXECUTION_SENT

    async def test_coordinator_does_not_mutate_signal(
        self,
        coordinator,
        mock_take_service,
        mock_firewall,
        pending_take_response,
        approved_firewall_result,
        test_signal,
        test_account,
    ):
        """Coordinator must NEVER modify the signal dict."""
        mock_take_service.get.return_value = pending_take_response
        mock_firewall.evaluate.return_value = approved_firewall_result
        mock_take_service.transition.return_value = pending_take_response

        signal_copy = test_signal.copy()
        with patch("infrastructure.stream_publisher.StreamPublisher.publish", new_callable=AsyncMock):
            await coordinator.process_take_signal("take_001", test_signal, test_account)
        assert test_signal == signal_copy, "Signal was mutated by coordinator!"


# ── Rejection paths ───────────────────────────────────────────────────────


class TestOrchestratorRejection:
    async def test_firewall_rejection_stops_flow(
        self,
        coordinator,
        mock_take_service,
        mock_firewall,
        pending_take_response,
        rejected_firewall_result,
        test_signal,
        test_account,
    ):
        """Firewall rejection → FIREWALL_REJECTED, no execution dispatch."""
        mock_take_service.get.return_value = pending_take_response
        mock_firewall.evaluate.return_value = rejected_firewall_result
        mock_take_service.transition.return_value = pending_take_response

        result = await coordinator.process_take_signal("take_001", test_signal, test_account)

        assert result.verdict == "REJECTED"
        assert result.status == TakeSignalStatus.FIREWALL_REJECTED.value

        # Only one transition call (FIREWALL_REJECTED), no EXECUTION_SENT
        calls = mock_take_service.transition.call_args_list
        assert len(calls) == 1
        assert calls[0].args[1] == TakeSignalStatus.FIREWALL_REJECTED

    async def test_take_not_found_returns_error(self, coordinator, mock_take_service, test_signal, test_account):
        mock_take_service.get.return_value = None
        result = await coordinator.process_take_signal("missing", test_signal, test_account)
        assert result.verdict == "REJECTED"
        assert result.status == "ERROR"

    async def test_non_pending_take_returns_noop(self, coordinator, mock_take_service, test_signal, test_account):
        resp = TakeSignalResponse(
            take_id="take_001",
            request_id="req-001",
            signal_id="SIG-001",
            account_id="ACC-001",
            ea_instance_id="EA-001",
            status=TakeSignalStatus.EXECUTED,  # already terminal
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        mock_take_service.get.return_value = resp
        result = await coordinator.process_take_signal("take_001", test_signal, test_account)
        assert result.verdict == "NOOP"
        assert result.status == "EXECUTED"

    async def test_firewall_exception_rejects(
        self,
        coordinator,
        mock_take_service,
        mock_firewall,
        pending_take_response,
        test_signal,
        test_account,
    ):
        """Firewall evaluation error → REJECTED with error reason."""
        mock_take_service.get.return_value = pending_take_response
        mock_firewall.evaluate.side_effect = RuntimeError("Firewall crashed")
        mock_take_service.transition.return_value = pending_take_response

        result = await coordinator.process_take_signal("take_001", test_signal, test_account)
        assert result.verdict == "REJECTED"
        assert result.status == "ERROR"
        assert "Firewall error" in result.reason


# ── Orchestration Result ──────────────────────────────────────────────────


class TestOrchestrationResult:
    def test_to_dict(self):
        r = OrchestrationResult(
            take_id="take_001",
            verdict="APPROVED",
            firewall_id="fw_001",
            execution_intent_id="ei_001",
            status="EXECUTION_SENT",
            reason="Dispatched",
        )
        d = r.to_dict()
        assert d["take_id"] == "take_001"
        assert d["verdict"] == "APPROVED"
        assert d["firewall_id"] == "fw_001"
        assert d["execution_intent_id"] == "ei_001"
        assert "timestamp" in d

    def test_default_values(self):
        r = OrchestrationResult(take_id="take_x", verdict="HOLD")
        assert r.status == "PENDING"
        assert r.reason == ""
        assert r.firewall_id is None
        assert r.execution_intent_id is None


# ── Dispatch failure ──────────────────────────────────────────────────────


class TestDispatchFailure:
    async def test_stream_publish_failure_does_not_transition_to_execution_sent(
        self,
        coordinator,
        mock_take_service,
        mock_firewall,
        pending_take_response,
        approved_firewall_result,
        test_signal,
        test_account,
    ):
        """If stream publish fails, EXECUTION_SENT must NOT be reached (SVC-BUG-04)."""
        mock_take_service.get.return_value = pending_take_response
        mock_firewall.evaluate.return_value = approved_firewall_result
        mock_take_service.transition.return_value = pending_take_response

        from unittest.mock import patch

        with (
            patch(
                "infrastructure.stream_publisher.StreamPublisher.publish",
                side_effect=ConnectionError("Redis down"),
            ),
            pytest.raises(ConnectionError, match="Redis down"),
        ):
            await coordinator.process_take_signal("take_001", test_signal, test_account)

        # Only one transition (FIREWALL_APPROVED) — never EXECUTION_SENT
        calls = mock_take_service.transition.call_args_list
        statuses = [c.args[1] for c in calls]
        assert TakeSignalStatus.EXECUTION_SENT not in statuses
