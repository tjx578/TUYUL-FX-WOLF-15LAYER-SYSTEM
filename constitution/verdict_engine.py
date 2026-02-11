from __future__ import annotations

import logging

from typing import Any

from config.constitution import CONSTITUTION_THRESHOLDS
from constitution.violation_log import log_violation
from context.live_context_bus import LiveContextBus
from utils.timezone_utils import format_utc, now_utc

logger = logging.getLogger(__name__)


def _gate(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def generate_l12_verdict(synthesis: dict[str, Any]) -> dict[str, Any]:
    """
    Input: synthesis output from analysis.synthesis (L1-L11).
    Output: final L12 verdict (constitutional).
    """

    # Feed staleness circuit breaker
    context_bus = LiveContextBus()
    pair = synthesis.get("pair")
    
    if pair and isinstance(pair, str) and pair.strip() and context_bus.is_feed_stale(pair):
        feed_age = context_bus.get_feed_age(pair)
        logger.warning(
            "Feed stale — circuit breaker activated",
            extra={"pair": pair, "feed_age_s": feed_age},
        )
        return {
            "schema": "v7.4r∞",
            "pair": pair,
            "timestamp": format_utc(now_utc()),
            "verdict": "HOLD",
            "confidence": "LOW",
            "wolf_status": "NO_HUNT",
            "gates": {"passed": 0, "total": 9},
            "execution": {},
            "scores": synthesis.get("scores", {}),
            "proceed_to_L13": False,
            "circuit_breaker": "FEED_STALE",
            "feed_age_s": feed_age,
        }

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

    # Check for F/T conflict - NEUTRAL is compatible with any direction
    if bias["fundamental"] != bias["technical"]:
        if bias["fundamental"] != "NEUTRAL" and bias["technical"] != "NEUTRAL":
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
        # Determine direction from execution or bias
        # If direction is missing or HOLD, infer from technical bias
        direction = execution.get("direction")
        if not direction or direction == "HOLD":
            # Infer from technical bias (BULLISH -> BUY, BEARISH -> SELL)
            if bias["technical"] == "BULLISH":
                direction = "BUY"
            elif bias["technical"] == "BEARISH":
                direction = "SELL"
            else:
                direction = "HOLD"

        verdict = f"EXECUTE_{direction}"
        confidence = "VERY_HIGH" if scores["wolf_30_point"] >= 27 else "HIGH"
        wolf_status = "ALPHA" if scores["wolf_30_point"] >= 27 else "PACK"

    l12_output = {
        "schema": "v7.4r∞",
        "pair": synthesis["pair"],
        "timestamp": format_utc(now_utc()),
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
