from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from config.constitution import CONSTITUTION_THRESHOLDS
from constitution.violation_log import log_violation


def _gate(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def generate_l12_verdict(synthesis: Dict[str, Any]) -> Dict[str, Any]:
    """
    Input: synthesis output from analysis.synthesis (L1-L11).
    Output: final L12 verdict (constitutional).
    """

    try:
        scores = synthesis["scores"]
        layers = synthesis["layers"]
        execution = synthesis["execution"]
        propfirm = synthesis["propfirm"]
        risk = synthesis["risk"]
        bias = synthesis["bias"]
    except KeyError as exc:
        raise ValueError(f"L12 ERROR: Missing required synthesis field {exc}") from exc

    tii_min = CONSTITUTION_THRESHOLDS["tii_min"]
    integrity_min = CONSTITUTION_THRESHOLDS["integrity_min"]
    rr_min = CONSTITUTION_THRESHOLDS["rr_min"]
    fta_min = CONSTITUTION_THRESHOLDS["fta_min"]
    monte_min = CONSTITUTION_THRESHOLDS["monte_min"]
    conf12_min = CONSTITUTION_THRESHOLDS["conf12_min"]
    max_drawdown = CONSTITUTION_THRESHOLDS["max_drawdown"]

    gates = {
        "gate_1_tii": _gate(layers["L8_tii_sym"] >= tii_min),
        "gate_2_integrity": _gate(layers["L8_integrity_index"] >= integrity_min),
        "gate_3_rr": _gate(execution["rr_ratio"] >= rr_min),
        "gate_4_fta": _gate(scores["fta_score"] >= fta_min),
        "gate_5_montecarlo": _gate(layers["L7_monte_carlo_win"] >= monte_min),
        "gate_6_propfirm": _gate(propfirm["compliant"] is True),
        "gate_7_drawdown": _gate(risk["current_drawdown"] <= max_drawdown),
        "gate_8_latency": _gate(synthesis["system"]["latency_ms"] <= 250),
        "gate_9_conf12": _gate(layers["conf12"] >= conf12_min),
    }

    passed_gates = sum(1 for gate in gates.values() if gate == "PASS")

    violations = []

    if bias["fundamental"] != bias["technical"]:
        violations.append("F_T_CONFLICT")

    if scores["exec_score"] < 6:
        violations.append("EXEC_SCORE_VIOLATION")

    if violations:
        verdict = "NO_TRADE"
        confidence = "LOW"
        wolf_status = "NO_HUNT"

        for violation in violations:
            log_violation(pair=synthesis["pair"], reason=violation)
    elif passed_gates < 9:
        verdict = "HOLD"
        confidence = "MEDIUM"
        wolf_status = "SCOUT"

        failed = [key for key, value in gates.items() if value == "FAIL"]
        log_violation(pair=synthesis["pair"], reason=f"GATES_FAILED: {failed}")
    else:
        verdict = f"EXECUTE_{execution['direction']}"
        confidence = "VERY_HIGH" if scores["wolf_30_point"] >= 27 else "HIGH"
        wolf_status = "ALPHA" if scores["wolf_30_point"] >= 27 else "PACK"

    l12_output = {
        "schema": "v7.4r∞",
        "pair": synthesis["pair"],
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "verdict": verdict,
        "confidence": confidence,
        "wolf_status": wolf_status,
        "gates": {
            **gates,
            "passed": passed_gates,
            "total": 9,
        },
        "execution": {
            "direction": execution.get("direction"),
            "entry_zone": execution.get("entry_zone"),
            "entry_price": execution.get("entry_price"),
            "stop_loss": execution.get("stop_loss"),
            "take_profit_1": execution.get("take_profit_1"),
            "execution_mode": "TP1_ONLY",
            "rr_ratio": execution.get("rr_ratio"),
            "lot_size": execution.get("lot_size"),
            "risk_percent": execution.get("risk_percent"),
            "risk_amount": execution.get("risk_amount"),
        },
        "scores": {
            "wolf_30_point": scores["wolf_30_point"],
            "f_score": scores["f_score"],
            "t_score": scores["t_score"],
            "fta_score": scores["fta_score"],
            "exec_score": scores["exec_score"],
        },
        "proceed_to_L13": verdict.startswith("EXECUTE"),
    }

    return l12_output
"""
Verdict Engine — L12 Final Authority
"""

from constitution.gatekeeper import Gatekeeper


class VerdictEngine:
    def __init__(self):
        self.gatekeeper = Gatekeeper()

    def issue_verdict(self, candidate: dict) -> dict:
        gate_result = self.gatekeeper.evaluate(candidate)

        if not gate_result["passed"]:
            return {
                "verdict": "NO_TRADE",
                "reason": gate_result["reason"],
                "confidence": "LOW",
            }

        direction = self._infer_direction(candidate)

        return {
            "verdict": f"EXECUTE_{direction}",
            "confidence": "HIGH",
            "execution_mode": "TP1_ONLY",
        }

    @staticmethod
    def _infer_direction(candidate: dict) -> str:
        trend = candidate["L3"].get("trend", "NEUTRAL")
        if trend == "BULLISH":
            return "BUY"
        if trend == "BEARISH":
            return "SELL"
        return "HOLD"
# Placeholder
