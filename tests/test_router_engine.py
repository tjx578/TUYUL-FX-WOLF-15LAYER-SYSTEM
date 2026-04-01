"""
Tests for agents.router_engine — registry, routing, scoring, orchestration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.router_engine import (
    DefaultModeRunner,
    DimensionScorer,
    MemoryAdapter,
    ObjectiveNormalizer,
    ObjectiveValidationError,
    OrchestrationEngine,
    OrchestrationStateMachine,
    Registry,
    RegistryError,
    RouteDecision,
    RouterEngine,
    RoutingError,
    RuleEvaluator,
    VerificationSink,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"
REGISTRY_PATH = AGENTS_DIR / "registry.json"
SAMPLE_OBJECTIVE_PATH = AGENTS_DIR / "sample_objective.json"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def raw_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def registry(raw_registry: dict) -> Registry:
    return Registry(raw_registry)


@pytest.fixture()
def sample_payload() -> dict:
    return json.loads(SAMPLE_OBJECTIVE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def minimal_payload() -> dict:
    return {"user_request": "Fix the login bug"}


@pytest.fixture()
def router(registry: Registry) -> RouterEngine:
    return RouterEngine(registry)


@pytest.fixture()
def engine(registry: Registry) -> OrchestrationEngine:
    return OrchestrationEngine(registry=registry)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_load_from_path(self) -> None:
        reg = Registry.from_path(REGISTRY_PATH)
        assert len(reg.registry_items) >= 15

    def test_all_ids_unique(self, registry: Registry) -> None:
        ids = [item["id"] for item in registry.registry_items]
        assert len(ids) == len(set(ids))

    def test_has_mode(self, registry: Registry) -> None:
        assert registry.has_mode("scout")
        assert registry.has_mode("implementation")
        assert registry.has_mode("verification")
        assert not registry.has_mode("nonexistent_mode")

    def test_get_mode(self, registry: Registry) -> None:
        mode = registry.get_mode("research")
        assert mode["id"] == "research"
        assert "topology_support" in mode

    def test_get_mode_unknown_raises(self, registry: Registry) -> None:
        with pytest.raises(RegistryError, match="Unknown mode"):
            registry.get_mode("nonexistent")

    def test_topology_rules_present(self, registry: Registry) -> None:
        assert len(registry.topology_rules) >= 1

    def test_gate_injection_present(self, registry: Registry) -> None:
        assert isinstance(registry.gate_injection, dict)
        assert len(registry.gate_injection) >= 1

    def test_state_machine_present(self, registry: Registry) -> None:
        assert isinstance(registry.state_machine, dict)

    def test_invalid_empty_registry_raises(self) -> None:
        with pytest.raises(RegistryError):
            Registry({"registry": [], "topology_rules": []})

    def test_duplicate_ids_raises(self, raw_registry: dict) -> None:
        raw = dict(raw_registry)
        raw["registry"] = raw["registry"] + [raw["registry"][0]]
        with pytest.raises(RegistryError, match="unique"):
            Registry(raw)


# ---------------------------------------------------------------------------
# Objective normalization
# ---------------------------------------------------------------------------


class TestObjectiveNormalizer:
    def test_from_sample_payload(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        assert obj.user_request
        assert obj.normalized_objective
        assert "backend" in obj.domain_tags
        assert obj.constraints.security_sensitivity == "high"
        assert obj.preferences.allow_swarm is True
        assert obj.preferences.require_spec_first is True

    def test_minimal_payload(self, minimal_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        assert obj.user_request == "Fix the login bug"
        assert obj.normalized_objective == "Fix the login bug"
        assert obj.domain_tags == []
        assert obj.constraints.security_sensitivity == "low"
        assert obj.preferences.prefer_fast_path is True

    def test_missing_user_request_raises(self) -> None:
        with pytest.raises(ObjectiveValidationError, match="user_request"):
            ObjectiveNormalizer.from_payload({})

    def test_empty_user_request_raises(self) -> None:
        with pytest.raises(ObjectiveValidationError, match="must not be empty"):
            ObjectiveNormalizer.from_payload({"user_request": "   "})

    def test_auto_generates_objective_id(self, minimal_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        assert obj.objective_id.startswith("obj-")

    def test_explicit_objective_id(self, minimal_payload: dict) -> None:
        minimal_payload["objective_id"] = "custom-123"
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        assert obj.objective_id == "custom-123"


# ---------------------------------------------------------------------------
# Dimension scorer
# ---------------------------------------------------------------------------


class TestDimensionScorer:
    def test_minimal_scores_low(self, minimal_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        dims = DimensionScorer.score(obj)
        assert dims.complexity <= 2
        assert dims.security_risk <= 2
        assert dims.memory_value <= 1

    def test_sample_payload_high_security(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        dims = DimensionScorer.score(obj)
        assert dims.security_risk >= 4  # high sensitivity + "auth" keyword
        assert dims.architecture_impact >= 3
        assert dims.memory_value >= 3

    def test_all_dimensions_bounded(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        dims = DimensionScorer.score(obj)
        for name in [
            "complexity",
            "ambiguity",
            "security_risk",
            "performance_risk",
            "architecture_impact",
            "delivery_scope",
            "memory_value",
        ]:
            val = getattr(dims, name)
            assert 0 <= val <= 5, f"{name}={val} out of bounds"

    def test_performance_keywords(self) -> None:
        obj = ObjectiveNormalizer.from_payload(
            {"user_request": "Optimize latency for the hot path"}
        )
        dims = DimensionScorer.score(obj)
        assert dims.performance_risk >= 2  # keyword boost


# ---------------------------------------------------------------------------
# Rule evaluator
# ---------------------------------------------------------------------------


class TestRuleEvaluator:
    def test_always(self) -> None:
        obj = ObjectiveNormalizer.from_payload({"user_request": "test"})
        dims = DimensionScorer.score(obj)
        assert RuleEvaluator.evaluate("always", obj, dims) is True

    def test_numeric_comparison(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        dims = DimensionScorer.score(obj)
        assert RuleEvaluator.evaluate("security_risk >= 3", obj, dims) is True

    def test_contains_deliverable(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        dims = DimensionScorer.score(obj)
        assert RuleEvaluator.evaluate("deliverable_types contains code", obj, dims)
        assert not RuleEvaluator.evaluate(
            "deliverable_types contains nonexistent", obj, dims
        )

    def test_memory_required(self, sample_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        dims = DimensionScorer.score(obj)
        assert RuleEvaluator.evaluate(
            "constraints.memory_required == true", obj, dims
        )

    def test_invalid_expression_raises(self) -> None:
        obj = ObjectiveNormalizer.from_payload({"user_request": "x"})
        dims = DimensionScorer.score(obj)
        with pytest.raises(RoutingError, match="Failed to evaluate"):
            RuleEvaluator.evaluate("totally_invalid_var >= 5", obj, dims)


# ---------------------------------------------------------------------------
# Router engine
# ---------------------------------------------------------------------------


class TestRouterEngine:
    def test_route_returns_decision(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        assert isinstance(decision, RouteDecision)
        assert decision.objective_id
        assert decision.route_id.startswith("route-")
        assert decision.selected_topology
        assert decision.selected_modes

    def test_route_sample_includes_security_gate(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        assert "security" in decision.selected_modes

    def test_route_sample_includes_verification(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        assert "verification" in decision.selected_modes

    def test_route_spec_first_injects_specification(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        if "specification" in decision.selected_modes:
            assert True
        else:
            # require_spec_first = true should inject it
            assert "preference_require_spec_first" in decision.matched_rules

    def test_route_modes_exist_in_registry(
        self, router: RouterEngine, registry: Registry, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        for mode in decision.selected_modes:
            assert registry.has_mode(mode), f"Routed mode '{mode}' missing in registry"

    def test_route_dimensions_present(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = router.route(obj)
        assert "complexity" in decision.dimensions
        assert "security_risk" in decision.dimensions

    def test_minimal_objective_gets_fast_path(
        self, router: RouterEngine, minimal_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        decision = router.route(obj)
        # minimal + prefer_fast_path=True => likely single topology
        assert decision.selected_topology in {"single", "pipeline"}

    def test_swarm_disabled_blocks_swarm_topology(
        self, router: RouterEngine
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(
            {
                "user_request": "Complex multi-step integration",
                "domain_tags": ["backend"],
                "deliverable_types": ["code"],
                "constraints": {"architecture_impact": "cross_system"},
                "preferences": {"allow_swarm": False, "prefer_fast_path": False},
            }
        )
        decision = router.route(obj)
        assert decision.selected_topology not in {
            "parallel_swarm",
            "hierarchical_swarm",
        }


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestOrchestrationStateMachine:
    def test_happy_path(self) -> None:
        sm = OrchestrationStateMachine()
        assert sm.state == "intake"
        sm.transition("normalized")
        sm.transition("classified")
        sm.transition("routed")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("persistence")
        sm.transition("completed")
        assert sm.state == "completed"
        assert sm.history == [
            "intake",
            "normalized",
            "classified",
            "routed",
            "executing",
            "verifying",
            "persistence",
            "completed",
        ]

    def test_blocked_then_failed(self) -> None:
        sm = OrchestrationStateMachine()
        sm.transition("normalized")
        sm.transition("classified")
        sm.transition("routed")
        sm.transition("executing")
        sm.transition("blocked")
        sm.transition("failed")
        assert sm.state == "failed"

    def test_blocked_then_reroute(self) -> None:
        sm = OrchestrationStateMachine()
        sm.transition("normalized")
        sm.transition("classified")
        sm.transition("routed")
        sm.transition("executing")
        sm.transition("blocked")
        sm.transition("reroute_required")
        sm.transition("routed")
        assert sm.state == "routed"

    def test_illegal_transition_raises(self) -> None:
        sm = OrchestrationStateMachine()
        with pytest.raises(RoutingError, match="Illegal state transition"):
            sm.transition("completed")

    def test_completed_is_terminal(self) -> None:
        sm = OrchestrationStateMachine()
        sm.transition("normalized")
        sm.transition("classified")
        sm.transition("routed")
        sm.transition("executing")
        sm.transition("verifying")
        sm.transition("persistence")
        sm.transition("completed")
        with pytest.raises(RoutingError):
            sm.transition("executing")


# ---------------------------------------------------------------------------
# Verification sink
# ---------------------------------------------------------------------------


class TestVerificationSink:
    def test_pass_verdict(self, sample_payload: dict, router: RouterEngine) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        route = router.route(obj)
        from agents.router_engine import ModeResult

        results = [
            ModeResult(mode="research", status="success", summary="ok"),
            ModeResult(mode="security", status="success", summary="ok"),
            ModeResult(mode="performance", status="success", summary="ok"),
            ModeResult(mode="test", status="success", summary="ok"),
        ]
        sink = VerificationSink()
        v = sink.verify(obj, route, results)
        assert v.overall_verdict == "pass"
        assert v.confidence >= 0.9
        assert v.ship_recommendation == "ship"

    def test_blocked_result_causes_fail(
        self, sample_payload: dict, router: RouterEngine
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        route = router.route(obj)
        from agents.router_engine import ModeResult

        results = [
            ModeResult(
                mode="security",
                status="blocked",
                summary="fail",
                blockers=["Critical CVE"],
            ),
        ]
        sink = VerificationSink()
        v = sink.verify(obj, route, results)
        assert v.overall_verdict == "fail"
        assert "Critical CVE" in v.blockers
        assert v.ship_recommendation == "do_not_ship"


# ---------------------------------------------------------------------------
# Memory adapter
# ---------------------------------------------------------------------------


class TestMemoryAdapter:
    def test_writeback(self, sample_payload: dict, router: RouterEngine) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        route = router.route(obj)
        from agents.router_engine import ModeResult, VerificationResult

        results = [ModeResult(mode="research", status="success", summary="ok")]
        vr = VerificationResult(
            checks={}, overall_verdict="pass", blockers=[], confidence=0.9, ship_recommendation="ship"
        )
        adapter = MemoryAdapter()
        mem = adapter.writeback(obj, route, results, vr)
        assert mem["writeback_status"] == "written"
        assert len(mem["namespaces"]) >= 2


# ---------------------------------------------------------------------------
# Orchestration engine — route only
# ---------------------------------------------------------------------------


class TestOrchestrationRouteOnly:
    def test_route_only_returns_decision(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        decision = engine.route_only(obj)
        assert isinstance(decision, RouteDecision)
        assert decision.selected_modes

    def test_route_only_minimal(
        self, engine: OrchestrationEngine, minimal_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        decision = engine.route_only(obj)
        assert decision.selected_topology in {"single", "pipeline"}


# ---------------------------------------------------------------------------
# Orchestration engine — full execution
# ---------------------------------------------------------------------------


class TestOrchestrationExecution:
    def test_execute_success(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        result = engine.execute(obj)
        assert result.objective_id
        assert result.route_id
        assert result.selected_topology
        assert result.selected_modes
        assert result.execution_status in {"success", "partial"}
        assert result.state_history[0] == "intake"
        assert result.state_history[-1] in {"completed", "failed"}

    def test_execute_has_verification(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        result = engine.execute(obj)
        assert result.verification
        assert "overall_verdict" in result.verification

    def test_execute_has_memory_writeback(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        result = engine.execute(obj)
        if result.execution_status in {"success", "partial"}:
            assert result.memory["writeback_status"] == "written"

    def test_execute_minimal(
        self, engine: OrchestrationEngine, minimal_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        result = engine.execute(obj)
        assert result.execution_status in {"success", "partial"}

    def test_execute_blocked_mode(self, registry: Registry) -> None:
        """A mode runner that returns blocked should halt the pipeline."""
        from agents.router_engine import ModeResult

        class BlockingRunner:
            def run(self, mode_id, objective, route, prior_results):
                if mode_id == "implementation":
                    return ModeResult(
                        mode=mode_id,
                        status="blocked",
                        summary="Cannot proceed",
                        blockers=["Missing dependency"],
                    )
                return ModeResult(
                    mode=mode_id, status="success", summary=f"{mode_id} ok"
                )

        engine = OrchestrationEngine(
            registry=registry, mode_runner=BlockingRunner()
        )
        obj = ObjectiveNormalizer.from_payload(
            {"user_request": "Build something", "preferences": {"prefer_fast_path": True}}
        )
        result = engine.execute(obj)
        assert result.execution_status == "blocked"
        assert "Missing dependency" in result.verification["blockers"]

    def test_execute_state_history_valid(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        result = engine.execute(obj)
        # All transitions must be legal
        legal = OrchestrationStateMachine.LEGAL
        for prev_state, next_state in zip(
            result.state_history[:-1], result.state_history[1:], strict=False
        ):
            assert next_state in legal.get(prev_state, set()), (
                f"Illegal transition in history: {prev_state} -> {next_state}"
            )

    def test_execute_governance_present(
        self, engine: OrchestrationEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        result = engine.execute(obj)
        assert "verification_status" in result.governance


# ---------------------------------------------------------------------------
# Default mode runner
# ---------------------------------------------------------------------------


class TestDefaultModeRunner:
    def test_research_output(self, router: RouterEngine, minimal_payload: dict) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        route = router.route(obj)
        runner = DefaultModeRunner()
        result = runner.run("research", obj, route, [])
        assert result.status == "success"
        assert result.mode == "research"
        assert result.findings

    def test_security_high_decision(
        self, router: RouterEngine, sample_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(sample_payload)
        route = router.route(obj)
        runner = DefaultModeRunner()
        result = runner.run("security", obj, route, [])
        assert any("specialist" in d.lower() for d in result.decisions)

    def test_unknown_mode_still_works(
        self, router: RouterEngine, minimal_payload: dict
    ) -> None:
        obj = ObjectiveNormalizer.from_payload(minimal_payload)
        route = router.route(obj)
        runner = DefaultModeRunner()
        result = runner.run("custom_mode", obj, route, [])
        assert result.status == "success"


# ---------------------------------------------------------------------------
# CLI integration (route-only)
# ---------------------------------------------------------------------------


class TestCLIRouteOnly:
    def test_cli_route_only(self, tmp_path: Path) -> None:
        """Verify CLI runs route-only without error."""
        import subprocess

        out_file = tmp_path / "route_result.json"
        result = subprocess.run(
            [
                "python",
                "-m",
                "agents.router_engine",
                "--registry",
                str(REGISTRY_PATH),
                "--objective",
                str(SAMPLE_OBJECTIVE_PATH),
                "--route-only",
                "--pretty",
                "--out",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "selected_topology" in data
        assert "selected_modes" in data

    def test_cli_full_execution(self, tmp_path: Path) -> None:
        """Verify CLI runs full execution without error."""
        import subprocess

        out_file = tmp_path / "exec_result.json"
        result = subprocess.run(
            [
                "python",
                "-m",
                "agents.router_engine",
                "--registry",
                str(REGISTRY_PATH),
                "--objective",
                str(SAMPLE_OBJECTIVE_PATH),
                "--out",
                str(out_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert "execution_status" in data
        assert "state_history" in data
