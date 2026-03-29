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

    def test_is_dataclass_with_slots(self):
        import dataclasses

        assert dataclasses.is_dataclass(OrchestrationResult)
        assert hasattr(OrchestrationResult, "__slots__")
        assert "verdict" in OrchestrationResult.__slots__
        assert "timestamp" in OrchestrationResult.__slots__
        # slots=True means no __dict__
        r = OrchestrationResult(take_id="t", verdict="X")
        assert not hasattr(r, "__dict__")

    def test_auto_eq(self):
        a = OrchestrationResult(take_id="t", verdict="X", timestamp="fixed")
        b = OrchestrationResult(take_id="t", verdict="X", timestamp="fixed")
        assert a == b
        c = OrchestrationResult(take_id="t", verdict="Y", timestamp="fixed")
        assert a != c

    def test_auto_repr(self):
        r = OrchestrationResult(take_id="t", verdict="X")
        text = repr(r)
        assert "OrchestrationResult" in text
        assert "take_id='t'" in text

    def test_timestamp_auto_generated(self):
        r = OrchestrationResult(take_id="t", verdict="X")
        assert isinstance(r.timestamp, str)
        assert len(r.timestamp) > 0


# ── Pipeline decomposition (DEBT-SVC-07) ─────────────────────────────────


class TestPipelineDecomposition:
    """Verify process_take_signal is decomposed into testable pipeline steps."""

    def test_pipeline_methods_exist(self):
        coord = OrchestratorCoordinator(
            take_signal_service=AsyncMock(), risk_firewall=AsyncMock(),
        )
        assert callable(getattr(coord, "_validate_take", None))
        assert callable(getattr(coord, "_evaluate_firewall", None))
        assert callable(getattr(coord, "_handle_rejection", None))
        assert callable(getattr(coord, "_dispatch_and_complete", None))

    def test_process_take_signal_is_short(self):
        """The public method should be a short pipeline dispatcher, not a god method."""
        import inspect
        import textwrap

        source = inspect.getsource(OrchestratorCoordinator.process_take_signal)
        lines = [l for l in textwrap.dedent(source).splitlines() if l.strip() and not l.strip().startswith(("#", '"""', "\'\'\'"))]  # noqa: E741
        assert len(lines) <= 30, f"process_take_signal still too long: {len(lines)} lines"

    async def test_validate_take_not_found(self, coordinator, mock_take_service):
        mock_take_service.get.return_value = None
        result = await coordinator._validate_take("missing")
        assert isinstance(result, OrchestrationResult)
        assert result.verdict == "REJECTED"
        assert result.status == "ERROR"

    async def test_validate_take_non_pending(self, coordinator, mock_take_service):
        from execution.take_signal_models import TakeSignalResponse, TakeSignalStatus

        resp = TakeSignalResponse(
            take_id="t", request_id="r", signal_id="s", account_id="a",
            ea_instance_id="e", status=TakeSignalStatus.EXECUTED,
            created_at="x", updated_at="x",
        )
        mock_take_service.get.return_value = resp
        result = await coordinator._validate_take("t")
        assert isinstance(result, OrchestrationResult)
        assert result.verdict == "NOOP"

    async def test_validate_take_pending_returns_response(
        self, coordinator, mock_take_service, pending_take_response,
    ):
        mock_take_service.get.return_value = pending_take_response
        result = await coordinator._validate_take("take_001")
        assert not isinstance(result, OrchestrationResult)
        assert result.signal_id == "SIG-001"

    async def test_evaluate_firewall_error_returns_result(
        self, coordinator, mock_firewall,
    ):
        mock_firewall.evaluate.side_effect = RuntimeError("boom")
        result = await coordinator._evaluate_firewall("t", {}, {})
        assert isinstance(result, OrchestrationResult)
        assert result.verdict == "REJECTED"
        assert "Firewall error" in result.reason

    async def test_evaluate_firewall_success_returns_fw_result(
        self, coordinator, mock_firewall, approved_firewall_result,
    ):
        mock_firewall.evaluate.return_value = approved_firewall_result
        result = await coordinator._evaluate_firewall("t", {}, {})
        assert not isinstance(result, OrchestrationResult)
        assert result.firewall_id == "fw_001"

    async def test_handle_rejection(
        self, coordinator, rejected_firewall_result,
    ):
        result = await coordinator._handle_rejection("take_001", rejected_firewall_result)
        assert isinstance(result, OrchestrationResult)
        assert result.verdict == "REJECTED"
        assert result.firewall_id == "fw_002"


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


# ── ARCH-GAP-09: Decoupling boundary tests ───────────────────────────────


class TestArchGap09Decoupling:
    """Verify coordinator module is decoupled from execution.* and risk.* at module level."""

    def test_coordinator_does_not_import_execution_at_module_level(self):
        """coordinator.py must not have top-level imports from execution.*."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "orchestrator" / "coordinator.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("execution"), (
                    f"coordinator.py has top-level import from {node.module}"
                )

    def test_coordinator_does_not_import_risk_at_module_level(self):
        """coordinator.py must not have top-level imports from risk.*."""
        import ast
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent / "services" / "orchestrator" / "coordinator.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("risk"), f"coordinator.py has top-level import from {node.module}"

    def test_coordinator_uses_protocol_types(self):
        """OrchestratorCoordinator accepts any Protocol-satisfying dependency."""

        # AsyncMock satisfies Protocol (duck typing)
        svc = AsyncMock()
        fw = AsyncMock()
        coord = OrchestratorCoordinator(take_signal_service=svc, risk_firewall=fw)
        assert coord._take_svc is svc
        assert coord._firewall is fw

    def test_transition_accepts_plain_string(self):
        """TakeSignalService.transition() accepts plain str (ARCH-GAP-09 coercion)."""
        import inspect

        from execution.take_signal_service import TakeSignalService

        sig = inspect.signature(TakeSignalService.transition)
        param = sig.parameters["new_status"]
        annotation = str(param.annotation)
        # Should accept str (either 'str | TakeSignalStatus' or union including str)
        assert "str" in annotation
