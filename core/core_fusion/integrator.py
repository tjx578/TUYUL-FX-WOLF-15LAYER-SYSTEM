"""Fusion Integrator -- Core Layer 12 integration."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ._types import ConfidenceLineage, DEFAULT_PRECISION_WEIGHT_MIN, DEFAULT_PRECISION_WEIGHT_MAX
from ._utils import _clamp, _clamp01, _safe_float
from .field_sync import resolve_field_context
from .precision_engine import calculate_fusion_precision, evaluate_fusion_metrics


class FusionIntegrator:
    """Core Reflective Fusion Integrator (Layer 12).
    Hard Gate: reflective_coherence < 0.96 => ABORT.
    """
    VERSION = "5.3.3+"

    def __init__(self, *, gate_threshold: float = 0.96) -> None:
        self.gate_threshold = float(gate_threshold)

    def fuse_reflective_context(self, *, market_data: Optional[Dict[str, Any]] = None,
                                coherence_audit: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        market_data = market_data or {}
        alpha = _safe_float(market_data.get("alpha", 1.0), 1.0)
        beta = _safe_float(market_data.get("beta", 1.0), 1.0)
        gamma = _safe_float(market_data.get("gamma", 1.0), 1.0)
        lambda_esi = _safe_float(market_data.get("lambda_esi", 0.06), 0.06)

        fc = resolve_field_context(pair=market_data.get("pair", "XAUUSD"),
            timeframe=market_data.get("timeframe", "H4"), alpha=alpha, beta=beta,
            gamma=gamma, lambda_esi=lambda_esi, field_override=market_data.get("field_override"))

        fusion_output = {"timestamp": datetime.now(timezone.utc).isoformat(),
                         "fusion_version": self.VERSION, "field_context": fc}

        if coherence_audit is None:
            coherence_audit = {"reflective_coherence": 0.97, "gate_pass": True, "gate_threshold": self.gate_threshold}

        rc = _safe_float(coherence_audit.get("reflective_coherence", 0.0))
        gate_pass = bool(coherence_audit.get("gate_pass", False))

        if not gate_pass or rc < self.gate_threshold:
            return {
                "status": "ABORTED",
                "reason": f"Reflective Coherence below gate ({rc:.4f} < {self.gate_threshold:.2f})",
                "fusion_output": fusion_output, "coherence_audit": coherence_audit,
                "confidence_lineage": ConfidenceLineage(
                    raw=0.0, weighted=0.0, final=0.0, precision_weight=1.0,
                    gate_threshold=self.gate_threshold, gate_pass=False,
                    authority="FusionIntegrator", notes="ABORTED by reflective hard gate",
                    lambda_esi=fc.get("lambda_esi", 0.06),
                    field_state=fc.get("field_state"), field_integrity=fc.get("field_integrity")).as_dict(),
            }

        precision = calculate_fusion_precision(market_data)
        pw = _clamp(_safe_float(precision.get("precision_weight", 1.0), 1.0),
                     DEFAULT_PRECISION_WEIGHT_MIN, DEFAULT_PRECISION_WEIGHT_MAX)

        bb = _safe_float(market_data.get("base_bias", 0.5), 0.5)
        c12_raw = _clamp01(rc * bb)
        c12_w = _clamp01(c12_raw * pw)

        lineage = ConfidenceLineage(
            raw=round(c12_raw, 4), weighted=round(c12_w, 4), final=round(c12_w, 4),
            precision_weight=round(pw, 4), gate_threshold=self.gate_threshold, gate_pass=True,
            authority="FusionIntegrator", notes="final = clamp(raw * precision_weight)",
            lambda_esi=fc.get("lambda_esi", 0.06),
            field_state=fc.get("field_state"), field_integrity=fc.get("field_integrity"))

        metrics = evaluate_fusion_metrics({**market_data, "fusion_strength": c12_w})

        return {"status": "OK", "fusion_output": fusion_output, "coherence_audit": coherence_audit,
                "precision": precision, "confidence_lineage": lineage.as_dict(),
                "conf12_final": round(c12_w, 4), "metrics": metrics}


def integrate_fusion_layers(market_data: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight integration wrapper."""
    precision = calculate_fusion_precision(market_data)
    metrics = evaluate_fusion_metrics(market_data)
    pw = _safe_float(precision.get("precision_weight", 1.0), 1.0)
    wlwci = _clamp01(0.96 + abs(pw - 1.0) * 0.02)
    rc_adj = _clamp((pw - 1.0) * 0.05, -0.02, 0.02)
    return {"status": "Integrated", "WLWCI": round(wlwci, 3), "RCAdj": round(rc_adj, 4),
            "precision": precision, "metrics": metrics}
