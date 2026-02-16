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

    # ─── Enrichment-aware confidence adjustment (advisory) ───
    # Enrichment engines (cognitive, quantum, fusion, etc.) produce
    # an enrichment_score in [0, 1].  This is ADVISORY -- it adjusts
    # the confidence tier but NEVER overrides the verdict itself.
    enrichment_score = layers.get("enrichment_score", 0.0)
    enrichment_applied = False

    if isinstance(enrichment_score, (int, float)) and enrichment_score > 0:
        if verdict.startswith("EXECUTE"):  # pyright: ignore[reportPossiblyUnboundVariable]
            if enrichment_score >= 0.75 and confidence == "HIGH":  # pyright: ignore[reportPossiblyUnboundVariable]
                confidence = "VERY_HIGH"
                enrichment_applied = True
            elif enrichment_score < 0.30 and confidence in ("HIGH", "VERY_HIGH"):  # pyright: ignore[reportPossiblyUnboundVariable]
                confidence = "MEDIUM"
                enrichment_applied = True
        elif verdict == "HOLD" and enrichment_score < 0.20:  # pyright: ignore[reportPossiblyUnboundVariable]
            # Very low engine agreement reinforces HOLD
            enrichment_applied = True  # confidence stays MEDIUM, logged only

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
            "enrichment_score": enrichment_score,
        },
        "enrichment_applied": enrichment_applied,
        "proceed_to_L13": verdict.startswith("EXECUTE"), # pyright: ignore[reportPossiblyUnboundVariable]
    }

    return l12_output


class VerdictEngine:
    """Layer-12 Constitutional Verdict Engine -- sole decision authority.

    Enhancement (Tier 2):
        ✅ Gate 11: Kelly Edge Gate (optional, enabled via config)
        When DynamicPositionSizingEngine reports edge_negative=True,
        verdict is forced to NO_TRADE regardless of other gate scores.
        This is a CONSTITUTIONAL SAFETY gate, not a market opinion.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._kelly_gate_enabled = self._config.get(
            "kelly_edge_gate_enabled", False
        )
        self.analyzers: list = []

    def _extract_l7_probability_metrics(
        self, layer_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract and normalize L7 Monte Carlo + Bayesian metrics.

        Returns a flat dict of validated L7 fields with fail-safe defaults.
        These are ADVISORY inputs to the verdict -- they inform confidence
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
        - High posterior win + low risk-of-ruin -> boost (max +0.08)
        - High risk-of-ruin or FAIL validation -> penalty (max -0.12)
        - CONDITIONAL validation -> mild penalty (-0.04)

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
            # Bayesian belief is below coin-flip -- penalize
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
            layer_results: Dict of all layer outputs (L1-L11+).
            gate_results: Pre-computed gate results (if available).

        Returns:
            Enriched verdict dict with L7 probability context.
        """
        # ── Evaluate gates if not pre-computed ───────────────────────
        if gate_results is None:
            gate_results = {}

        passed_count = sum(
            1 for v in gate_results.values()
            if isinstance(v, dict) and v.get("passed", False)
        )
        total_gates = max(len(gate_results), 1)

        # ── Determine base verdict from gate pass rate ───────────────
        pass_rate = passed_count / total_gates
        if pass_rate >= 0.9:
            verdict_label = "EXECUTE"
            base_confidence = 0.70 + 0.20 * pass_rate  # 0.88-0.90
        elif pass_rate >= 0.7:
            verdict_label = "HOLD"
            base_confidence = 0.40 + 0.20 * pass_rate  # 0.54-0.58
        else:
            verdict_label = "NO_TRADE"
            base_confidence = max(0.10, 0.30 * pass_rate)

        # ── Extract L7 probability metrics ───────────────────────────
        l7_metrics = self._extract_l7_probability_metrics(layer_results)

        # ── Adjust confidence with L7 data ───────────────────────────
        confidence = self._compute_confidence_with_l7(
            base_confidence=base_confidence,
            l7_metrics=l7_metrics,
        )

        # ── Build verdict dict ───────────────────────────────────────
        verdict: dict[str, Any] = {
            "symbol": symbol,
            "verdict": verdict_label,
            "confidence": confidence,
            "gate_results": gate_results,
            "gates_passed": passed_count,
            "gates_total": total_gates,
        }

        # ── Enrich verdict with L7 probability context ───────────────
        # These fields are informational for downstream consumers
        # (dashboard, journal, reflection) -- they do NOT change the verdict.
        verdict["probability_context"] = {
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

        return verdict

    def evaluate(
        self,
        gate_scores: dict,
        kelly_edge_data: dict | None = None,
    ) -> dict:
        """Evaluate all constitutional gates and produce verdict.

        Args:
            gate_scores: Dict of gate_name -> score/pass from L1-L11.
            kelly_edge_data: Optional dict from DynamicPositionSizingEngine.
                Expected keys: {"edge_negative": bool, "kelly_raw": float,
                                "final_fraction": float}
                If None, Gate 11 is skipped (backward-compatible).

        Returns:
            Verdict dict with 'verdict', 'confidence', 'gate_results', etc.
        """
        gate_results: dict[str, Any] = {}
        violations: list[str] = []

        # ── Evaluate gates from scores ───────────────────────────────
        for gate_name, score in gate_scores.items():
            if isinstance(score, dict):
                passed = score.get("passed", False)
            elif isinstance(score, (int, float)):
                passed = score >= 0.5
            else:
                passed = bool(score)
            gate_results[gate_name] = {"passed": passed, "score": score}
            if not passed:
                violations.append(gate_name)

        # ── Gate 11: Kelly Edge Gate (Optional) ──────────────────────
        if self._kelly_gate_enabled and kelly_edge_data is not None:
            gate_11 = self._evaluate_kelly_edge_gate(kelly_edge_data)
            gate_results["gate_11_kelly_edge"] = gate_11
            if not gate_11["passed"]:
                violations.append("GATE_11_KELLY_NO_EDGE")

        # ── Determine verdict from violations ────────────────────────
        if violations:
            verdict = "NO_TRADE"
            confidence = max(0.10, 0.50 - 0.05 * len(violations))
        else:
            verdict = "EXECUTE"
            confidence = 0.80 + 0.02 * len(gate_results)
            confidence = min(confidence, 1.0)

        return {
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "gate_results": gate_results,
            "violations": violations,
        }

    def _evaluate_kelly_edge_gate(self, kelly_edge_data: dict) -> dict:
        """Gate 11: Kelly Edge Verification.

        Constitutional safety gate that prevents trading when the
        DynamicPositionSizingEngine determines there is no statistical
        edge (Kelly fraction ≤ 0).

        This is NOT a market opinion -- it's a mathematical statement:
        "Given the observed win rate and payoff ratio, risking capital
        has negative expected geometric growth."

        Args:
            kelly_edge_data: Must contain at minimum:
                - edge_negative (bool): True if Kelly raw ≤ 0
                - kelly_raw (float): Raw Kelly fraction

        Returns:
            Gate result dict with passed, reason, and diagnostics.
        """
        edge_negative = kelly_edge_data.get("edge_negative", False)
        kelly_raw = kelly_edge_data.get("kelly_raw", 0.0)
        final_fraction = kelly_edge_data.get("final_fraction", 0.0)

        if edge_negative:
            return {
                "passed": False,
                "gate": "GATE_11_KELLY_EDGE",
                "reason": (
                    f"No statistical edge detected. "
                    f"Kelly raw = {kelly_raw:.4f} (negative). "
                    f"Trading would produce negative geometric growth."
                ),
                "kelly_raw": kelly_raw,
                "final_fraction": final_fraction,
                "severity": "HARD_BLOCK",
            }

        return {
            "passed": True,
            "gate": "GATE_11_KELLY_EDGE",
            "reason": f"Kelly edge confirmed: raw = {kelly_raw:.4f}",
            "kelly_raw": kelly_raw,
            "final_fraction": final_fraction,
            "severity": "NONE",
        }


class _LegacyVerdictPipeline:
    """DEPRECATED: Use pipeline.WolfConstitutionalPipeline instead.

    Simplified verdict-only wrapper kept for backward compatibility.
    Do NOT import this directly — use the real v8.0 pipeline.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._kelly_gate_enabled = self._config.get(
            "kelly_edge_gate_enabled", False
        )
        self.analyzers: list = []

    def _run_analysis(self, symbol: str, timeframe: str, context: dict) -> dict:
        """Run L1-L11 analysis layers and return aggregated scores."""
        scores = {}
        if hasattr(self, 'analyzers'):
            for analyzer in self.analyzers:
                try:
                    result = analyzer.analyze(symbol, timeframe, context)
                    scores.update(result or {})
                except Exception as e:
                    scores[analyzer.__class__.__name__] = {"error": str(e)}
        return scores

    def _evaluate_verdict(self, symbol: str, analysis_result: dict, context: dict) -> dict:
        """L12 constitutional gate: evaluate analysis and produce verdict."""
        wolf_score = analysis_result.get("wolf_score", 0.0)
        tii_score = analysis_result.get("tii_score", 0.0)
        frpc_score = analysis_result.get("frpc_score", 0.0)

        confidence = (wolf_score + tii_score + frpc_score) / 3.0 if any([wolf_score, tii_score, frpc_score]) else 0.0

        # Constitutional threshold
        threshold = getattr(self, 'threshold', 0.6)

        if confidence >= threshold:
            direction = analysis_result.get("direction", "LONG")
            verdict_value = "EXECUTE"
        else:
            direction = None
            verdict_value = "NO_TRADE"

        verdict = {
            "symbol": symbol,
            "verdict": verdict_value,
            "confidence": round(confidence, 4),
            "direction": direction,
            "scores": {
                "wolf_score": wolf_score,
                "tii_score": tii_score,
                "frpc_score": frpc_score,
            },
            "entry_price": analysis_result.get("entry_price"),
            "stop_loss": analysis_result.get("stop_loss"),
            "take_profit_1": analysis_result.get("take_profit_1"),
        }

        return verdict

    def run(self, symbol: str, timeframe: str = "H1", context: dict | None = None) -> dict:
        """Run the full constitutional pipeline for a symbol.

        Returns a Layer-12 verdict dict with at minimum:
        symbol, verdict, confidence.
        """
        context = context or {}

        # Run L1-L11: Gather analysis scores
        analysis = self._run_analysis(symbol, timeframe, context)

        # L12: Constitutional gate — single decision authority
        verdict = self._evaluate_verdict(symbol, analysis, context)

        # Enforce minimal schema
        verdict.setdefault("symbol", symbol)
        verdict.setdefault("verdict", "NO_TRADE")
        verdict.setdefault("confidence", 0.0)
        verdict.setdefault("timeframe", timeframe)

        return verdict
