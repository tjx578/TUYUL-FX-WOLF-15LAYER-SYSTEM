
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Data contracts ────────────────────────────────────────────────────────────

@dataclass
class VerdictThresholds:
    """Constitutional score thresholds for the evaluate() V1 path."""
    wolf_min_score: float = 0.70
    tii_min_score: float = 0.90
    frpc_min_score: float = 0.93
    exhaustion_min_confidence: float = 0.70
    exhaustion_min_score: float = 0.65


@dataclass
class ExhaustionLayerInput:
    """L7 exhaustion data passed into the constitutional evaluate() gate."""
    score: float
    confidence: float
    reason: str = ""
    missing_tfs: list[str] = field(default_factory=list)


# ── Pure gate functions (used by layer pipeline) ──────────────────────────────

def meta_gate_structural_edge(exhaustion_conf: float, liquidity: float) -> bool:
    return min(exhaustion_conf, liquidity) >= 0.70


def meta_gate_model_integrity(tii: float, frpc: float, integrity: float, thresholds: dict[str, float]) -> str:
    pass_all = tii >= thresholds["tii"] and frpc >= thresholds["frpc"] and integrity >= thresholds["integrity"]
    conditional = (
        (thresholds["tii"] - 0.03 <= tii < thresholds["tii"])
        or (thresholds["frpc"] - 0.03 <= frpc < thresholds["frpc"])
        or (thresholds["integrity"] - 0.02 <= integrity < thresholds["integrity"])
    )
    if pass_all:
        return "PASS"
    elif conditional:
        return "CONDITIONAL"
    return "FAIL"


def meta_gate_statistical_edge(mc_win: float, mc_pf: float, rr: float, posterior: float, thresholds: dict[str, float]) -> bool:
    return (
        mc_win >= thresholds["mc_win"]
        and mc_pf >= thresholds["mc_pf"]
        and rr >= thresholds["rr"]
        and posterior >= thresholds["posterior"]
    )


def layer12_verdict_layer(meta_results: dict[str, str]) -> str:
    pass_count = sum(1 for v in meta_results.values() if v == "PASS")
    conditional_count = sum(1 for v in meta_results.values() if v == "CONDITIONAL")
    if pass_count == 3:
        return "EXECUTE"
    elif pass_count == 2 and conditional_count == 1:
        return "EXECUTE_REDUCED_RISK"
    return "HOLD"


# ── VerdictEngine: sole constitutional authority (Layer 12) ───────────────────

class VerdictEngine:
    """
    Constitutional verdict authority — Layer 12.

    This is the SOLE decision-making authority for the entire system.
    No other module may produce or override verdicts.

    Methods:
        evaluate()                  — V1 path: score-based gate evaluation.
        produce_verdict()           — V2 path: full layer/gate integration.
        _evaluate_kelly_edge_gate() — Gate 11: Kelly statistical-edge guard.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        thresholds: VerdictThresholds | None = None,
    ) -> None:
        self.config: dict[str, Any] = config or {}
        self.thresholds: VerdictThresholds = thresholds or VerdictThresholds()
        self._kelly_gate_enabled: bool = bool(self.config.get("kelly_edge_gate_enabled", True))

    # ── V1 path: direct score evaluation ─────────────────────────────────────

    def evaluate(
        self,
        wolf_score: float,
        tii_score: float,
        frpc_score: float,
        exhaustion_input: ExhaustionLayerInput | None = None,
    ) -> dict[str, Any]:
        """
        Constitutional verdict evaluation from raw gate scores.

        Returns:
            {
                "verdict": "EXECUTE" | "HOLD" | "NO_TRADE" | "ABORT",
                "confidence": float,
                "reason": str,
                "gate_results": dict,  # Per-layer pass/fail
            }
        """
        gate_results: dict[str, Any] = {}
        rejection_reasons: list[str] = []

        # Gate 1: Wolf (L1–L6 fusion)
        wolf_pass = wolf_score >= self.thresholds.wolf_min_score
        gate_results["wolf"] = {
            "pass": wolf_pass,
            "score": wolf_score,
            "threshold": self.thresholds.wolf_min_score,
        }
        if not wolf_pass:
            rejection_reasons.append(f"WOLF_WEAK: {wolf_score:.2f} < {self.thresholds.wolf_min_score}")

        # Gate 2: TII (L8)
        tii_pass = tii_score >= self.thresholds.tii_min_score
        gate_results["tii"] = {
            "pass": tii_pass,
            "score": tii_score,
            "threshold": self.thresholds.tii_min_score,
        }
        if not tii_pass:
            rejection_reasons.append(f"TII_WEAK: {tii_score:.2f} < {self.thresholds.tii_min_score}")

        # Gate 3: FRPC (L9)
        frpc_pass = frpc_score >= self.thresholds.frpc_min_score
        gate_results["frpc"] = {
            "pass": frpc_pass,
            "score": frpc_score,
            "threshold": self.thresholds.frpc_min_score,
        }
        if not frpc_pass:
            rejection_reasons.append(f"FRPC_WEAK: {frpc_score:.2f} < {self.thresholds.frpc_min_score}")

        # Gate 4: Exhaustion (L7)
        exhaustion_pass = True  # Optional gate — skipped if input not provided
        if exhaustion_input:
            # Data-availability hard check first
            if exhaustion_input.missing_tfs:
                gate_results["exhaustion"] = {
                    "pass": False,
                    "score": 0.0,
                    "confidence": 0.0,
                    "abort_reason": f"INSUFFICIENT_DATA: Missing {exhaustion_input.missing_tfs}",
                }
                return {
                    "verdict": "ABORT",
                    "confidence": 0.0,
                    "reason": f"EXHAUSTION_DATA_UNAVAILABLE: {', '.join(exhaustion_input.missing_tfs)}",
                    "gate_results": gate_results,
                }

            exhaustion_pass = (
                exhaustion_input.confidence >= self.thresholds.exhaustion_min_confidence
                and exhaustion_input.score >= self.thresholds.exhaustion_min_score
            )
            gate_results["exhaustion"] = {
                "pass": exhaustion_pass,
                "score": exhaustion_input.score,
                "confidence": exhaustion_input.confidence,
                "threshold_confidence": self.thresholds.exhaustion_min_confidence,
                "threshold_score": self.thresholds.exhaustion_min_score,
                "reason": exhaustion_input.reason,
            }
            if not exhaustion_pass:
                rejection_reasons.append(
                    f"EXHAUSTION_WEAK: conf={exhaustion_input.confidence:.2f} < {self.thresholds.exhaustion_min_confidence} "
                    f"or score={exhaustion_input.score:.2f} < {self.thresholds.exhaustion_min_score}"
                )

        all_gates_pass = wolf_pass and tii_pass and frpc_pass and exhaustion_pass

        if all_gates_pass:
            weights = {"wolf": 0.3, "tii": 0.25, "frpc": 0.25, "exhaustion": 0.2}
            overall_confidence = (
                wolf_score * weights["wolf"]
                + tii_score * weights["tii"]
                + frpc_score * weights["frpc"]
                + (exhaustion_input.score if exhaustion_input else 0.0) * weights["exhaustion"]
            )
            return {
                "verdict": "EXECUTE",
                "confidence": round(overall_confidence, 3),
                "reason": "ALL_GATES_PASSED",
                "gate_results": gate_results,
            }

        if rejection_reasons:
            return {
                "verdict": "NO_TRADE",
                "confidence": 0.0,
                "reason": " | ".join(rejection_reasons),
                "gate_results": gate_results,
            }

        # Fallback (should not reach here in normal operation)
        return {
            "verdict": "HOLD",
            "confidence": 0.0,
            "reason": "EVALUATION_INCOMPLETE",
            "gate_results": gate_results,
        }

    # ── Gate 11: Kelly statistical-edge guard ────────────────────────────────

    def _evaluate_kelly_edge_gate(self, kelly_edge_data: dict[str, Any]) -> dict[str, Any]:
        """
        Gate 11: Kelly Edge Guard.

        Blocks execution when there is no positive statistical edge
        (kelly_raw ≤ 0). This is a purely mathematical constitutional gate —
        it does NOT reference market direction or signal content.

        Args:
            kelly_edge_data: dict with optional keys:
                edge_negative (bool, default False),
                kelly_raw (float, default 0.0),
                final_fraction (float, default 0.0).

        Returns:
            Gate result dict: gate, passed, severity, reason,
            kelly_raw, final_fraction.
        """
        edge_negative: bool = kelly_edge_data.get("edge_negative", False)
        kelly_raw: float = kelly_edge_data.get("kelly_raw", 0.0)
        final_fraction: float = kelly_edge_data.get("final_fraction", 0.0)

        if edge_negative:
            return {
                "gate": "GATE_11_KELLY_EDGE",
                "passed": False,
                "severity": "HARD_BLOCK",
                "reason": f"No statistical edge: kelly_raw={kelly_raw:.4f} \u2264 0",
                "kelly_raw": kelly_raw,
                "final_fraction": final_fraction,
            }
        return {
            "gate": "GATE_11_KELLY_EDGE",
            "passed": True,
            "severity": "NONE",
            "reason": "Positive Kelly edge confirmed",
            "kelly_raw": kelly_raw,
            "final_fraction": final_fraction,
        }

    # ── V2 path: full layer + gate integration ────────────────────────────────

    def produce_verdict(
        self,
        symbol: str,
        layer_results: dict[str, Any],
        gates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Full constitutional verdict from layer results and gate evaluations.

        Authority rule: enrichment scores may modulate *confidence* but
        CANNOT promote a HOLD/NO_TRADE verdict to EXECUTE.

        Args:
            symbol: Trading pair symbol.
            layer_results: Dict of layer outputs. May include L7 data,
                enrichment_score, enrichment_confidence_adj, kelly_edge_data.
            gates: Dict of gate results, each with a 'passed' bool and 'score'.

        Returns:
            {
                "verdict": "EXECUTE" | "NO_TRADE",
                "confidence": float,
                "symbol": str,
                "enrichment_applied": bool,
                "enrichment_context": dict,
                "gate_summary": dict,
            }
        """
        # Inject Gate 11 if enabled and data is present
        kelly_gate_result: dict[str, Any] | None = None
        kelly_edge_data = layer_results.get("kelly_edge_data")
        if self._kelly_gate_enabled and kelly_edge_data is not None:
            kelly_gate_result = self._evaluate_kelly_edge_gate(kelly_edge_data)
            gates = dict(gates)  # avoid mutating caller's dict
            gates["gate_11_kelly"] = kelly_gate_result

        # Gate pass ratio → base verdict
        total_gates = len(gates)
        passed_gates = sum(1 for g in gates.values() if g.get("passed", False))
        pass_ratio = passed_gates / total_gates if total_gates > 0 else 0.0

        base_verdict = "EXECUTE" if pass_ratio >= 1.0 else "NO_TRADE"

        # L7 base confidence
        l7: dict[str, Any] = layer_results.get("L7", {})
        base_conf = float(l7.get("conf12_raw", pass_ratio))
        if l7.get("mc_passed_threshold"):
            mc_win = l7.get("win_probability", 50.0) / 100.0
            base_conf = max(base_conf, mc_win)

        # Enrichment: modulates confidence only — cannot change verdict
        enrichment_score: float = float(layer_results.get("enrichment_score", 0.0))
        enrichment_confidence_adj: float = float(layer_results.get("enrichment_confidence_adj", 0.0))
        enrichment_applied = enrichment_score > 0.0 or enrichment_confidence_adj != 0.0

        if enrichment_applied:
            adjusted_conf = base_conf * 0.7 + enrichment_score * 0.3 + enrichment_confidence_adj
            adjusted_conf = max(0.0, min(1.0, adjusted_conf))
        else:
            adjusted_conf = base_conf

        # Kelly gate hard block overrides EXECUTE → NO_TRADE
        if kelly_gate_result and not kelly_gate_result.get("passed", True):
            base_verdict = "NO_TRADE"

        return {
            "verdict": base_verdict,
            "confidence": round(adjusted_conf, 4),
            "symbol": symbol,
            "enrichment_applied": enrichment_applied,
            "enrichment_context": {
                "enrichment_score": enrichment_score,
                "enrichment_confidence_adj": enrichment_confidence_adj,
            },
            "gate_summary": {
                "total": total_gates,
                "passed": passed_gates,
                "pass_ratio": round(pass_ratio, 4),
            },
        }


# ── Standalone helper (no account params — authority boundary) ────────────────

def compute_verdict(
    wolf_score: float,
    tii_score: float,
    frpc_score: float,
    exhaustion_input: ExhaustionLayerInput | None = None,
    thresholds: VerdictThresholds | None = None,
) -> dict[str, Any]:
    """
    Stateless constitutional verdict function.

    Must NOT accept account-state parameters (balance, equity, account).
    Authority boundary: this is a pure constitutional gate with no
    market-direction logic.
    """
    engine = VerdictEngine(thresholds=thresholds)
    return engine.evaluate(wolf_score, tii_score, frpc_score, exhaustion_input)
