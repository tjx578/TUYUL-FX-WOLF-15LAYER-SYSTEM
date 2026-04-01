from __future__ import annotations

"""
Gate Penalty Engine — Soft-penalty scoring + adaptive sizing + navigation-weighted confidence.

Converts the former binary hard-reject model for soft gates into a graduated
penalty system:

    HARD gates  → immediate NO_TRADE (unchanged: FOUNDATION, STRUCTURE, RISK_CHAIN, FIREWALL)
    SOFT gates  → confidence penalty + sizing multiplier reduction
    ADVISORY    → minimal penalty, warning only

Constitutional boundaries preserved:
    - L12 remains sole verdict authority
    - Sizing multiplier is ADVISORY — dashboard/risk zone makes final lot decision
    - No account state enters L12 signal
    - Hard gates remain absolute
"""

from dataclasses import dataclass  # noqa: E402
from enum import Enum  # noqa: E402

# ── Gate tier classification ──────────────────────────────────────────────────


class GateTier(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"


class GateStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


# ── Gate penalty config ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class GatePenaltyConfig:
    """Penalty parameters for a single gate.

    Attributes:
        tier: HARD / SOFT / ADVISORY classification.
        fail_penalty: Confidence penalty on FAIL (subtracted from score).
        warn_penalty: Confidence penalty on WARN (typically half of fail_penalty).
        fail_sizing_factor: Sizing multiplier on FAIL (e.g. 0.50 = halve size).
        warn_sizing_factor: Sizing multiplier on WARN (e.g. 0.80).
    """

    tier: GateTier
    fail_penalty: float = 0.0
    warn_penalty: float = 0.0
    fail_sizing_factor: float = 1.0
    warn_sizing_factor: float = 1.0


# ── Default 9-gate penalty registry ─────────────────────────────────────────


GATE_PENALTY_REGISTRY: dict[str, GatePenaltyConfig] = {
    # HARD gates — no penalty math, they veto directly
    "FOUNDATION_OK": GatePenaltyConfig(tier=GateTier.HARD),
    "STRUCTURE_OK": GatePenaltyConfig(tier=GateTier.HARD),
    "RISK_CHAIN_OK": GatePenaltyConfig(tier=GateTier.HARD),
    "FIREWALL_OK": GatePenaltyConfig(tier=GateTier.HARD),
    # SOFT gates — graduated penalty
    "SCORING_OK": GatePenaltyConfig(
        tier=GateTier.SOFT,
        fail_penalty=0.12,
        warn_penalty=0.06,
        fail_sizing_factor=0.60,
        warn_sizing_factor=0.85,
    ),
    "INTEGRITY_OK": GatePenaltyConfig(
        tier=GateTier.SOFT,
        fail_penalty=0.15,
        warn_penalty=0.07,
        fail_sizing_factor=0.50,
        warn_sizing_factor=0.80,
    ),
    "PROBABILITY_OK": GatePenaltyConfig(
        tier=GateTier.SOFT,
        fail_penalty=0.10,
        warn_penalty=0.05,
        fail_sizing_factor=0.65,
        warn_sizing_factor=0.85,
    ),
    "GOVERNANCE_OK": GatePenaltyConfig(
        tier=GateTier.SOFT,
        fail_penalty=0.08,
        warn_penalty=0.04,
        fail_sizing_factor=0.75,
        warn_sizing_factor=0.90,
    ),
    # ADVISORY gate — minimal
    "ENRICHMENT_OK": GatePenaltyConfig(
        tier=GateTier.ADVISORY,
        fail_penalty=0.03,
        warn_penalty=0.01,
        fail_sizing_factor=0.90,
        warn_sizing_factor=0.95,
    ),
}


# ── Navigation-weighted confidence ───────────────────────────────────────────


NAVIGATION_WEIGHTS: dict[str, float] = {
    "L1": 0.10,   # Context / regime
    "L2": 0.12,   # Multi-timeframe alignment
    "L3": 0.12,   # Trend confirmation
    "L4": 0.08,   # Session scoring
    "L5": 0.06,   # Psychology / discipline
    "L7": 0.12,   # Probability / Monte Carlo
    "L8": 0.10,   # Integrity / TII
    "L9": 0.12,   # SMC / entry timing
    "L11": 0.10,  # Risk-reward structure
    "L6": 0.08,   # Risk firewall
}


# ── Result contracts ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GatePenaltyResult:
    """Penalty evaluation for a single gate."""

    gate: str
    tier: str
    status: str
    confidence_penalty: float
    sizing_factor: float
    is_hard_veto: bool


@dataclass(frozen=True)
class PenaltyEngineResult:
    """Aggregate result from the penalty engine.

    Attributes:
        raw_confidence: Navigation-weighted confidence before penalties.
        penalized_confidence: Confidence after soft-gate penalties applied.
        sizing_multiplier: Product of all sizing factors [0.0, 1.0].
        hard_veto: True if any hard gate failed.
        hard_veto_gates: List of hard gate names that failed.
        gate_penalties: Per-gate penalty details.
        soft_fail_count: Number of soft gates in FAIL state.
        soft_warn_count: Number of soft gates in WARN state.
        penalty_breakdown: Human-readable penalty audit trail.
    """

    raw_confidence: float
    penalized_confidence: float
    sizing_multiplier: float
    hard_veto: bool
    hard_veto_gates: list[str]
    gate_penalties: list[GatePenaltyResult]
    soft_fail_count: int
    soft_warn_count: int
    penalty_breakdown: list[str]


# ── Penalty Engine ───────────────────────────────────────────────────────────


class GatePenaltyEngine:
    """Evaluates gate statuses into graduated penalties and sizing multipliers.

    Constitutional invariants:
        - HARD gates produce immediate veto (NO_TRADE)
        - SOFT gate failures degrade confidence + sizing, never veto
        - ADVISORY gate failures produce minimal degradation
        - Sizing multiplier is advisory — dashboard/risk zone decides final lot
        - Navigation weights sum to 1.0 and are score-only (no account state)
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        registry: dict[str, GatePenaltyConfig] | None = None,
        nav_weights: dict[str, float] | None = None,
    ) -> None:
        self._registry = registry or dict(GATE_PENALTY_REGISTRY)
        self._nav_weights = nav_weights or dict(NAVIGATION_WEIGHTS)

    def compute_navigation_confidence(
        self,
        layer_scores: dict[str, float],
    ) -> float:
        """Compute navigation-weighted confidence from layer scores.

        Layers with higher structural/timing relevance get more weight.
        Missing layers use weight 0 and their weight is redistributed.

        Returns:
            Weighted confidence in [0.0, 1.0].
        """
        total_weight = 0.0
        weighted_sum = 0.0

        for layer, weight in self._nav_weights.items():
            score = layer_scores.get(layer)
            if score is not None and isinstance(score, (int, float)):
                weighted_sum += float(score) * weight
                total_weight += weight

        if total_weight <= 0.0:
            return 0.0

        return round(min(max(weighted_sum / total_weight, 0.0), 1.0), 6)

    def evaluate_gate_penalties(
        self,
        gate_summary: dict[str, str],
    ) -> tuple[float, float, list[GatePenaltyResult], list[str]]:
        """Evaluate all gates and compute aggregate penalty + sizing.

        Args:
            gate_summary: {gate_name: "PASS"|"WARN"|"FAIL"} for all 9 gates.

        Returns:
            Tuple of:
                total_penalty: Sum of confidence penalties.
                sizing_multiplier: Product of sizing factors [0.0, 1.0].
                gate_results: Per-gate penalty results.
                breakdown: Audit trail strings.
        """
        total_penalty = 0.0
        sizing_multiplier = 1.0
        gate_results: list[GatePenaltyResult] = []
        breakdown: list[str] = []

        for gate_name, status_str in gate_summary.items():
            config = self._registry.get(gate_name)
            if config is None:
                continue

            status = status_str.upper().strip()
            penalty = 0.0
            sizing = 1.0
            is_hard_veto = False

            if status == "FAIL":
                if config.tier == GateTier.HARD:
                    is_hard_veto = True
                    breakdown.append(f"{gate_name}=FAIL -> HARD_VETO")
                else:
                    penalty = config.fail_penalty
                    sizing = config.fail_sizing_factor
                    breakdown.append(
                        f"{gate_name}=FAIL -> penalty={penalty:.2f}, sizing×{sizing:.2f}"
                    )
            elif status == "WARN":
                penalty = config.warn_penalty
                sizing = config.warn_sizing_factor
                if penalty > 0.0:
                    breakdown.append(
                        f"{gate_name}=WARN -> penalty={penalty:.2f}, sizing×{sizing:.2f}"
                    )

            total_penalty += penalty
            sizing_multiplier *= sizing

            gate_results.append(
                GatePenaltyResult(
                    gate=gate_name,
                    tier=config.tier.value,
                    status=status,
                    confidence_penalty=penalty,
                    sizing_factor=sizing,
                    is_hard_veto=is_hard_veto,
                )
            )

        sizing_multiplier = round(max(sizing_multiplier, 0.0), 6)
        total_penalty = round(total_penalty, 6)

        return total_penalty, sizing_multiplier, gate_results, breakdown

    def evaluate(
        self,
        gate_summary: dict[str, str],
        layer_scores: dict[str, float],
    ) -> PenaltyEngineResult:
        """Full penalty evaluation: navigation confidence + gate penalties.

        Args:
            gate_summary: 9-gate status map.
            layer_scores: Per-layer numeric scores.

        Returns:
            PenaltyEngineResult with all metrics.
        """
        raw_confidence = self.compute_navigation_confidence(layer_scores)

        total_penalty, sizing_multiplier, gate_results, breakdown = (
            self.evaluate_gate_penalties(gate_summary)
        )

        penalized = round(max(raw_confidence - total_penalty, 0.0), 6)

        hard_veto_gates = [g.gate for g in gate_results if g.is_hard_veto]
        soft_fail_count = sum(
            1 for g in gate_results
            if g.tier == GateTier.SOFT.value and g.status == "FAIL"
        )
        soft_warn_count = sum(
            1 for g in gate_results
            if g.tier == GateTier.SOFT.value and g.status == "WARN"
        )

        return PenaltyEngineResult(
            raw_confidence=raw_confidence,
            penalized_confidence=penalized,
            sizing_multiplier=sizing_multiplier,
            hard_veto=bool(hard_veto_gates),
            hard_veto_gates=hard_veto_gates,
            gate_penalties=gate_results,
            soft_fail_count=soft_fail_count,
            soft_warn_count=soft_warn_count,
            penalty_breakdown=breakdown,
        )
