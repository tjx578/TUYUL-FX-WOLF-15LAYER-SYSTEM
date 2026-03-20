"""
Pipeline Engines v7.4r∞ -- Reusable L13 Reflective & L15 Meta Sovereignty.

Extracted from the merged Constitutional + Sovereign pipeline to provide
standalone, testable, reusable governance components.

Architecture:
    L13ReflectiveEngine  -- LRCE + FRPC + αβγ field computation
    L15MetaSovereigntyEngine -- Meta integrity, zona health, sovereignty enforcement

Authority: Layer-12 remains the SOLE decision authority.
These engines NEVER override L12 -- they augment reflective governance.
"""

from __future__ import annotations

from typing import Any


class L13ReflectiveEngine:
    """Layer 13: Reflective Learning Engine.

    Consumes historical verdict + outcome data to produce reflective
    scores. Now enriched with L7 Bayesian posterior tracking for
    probability calibration analysis.

    Authority: ANALYSIS-ONLY. No execution side-effects.
    Reads from journal (immutable). Produces advisory metrics only.
    """

    def reflect(
        self,
        symbol: str,
        historical_verdicts: list[dict[str, Any]],
        current_layer_results: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce reflective score with probability calibration analysis.

        Args:
            symbol: Instrument identifier.
            historical_verdicts: Past verdict records (from journal J2/J4).
            current_layer_results: Current cycle's layer outputs (optional).

        Returns:
            Reflective analysis dict including probability calibration.

        Authority: ANALYSIS-ONLY. No execution side-effects.
        """
        # Run a single reflective pass
        synthesis = current_layer_results or {}
        l12_verdict = {"verdict": "HOLD", "confidence": "LOW", "wolf_status": "NO_HUNT"}
        meta_integrity = 1.0

        lrce_score = self._compute_lrce(synthesis)
        frpc_score = self._compute_verdict_consistency(synthesis, l12_verdict)

        # αβγ from TRQ-3D -- meta_integrity modulates gamma channel
        alpha = lrce_score
        beta = frpc_score
        gamma = meta_integrity

        abg_score = alpha * 0.40 + beta * 0.30 + gamma * 0.30

        drift = synthesis.get("trq3d", {}).get("drift", 0.0)
        lrce_field = synthesis.get("risk", {}).get("lrce", 0.0)

        # Base reflective result
        reflection = {
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
            "execution_window": ("OPTIMAL" if abg_score >= 0.85 else "GOOD" if abg_score >= 0.70 else "POOR"),
        }

        # ── Probability calibration (L7 Bayesian posterior tracking) ──
        calibration = self._extract_probability_calibration(historical_verdicts)
        ror_trend = self._extract_risk_of_ruin_trend(historical_verdicts)

        # ── Enrich reflection output with probability analysis ────────
        reflection["probability_calibration"] = calibration
        reflection["risk_of_ruin_trend"] = ror_trend

        # ── Adjust reflective confidence if calibration is poor ──────
        if calibration["calibration_grade"] in ("D", "F"):
            _penalty = 0.05 if calibration["calibration_grade"] == "D" else 0.10
            reflection["reflective_confidence"] = round(
                max(0.0, float(reflection.get("reflective_confidence", 0.5)) - _penalty),
                4,
            )
            reflection["calibration_warning"] = (
                f"Probability calibration grade {calibration['calibration_grade']} -- "
                f"error={calibration['calibration_error']:.4f}. "
                f"L7 predictions may be unreliable."
            )

        if ror_trend["ror_trend"] == "DETERIORATING":
            reflection["ror_warning"] = (
                f"Risk-of-ruin trend DETERIORATING: "
                f"mean={ror_trend['ror_mean']:.4f} latest={ror_trend['ror_latest']:.4f}. "
                f"Review strategy health."
            )

        return reflection

    # ── Direction / bias alignment helpers ──

    @staticmethod
    def _is_direction_aligned(direction: str, technical_bias: str) -> bool:
        """Check if direction is aligned with technical bias."""
        if direction == "BUY" and technical_bias == "BULLISH":
            return True
        return bool(direction == "SELL" and technical_bias == "BEARISH")

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

    def _compute_verdict_consistency(
        self,
        synthesis: dict[str, Any],
        l12_verdict: dict[str, Any],
    ) -> float:
        """Compute verdict/bias consistency score.

        Returns a discrete consistency measure {0.3, 0.5, 0.7, 0.8, 1.0}
        based on alignment between L12 verdict and technical bias.
        NOT the canonical FRPC from ``analysis.formulas.frpc_formula``.
        """
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

    def _extract_probability_calibration(
        self,
        historical_verdicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Analyze L7 Bayesian posterior calibration across historical verdicts.

        Compares predicted win probability (L7 posterior) against actual
        outcomes to measure how well-calibrated the probability engine is.

        Args:
            historical_verdicts: List of verdict dicts that include
                ``probability_context`` and ``outcome`` fields.

        Returns:
            Calibration metrics dict:
            - calibration_error: Mean absolute difference between predicted and actual
            - overconfidence_ratio: Fraction of trades where predicted > actual
            - posterior_mean: Mean posterior win probability across history
            - actual_win_rate: Actual observed win rate
            - sample_size: Number of verdicts with both probability + outcome data
            - calibration_grade: A/B/C/D/F based on calibration_error

        Authority: Pure computation, read-only. No side-effects.
        """
        predicted: list[float] = []
        actual: list[float] = []

        for v in historical_verdicts:
            prob_ctx = v.get("probability_context", {})
            outcome = v.get("outcome", {})

            if not isinstance(prob_ctx, dict) or not isinstance(outcome, dict):
                continue

            posterior = prob_ctx.get("bayesian_posterior", None)
            won = outcome.get("won", None)

            if posterior is None or won is None:
                continue

            predicted.append(float(posterior))
            actual.append(1.0 if won else 0.0)

        if len(predicted) < 5:
            return {
                "calibration_error": None,
                "overconfidence_ratio": None,
                "posterior_mean": None,
                "actual_win_rate": None,
                "sample_size": len(predicted),
                "calibration_grade": "N/A",
                "note": f"insufficient_samples_{len(predicted)}/5",
            }

        import numpy as np  # noqa: PLC0415

        pred_arr = np.array(predicted)
        act_arr = np.array(actual)

        calibration_error = float(np.mean(np.abs(pred_arr - act_arr)))
        overconfidence_ratio = float(np.mean(pred_arr > act_arr))
        posterior_mean = float(np.mean(pred_arr))
        actual_win_rate = float(np.mean(act_arr))

        # Grade: A ≤ 0.05, B ≤ 0.10, C ≤ 0.15, D ≤ 0.25, F > 0.25
        if calibration_error <= 0.05:
            grade = "A"
        elif calibration_error <= 0.10:
            grade = "B"
        elif calibration_error <= 0.15:
            grade = "C"
        elif calibration_error <= 0.25:
            grade = "D"
        else:
            grade = "F"

        return {
            "calibration_error": round(calibration_error, 4),
            "overconfidence_ratio": round(overconfidence_ratio, 4),
            "posterior_mean": round(posterior_mean, 4),
            "actual_win_rate": round(actual_win_rate, 4),
            "sample_size": len(predicted),
            "calibration_grade": grade,
        }

    def _extract_risk_of_ruin_trend(
        self,
        historical_verdicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Track risk-of-ruin trajectory across recent verdicts.

        Args:
            historical_verdicts: List of verdict dicts with probability_context.

        Returns:
            Trend metrics for risk-of-ruin.

        Authority: Pure computation, read-only. No side-effects.
        """
        ror_values: list[float] = []

        for v in historical_verdicts:
            prob_ctx = v.get("probability_context", {})
            if not isinstance(prob_ctx, dict):
                continue
            ror = prob_ctx.get("risk_of_ruin", None)
            if ror is not None:
                ror_values.append(float(ror))

        if len(ror_values) < 3:
            return {
                "ror_mean": None,
                "ror_latest": None,
                "ror_trend": "UNKNOWN",
                "ror_above_threshold_pct": None,
                "sample_size": len(ror_values),
            }

        import numpy as np  # noqa: PLC0415

        arr = np.array(ror_values)
        n = len(arr)
        half = n // 2

        ror_mean = float(np.mean(arr))
        ror_latest = float(arr[-1])
        first_half_mean = float(np.mean(arr[:half])) if half > 0 else ror_mean
        second_half_mean = float(np.mean(arr[half:])) if half > 0 else ror_mean

        if second_half_mean > first_half_mean + 0.02:
            trend = "DETERIORATING"
        elif second_half_mean < first_half_mean - 0.02:
            trend = "IMPROVING"
        else:
            trend = "STABLE"

        # Fraction of verdicts where RoR exceeded the 20% gate threshold
        above_threshold = float(np.mean(arr >= 0.20))

        return {
            "ror_mean": round(ror_mean, 4),
            "ror_latest": round(ror_latest, 4),
            "ror_trend": trend,
            "ror_above_threshold_pct": round(above_threshold, 4),
            "sample_size": n,
        }


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
        zona_1_pass = all(
            [
                synthesis.get("layers", {}).get("L1_context_coherence", 0) >= 0.90,
                synthesis.get("layers", {}).get("L2_reflex_coherence", 0) >= 0.88,
                synthesis.get("layers", {}).get("L3_trq3d_energy", 0) >= 0.65,
            ]
        )
        zona_2_pass = wolf_score >= 24  # 24/30 = 80% minimum wolf quality for Zona 2
        zona_3_pass = all(
            [
                gates.get("gate_1_tii") == "PASS",
                gates.get("gate_2_montecarlo") == "PASS",
            ]
        )
        zona_4_pass = l12_verdict.get("verdict", "").startswith("EXECUTE")
        zona_5_pass = reflective_pass1 is not None and reflective_pass1.get("abg_score", 0) >= 0.70

        all_harmonized = all(
            [
                zona_1_pass,
                zona_2_pass,
                zona_3_pass,
                zona_4_pass,
                zona_5_pass,
            ]
        )

        # ── Meta integrity score (weighted composite) ──
        pass1_abg = reflective_pass1.get("abg_score", 0.0) if reflective_pass1 else 0.0
        vault_sync = sovereignty.get("vault_sync", 0.0)
        frpc = reflective_pass1.get("frpc_score", 0.0) if reflective_pass1 else 0.0
        meta_integrity = pass1_abg * 0.40 + vault_sync * 0.30 + frpc * 0.20 + (integrity * 0.10)

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

        if execution_rights == "GRANTED":  # noqa: SIM102
            # Even if vault says GRANTED, check drift stability
            if vault_sync < self.VAULT_SYNC_MIN_GRANTED or drift_ratio > self.DRIFT_MAX_GRANTED:
                execution_rights = "RESTRICTED"

        if execution_rights == "RESTRICTED":  # noqa: SIM102
            # Restricted: allow but with caution
            if vault_sync < self.VAULT_SYNC_MIN_RESTRICTED or drift_ratio > self.DRIFT_MAX_RESTRICTED:
                execution_rights = "REVOKED"

        if execution_rights == "REVOKED":  # noqa: SIM102
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
