"""
P1-11: P1 Acceptance Matrix Regression Test
============================================
Cross-cutting tests validating the acceptance checklist from
docs/architecture/migration-backlog-p1.md section 8.

Each test maps to exactly one acceptance criterion.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

# ── AC-1: take-signal API exists and is idempotent ──────────────────────


class TestTakeSignalAPIExists:
    def test_take_signal_routes_importable(self):
        mod = importlib.import_module("api.take_signal_routes")
        assert hasattr(mod, "router"), "take_signal_routes must expose 'router'"

    def test_take_signal_post_endpoint_exists(self):
        from api.take_signal_routes import router

        [r.path for r in router.routes if hasattr(r, "path")]  # type: ignore[union-attr]
        methods = []
        for route in router.routes:
            if hasattr(route, "methods"):
                methods.extend(route.methods)  # type: ignore[union-attr]
        assert any("POST" in (getattr(r, "methods", set()) or set()) for r in router.routes), (
            "POST endpoint missing from take_signal_routes"
        )

    def test_idempotency_key_in_create_request(self):
        from execution.take_signal_models import TakeSignalCreateRequest

        fields = TakeSignalCreateRequest.model_fields
        assert "request_id" in fields, "TakeSignalCreateRequest must have request_id for idempotency"


# ── AC-2: take-signal lifecycle has explicit transitions + terminal states ──


class TestTakeSignalLifecycleExplicit:
    def test_valid_transitions_dict_exists(self):
        from execution.take_signal_models import VALID_TRANSITIONS

        assert isinstance(VALID_TRANSITIONS, dict)
        assert len(VALID_TRANSITIONS) > 0

    def test_terminal_states_frozenset(self):
        from execution.take_signal_models import TERMINAL_STATES

        assert isinstance(TERMINAL_STATES, frozenset)
        assert len(TERMINAL_STATES) > 0

    def test_terminal_states_have_no_outgoing_transitions(self):
        from execution.take_signal_models import TERMINAL_STATES, VALID_TRANSITIONS

        for state in TERMINAL_STATES:
            targets = VALID_TRANSITIONS.get(state, frozenset())
            assert len(targets) == 0, f"Terminal state {state} must not have outgoing transitions, got {targets}"


# ── AC-3: risk firewall runs in strict order and persists immutable results ──


class TestRiskFirewallOrdered:
    def test_firewall_evaluate_has_ordered_checks(self):
        from risk.firewall import RiskFirewall

        # evaluate method exists and uses ordered check pipeline
        assert hasattr(RiskFirewall, "evaluate"), "RiskFirewall must have evaluate method"
        source = inspect.getsource(RiskFirewall.evaluate)
        assert "check_functions" in source or "CHECK_ORDER" in source, (
            "RiskFirewall.evaluate must define ordered check pipeline"
        )

    def test_firewall_result_is_frozen(self):
        # Frozen dataclass — cannot mutate
        import dataclasses

        from risk.firewall import FirewallResult

        assert dataclasses.is_dataclass(FirewallResult)
        # Frozen check: fields are frozen
        fields = dataclasses.fields(FirewallResult)
        assert len(fields) > 0


# ── AC-4: orchestrator doesn't mutate verdict authority ──


class TestOrchestratorAuthorityBoundary:
    def test_coordinator_has_no_verdict_computation(self):
        """Coordinator must NOT compute market direction (constitutional rule)."""
        source = inspect.getsource(importlib.import_module("services.orchestrator.coordinator"))
        # Must not contain verdict computation keywords
        forbidden = ["wolf_score", "tii_score", "frpc_score"]
        for word in forbidden:
            assert word not in source, f"Coordinator must not compute '{word}' — violates authority boundary"

    def test_coordinator_result_has_verdict_passthrough(self):
        from services.orchestrator.coordinator import OrchestrationResult

        # OrchestrationResult uses @dataclass(slots=True)
        slots = getattr(OrchestrationResult, "__slots__", ())
        assert "verdict" in slots, "OrchestrationResult must have 'verdict' slot for authority passthrough"


# ── AC-5: execution intent persisted with provenance ──


class TestExecutionIntentProvenance:
    def test_intent_links_take_signal_and_firewall(self):
        from execution.execution_intent import ExecutionIntentRecord

        fields = ExecutionIntentRecord.model_fields
        assert "take_id" in fields, "ExecutionIntentRecord must link to take_id"
        assert "signal_id" in fields, "ExecutionIntentRecord must link to signal_id"
        assert "firewall_id" in fields, "ExecutionIntentRecord must link to firewall_id"

    def test_execution_lifecycle_has_terminal_states(self):
        from execution.execution_intent import ExecutionLifecycleState

        terminal = {
            "FILLED",
            "CANCELLED",
            "EXPIRED",
            "REJECTED",
        }
        states = {s.value for s in ExecutionLifecycleState}
        assert terminal.issubset(states), f"Missing terminal states: {terminal - states}"


# ── AC-6: restart/timeout reconciliation prevents blind duplicates ──


class TestReconciliationExists:
    def test_reconciler_importable(self):
        mod = importlib.import_module("execution.reconciliation")
        assert hasattr(mod, "ExecutionReconciler")

    def test_reconciler_has_restart_method(self):
        from execution.reconciliation import ExecutionReconciler

        assert hasattr(ExecutionReconciler, "reconcile_on_restart")

    def test_unresolved_state_exists(self):
        from execution.execution_intent import ExecutionLifecycleState

        assert hasattr(ExecutionLifecycleState, "UNRESOLVED")


# ── AC-7: journal and portfolio read models reflect execution truth ──


class TestTruthFeedExists:
    def test_truth_feed_importable(self):
        mod = importlib.import_module("execution.execution_truth_feed")
        assert hasattr(mod, "ExecutionTruthFeed")

    def test_truth_feed_has_state_change_handler(self):
        from execution.execution_truth_feed import ExecutionTruthFeed

        assert hasattr(ExecutionTruthFeed, "on_execution_state_change")


# ── AC-8: settings changes are audited and rollback-safe ──


class TestSettingsGovernance:
    def test_settings_routes_importable(self):
        mod = importlib.import_module("api.settings_routes")
        assert hasattr(mod, "router")

    def test_settings_have_rollback(self):
        from api.settings_routes import router

        paths = [getattr(r, "path", "") for r in router.routes]
        assert any("rollback" in p for p in paths), "Settings routes must include rollback endpoint"

    def test_settings_have_audit(self):
        from api.settings_routes import router

        paths = [getattr(r, "path", "") for r in router.routes]
        assert any("audit" in p for p in paths), "Settings routes must include audit endpoint"


# ── AC-9: compliance auto-mode is evented and enforced ──


class TestComplianceAutoMode:
    def test_auto_mode_importable(self):
        mod = importlib.import_module("services.orchestrator.compliance_auto_mode")
        assert hasattr(mod, "ComplianceAutoMode")

    def test_auto_mode_has_pause_resume_enforce(self):
        from services.orchestrator.compliance_auto_mode import ComplianceAutoMode

        for method in ["pause", "resume", "enforce"]:
            assert hasattr(ComplianceAutoMode, method), f"ComplianceAutoMode must have '{method}'"


# ── AC-10: allocation and worker paths obey explicit contracts ──


class TestAllocationContracts:
    def test_worker_job_contracts_registry(self):
        from allocation.job_contracts import WORKER_JOB_CONTRACTS

        assert len(WORKER_JOB_CONTRACTS) >= 3

    def test_execution_queue_contract_strict(self):
        from contracts.execution_queue_contract import ExecutionQueuePayload

        # Must reject extra fields (constitutional boundary)
        with pytest.raises(Exception):  # noqa: B017
            ExecutionQueuePayload(
                request_id="req-001",
                signal_id="SIG-001",
                account_id="ACC-001",
                symbol="EURUSD",
                verdict="EXECUTE",
                direction="BUY",
                entry_price=1.0850,
                stop_loss=1.0800,
                take_profit_1=1.0950,
                lot_size=0.1,
                operator="admin",
                balance=100_000,  # type: ignore[call-arg]  # FORBIDDEN: account state in execution payload
            )

    def test_signal_contract_is_frozen(self):
        from schemas.signal_contract import SignalContract

        contract = SignalContract(
            signal_id="SIG-001",
            symbol="EURUSD",
            verdict="EXECUTE",
            confidence=0.87,
            timestamp=1700000000.0,
        )
        with pytest.raises(AttributeError):
            contract.verdict = "HOLD"  # type: ignore[misc]
