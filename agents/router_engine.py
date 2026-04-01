from __future__ import annotations

"""
router_engine.py

Production-grade skeleton for the Ultimate Agent orchestration engine.

Features:
- Registry loader from registry.json
- Objective normalization and validation
- Routing dimension scoring
- Deterministic topology/rule selection
- Gate injection
- State machine tracking
- Mode runner interface + default skeleton runner
- Verification sink + memory adapter stubs
- CLI for route-only or full execution

Usage:
    python router_engine.py --registry registry.json --objective objective.json --route-only
    python router_engine.py --registry registry.json --objective objective.json --out result.json
"""

import argparse  # noqa: E402
import json  # noqa: E402
import uuid  # noqa: E402
from collections.abc import Sequence  # noqa: E402
from dataclasses import asdict, dataclass, field  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, List, Optional, Protocol, Tuple  # noqa: E402, UP035

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryError(Exception):
    """Raised when the registry file is invalid."""


class ObjectiveValidationError(Exception):
    """Raised when the objective payload is invalid."""


class RoutingError(Exception):
    """Raised when route selection cannot complete safely."""


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


SENSITIVITY_MAP = {"low": 1, "medium": 3, "high": 5}
ARCH_IMPACT_MAP = {"none": 0, "local": 1, "cross_module": 3, "cross_system": 5}
RELEASE_IMPACT_MAP = {"none": 0, "minor": 2, "major": 4}


def _safe_json_load(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RegistryError(f"File not found: {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError(f"JSON root must be an object: {path}")
    return data


def _unique_preserve_order(items: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _insert_after(items: List[str], anchor: str, value: str) -> List[str]:
    items = list(items)
    if value in items:
        return items
    if anchor in items:
        idx = items.index(anchor)
        items.insert(idx + 1, value)
    else:
        items.append(value)
    return items


def _insert_before(items: List[str], anchor: str, value: str) -> List[str]:
    items = list(items)
    if value in items:
        return items
    if anchor in items:
        idx = items.index(anchor)
        items.insert(idx, value)
    else:
        items.append(value)
    return items


def _contains(values: Sequence[str], item: str) -> bool:
    return item in values


# ---------------------------------------------------------------------------
# Data contracts
# ---------------------------------------------------------------------------


@dataclass
class ObjectiveConstraints:
    time_sensitivity: str = "low"
    security_sensitivity: str = "low"
    performance_sensitivity: str = "low"
    architecture_impact: str = "none"
    release_impact: str = "none"
    memory_required: bool = False
    audit_required: bool = False


@dataclass
class ObjectiveContext:
    repo_available: bool = False
    artifacts_available: bool = False
    historical_memory_available: bool = False
    external_systems_involved: List[str] = field(default_factory=list)


@dataclass
class ObjectivePreferences:
    prefer_fast_path: bool = True
    allow_swarm: bool = False
    require_spec_first: bool = False


@dataclass
class Objective:
    objective_id: str
    user_request: str
    normalized_objective: str
    domain_tags: List[str] = field(default_factory=list)
    deliverable_types: List[str] = field(default_factory=list)
    constraints: ObjectiveConstraints = field(default_factory=ObjectiveConstraints)
    context: ObjectiveContext = field(default_factory=ObjectiveContext)
    preferences: ObjectivePreferences = field(default_factory=ObjectivePreferences)


@dataclass
class RoutingDimensions:
    complexity: int
    ambiguity: int
    security_risk: int
    performance_risk: int
    architecture_impact: int
    delivery_scope: int
    memory_value: int


@dataclass
class RouteDecision:
    objective_id: str
    route_id: str
    selected_topology: str
    selected_modes: List[str]
    injected_gates: List[str]
    matched_rules: List[str]
    routing_reason: List[str]
    dimensions: Dict[str, int]


@dataclass
class ModeResult:
    mode: str
    status: str  # success | warn | blocked | failed
    summary: str
    artifacts: List[str] = field(default_factory=list)
    findings: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    checks: Dict[str, str]
    overall_verdict: str
    blockers: List[str]
    confidence: float
    ship_recommendation: str


@dataclass
class OrchestrationResult:
    objective_id: str
    route_id: str
    selected_topology: str
    selected_modes: List[str]
    execution_status: str
    deliverables: Dict[str, List[str]]
    governance: Dict[str, Any]
    memory: Dict[str, Any]
    next_actions: List[str]
    mode_results: List[Dict[str, Any]]
    verification: Dict[str, Any]
    state_history: List[str]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class Registry:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.raw = raw
        self.meta = raw.get("meta", {})
        self.registry_items = raw.get("registry", [])
        self.topology_rules = raw.get("topology_rules", [])
        self.gate_injection = raw.get("gate_injection", {})
        self.state_machine = raw.get("state_machine", {})
        self.standard_routes = raw.get("standard_routes", {})
        self._validate()

    def _validate(self) -> None:
        if not isinstance(self.registry_items, list) or not self.registry_items:
            raise RegistryError("Registry must contain a non-empty 'registry' list.")
        if not isinstance(self.topology_rules, list) or not self.topology_rules:
            raise RegistryError("Registry must contain a non-empty 'topology_rules' list.")
        ids = [item.get("id") for item in self.registry_items]
        if any(not isinstance(i, str) or not i for i in ids):
            raise RegistryError("All registry items must have a non-empty string 'id'.")
        if len(ids) != len(set(ids)):
            raise RegistryError("Registry item IDs must be unique.")

    @classmethod
    def from_path(cls, path: Path) -> "Registry":
        return cls(_safe_json_load(path))

    def get_mode(self, mode_id: str) -> Dict[str, Any]:
        for item in self.registry_items:
            if item["id"] == mode_id:
                return item
        raise RegistryError(f"Unknown mode in registry: {mode_id}")

    def has_mode(self, mode_id: str) -> bool:
        return any(item["id"] == mode_id for item in self.registry_items)


# ---------------------------------------------------------------------------
# Objective normalization and validation
# ---------------------------------------------------------------------------


class ObjectiveNormalizer:
    @staticmethod
    def from_payload(payload: Dict[str, Any]) -> Objective:
        if "user_request" not in payload:
            raise ObjectiveValidationError("Missing required field: user_request")

        objective_id = str(payload.get("objective_id") or f"obj-{uuid.uuid4().hex[:10]}")
        user_request = str(payload["user_request"]).strip()
        if not user_request:
            raise ObjectiveValidationError("user_request must not be empty")

        normalized = str(payload.get("normalized_objective") or user_request).strip()
        domain_tags = [str(v).strip() for v in payload.get("domain_tags", []) if str(v).strip()]
        deliverable_types = [
            str(v).strip() for v in payload.get("deliverable_types", []) if str(v).strip()
        ]

        constraints_payload = payload.get("constraints", {})
        context_payload = payload.get("context", {})
        pref_payload = payload.get("preferences", {})

        constraints = ObjectiveConstraints(
            time_sensitivity=str(constraints_payload.get("time_sensitivity", "low")),
            security_sensitivity=str(constraints_payload.get("security_sensitivity", "low")),
            performance_sensitivity=str(constraints_payload.get("performance_sensitivity", "low")),
            architecture_impact=str(constraints_payload.get("architecture_impact", "none")),
            release_impact=str(constraints_payload.get("release_impact", "none")),
            memory_required=bool(constraints_payload.get("memory_required", False)),
            audit_required=bool(constraints_payload.get("audit_required", False)),
        )
        context = ObjectiveContext(
            repo_available=bool(context_payload.get("repo_available", False)),
            artifacts_available=bool(context_payload.get("artifacts_available", False)),
            historical_memory_available=bool(
                context_payload.get("historical_memory_available", False)
            ),
            external_systems_involved=[
                str(v).strip()
                for v in context_payload.get("external_systems_involved", [])
                if str(v).strip()
            ],
        )
        preferences = ObjectivePreferences(
            prefer_fast_path=bool(pref_payload.get("prefer_fast_path", True)),
            allow_swarm=bool(pref_payload.get("allow_swarm", False)),
            require_spec_first=bool(pref_payload.get("require_spec_first", False)),
        )

        return Objective(
            objective_id=objective_id,
            user_request=user_request,
            normalized_objective=normalized,
            domain_tags=domain_tags,
            deliverable_types=deliverable_types,
            constraints=constraints,
            context=context,
            preferences=preferences,
        )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


class DimensionScorer:
    """Heuristic but deterministic dimension scorer."""

    COMPLEXITY_KEYWORDS = {
        "multi-step",
        "cross-domain",
        "integration",
        "system",
        "orchestration",
        "workflow",
        "pipeline",
        "refactor",
        "architecture",
        "deployment",
        "release",
        "distributed",
    }
    AMBIGUITY_KEYWORDS = {"improve", "optimize", "fix", "support", "enhance", "upgrade"}
    SECURITY_KEYWORDS = {
        "auth",
        "secret",
        "token",
        "credential",
        "payment",
        "user data",
        "oauth",
    }
    PERFORMANCE_KEYWORDS = {
        "latency",
        "throughput",
        "memory",
        "performance",
        "benchmark",
        "scale",
    }
    DELIVERY_KEYWORDS = {"release", "deploy", "ci", "cd", "workflow", "pr", "issue", "rollout"}

    @classmethod
    def score(cls, objective: Objective) -> RoutingDimensions:
        text = (
            f"{objective.user_request} {objective.normalized_objective} "
            f"{' '.join(objective.domain_tags)}"
        ).lower()
        external_count = len(objective.context.external_systems_involved)
        deliverable_count = len(objective.deliverable_types)
        domain_count = len(objective.domain_tags)

        complexity = 0
        complexity += 1 if deliverable_count >= 1 else 0
        complexity += 1 if deliverable_count >= 2 else 0
        complexity += 1 if domain_count >= 2 else 0
        complexity += 1 if external_count >= 1 else 0
        complexity += 1 if any(k in text for k in cls.COMPLEXITY_KEYWORDS) else 0
        complexity = min(complexity, 5)

        ambiguity = 0
        ambiguity += 1 if len(objective.normalized_objective.split()) < 8 else 0
        ambiguity += 1 if objective.preferences.require_spec_first else 0
        ambiguity += 1 if any(k in text for k in cls.AMBIGUITY_KEYWORDS) else 0
        ambiguity += 1 if not objective.domain_tags else 0
        ambiguity += 1 if not objective.deliverable_types else 0
        ambiguity = min(ambiguity, 5)

        security_risk = SENSITIVITY_MAP.get(objective.constraints.security_sensitivity, 1)
        security_risk = min(
            5,
            security_risk + (1 if any(k in text for k in cls.SECURITY_KEYWORDS) else 0),
        )

        performance_risk = SENSITIVITY_MAP.get(
            objective.constraints.performance_sensitivity, 1
        )
        performance_risk = min(
            5,
            performance_risk + (1 if any(k in text for k in cls.PERFORMANCE_KEYWORDS) else 0),
        )

        architecture_impact = ARCH_IMPACT_MAP.get(
            objective.constraints.architecture_impact, 0
        )
        if "architecture" in text or "cross-module" in text or "cross system" in text:
            architecture_impact = min(5, max(architecture_impact, 3))

        delivery_scope = RELEASE_IMPACT_MAP.get(objective.constraints.release_impact, 0)
        delivery_scope += 1 if any(k in text for k in cls.DELIVERY_KEYWORDS) else 0
        delivery_scope += 1 if "release" in objective.deliverable_types else 0
        delivery_scope = min(delivery_scope, 5)

        memory_value = 0
        memory_value += 2 if objective.constraints.memory_required else 0
        memory_value += 1 if objective.context.historical_memory_available else 0
        memory_value += 1 if "memory" in objective.deliverable_types else 0
        memory_value += 1 if objective.constraints.audit_required else 0
        memory_value = min(memory_value, 5)

        return RoutingDimensions(
            complexity=complexity,
            ambiguity=ambiguity,
            security_risk=security_risk,
            performance_risk=performance_risk,
            architecture_impact=architecture_impact,
            delivery_scope=delivery_scope,
            memory_value=memory_value,
        )


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


class RuleEvaluator:
    """Restricted expression evaluator for routing rules."""

    @staticmethod
    def evaluate(expr: str, objective: Objective, dims: RoutingDimensions) -> bool:
        expr = expr.strip()
        if expr == "always":
            return True

        if " contains " in expr:
            left, _, right = expr.partition(" contains ")
            left = left.strip()
            right = right.strip()
            if left == "deliverable_types":
                return _contains(objective.deliverable_types, right)
            raise RoutingError(f"Unsupported contains expression: {expr}")

        translated = expr.replace("== true", " is True").replace("== false", " is False")
        translated = translated.replace("constraints.memory_required", "memory_required")

        safe_locals = {
            "complexity": dims.complexity,
            "ambiguity": dims.ambiguity,
            "security_risk": dims.security_risk,
            "performance_risk": dims.performance_risk,
            "architecture_impact": dims.architecture_impact,
            "delivery_scope": dims.delivery_scope,
            "memory_value": dims.memory_value,
            "memory_required": objective.constraints.memory_required,
        }

        try:
            return bool(eval(translated, {"__builtins__": {}}, safe_locals))  # noqa: S307
        except Exception as exc:
            raise RoutingError(f"Failed to evaluate rule '{expr}': {exc}") from exc


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class RouterEngine:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def route(self, objective: Objective) -> RouteDecision:
        dims = DimensionScorer.score(objective)

        matched_rules: List[str] = []
        chosen_topology = None
        chosen_modes: List[str] = []

        for rule in self.registry.topology_rules:
            conditions = rule.get("if_all", [])
            if all(RuleEvaluator.evaluate(cond, objective, dims) for cond in conditions):
                matched_rules.append(str(rule["name"]))
                select = rule["select"]
                candidate_topology = str(select["topology"])
                if candidate_topology in {
                    "parallel_swarm",
                    "hierarchical_swarm",
                } and not objective.preferences.allow_swarm:
                    continue
                chosen_topology = candidate_topology
                chosen_modes = list(select["modes"])

        if objective.preferences.require_spec_first and "specification" not in chosen_modes:
            chosen_modes = _insert_after(chosen_modes, "research", "specification")
            matched_rules.append("preference_require_spec_first")

        if not chosen_topology:
            if objective.preferences.prefer_fast_path:
                chosen_topology = "single"
                chosen_modes = ["research", "implementation", "verification"]
                matched_rules.append("default_single_fast_path")
            else:
                chosen_topology = "pipeline"
                chosen_modes = ["research", "planner", "implementation", "verification"]
                matched_rules.append("default_pipeline")

        chosen_modes, injected_gates = self._inject_gates(chosen_modes, objective, dims)
        chosen_topology, chosen_modes, compatibility_reason = (
            self._resolve_topology_compatibility(chosen_topology, chosen_modes)
        )
        if compatibility_reason:
            matched_rules.append(compatibility_reason)
        chosen_modes = self._validate_modes(chosen_modes, chosen_topology)

        reasons = self._build_reasons(objective, dims, matched_rules, injected_gates)
        return RouteDecision(
            objective_id=objective.objective_id,
            route_id=f"route-{uuid.uuid4().hex[:10]}",
            selected_topology=chosen_topology,
            selected_modes=chosen_modes,
            injected_gates=injected_gates,
            matched_rules=matched_rules,
            routing_reason=reasons,
            dimensions=asdict(dims),
        )

    def _inject_gates(
        self,
        modes: List[str],
        objective: Objective,
        dims: RoutingDimensions,
    ) -> Tuple[List[str], List[str]]:
        injected: List[str] = []
        for gate_name, config in self.registry.gate_injection.items():
            condition = str(config.get("inject_if", ""))
            if not RuleEvaluator.evaluate(condition, objective, dims):
                continue
            if gate_name == "verification":
                modes = [m for m in modes if m != "verification"]
                modes.append("verification")
                injected.append(gate_name)
                continue
            if "insert_after" in config:
                modes = _insert_after(modes, str(config["insert_after"]), gate_name)
                injected.append(gate_name)
            elif "insert_before" in config:
                modes = _insert_before(modes, str(config["insert_before"]), gate_name)
                injected.append(gate_name)
            else:
                modes.append(gate_name)
                injected.append(gate_name)

        return _unique_preserve_order(modes), _unique_preserve_order(injected)

    def _resolve_topology_compatibility(
        self,
        topology: str,
        modes: List[str],
    ) -> Tuple[str, List[str], Optional[str]]:
        topology_specific_modes = {
            "swarm_coordination": {"parallel_swarm", "hierarchical_swarm"}
        }

        def normalize_modes_for_candidate(candidate_topology: str) -> List[str]:
            normalized_modes: List[str] = []
            for mode in modes:
                if (
                    mode in topology_specific_modes
                    and candidate_topology not in topology_specific_modes[mode]
                ):
                    continue
                normalized_modes.append(mode)
            return normalized_modes

        def supports(candidate_topology: str, candidate_modes: List[str]) -> bool:
            return all(
                candidate_topology in self.registry.get_mode(mode).get("topology_support", [])
                for mode in candidate_modes
            )

        current_modes = normalize_modes_for_candidate(topology)
        if supports(topology, current_modes):
            return topology, current_modes, None

        fallback_order: List[str] = []
        if topology in {"parallel_swarm", "hierarchical_swarm"}:
            fallback_order = ["pipeline", "single"]
        elif topology == "pipeline":
            fallback_order = ["single"]

        for candidate in fallback_order:
            candidate_modes = normalize_modes_for_candidate(candidate)
            if supports(candidate, candidate_modes):
                return (
                    topology if candidate == topology else candidate,
                    candidate_modes,
                    f"topology_downgrade_to_{candidate}",
                )

        raise RoutingError(
            f"No compatible topology found for modes {modes!r} "
            f"starting from topology {topology!r}"
        )

    def _validate_modes(self, modes: List[str], topology: str) -> List[str]:
        validated: List[str] = []
        for mode in modes:
            if not self.registry.has_mode(mode):
                raise RoutingError(f"Route selected unknown mode: {mode}")
            entry = self.registry.get_mode(mode)
            if topology not in entry.get("topology_support", []):
                raise RoutingError(f"Mode '{mode}' does not support topology '{topology}'")
            validated.append(mode)
        return validated

    @staticmethod
    def _build_reasons(
        objective: Objective,
        dims: RoutingDimensions,
        matched_rules: List[str],
        injected_gates: List[str],
    ) -> List[str]:
        reasons = [
            f"complexity={dims.complexity}",
            f"ambiguity={dims.ambiguity}",
            f"security_risk={dims.security_risk}",
            f"performance_risk={dims.performance_risk}",
            f"architecture_impact={dims.architecture_impact}",
            f"delivery_scope={dims.delivery_scope}",
            f"memory_value={dims.memory_value}",
        ]
        reasons.extend([f"matched:{r}" for r in matched_rules])
        reasons.extend([f"injected:{g}" for g in injected_gates])
        if objective.preferences.allow_swarm:
            reasons.append("preference:allow_swarm")
        if objective.preferences.require_spec_first:
            reasons.append("preference:require_spec_first")
        return reasons


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class OrchestrationStateMachine:
    LEGAL = {
        "intake": {"normalized"},
        "normalized": {"classified"},
        "classified": {"routed"},
        "routed": {"executing"},
        "executing": {"waiting_handoff", "blocked", "verifying"},
        "waiting_handoff": {"executing"},
        "blocked": {"reroute_required", "failed"},
        "reroute_required": {"routed"},
        "verifying": {"persistence", "blocked"},
        "persistence": {"completed"},
        "completed": set(),
        "failed": set(),
    }

    def __init__(self) -> None:
        self.state = "intake"
        self.history = [self.state]

    def transition(self, next_state: str) -> None:
        legal_targets = self.LEGAL.get(self.state, set())
        if next_state not in legal_targets:
            raise RoutingError(f"Illegal state transition: {self.state} -> {next_state}")
        self.state = next_state
        self.history.append(self.state)


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


class ModeRunner(Protocol):
    def run(
        self,
        mode_id: str,
        objective: Objective,
        route: RouteDecision,
        prior_results: Sequence[ModeResult],
    ) -> ModeResult: ...


class DefaultModeRunner:
    """
    Safe default runner.
    It does not perform real side effects. It emits structured placeholders that
    can later be swapped with specialized runners per mode.
    """

    def run(
        self,
        mode_id: str,
        objective: Objective,
        route: RouteDecision,
        prior_results: Sequence[ModeResult],
    ) -> ModeResult:
        summary = (
            f"{mode_id} completed in skeleton mode "
            f"for objective '{objective.objective_id}'."
        )
        findings = [f"{mode_id}: placeholder output generated"]
        decisions: list[str] = []
        blockers: List[str] = []
        artifacts: List[str] = []

        if mode_id == "research":
            findings = [
                "Research skeleton executed.",
                f"Objective normalized as: {objective.normalized_objective}",
            ]
            decisions = ["Proceed based on routed topology."]
        elif mode_id == "specification":
            findings = ["Acceptance criteria should be formalized."]
            decisions = ["Scope should remain aligned to normalized objective."]
        elif mode_id == "architecture":
            findings = ["Architecture review suggested for cross-module impacts."]
            decisions = [
                "Component contracts should be finalized before deep implementation."
            ]
        elif mode_id == "implementation":
            findings = [
                "Implementation skeleton executed; "
                "no file mutation performed by default runner."
            ]
            decisions = [
                "Replace DefaultModeRunner with project-specific implementation runner."
            ]
        elif mode_id == "review":
            findings = ["Review skeleton found no concrete artifacts to inspect."]
        elif mode_id == "test":
            findings = ["Test skeleton recommends contract tests + regression coverage."]
        elif mode_id == "security":
            findings = ["Security gate skeleton executed."]
            if objective.constraints.security_sensitivity == "high":
                decisions.append("Security specialist review required before ship.")
        elif mode_id == "performance":
            findings = ["Performance gate skeleton executed."]
            if objective.constraints.performance_sensitivity == "high":
                decisions.append("Benchmark hot paths before ship.")
        elif mode_id == "memory_learning":
            findings = ["Memory writeback requested."]
        elif mode_id == "verification":
            findings = [
                "Verification should be executed by VerificationSink, "
                "not DefaultModeRunner."
            ]
        elif mode_id == "swarm_coordination":
            findings = [
                "Swarm topology should assign specialists and synthesis path."
            ]
        elif mode_id == "github_release":
            findings = [
                "Release checklist should be derived from review/test/verification outputs."
            ]
        elif mode_id == "platform_ops":
            findings = [
                "Operational runbook should be prepared for affected environments."
            ]

        return ModeResult(
            mode=mode_id,
            status="success",
            summary=summary,
            artifacts=artifacts,
            findings=findings,
            decisions=decisions,
            blockers=blockers,
            outputs={
                "objective_id": objective.objective_id,
                "route_id": route.route_id,
                "mode_id": mode_id,
            },
        )


# ---------------------------------------------------------------------------
# Verification and memory adapters
# ---------------------------------------------------------------------------


class VerificationSink:
    def verify(
        self,
        objective: Objective,
        route: RouteDecision,
        results: Sequence[ModeResult],
    ) -> VerificationResult:
        blockers: List[str] = []
        statuses = {result.mode: result.status for result in results}
        has_code = "code" in objective.deliverable_types

        checks = {
            "clarity": "pass" if objective.normalized_objective else "fail",
            "completeness": "pass" if results else "fail",
            "consistency": "pass",
            "security": "not_applicable",
            "performance": "not_applicable",
            "evidence": "pass" if not has_code or "test" in statuses else "warn",
        }

        if objective.constraints.security_sensitivity in {"medium", "high"}:
            checks["security"] = "pass" if "security" in statuses else "warn"
        if objective.constraints.performance_sensitivity in {"medium", "high"}:
            checks["performance"] = "pass" if "performance" in statuses else "warn"

        for result in results:
            if result.status in {"blocked", "failed"}:
                blockers.extend(
                    result.blockers or [f"{result.mode} reported {result.status}"]
                )

        overall = "pass"
        if blockers or any(v == "fail" for v in checks.values()):
            overall = "fail"
        elif any(v == "warn" for v in checks.values()):
            overall = "warn"

        confidence = (
            0.92 if overall == "pass" else 0.75 if overall == "warn" else 0.35
        )
        ship = (
            "ship"
            if overall == "pass"
            else "ship_with_caveats"
            if overall == "warn"
            else "do_not_ship"
        )
        return VerificationResult(
            checks=checks,
            overall_verdict=overall,
            blockers=_unique_preserve_order(blockers),
            confidence=confidence,
            ship_recommendation=ship,
        )


class MemoryAdapter:
    def writeback(
        self,
        objective: Objective,
        route: RouteDecision,
        results: Sequence[ModeResult],
        verification: VerificationResult,
    ) -> Dict[str, Any]:
        namespaces = [
            f"coordination/{route.route_id}",
            f"verification/{route.route_id}",
        ]
        if objective.domain_tags:
            namespaces.extend([f"project/{tag}" for tag in objective.domain_tags[:2]])
        stored_items = [
            "normalized_objective",
            "selected_topology",
            "selected_modes",
            "verification_verdict",
        ]
        return {
            "writeback_status": "written",
            "namespaces": _unique_preserve_order(namespaces),
            "stored_items": stored_items,
        }


# ---------------------------------------------------------------------------
# Orchestration engine
# ---------------------------------------------------------------------------


class OrchestrationEngine:
    def __init__(
        self,
        registry: Registry,
        router: Optional[RouterEngine] = None,
        mode_runner: Optional[ModeRunner] = None,
        verification_sink: Optional[VerificationSink] = None,
        memory_adapter: Optional[MemoryAdapter] = None,
    ) -> None:
        self.registry = registry
        self.router = router or RouterEngine(registry)
        self.mode_runner = mode_runner or DefaultModeRunner()
        self.verification_sink = verification_sink or VerificationSink()
        self.memory_adapter = memory_adapter or MemoryAdapter()

    def route_only(self, objective: Objective) -> RouteDecision:
        return self.router.route(objective)

    def execute(self, objective: Objective) -> OrchestrationResult:
        sm = OrchestrationStateMachine()
        sm.transition("normalized")
        sm.transition("classified")
        route = self.router.route(objective)
        sm.transition("routed")
        sm.transition("executing")

        results: List[ModeResult] = []
        verification: Optional[VerificationResult] = None
        memory_payload: Dict[str, Any] = {
            "writeback_status": "pending",
            "namespaces": [],
            "stored_items": [],
        }

        for idx, mode_id in enumerate(route.selected_modes):
            if mode_id == "verification":
                continue

            result = self.mode_runner.run(mode_id, objective, route, results)
            results.append(result)

            if result.status in {"blocked", "failed"}:
                sm.transition("blocked")
                sm.transition("failed")
                verification = VerificationResult(
                    checks={
                        "clarity": "pass",
                        "completeness": "fail",
                        "consistency": "warn",
                        "security": "not_applicable",
                        "performance": "not_applicable",
                        "evidence": "fail",
                    },
                    overall_verdict="fail",
                    blockers=result.blockers or [f"{mode_id} blocked execution"],
                    confidence=0.2,
                    ship_recommendation="do_not_ship",
                )
                return self._build_result(
                    objective,
                    route,
                    results,
                    verification,
                    memory_payload,
                    sm.history,
                    execution_status="blocked",
                )

            if idx < len(route.selected_modes) - 1:
                sm.transition("waiting_handoff")
                sm.transition("executing")

        sm.transition("verifying")
        verification = self.verification_sink.verify(objective, route, results)
        if verification.overall_verdict == "fail":
            sm.transition("blocked")
            sm.transition("failed")
            return self._build_result(
                objective,
                route,
                results,
                verification,
                memory_payload,
                sm.history,
                execution_status="failed",
            )

        sm.transition("persistence")
        memory_payload = self.memory_adapter.writeback(
            objective, route, results, verification
        )
        sm.transition("completed")
        return self._build_result(
            objective,
            route,
            results,
            verification,
            memory_payload,
            sm.history,
            execution_status=(
                "success" if verification.overall_verdict == "pass" else "partial"
            ),
        )

    @staticmethod
    def _build_result(
        objective: Objective,
        route: RouteDecision,
        results: Sequence[ModeResult],
        verification: VerificationResult,
        memory_payload: Dict[str, Any],
        state_history: Sequence[str],
        execution_status: str,
    ) -> OrchestrationResult:
        artifacts: List[str] = []
        tests: List[str] = []
        issues: List[str] = []
        changed_files: List[str] = []

        for result in results:
            artifacts.extend(result.artifacts)
            if result.mode == "test":
                tests.extend(result.findings)
            issues.extend(result.blockers)

        governance = {
            "security_review_required": "security" in route.selected_modes,
            "performance_review_required": "performance" in route.selected_modes,
            "verification_status": verification.overall_verdict,
            "blockers": _unique_preserve_order(verification.blockers + issues),
        }

        next_actions: List[str] = []
        if verification.overall_verdict == "warn":
            next_actions.append(
                "Resolve verification warnings before production rollout."
            )
        elif verification.overall_verdict == "fail":
            next_actions.append("Resolve blockers before re-routing or publish.")
        else:
            next_actions.append(
                "Swap skeleton runners with real project-specific mode runners."
            )

        return OrchestrationResult(
            objective_id=objective.objective_id,
            route_id=route.route_id,
            selected_topology=route.selected_topology,
            selected_modes=route.selected_modes,
            execution_status=execution_status,
            deliverables={
                "summaries": [r.summary for r in results],
                "artifacts": _unique_preserve_order(artifacts),
                "changed_files": _unique_preserve_order(changed_files),
                "tests": _unique_preserve_order(tests),
                "issues": _unique_preserve_order(issues),
            },
            governance=governance,
            memory=memory_payload,
            next_actions=next_actions,
            mode_results=[asdict(r) for r in results],
            verification=asdict(verification),
            state_history=list(state_history),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ultimate Agent Router Engine skeleton."
    )
    parser.add_argument(
        "--registry", type=Path, required=True, help="Path to registry.json"
    )
    parser.add_argument(
        "--objective", type=Path, required=True, help="Path to objective JSON"
    )
    parser.add_argument("--out", type=Path, help="Optional output JSON path")
    parser.add_argument(
        "--route-only",
        action="store_true",
        help="Emit route decision without execution",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print JSON output"
    )
    return parser.parse_args()


def _serialize(data: Any, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(data, indent=2)
    return json.dumps(data)


def main() -> None:
    args = _parse_args()
    registry = Registry.from_path(args.registry)
    objective_payload = _safe_json_load(args.objective)
    objective = ObjectiveNormalizer.from_payload(objective_payload)

    engine = OrchestrationEngine(registry=registry)

    if args.route_only:
        result = asdict(engine.route_only(objective))
    else:
        result = asdict(engine.execute(objective))

    serialized = _serialize(result, pretty=args.pretty)
    if args.out:
        args.out.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)  # noqa: T201


if __name__ == "__main__":
    main()
