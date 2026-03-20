"""
Phase 5 — 9-Gate Constitutional Check.

Evaluates all nine constitutional gates from the L12 synthesis dict.
This is a pure function: no side effects, no execution authority.
Authority: Layer-12 is the SOLE CONSTITUTIONAL AUTHORITY.
"""

from __future__ import annotations

from typing import Any

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from pipeline.constants import (
    get_conf12_min,
    get_integrity_min,
    get_max_drawdown,
    get_max_latency_ms,
    get_monte_min,
    get_rr_min,
    get_tii_min,
)


def evaluate_9_gates(synthesis: dict[str, Any]) -> dict[str, Any]:
    """Evaluate the 9 constitutional gates against a synthesis dict.

    Gate 2 Enhancement (v2.1):
        Now requires BOTH conditions:
        - win_pct >= monte_min * 100  (original MC win-rate check)
        - risk_of_ruin < 0.20         (new: must not exceed 20% ruin probability)

    Args:
        synthesis: The L12 synthesis dict (output of build_l12_synthesis).

    Returns:
        dict with per-gate booleans, overall pass, and metadata.
    """
    # Gate 1: TIIsym >= 0.93
    tii = synthesis.get("L8", {}).get("tii_sym", 0.0)
    g1 = tii >= get_tii_min()

    # Gate 2: Monte Carlo Win-Rate + Risk of Ruin
    l7 = synthesis.get("L7", {})

    _raw_win = l7.get("win_probability", 0.0)
    win_pct = _raw_win if _raw_win > 1.0 else _raw_win * 100.0

    _monte_min = get_monte_min()
    g2_win = win_pct >= (_monte_min * 100.0)

    _risk_of_ruin = l7.get("risk_of_ruin", 1.0)
    _ror_threshold = 0.20
    g2_ror = _risk_of_ruin < _ror_threshold

    g2 = g2_win and g2_ror

    # Gate 3: FRPC State = SYNC
    frpc_state = synthesis.get("L2", {}).get("frpc_state", "DESYNC")
    g3 = frpc_state == "SYNC"

    # Gate 4: CONF12 >= 0.75
    conf12 = synthesis.get("L2", {}).get("conf12", 0.0)
    g4 = conf12 >= get_conf12_min()

    # Gate 5: RR >= 1:2.0
    rr = synthesis.get("L11", {}).get("rr", 0.0)
    g5 = rr >= get_rr_min()

    # Gate 6: Integrity >= 0.97
    integrity = synthesis.get("L8", {}).get("integrity", 0.0)
    g6 = integrity >= get_integrity_min()

    # Gate 7: PropFirm Compliant
    compliant = synthesis.get("L6", {}).get("propfirm_compliant", True)
    g7 = bool(compliant)

    # Gate 8: Drawdown <= 2.5%
    drawdown = synthesis.get("risk", {}).get("current_drawdown", 0.0)
    g8 = drawdown <= get_max_drawdown()

    # Gate 9: Latency <= 250ms
    latency = synthesis.get("system", {}).get("latency_ms", 0.0)
    g9 = latency <= get_max_latency_ms()

    passed = sum([g1, g2, g3, g4, g5, g6, g7, g8, g9])

    # Log Gate 2 detail for audit trail
    logger.debug(
        "[Gate-2] win_pct=%.1f%% (min=%.1f%%) %s | risk_of_ruin=%.4f (max=%.2f) %s | gate=%s",
        win_pct,
        _monte_min * 100.0,
        "PASS" if g2_win else "FAIL",
        _risk_of_ruin,
        _ror_threshold,
        "PASS" if g2_ror else "FAIL",
        "PASS" if g2 else "FAIL",
    )

    return {
        "total_passed": passed,
        "total_gates": 9,
        "gate_1_tii": "PASS" if g1 else "FAIL",
        "gate_2_montecarlo": "PASS" if g2 else "FAIL",
        "gate_3_frpc": "PASS" if g3 else "FAIL",
        "gate_4_conf12": "PASS" if g4 else "FAIL",
        "gate_5_rr": "PASS" if g5 else "FAIL",
        "gate_6_integrity": "PASS" if g6 else "FAIL",
        "gate_7_propfirm": "PASS" if g7 else "FAIL",
        "gate_8_drawdown": "PASS" if g8 else "FAIL",
        "gate_9_latency": "PASS" if g9 else "FAIL",
    }
