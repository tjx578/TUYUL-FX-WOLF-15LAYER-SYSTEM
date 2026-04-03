"""Lorentzian Field Stabilizer — advisory enrichment engine.

Runs as Phase 2.5 advisory enricher within the Wolf-15 pipeline.
Output is strictly advisory — never overrides L12 verdict.
"""

from __future__ import annotations

import logging
from typing import Any

from analysis.reflective.lorentzian_field_adapter import map_layer_results_to_abg
from analysis.reflective.lorentzian_field_contracts import LorentzianFieldResult
from analysis.reflective.lorentzian_field_engine import (
    classify_phase,
    compute_confidence_adj,
    compute_e_norm,
    compute_gradient_abs,
    compute_gradient_signed,
    compute_lrce,
)

logger = logging.getLogger(__name__)

# ── Rescue eligibility constants ──────────────────────────────────
_RESCUE_LRCE_MIN = 0.970
_RESCUE_DRIFT_MAX = 0.0045
_RESCUE_GRAD_MAX = 0.005
_RESCUE_E_NORM_MIN = 0.94
_RESCUE_E_NORM_MAX = 1.03


class LorentzianFieldEnricher:
    """Advisory-only Lorentzian field enrichment engine.

    Consumes a Wolf synthesis dict and optional historical α–β–γ snapshot.
    Produces a ``LorentzianFieldResult`` for injection into enrichment data.
    """

    def analyze(
        self,
        synthesis: dict[str, Any],
        history: dict[str, float] | None = None,
    ) -> LorentzianFieldResult:
        """Run LFS analysis on a synthesis payload.

        Parameters
        ----------
        synthesis : dict
            The synthesis dict built by ``build_l12_synthesis()``.
        history : dict | None
            Previous cycle's α–β–γ values (keys: ``alpha``, ``beta``, ``gamma``).
            If ``None``, deltas default to 0 (stabilization phase assumed).
        """
        alpha, beta, gamma = map_layer_results_to_abg(synthesis)

        prev = history or {}
        d_alpha = alpha - float(prev.get("alpha", alpha))
        d_beta = beta - float(prev.get("beta", beta))
        d_gamma = gamma - float(prev.get("gamma", gamma))

        e_norm = compute_e_norm(alpha, beta, gamma)
        gradient_signed = compute_gradient_signed(d_alpha, d_beta, d_gamma)
        gradient_abs = compute_gradient_abs(alpha, beta, gamma)

        trq3d = synthesis.get("trq3d", {})
        drift = float(trq3d.get("drift", 0.0) if isinstance(trq3d, dict) else 0.0)

        layers = synthesis.get("layers", {})
        integrity_index = float(
            layers.get("L8_integrity_index", 0.0) if isinstance(layers, dict) else 0.0,
        )
        meta_integrity = 1.0  # placeholder until meta-integrity feed is available

        lrce = compute_lrce(e_norm, meta_integrity, integrity_index, drift)
        phase = classify_phase(gradient_signed)
        adj = compute_confidence_adj(lrce, drift, gradient_signed)

        rescue_eligible = (
            lrce >= _RESCUE_LRCE_MIN
            and drift <= _RESCUE_DRIFT_MAX
            and abs(gradient_signed) <= _RESCUE_GRAD_MAX
            and _RESCUE_E_NORM_MIN <= e_norm <= _RESCUE_E_NORM_MAX
        )

        if rescue_eligible:
            quality_band = "STABLE"
        elif lrce >= 0.955:
            quality_band = "CAUTION"
        else:
            quality_band = "WEAK"

        logger.info(
            "[LFS] e_norm=%.4f lrce=%.4f drift=%.4f grad=%.4f phase=%s band=%s rescue=%s adj=%.3f",
            e_norm,
            lrce,
            drift,
            gradient_signed,
            phase,
            quality_band,
            rescue_eligible,
            adj,
        )

        return LorentzianFieldResult(
            e_norm=round(e_norm, 6),
            lrce=round(lrce, 6),
            gradient_signed=round(gradient_signed, 6),
            gradient_abs=round(gradient_abs, 6),
            drift=round(drift, 6),
            field_phase=phase,
            quality_band=quality_band,
            rescue_eligible=rescue_eligible,
            confidence_adj=round(adj, 4),
        )
