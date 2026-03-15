"""Journal entry builders (J1 context + J2 decision).

Zone: journal/ — append-only audit, no decision power.

These builders translate pipeline synthesis results into immutable
journal entries for context (J1) and decision (J2) logging.
"""

from __future__ import annotations

from typing import Any

from journal.journal_schema import ContextJournal, DecisionJournal, VerdictType
from utils.timezone_utils import is_trading_session, now_utc

__all__ = ["build_j1", "build_j2"]


def build_j1(pair: str, synthesis: dict[str, Any]) -> ContextJournal:
    """Build a J1 context journal entry from pipeline synthesis."""
    layers: dict[str, Any] = dict(synthesis.get("layers") or {})
    bias: dict[str, Any] = dict(synthesis.get("bias") or {})
    session = is_trading_session()
    return ContextJournal(
        timestamp=now_utc(),
        pair=pair,
        session=session,
        market_regime=str(synthesis.get("market_regime", "UNKNOWN")),
        news_lock=bool(synthesis.get("news_lock", False)),
        context_coherence=float(layers.get("conf12", 0.5)),
        mta_alignment=bool(synthesis.get("mta_alignment", True)),
        technical_bias=str(bias.get("technical", "NEUTRAL")),
    )


def build_j2(pair: str, synthesis: dict[str, Any], l12: dict[str, Any]) -> DecisionJournal:
    """Build a J2 decision journal entry from pipeline synthesis + L12 verdict."""
    scores: dict[str, Any] = dict(synthesis.get("scores") or {})
    layers: dict[str, Any] = dict(synthesis.get("layers") or {})
    gates: dict[str, Any] = dict(l12.get("gates") or {})
    setup_id = f"{pair}_{now_utc().strftime('%Y%m%d_%H%M%S')}"

    failed_gates: list[str] = [
        str(gate_name)
        for gate_name, gate_value in gates.items()
        if gate_name not in ["passed", "total"] and gate_value == "FAIL"
    ]

    primary_rejection_reason = None
    if l12["verdict"] in [VerdictType.HOLD.value, VerdictType.NO_TRADE.value]:
        if failed_gates:
            primary_rejection_reason = f"Failed gates: {', '.join(failed_gates)}"
        else:
            primary_rejection_reason = "Constitutional violation"

    try:
        verdict_type = VerdictType(l12["verdict"])
    except ValueError:
        verdict_type = VerdictType.NO_TRADE

    return DecisionJournal(
        timestamp=now_utc(),
        pair=pair,
        setup_id=setup_id,
        wolf_30_score=int(scores.get("wolf_30_point", 0)),
        f_score=int(scores.get("f_score", 0)),
        t_score=int(scores.get("t_score", 0)),
        fta_score=int((scores.get("fta_score") or 0) * 10),
        exec_score=int(scores.get("exec_score", 0)),
        tii_sym=float(layers.get("L8_tii_sym", 0.0)),
        integrity_index=float(layers.get("L8_integrity_index", 0.0)),
        monte_carlo_win=float(layers.get("L7_monte_carlo_win", 0.0)),
        conf12=float(layers.get("conf12", 0.0)),
        verdict=verdict_type,
        confidence=str(l12.get("confidence", "LOW")),
        wolf_status=str(l12.get("wolf_status", "NO_HUNT")),
        gates_passed=int(gates.get("passed", 0)),
        gates_total=int(gates.get("total", 9)),
        failed_gates=failed_gates,
        violations=[],
        primary_rejection_reason=primary_rejection_reason,
    )
