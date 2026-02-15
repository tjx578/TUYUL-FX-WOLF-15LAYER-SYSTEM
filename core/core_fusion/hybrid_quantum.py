"""Hybrid Vault Quantum Engine — Quantum ↔ Fusion reflective core."""

import math
from typing import Any, Dict, List, Optional

from .vault_macro import VaultMacroLayer


class QuantumReflectiveEngine:
    """Entropy-based reflective field: αβγ gradient, energy, flux."""

    def __init__(self, alpha_weight: float = 0.4, beta_weight: float = 0.35, gamma_weight: float = 0.25) -> None:
        self.aw = alpha_weight; self.bw = beta_weight; self.gw = gamma_weight

    def evaluate_reflective_entropy(self, closes: List[float]) -> Dict[str, Any]:
        if len(closes) < 20:
            return {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "alpha_beta_gamma": 0.0,
                    "reflective_energy": 0.5, "flux_state": "Insufficient_Data"}
        rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] != 0]
        if not rets:
            return {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "alpha_beta_gamma": 0.0,
                    "reflective_energy": 0.5, "flux_state": "Insufficient_Data"}
        a = self._std(rets[-5:]) if len(rets) >= 5 else 0.0
        b = self._std(rets[-20:]) if len(rets) >= 20 else 0.0
        g = abs(sum(rets[-50:]) / 50) if len(rets) >= 50 else abs(sum(rets) / len(rets))
        abg = round(a * self.aw + b * self.bw + g * self.gw, 6)
        re = round(max(0.0, min(1.0, 1.0 - abg * 100)), 3)
        if abg <= 0.0015 and re >= 0.95: fs = "Stable"
        elif abg <= 0.0025 and re >= 0.90: fs = "High_Flux"
        else: fs = "Transitional"
        return {"alpha": round(a, 6), "beta": round(b, 6), "gamma": round(g, 6),
                "alpha_beta_gamma": abg, "reflective_energy": re, "flux_state": fs}

    def _std(self, vals: List[float]) -> float:
        if not vals or len(vals) < 2: return 0.0
        m = sum(vals) / len(vals)
        return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))


class HybridReflectiveCore:
    """L9 Hybrid: Quantum entropy + Vault Macro → Reflective Macro Coherence."""

    def __init__(self, ema_period: int = 200, sma_periods: Optional[List[int]] = None,
                 quantum_weight: float = 0.4, macro_weight: float = 0.6) -> None:
        self.quantum = QuantumReflectiveEngine()
        self.vault = VaultMacroLayer(ema_period=ema_period, sma_periods=sma_periods or [200, 800])
        self.qw = quantum_weight; self.mw = macro_weight

    def integrate(self, closes: List[float]) -> Dict[str, Any]:
        if not closes: return {"error": "No price data"}
        qf = self.quantum.evaluate_reflective_entropy(closes)
        vm = self.vault.get_reflective_gravity_score(closes)
        if "error" in vm: return vm

        pn = closes[-1]; er = vm["ema_200"] / pn if pn != 0 else 1.0
        en = min(1.0, max(0.5, er))
        rs = round(min(1.0, max(0.0, qf["reflective_energy"] * self.qw + en * self.mw)), 3)

        hb = vm["macro_bias"]
        if qf["flux_state"] == "Transitional" and rs < 0.85: hb = "Transitional"
        elif qf["flux_state"] == "High_Flux" and rs < 0.90: hb = "Cautious_" + vm["macro_bias"]

        rmc = round(min(1.0, max(0.0, qf["reflective_energy"] * 0.3 + vm["gravity_score"] * 0.3 + rs * 0.4)), 3)
        return {
            "alpha": qf["alpha"], "beta": qf["beta"], "gamma": qf["gamma"],
            "alpha_beta_gamma": qf["alpha_beta_gamma"], "reflective_energy": qf["reflective_energy"],
            "flux_state": qf["flux_state"], "ema_200": vm["ema_200"],
            "sma_200": vm.get("sma_200", 0.0), "sma_800": vm.get("sma_800", 0.0),
            "macro_bias": vm["macro_bias"], "distance_pct": vm["distance_pct"],
            "structural_alignment": vm["structural_alignment"], "gravity_score": vm["gravity_score"],
            "hybrid_reflective_strength": rs, "hybrid_bias": hb,
            "reflective_macro_coherence": rmc, "quantum_weight": self.qw, "macro_weight": self.mw,
        }

    def get_execution_status(self, closes: List[float], tii_threshold: float = 0.93) -> Dict[str, Any]:
        hd = self.integrate(closes)
        if "error" in hd:
            return {**hd, "pseudo_tii": 0.0, "execution_decision": "HOLD", "execution_reason": "Error in hybrid analysis"}
        pt = round(hd["reflective_energy"] * 0.4 + hd["gravity_score"] * 0.3 + hd["hybrid_reflective_strength"] * 0.3, 3)
        if pt >= tii_threshold and hd["flux_state"] == "Stable":
            dec, reason = "EXECUTE", f"TII={pt} >= {tii_threshold}, Flux=Stable"
        elif pt >= 0.90 and hd["flux_state"] in ["Stable", "High_Flux"]:
            dec, reason = "WAIT", f"TII={pt}, Flux={hd['flux_state']} - Pending confirmation"
        else:
            dec, reason = "HOLD", f"TII={pt} < threshold or Flux={hd['flux_state']}"
        return {**hd, "pseudo_tii": pt, "execution_decision": dec, "execution_reason": reason}
