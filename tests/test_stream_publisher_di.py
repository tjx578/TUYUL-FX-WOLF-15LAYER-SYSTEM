"""
DEBT-SVC-02: StreamPublisher DI Tests
======================================
Verifies that all modules accepting a StreamPublisher via constructor
injection actually use the injected instance (no inline instantiation).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_mock_publisher() -> AsyncMock:
    """Create a mock that satisfies StreamPublisher interface."""
    pub = AsyncMock()
    pub.publish = AsyncMock(return_value="mock-msg-id")
    return pub


# ═════════════════════════════════════════════════════════════════════════════
# 1. OrchestratorCoordinator
# ═════════════════════════════════════════════════════════════════════════════


class TestCoordinatorPublisherDI:
    def test_accepts_injected_publisher(self):
        from services.orchestrator.coordinator import OrchestratorCoordinator

        pub = _make_mock_publisher()
        coord = OrchestratorCoordinator(
            take_signal_service=AsyncMock(),
            risk_firewall=AsyncMock(),
            stream_publisher=pub,
        )
        assert coord._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from services.orchestrator.coordinator import OrchestratorCoordinator

        coord = OrchestratorCoordinator(
            take_signal_service=AsyncMock(),
            risk_firewall=AsyncMock(),
        )
        # _publisher starts as None; _get_publisher creates one lazily
        assert coord._publisher is None
        publisher = coord._get_publisher()
        assert publisher is not None
        # Subsequent call returns same instance
        assert coord._get_publisher() is publisher


# ═════════════════════════════════════════════════════════════════════════════
# 2. ComplianceAutoMode (orchestrator)
# ═════════════════════════════════════════════════════════════════════════════


class TestComplianceAutoModePublisherDI:
    def test_accepts_injected_publisher(self):
        from services.orchestrator.compliance_auto_mode import ComplianceAutoMode

        pub = _make_mock_publisher()
        cam = ComplianceAutoMode(stream_publisher=pub)
        assert cam._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from services.orchestrator.compliance_auto_mode import ComplianceAutoMode

        cam = ComplianceAutoMode()
        assert cam._publisher is None
        publisher = cam._get_publisher()
        assert publisher is not None
        assert cam._get_publisher() is publisher


# ═════════════════════════════════════════════════════════════════════════════
# 3. TakeSignalService
# ═════════════════════════════════════════════════════════════════════════════


class TestTakeSignalServicePublisherDI:
    def test_accepts_injected_publisher(self):
        from execution.take_signal_service import TakeSignalService

        pub = _make_mock_publisher()
        svc = TakeSignalService(stream_publisher=pub)
        assert svc._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from execution.take_signal_service import TakeSignalService

        svc = TakeSignalService()
        assert svc._stream_publisher is None
        publisher = svc._get_publisher()
        assert publisher is not None
        assert svc._get_publisher() is publisher

    async def test_emit_event_uses_injected_publisher(self):
        from execution.take_signal_models import TakeSignalRecord, TakeSignalStatus
        from execution.take_signal_service import TakeSignalService

        pub = _make_mock_publisher()
        svc = TakeSignalService(stream_publisher=pub)

        record = TakeSignalRecord(
            take_id="take_di_001",
            request_id="req-di-001",
            signal_id="SIG-DI-001",
            account_id="ACC-001",
            ea_instance_id="EA-001",
            operator="test",
            reason="DI test",
            status=TakeSignalStatus.PENDING,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        await svc._emit_event("TEST_EVENT", record)
        pub.publish.assert_awaited_once()
        call_kwargs = pub.publish.call_args
        assert call_kwargs.kwargs["fields"]["event_type"] == "TEST_EVENT"


# ═════════════════════════════════════════════════════════════════════════════
# 4. ExecutionReconciler
# ═════════════════════════════════════════════════════════════════════════════


class TestReconcilerPublisherDI:
    def test_accepts_injected_publisher(self):
        from execution.reconciliation import ExecutionReconciler

        pub = _make_mock_publisher()
        rec = ExecutionReconciler(stream_publisher=pub)
        assert rec._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from execution.reconciliation import ExecutionReconciler

        rec = ExecutionReconciler()
        assert rec._stream_publisher is None
        publisher = rec._get_publisher()
        assert publisher is not None
        assert rec._get_publisher() is publisher

    async def test_emit_reconciliation_event_uses_injected_publisher(self):
        from execution.reconciliation import ExecutionReconciler, ReconciliationResult

        pub = _make_mock_publisher()
        rec = ExecutionReconciler(stream_publisher=pub)

        results = [
            ReconciliationResult("ei_001", "ORDER_PLACED", "UNRESOLVED", "timeout", "300s"),
        ]
        await rec._emit_reconciliation_event(results)
        pub.publish.assert_awaited_once()
        call_kwargs = pub.publish.call_args
        assert call_kwargs.kwargs["fields"]["event_type"] == "RECONCILIATION_COMPLETED"
        assert call_kwargs.kwargs["fields"]["count"] == "1"


# ═════════════════════════════════════════════════════════════════════════════
# 5. ExecutionTruthFeed
# ═════════════════════════════════════════════════════════════════════════════


class TestTruthFeedPublisherDI:
    def test_accepts_injected_publisher(self):
        from execution.execution_truth_feed import ExecutionTruthFeed

        pub = _make_mock_publisher()
        tf = ExecutionTruthFeed(stream_publisher=pub)
        assert tf._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from execution.execution_truth_feed import ExecutionTruthFeed

        tf = ExecutionTruthFeed()
        assert tf._stream_publisher is None
        publisher = tf._get_publisher()
        assert publisher is not None
        assert tf._get_publisher() is publisher

    async def test_emit_truth_event_uses_injected_publisher(self):
        from execution.execution_intent import (
            ExecutionIntentRecord,
            ExecutionLifecycleState,
        )
        from execution.execution_truth_feed import ExecutionTruthFeed

        pub = _make_mock_publisher()
        tf = ExecutionTruthFeed(stream_publisher=pub)

        intent = ExecutionIntentRecord(
            execution_intent_id="ei_di_001",
            idempotency_key="idem_di_001",
            take_id="take_di_001",
            signal_id="SIG-DI-001",
            firewall_id="fw_di_001",
            account_id="ACC-001",
            symbol="EURUSD",
            direction="BUY",
            state=ExecutionLifecycleState.FILLED,
        )
        await tf._emit_truth_event(intent, ExecutionLifecycleState.ACKNOWLEDGED)
        pub.publish.assert_awaited_once()
        call_kwargs = pub.publish.call_args
        assert "EXECUTION_TRUTH_FILLED" in call_kwargs.kwargs["fields"]["event_type"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. RiskFirewall
# ═════════════════════════════════════════════════════════════════════════════


class TestFirewallPublisherDI:
    def test_accepts_injected_publisher(self):
        from risk.firewall import RiskFirewall

        pub = _make_mock_publisher()
        fw = RiskFirewall(stream_publisher=pub)
        assert fw._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from risk.firewall import RiskFirewall

        fw = RiskFirewall()
        assert fw._stream_publisher is None
        publisher = fw._get_publisher()
        assert publisher is not None
        assert fw._get_publisher() is publisher

    async def test_emit_event_uses_injected_publisher(self):
        from risk.firewall import (
            CheckSeverity,
            FirewallCheckResult,
            FirewallResult,
            FirewallVerdict,
            RiskFirewall,
        )

        pub = _make_mock_publisher()
        fw = RiskFirewall(stream_publisher=pub)

        result = FirewallResult(
            firewall_id="fw_di_001",
            take_id="take_di_001",
            verdict=FirewallVerdict.APPROVED,
            checks=(
                FirewallCheckResult(
                    check_name="kill_switch",
                    order=1,
                    severity=CheckSeverity.PASS,
                    code="OK",
                    message="test",
                ),
            ),
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:01Z",
        )
        await fw._emit_event(result)
        pub.publish.assert_awaited_once()
        call_kwargs = pub.publish.call_args
        assert call_kwargs.kwargs["fields"]["event_type"] == "FIREWALL_APPROVED"


# ═════════════════════════════════════════════════════════════════════════════
# 7. ComplianceAutoModeEngine
# ═════════════════════════════════════════════════════════════════════════════


class TestComplianceEnginePublisherDI:
    def test_accepts_injected_publisher(self):
        from risk.compliance_engine import ComplianceAutoModeEngine

        pub = _make_mock_publisher()
        engine = ComplianceAutoModeEngine(stream_publisher=pub)
        assert engine._get_publisher() is pub

    def test_lazy_fallback_when_none(self):
        from risk.compliance_engine import ComplianceAutoModeEngine

        engine = ComplianceAutoModeEngine()
        assert engine._stream_publisher is None
        publisher = engine._get_publisher()
        assert publisher is not None
        assert engine._get_publisher() is publisher

    async def test_emit_mode_change_uses_injected_publisher(self):
        from risk.compliance_engine import (
            ComplianceAutoModeEngine,
            ComplianceMode,
            ComplianceModeResult,
        )

        pub = _make_mock_publisher()
        engine = ComplianceAutoModeEngine(stream_publisher=pub)

        result = ComplianceModeResult(
            account_id="ACC-001",
            previous_mode=ComplianceMode.NORMAL,
            current_mode=ComplianceMode.REDUCE_RISK_MODE,
            changed=True,
            reason="Daily DD 82%",
            daily_usage_percent=82.0,
            total_usage_percent=50.0,
            daily_threshold_warn=80.0,
            daily_threshold_block=95.0,
            total_threshold_warn=80.0,
            total_threshold_block=95.0,
        )
        await engine._emit_mode_change(result)
        pub.publish.assert_awaited_once()
        call_kwargs = pub.publish.call_args
        assert call_kwargs.kwargs["fields"]["event_type"] == "COMPLIANCE_MODE_CHANGED"
        assert call_kwargs.kwargs["fields"]["account_id"] == "ACC-001"


# ═════════════════════════════════════════════════════════════════════════════
# 8. Cross-cutting: no inline StreamPublisher() in emit methods
# ═════════════════════════════════════════════════════════════════════════════


class TestNoInlineInstantiation:
    """Verify emit methods no longer create StreamPublisher() inline."""

    @pytest.mark.parametrize(
        "module_path,class_name,method_name",
        [
            ("execution.take_signal_service", "TakeSignalService", "_emit_event"),
            ("execution.reconciliation", "ExecutionReconciler", "_emit_reconciliation_event"),
            ("execution.execution_truth_feed", "ExecutionTruthFeed", "_emit_truth_event"),
            ("risk.firewall", "RiskFirewall", "_emit_event"),
            ("risk.compliance_engine", "ComplianceAutoModeEngine", "_emit_mode_change"),
            ("services.orchestrator.coordinator", "OrchestratorCoordinator", "_emit_event"),
            ("services.orchestrator.coordinator", "OrchestratorCoordinator", "_dispatch_to_execution"),
            ("services.orchestrator.compliance_auto_mode", "ComplianceAutoMode", "_emit_transition_event"),
        ],
    )
    def test_emit_method_has_no_inline_publisher(self, module_path, class_name, method_name):
        """Emit methods must not contain `StreamPublisher()` — they should use _get_publisher()."""
        import importlib
        import inspect

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        method = getattr(cls, method_name)
        source = inspect.getsource(method)
        assert "StreamPublisher()" not in source, (
            f"{class_name}.{method_name} still contains inline StreamPublisher() instantiation"
        )

    @pytest.mark.parametrize(
        "module_path,class_name",
        [
            ("execution.take_signal_service", "TakeSignalService"),
            ("execution.reconciliation", "ExecutionReconciler"),
            ("execution.execution_truth_feed", "ExecutionTruthFeed"),
            ("risk.firewall", "RiskFirewall"),
            ("risk.compliance_engine", "ComplianceAutoModeEngine"),
            ("services.orchestrator.coordinator", "OrchestratorCoordinator"),
            ("services.orchestrator.compliance_auto_mode", "ComplianceAutoMode"),
        ],
    )
    def test_class_has_get_publisher_method(self, module_path, class_name):
        """All DI-enabled classes must have _get_publisher() lazy-init method."""
        import importlib

        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        assert hasattr(cls, "_get_publisher"), f"{class_name} missing _get_publisher() method"
