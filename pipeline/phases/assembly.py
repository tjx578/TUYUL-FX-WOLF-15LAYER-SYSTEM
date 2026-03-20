"""
Phase 8 — L14 JSON Export & Final Assembly.

Builds the full L14 JSON export dict from all upstream layer results.
This is a pure function: no side effects, no execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_l14_json(  # noqa: PLR0913
    schema_version: str,
    symbol: str,
    now: datetime,
    synthesis: dict[str, Any],
    l12_verdict: dict[str, Any],
    reflective: dict[str, Any] | None,
    gates: dict[str, Any],
    l10: dict[str, Any],
    sovereignty: dict[str, Any],
    enforcement: dict[str, Any] | None,
    latency_ms: float,  # noqa: ARG001
) -> dict[str, Any]:
    """Build full L14 JSON export matching v8.0 schema.

    Args:
        schema_version: Pipeline schema version string (e.g. "v8.0").
        symbol: Trading pair symbol.
        now: Current datetime (GMT+8).
        synthesis: L12 synthesis dict.
        l12_verdict: Constitutional verdict dict.
        reflective: Best available L13 reflective pass (or None).
        gates: 9-gate evaluation result.
        l10: Layer-10 position sizing result.
        sovereignty: Vault sync computation result.
        enforcement: Sovereignty enforcement result (or None).
        latency_ms: Pipeline execution time in milliseconds.
    """
    verdict_str = l12_verdict.get("verdict", "HOLD")
    confidence = l12_verdict.get("confidence", "LOW")
    wolf_status = l12_verdict.get("wolf_status", "NO_HUNT")

    return {
        "schema": schema_version,
        "pair": symbol,
        "timestamp": now.strftime("%Y-%m-%d %H:%M GMT+8"),
        "verdict": verdict_str,
        "confidence": confidence,
        "wolf_status": wolf_status,
        "battle_strategy": synthesis.get("execution", {}).get("battle_strategy", "SHADOW_STRIKE"),
        "modules": {
            "cognitive": "core_cognitive_unified.py",
            "fusion": "core_fusion_unified.py",
            "quantum": "core_quantum_unified.py",
            "reflective": "core_reflective_unified.py",
        },
        "scores": synthesis.get("scores", {}),
        "layers": synthesis.get("layers", {}),
        "cognitive": synthesis.get("cognitive", {}),
        "fusion_frpc": synthesis.get("fusion_frpc", {}),
        "trq3d": synthesis.get("trq3d", {}),
        "lfs": {
            "mean_energy": synthesis.get("trq3d", {}).get("mean_energy", 0.0),
            "lrce": synthesis.get("risk", {}).get("lrce", 0.0),
            "phase": "EXPANSION" if reflective and reflective.get("abg_score", 0) >= 0.80 else "STABILIZATION",
        },
        "smc": synthesis.get("smc", {}),
        "execution": synthesis.get("execution", {}),
        "gates": gates,
        "propfirm": synthesis.get("propfirm", {}),
        "meta16": {
            "meta_integrity": sovereignty.get("meta_integrity", 0.0),
            "reflective_coherence": reflective.get("frpc_score", 0.0) if reflective else 0.0,
            "vault_sync": sovereignty.get("vault_sync", 0.0),
            "evolution_drift": reflective.get("drift", 0.0) if reflective else 0.0,
            "meta_state": l10.get("meta_state", "STABLE"),
        },
        "wolf_discipline": synthesis.get("wolf_discipline", {}),
        "enforcement": {
            "execution_rights": enforcement.get("execution_rights", "REVOKED") if enforcement else "REVOKED",
            "drift_ratio": enforcement.get("drift_ratio", 0.0) if enforcement else 0.0,
            "verdict_downgraded": enforcement.get("verdict_downgraded", False) if enforcement else False,
        },
        "final_gate": "ALL_PASS"
        if gates.get("total_passed", 0) == 9
        else f"GATE_{9 - gates.get('total_passed', 0)}_FAIL",
    }
