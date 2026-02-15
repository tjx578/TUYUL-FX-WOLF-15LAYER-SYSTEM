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


def generate_l12_verdict(synthesis: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0912
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
            "Feed stale - circuit breaker activated",
            extra={"pair": pair, "feed_age_s": feed_age},
        )
        return {
            "schema": "v7.4r∞",
            "pair": pair,
            "timestamp": format_utc(now_utc()),
            "verdict": "HOLD",
            "confidence": "LOW",
            "wolf_status": "NO_HUNT",
            "gates": {"passed": 0, "total": 10},
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
        "gate_6_propfirm": _gate(bool(propfirm.get("compliant", False))),
        "gate_7_drawdown": _gate(risk["current_drawdown"] <= max_drawdown),
        "gate_8_latency": _gate(synthesis["system"]["latency_ms"] <= 250),
        "gate_9_conf12": _gate(layers["conf12"] >= conf12_min),
    }

    # Gate #10: Macro VIX regime check
    macro_vix = synthesis.get("macro_vix", {})
    vix_regime_state = macro_vix.get("regime_state", 1)
    safe_mode = synthesis.get("system", {}).get("safe_mode", False)
    gates["gate_10_macro_regime"] = _gate(vix_regime_state < 2 or safe_mode)

    passed_gates = sum(1 for gate in gates.values() if gate == "PASS")

    violations = []

    # ─── MN Bias Conflict Guard (internal, non-gate) ───
    # If monthly macro regime conflicts with trade direction,
    # downgrade verdict to HOLD unless confidence is extremely high
    macro_data = synthesis.get("macro", {})
    mn_regime = macro_data.get("regime", "UNKNOWN")
    mn_bias_override = macro_data.get("bias_override", {})

    mn_conflict = False
    mn_override_active = False
    if mn_bias_override.get("active", False):
        # Determine trade direction
        trade_direction = execution.get("direction")
        penalized_direction = mn_bias_override.get("penalized_direction")

        if trade_direction == penalized_direction:
            mn_conflict = True
            # Apply confidence penalty
            adjusted_conf12 = layers["conf12"] * mn_bias_override.get(
                "confidence_multiplier", 1.0
            )
            # If adjusted conf12 drops below threshold and we passed 7+ gates,
            # consider downgrading to HOLD for counter-macro trades
            if adjusted_conf12 < conf12_min and passed_gates >= 7:
                mn_override_active = True

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
    elif mn_override_active:
        # MN bias conflict override: downgrade to HOLD
        verdict = "HOLD"
        confidence = "MEDIUM"
        wolf_status = "SCOUT"
        log_violation(
            pair=synthesis["pair"],
            reason=f"MN_BIAS_CONFLICT: counter-macro trade in {mn_regime}",
        )
    elif passed_gates < 10:
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
                # No directional bias - return HOLD, not EXECUTE_HOLD
                verdict = "HOLD"
                confidence = "MEDIUM"
                wolf_status = "SCOUT"
                direction = None  # Clear direction

        if direction:  # Only set EXECUTE verdict if we have a valid direction
            verdict = f"EXECUTE_{direction}"
            confidence = "VERY_HIGH" if scores["wolf_30_point"] >= 27 else "HIGH"
            wolf_status = "ALPHA" if scores["wolf_30_point"] >= 27 else "PACK"

    l12_output = {
        "schema": "v7.4r∞",
        "pair": synthesis["pair"],
        "timestamp": format_utc(now_utc()),
        "verdict": verdict, # pyright: ignore[reportPossiblyUnboundVariable]
        "confidence": confidence, # pyright: ignore[reportPossiblyUnboundVariable]
        "wolf_status": wolf_status, # pyright: ignore[reportPossiblyUnboundVariable]
        "gates": {
            **gates,
            "passed": passed_gates,
            "total": 10,
        },
        "mn_conflict": mn_conflict,
        "mn_regime": mn_regime,
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
        "proceed_to_L13": verdict.startswith("EXECUTE"), # pyright: ignore[reportPossiblyUnboundVariable]
    }

    return l12_output


class VerdictEngine:
    """Layer-12 Constitutional Verdict Engine.

    SOLE DECISION AUTHORITY. All other layers are advisory.
    """

    def _extract_l7_probability_metrics(
        self, layer_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract and normalize L7 Monte Carlo + Bayesian metrics.

        Returns a flat dict of validated L7 fields with fail-safe defaults.
        These are ADVISORY inputs to the verdict — they inform confidence
        scoring but do not independently authorize or block trades.
        The gate logic (PASS/CONDITIONAL/FAIL) is evaluated by _evaluate_9_gates().

        Authority: READ-ONLY extraction. No side-effects.
        """
        l7 = layer_results.get("L7", {})
        if not isinstance(l7, dict):
            l7 = {}

        # Normalize win_probability: L7 outputs 0-100, verdict needs 0.0-1.0
        raw_win = l7.get("win_probability", 0.0)
        win_prob = raw_win / 100.0 if raw_win > 1.0 else raw_win

        return {
            "l7_win_probability": round(float(win_prob), 4),
            "l7_profit_factor": round(float(l7.get("profit_factor", 0.0)), 2),
            "l7_risk_of_ruin": round(float(l7.get("risk_of_ruin", 1.0)), 4),
            "l7_posterior_win": round(
                float(l7.get("bayesian_posterior", l7.get("posterior_win_probability", 0.0))),
                4,
            ),
            "l7_bayesian_ci_low": round(float(l7.get("bayesian_ci_low", 0.0)), 4),
            "l7_bayesian_ci_high": round(float(l7.get("bayesian_ci_high", 0.0)), 4),
            "l7_conf12_raw": round(float(l7.get("conf12_raw", 0.0)), 4),
            "l7_mc_passed": bool(l7.get("mc_passed_threshold", False)),
            "l7_validation": str(l7.get("validation", "FAIL")),
            "l7_expected_value": round(float(l7.get("expected_value", 0.0)), 2),
            "l7_max_drawdown": round(float(l7.get("max_drawdown", 0.0)), 2),
        }

    def _compute_confidence_with_l7(
        self,
        base_confidence: float,
        l7_metrics: dict[str, Any],
    ) -> float:
        """Adjust verdict confidence using L7 probability metrics.

        Applies bounded adjustments to base_confidence:
        - High posterior win + low risk-of-ruin → boost (max +0.08)
        - High risk-of-ruin or FAIL validation → penalty (max -0.12)
        - CONDITIONAL validation → mild penalty (-0.04)

        Result is clamped to [0.0, 1.0].

        Authority: Pure computation. No side-effects.
        """
        adjustment = 0.0

        posterior = l7_metrics["l7_posterior_win"]
        ror = l7_metrics["l7_risk_of_ruin"]
        validation = l7_metrics["l7_validation"]
        mc_passed = l7_metrics["l7_mc_passed"]

        # ── Positive adjustments (capped at +0.08) ───────────────────
        if mc_passed and posterior >= 0.60 and ror < 0.10:
            # Strong probability profile: high posterior, low ruin risk
            adjustment += 0.06
        elif mc_passed and posterior >= 0.55:
            adjustment += 0.03

        if ror < 0.05:
            # Very low ruin risk bonus
            adjustment += 0.02

        adjustment = min(adjustment, 0.08)

        # ── Negative adjustments (capped at -0.12) ──────────────────
        penalty = 0.0

        if validation == "FAIL":
            penalty += 0.08
        elif validation == "CONDITIONAL":
            penalty += 0.04

        if ror >= 0.30:
            # Dangerously high ruin risk
            penalty += 0.06
        elif ror >= 0.20:
            penalty += 0.04

        if posterior < 0.45 and posterior > 0.0:
            # Bayesian belief is below coin-flip — penalize
            penalty += 0.04

        penalty = min(penalty, 0.12)

        adjusted = base_confidence + adjustment - penalty
        return round(max(0.0, min(1.0, adjusted)), 4)

    def produce_verdict(
        self,
        symbol: str,
        layer_results: dict[str, Any],
        gate_results: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce the constitutional verdict for a trade candidate.

        This is the SOLE AUTHORITY that decides EXECUTE / HOLD / ABORT.
        L7 probability metrics are advisory inputs that inform confidence.

        Args:
            symbol: Instrument identifier.
            layer_results: Dict of all layer outputs (L1–L11+).
            gate_results: Pre-computed gate results (if available).

        Returns:
            Enriched verdict dict with L7 probability context.
        """
        # ...existing code...

        # ── Extract L7 probability metrics ───────────────────────────
        l7_metrics = self._extract_l7_probability_metrics(layer_results)

        # ── Adjust confidence with L7 data ───────────────────────────
        # base_confidence comes from existing verdict logic (upstream)
        # ...existing code that computes base_confidence...
        confidence = self._compute_confidence_with_l7(
            base_confidence=confidence,  # type: ignore[possibly-undefined]  # noqa: F821
            l7_metrics=l7_metrics,
        )

        # ...existing code that builds the verdict dict...

        # ── Enrich verdict with L7 probability context ───────────────
        # These fields are informational for downstream consumers
        # (dashboard, journal, reflection) — they do NOT change the verdict.
        verdict["probability_context"] = {  # noqa: F821 # pyright: ignore[reportUndefinedVariable]
            "monte_carlo_win_rate": l7_metrics["l7_win_probability"],
            "profit_factor": l7_metrics["l7_profit_factor"],
            "risk_of_ruin": l7_metrics["l7_risk_of_ruin"],
            "bayesian_posterior": l7_metrics["l7_posterior_win"],
            "bayesian_ci": [
                l7_metrics["l7_bayesian_ci_low"],
                l7_metrics["l7_bayesian_ci_high"],
            ],
            "conf12_raw": l7_metrics["l7_conf12_raw"],
            "mc_passed": l7_metrics["l7_mc_passed"],
            "l7_validation": l7_metrics["l7_validation"],
            "expected_value": l7_metrics["l7_expected_value"],
            "max_drawdown": l7_metrics["l7_max_drawdown"],
        }

        verdict["confidence"] = confidence  # pyright: ignore[reportUndefinedVariable] # noqa: F821

        # ...existing code...

        return verdict  # pyright: ignore[reportUndefinedVariable] # noqa: F821
