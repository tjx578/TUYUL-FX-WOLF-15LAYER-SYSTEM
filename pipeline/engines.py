"""
Pipeline Engines v7.4r∞ — Reusable L13 Reflective & L15 Meta Sovereignty.

Extracted from the merged Constitutional + Sovereign pipeline to provide
standalone, testable, reusable governance components.

Architecture:
    L13ReflectiveEngine  — LRCE + FRPC + αβγ field computation
    L15MetaSovereigntyEngine — Meta integrity, zona health, sovereignty enforcement

Authority: Layer-12 remains the SOLE decision authority.
These engines NEVER override L12 — they augment reflective governance.
"""

from __future__ import annotations

from typing import Any


class L13ReflectiveEngine:
    """
    L13: Reflective Execution Strategy Engine.

    Computes TRQ-3D energy field (αβγ), LRCE, FRPC synchronization.
    Supports two-pass governance: baseline pass (meta=1.0) → refined pass (real meta).

    Sources:
        core_quantum_unified.py    → QuantumExecutionOptimizer
        core_reflective_unified.py → ReflectiveTradePipelineController
    """

    def reflect(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        meta_integrity: float = 1.0,
    ) -> dict[str, Any]:
        """
        Run a single reflective pass.

        Args:
            synthesis: L12-contract synthesis dict.
            l12_verdict: L12 verdict output.
            meta_integrity: Meta integrity score (1.0 for baseline pass,
                            real value for refined pass).

        Returns:
            Reflective pass result with LRCE, FRPC, αβγ, drift, field state.
        """
        lrce_score = self._compute_lrce(synthesis)
        frpc_score = self._compute_frpc(synthesis, l12_verdict)

        # αβγ from TRQ-3D — meta_integrity modulates gamma channel
        alpha = lrce_score
        beta = frpc_score
        gamma = meta_integrity

        abg_score = alpha * 0.40 + beta * 0.30 + gamma * 0.30

        drift = synthesis.get("trq3d", {}).get("drift", 0.0)
        lrce_field = synthesis.get("risk", {}).get("lrce", 0.0)

        return {
            "lrce_score": lrce_score,
            "frpc_score": frpc_score,
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "meta_integrity": meta_integrity,
            "abg_score": abg_score,
            "drift": drift,
            "lrce_field": lrce_field,
            "field_state": "EXPANSION" if abg_score >= 0.80 else "COMPRESSION",
            "execution_window": (
                "OPTIMAL" if abg_score >= 0.85
                else "GOOD" if abg_score >= 0.70
                else "POOR"
            ),
        }

    # ── Direction / bias alignment helpers ──

    @staticmethod
    def _is_direction_aligned(direction: str, technical_bias: str) -> bool:
        """Check if direction is aligned with technical bias."""
        if direction == "BUY" and technical_bias == "BULLISH":
            return True
        if direction == "SELL" and technical_bias == "BEARISH":
            return True
        return False

    def _compute_lrce(self, synthesis: dict[str, Any]) -> float:
        """Compute Layer Recursive Coherence (directional alignment)."""
        direction = synthesis.get("execution", {}).get("direction")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")

        if not direction or direction == "HOLD":
            return 0.5
        if self._is_direction_aligned(direction, technical_bias):
            return 1.0
        if technical_bias == "NEUTRAL":
            return 0.7
        return 0.3

    def _compute_frpc(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> float:
        """Compute Fusion Recursive Pattern Check (verdict/bias consistency)."""
        verdict = l12_verdict.get("verdict", "HOLD")
        technical_bias = synthesis.get("bias", {}).get("technical", "NEUTRAL")
        direction = synthesis.get("execution", {}).get("direction")

        if verdict.startswith("EXECUTE"):
            if self._is_direction_aligned(direction, technical_bias):
                return 1.0
            if technical_bias == "NEUTRAL":
                return 0.7
            return 0.3
        if verdict == "HOLD":
            return 0.8 if technical_bias == "NEUTRAL" else 0.5
        return 0.5


class L15MetaSovereigntyEngine:
    """
    L15: Meta Synthesis & Sovereignty Enforcement Engine.

    Computes:
      - Meta integrity from reflective passes
      - Zona health aggregation (5 zonas × 15 layers)
      - Sovereignty enforcement (GRANTED / RESTRICTED / REVOKED)
      - Drift detection between two-pass governance
    """

    # ── Drift / sovereignty thresholds ──
    VAULT_SYNC_MIN_GRANTED = 0.985
    DRIFT_MAX_GRANTED = 0.15
    VAULT_SYNC_MIN_RESTRICTED = 0.95
    DRIFT_MAX_RESTRICTED = 0.20

    def compute_meta(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
        reflective_pass1: dict[str, Any],
        sovereignty: dict[str, Any],
        gates: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compute L15 meta synthesis from all layer data + Pass 1 reflective.

        Returns full meta dict including zona health and unity state.
        """
        integrity = synthesis.get("layers", {}).get("L8_integrity_index", 0.0)
        rr = synthesis.get("execution", {}).get("rr_ratio", 0.0)
        wolf_score = synthesis.get("scores", {}).get("wolf_30_point", 0)

        # ── Zona health aggregation ──
        zona_1_pass = all([
            synthesis.get("layers", {}).get("L1_context_coherence", 0) >= 0.90,
            synthesis.get("layers", {}).get("L2_reflex_coherence", 0) >= 0.88,
            synthesis.get("layers", {}).get("L3_trq3d_energy", 0) >= 0.65,
        ])
        zona_2_pass = wolf_score >= 24
        zona_3_pass = all([
            gates.get("gate_1_tii") == "PASS",
            gates.get("gate_2_montecarlo") == "PASS",
        ])
        zona_4_pass = l12_verdict.get("verdict", "").startswith("EXECUTE")
        zona_5_pass = (
            reflective_pass1 is not None
            and reflective_pass1.get("abg_score", 0) >= 0.70
        )

        all_harmonized = all([
            zona_1_pass, zona_2_pass, zona_3_pass,
            zona_4_pass, zona_5_pass,
        ])

        # ── Meta integrity score (weighted composite) ──
        pass1_abg = reflective_pass1.get("abg_score", 0.0) if reflective_pass1 else 0.0
        vault_sync = sovereignty.get("vault_sync", 0.0)
        frpc = reflective_pass1.get("frpc_score", 0.0) if reflective_pass1 else 0.0
        meta_integrity = (
            pass1_abg * 0.40
            + vault_sync * 0.30
            + frpc * 0.20
            + (integrity * 0.10)
        )

        return {
            "meta_integrity": meta_integrity,
            "reflective_coherence": frpc,
            "vault_sync": vault_sync,
            "evolution_drift": reflective_pass1.get("drift", 0.0) if reflective_pass1 else 0.0,
            "conscious_phase": "EXPANSION" if all_harmonized else "STABILIZATION",
            "wolf_discipline_score": wolf_score / 30.0 if wolf_score else 0.0,
            "zona_health": {
                "perception_context": {
                    "layers": "L1-L3",
                    "status": "PASS" if zona_1_pass else "FAIL",
                },
                "confluence_scoring": {
                    "layers": "L4-L6",
                    "status": "PASS" if zona_2_pass else "FAIL",
                },
                "probability_validation": {
                    "layers": "L7-L9",
                    "status": "PASS" if zona_3_pass else "FAIL",
                },
                "execution_decision": {
                    "layers": "L10-L12",
                    "status": "PASS" if zona_4_pass else "FAIL",
                },
                "meta_reflective": {
                    "layers": "L13-L15",
                    "status": "PASS" if zona_5_pass else "FAIL",
                },
            },
            "full_reflective_state": {
                "all_harmonized": all_harmonized,
                "integrity_check": integrity >= 0.97,
                "rr_check": rr >= 2.0,
                "constitutional_clear": l12_verdict.get("verdict", "").startswith("EXECUTE"),
                "achieved": all_harmonized and integrity >= 0.97 and rr >= 2.0,
            },
        }

    def enforce_sovereignty(
        self,
        l12_verdict: dict[str, Any],
        reflective_pass1: dict[str, Any] | None,
        reflective_pass2: dict[str, Any] | None,
        meta: dict[str, Any],
        sovereignty: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Sovereignty enforcement with drift detection and verdict downgrade.

        Two-pass drift: compares Pass 1 vs Pass 2 αβγ scores.
        If REVOKED, downgrades L12 verdict to HOLD (safety mechanism).

        Returns enforcement dict with execution_rights, drift info, and
        any verdict modifications applied.
        """
        execution_rights = sovereignty.get("execution_rights", "REVOKED")
        vault_sync = sovereignty.get("vault_sync", 0.0)

        # ── Drift detection between passes ──
        pass1_abg = reflective_pass1.get("abg_score", 0.0) if reflective_pass1 else 0.0
        pass2_abg = reflective_pass2.get("abg_score", 0.0) if reflective_pass2 else 0.0
        drift_ratio = abs(pass1_abg - pass2_abg)

        # ── Refine sovereignty based on drift ──
        verdict_downgraded = False
        original_verdict = l12_verdict.get("verdict", "HOLD")

        if execution_rights == "GRANTED":
            # Even if vault says GRANTED, check drift stability
            if vault_sync < self.VAULT_SYNC_MIN_GRANTED or drift_ratio > self.DRIFT_MAX_GRANTED:
                execution_rights = "RESTRICTED"

        if execution_rights == "RESTRICTED":
            # Restricted: allow but with caution
            if vault_sync < self.VAULT_SYNC_MIN_RESTRICTED or drift_ratio > self.DRIFT_MAX_RESTRICTED:
                execution_rights = "REVOKED"

        if execution_rights == "REVOKED":
            # Safety: downgrade EXECUTE verdict to HOLD
            if l12_verdict.get("verdict", "").startswith("EXECUTE"):
                l12_verdict["verdict"] = "HOLD"
                l12_verdict["confidence"] = "LOW"
                l12_verdict["wolf_status"] = "NO_HUNT"
                l12_verdict["sovereignty_downgrade"] = True
                verdict_downgraded = True

        return {
            "execution_rights": execution_rights,
            "vault_sync": vault_sync,
            "drift_ratio": drift_ratio,
            "pass1_abg": pass1_abg,
            "pass2_abg": pass2_abg,
            "verdict_downgraded": verdict_downgraded,
            "original_verdict": original_verdict,
            "lot_multiplier": sovereignty.get("lot_multiplier", 0.0),
            "meta_integrity": meta.get("meta_integrity", 0.0),
        }
