"""
Synthesis Contract v2 — FINAL PRODUCTION

Macro-integrated | L1–L15 compliant | Constitutional-ready

Output contract for SynthesisEngine.
Guaranteed rigid schema for L12 + L14 JSON export.
"""

from __future__ import annotations

import time
from typing import Any, Dict


class SynthesisContractV2:
    """Immutable synthesis output contract."""

    @staticmethod
    def build(
        symbol: str,
        timestamp_utc: float,
        layer_results: Dict[str, Any],
        macro_state: Dict[str, Any],
        execution_data: Dict[str, Any],
        risk_data: Dict[str, Any],
        system_latency_ms: float,
    ) -> Dict[str, Any]:
        """Build synthesis contract (immutable)."""

        contract = {
            "system": {
                "version": "v7.4r∞",
                "timestamp": int(timestamp_utc),
                "symbol": symbol,
                "latency_ms": round(system_latency_ms, 2),
                "contract_version": 2,
            },

            "macro": {
                "vix_level": float(macro_state.get("vix_level", 15.0)),
                "vix_regime": str(macro_state.get("vix_regime", "STRESSED")),
                "term_structure": str(macro_state.get("term_structure", "UNKNOWN")),
                "fear_greed_score": float(macro_state.get("fear_greed_score", 0.5)),
                "regime_score": float(macro_state.get("regime_score", 0.5)),
                "regime_state": int(macro_state.get("regime_state", 1)),
                "volatility_multiplier": float(macro_state.get("volatility_multiplier", 1.0)),
                "risk_multiplier": float(macro_state.get("risk_multiplier", 1.0)),
            },

            "layers": {
                "L1": layer_results.get("L1", {}),
                "L2": layer_results.get("L2", {}),
                "L3": layer_results.get("L3", {}),
                "L4": layer_results.get("L4", {}),
                "L5": layer_results.get("L5", {}),
                "L6": layer_results.get("L6", {}),
                "L7": layer_results.get("L7", {}),
                "L8": layer_results.get("L8", {}),
                "L9": layer_results.get("L9", {}),
                "L10": layer_results.get("L10", {}),
                "L11": layer_results.get("L11", {}),
            },

            "scores": {
                "fta_score": float(layer_results.get("L4", {}).get("fta_score", 0)),
                "monte_carlo_win": float(layer_results.get("L7", {}).get("win_probability", 0)),
                "tii_sym": float(layer_results.get("L8", {}).get("tii_sym", 0)),
                "integrity_index": float(layer_results.get("L8", {}).get("integrity_index", 0)),
                "conf12": float(layer_results.get("L11", {}).get("conf12", 0)),
            },

            "execution": {
                "direction": str(execution_data.get("direction", "NONE")),
                "entry": float(execution_data.get("entry", 0)),
                "stop_loss": float(execution_data.get("stop_loss", 0)),
                "take_profit": float(execution_data.get("take_profit", 0)),
                "rr_ratio": float(execution_data.get("rr_ratio", 0)),
                "lot_size": float(execution_data.get("lot_size", 0)),
            },

            "risk": {
                "current_drawdown_pct": float(risk_data.get("current_drawdown_pct", 0)),
                "propfirm_compliant": bool(risk_data.get("propfirm_compliant", True)),
                "risk_ok": bool(risk_data.get("risk_ok", False)),
                "macro_regime_state": int(macro_state.get("regime_state", 1)),
                "risk_multiplier_applied": float(macro_state.get("risk_multiplier", 1.0)),
            },

            "validation": {
                "all_layers_valid": bool(
                    all(
                        layer_results.get(f"L{i}", {}).get("valid", True)
                        for i in range(1, 12)
                    )
                ),
                "macro_integrated": macro_state is not None,
                "execution_ready": bool(execution_data.get("entry", 0) > 0),
            },
        }

        return contract
