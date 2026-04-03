"""
L7 Probability Analyzer -- Real Monte Carlo + Bayesian Validation.

Replaces PLACEHOLDER with production bootstrap Monte Carlo engine
and Bayesian posterior update for adaptive win probability.

Sources:
    engines/monte_carlo_engine.py     -> MonteCarloEngine
    engines/bayesian_update_engine.py -> BayesianProbabilityEngine

Gate Logic:
    IF Win% ≥ 55% AND PF ≥ 1.3  -> PASS      -> continue to L8+
    IF Win% ≥ 48% AND PF ≥ 1.1  -> CONDITIONAL -> continue with caution flag
    OTHERWISE                     -> FAIL       -> HOLD (no execution candidate)

Produces:
    - win_probability (float 0-100)
    - profit_factor (float)
    - conf12_raw (float)               -> target ≥ 0.92
    - max_drawdown (float)
    - risk_of_ruin (float)
    - expected_value (float)
    - posterior_win_probability (float)
    - confidence_interval (tuple[float, float])
    - bayesian_posterior (float)        -> alias for L12 synthesis
    - bayesian_ci_low (float)
    - bayesian_ci_high (float)
    - mc_passed_threshold (bool)
    - validation (str)                  -> PASS | CONDITIONAL | FAIL
    - valid (bool)
    - simulations (int)
    - symbol (str)

Authority Boundary:
    ANALYSIS-ONLY. No execution side-effects.
    Layer-12 Constitution is the sole decision authority.
"""  # noqa: N999

from __future__ import annotations

from typing import Any

from loguru import logger

from core.core_fusion._utils import _clamp01
from engines.bayesian_update_engine import (
    BayesianProbabilityEngine,
    BayesianResult,
)
from engines.monte_carlo_engine import (
    MonteCarloEngine,
    MonteCarloResult,
)

# ── Optional Engine Enrichment ────────────────────────────────────────────────
# WalkForwardValidator provides out-of-sample overfitting guard as an
# enrichment layer on top of the MC + Bayesian probability gate.
try:
    from engines.walk_forward_validation_engine import (
        WalkForwardValidator,
    )

    _wf_validator: WalkForwardValidator | None = WalkForwardValidator()
except Exception:  # pragma: no cover
    _wf_validator = None

# ── Sentinel for default wf_validator parameter ─────────────────────────────
_SENTINEL = object()

# ── Gate thresholds ──────────────────────────────────────────────────────────
_MC_WIN_THRESHOLD = 0.55  # Win-rate ≥ 55% -> PASS tier
_MC_WIN_CONDITIONAL = 0.48  # Win-rate ≥ 48% -> CONDITIONAL tier
_PF_THRESHOLD = 1.3  # Profit factor ≥ 1.3 -> PASS tier
_PF_CONDITIONAL = 1.1  # Profit factor ≥ 1.1 -> CONDITIONAL tier
_MIN_TRADES = 30  # Minimum sample for bootstrap MC

# ── CONF12 blending weights ─────────────────────────────────────────────────
_CONF12_W_BAYES = 0.6  # Bayesian posterior weight in conf12_raw
_CONF12_W_MC = 0.4  # MC win probability weight in conf12_raw

# ── Bayesian evidence blending weights ───────────────────────────────────────
_EVIDENCE_W_MC = 0.4  # MC win probability contribution to evidence
_EVIDENCE_W_DVG = 0.3  # Divergence confidence contribution
_EVIDENCE_W_LIQ = 0.3  # Liquidity score contribution


class L7ProbabilityAnalyzer:
    """Layer 7: Real Monte Carlo + Bayesian Probability Validation.

    This layer is the probability gate in the Wolf-15 analysis pipeline.
    It runs bootstrap Monte Carlo simulation over historical trade returns
    and updates a Beta-distributed Bayesian belief about win probability.

    Parameters
    ----------
    simulations : int
        Number of MC bootstrap iterations (default 1000).
    seed : int | None
        RNG seed for deterministic reproducibility.
    """

    def __init__(
        self,
        simulations: int = 1000,
        seed: int | None = 42,
        *,
        mc_simulations: int | None = None,
        mc_seed: int | None = None,
        wf_validator: Any | None = _SENTINEL,
    ) -> None:
        # Accept legacy kwarg names used by older callers / tests
        if mc_simulations is not None:
            simulations = mc_simulations
        if mc_seed is not None:
            seed = mc_seed
        self._mc_engine = MonteCarloEngine(
            simulations=simulations,
            seed=seed,
            min_trades=_MIN_TRADES,
            win_threshold=_MC_WIN_THRESHOLD,
            pf_threshold=_PF_THRESHOLD,
        )
        self._bayesian = BayesianProbabilityEngine(seed=seed)
        self._trade_history: list[float] = []
        # Injectable WF validator: default uses module-level singleton.
        self._wf_validator = _wf_validator if wf_validator is _SENTINEL else wf_validator
        # Upstream output for constitutional governance (Phase 2 / enrichment result)
        self._upstream_output: dict[str, Any] | None = None

    # ── Public API ───────────────────────────────────────────────────────────

    def set_trade_history(self, returns: list[float]) -> None:
        """Inject historical trade returns for bootstrap MC.

        Use this when trade_returns cannot be passed per-call (e.g.,
        shared history across multiple symbol analyses).
        """
        if not isinstance(returns, list | tuple):
            raise TypeError(f"Expected list[float], got {type(returns).__name__}")
        self._trade_history = [float(r) for r in returns]

    def set_upstream_output(self, upstream: dict[str, Any]) -> None:
        """Inject upstream output (Phase 2 / enrichment result) for constitutional governance."""
        self._upstream_output = upstream

    def analyze(
        self,
        symbol: str,
        *,
        technical_score: int = 0,
        trade_returns: list[float] | None = None,
        prior_wins: int = 60,
        prior_losses: int = 40,
        dvg_confidence: float = 0.5,
        liquidity_score: float = 0.5,
        synthetic_returns: bool = False,
    ) -> dict[str, Any]:
        """Run Monte Carlo + Bayesian probability validation.

        Args:
            symbol: Currency pair / instrument identifier.
            technical_score: Upstream technical analysis score (0-100).
                Used only for logging context; not blended into probability.
            trade_returns: Historical per-trade P&L list. If None, falls
                back to ``self._trade_history`` (set via ``set_trade_history``).
            prior_wins: Observed winning trades for Bayesian prior (≥ 0).
            prior_losses: Observed losing trades for Bayesian prior (≥ 0).
            dvg_confidence: Divergence confidence from L9 or upstream (0-1).
            liquidity_score: Liquidity score from L9 or upstream (0-1).
            synthetic_returns: True when returns are derived from candle
                prices (not real trade P&L). Walk-forward enrichment is
                skipped for synthetic returns because WF thresholds assume
                filtered trade outcomes, not raw price deltas.

        Returns:
            dict with full L7 output schema (see module docstring).

        Note:
            This method never raises. On any failure it returns a fail-safe
            fallback result with validation="FAIL" and risk_of_ruin=1.0.
        """
        # Resolve trade returns: explicit > instance > empty
        returns = trade_returns if trade_returns is not None else self._trade_history

        # ── Guard: insufficient data -> graceful fallback ─────────────
        if len(returns) < _MIN_TRADES:
            logger.warning(
                "[L7] {symbol} -- Insufficient trade history ({available}/{required}). Using fallback.",
                symbol=symbol,
                available=len(returns),
                required=_MIN_TRADES,
            )
            return self._apply_constitutional(
                self._fallback_result(symbol, len(returns)),
                symbol,
            )

        try:
            # ── Monte Carlo Bootstrap ────────────────────────────────
            mc_result: MonteCarloResult = self._mc_engine.run(returns)

            # ── Bayesian Evidence Score ──────────────────────────────
            # Blend MC win-rate with upstream signals into a single
            # evidence observation for the Beta-Binomial update.
            # Clamp inputs to [0, 1] defensively.
            _mc_wp = _clamp01(mc_result.win_probability)
            _dvg = _clamp01(dvg_confidence)
            _liq = _clamp01(liquidity_score)

            evidence_score = _mc_wp * _EVIDENCE_W_MC + _dvg * _EVIDENCE_W_DVG + _liq * _EVIDENCE_W_LIQ
            # Final clamp (should already be [0,1] but be explicit)
            evidence_score = _clamp01(evidence_score)

            bayes_result: BayesianResult = self._bayesian.update(
                prior_wins=max(0, prior_wins),
                prior_losses=max(0, prior_losses),
                new_evidence_score=evidence_score,
            )

            # ── Gate Logic ───────────────────────────────────────────
            wp = mc_result.win_probability  # 0.0 - 1.0
            pf = mc_result.profit_factor

            if wp >= _MC_WIN_THRESHOLD and pf >= _PF_THRESHOLD:
                validation = "PASS"
            elif wp >= _MC_WIN_CONDITIONAL and pf >= _PF_CONDITIONAL:
                validation = "CONDITIONAL"
            else:
                validation = "FAIL"

            # ── CONF12 raw score ─────────────────────────────────────
            # Blended confidence for Layer-12 consumption.
            # Bayesian posterior carries more weight (0.6) because it
            # incorporates both prior belief and new MC evidence.
            conf12_raw = bayes_result.posterior_win_probability * _CONF12_W_BAYES + wp * _CONF12_W_MC

            result: dict[str, Any] = {
                # ── Core MC outputs ──────────────────────────────────
                "win_probability": round(wp * 100.0, 2),
                "profit_factor": mc_result.profit_factor,
                "max_drawdown": mc_result.max_drawdown_mean,
                "risk_of_ruin": mc_result.risk_of_ruin,
                "expected_value": mc_result.expected_value,
                "mc_passed_threshold": mc_result.passed_threshold,
                "simulations": mc_result.simulations,
                # ── Bayesian outputs ─────────────────────────────────
                "posterior_win_probability": bayes_result.posterior_win_probability,
                "confidence_interval": (
                    bayes_result.confidence_interval_low,
                    bayes_result.confidence_interval_high,
                ),
                # Aliases for L12 synthesis compatibility
                "bayesian_posterior": bayes_result.posterior_win_probability,
                "bayesian_ci_low": bayes_result.confidence_interval_low,
                "bayesian_ci_high": bayes_result.confidence_interval_high,
                # ── Blended / Derived ────────────────────────────────
                "conf12_raw": round(conf12_raw, 4),
                # ── Gate result ──────────────────────────────────────
                "validation": validation,
                "valid": True,
                # ── Metadata ─────────────────────────────────────────
                "symbol": symbol,
                "returns_source": "synthetic" if synthetic_returns else "trade_history",
            }

            # ── Walk-Forward Enrichment (optional) ───────────────────
            # Skip WF for synthetic (candle-derived) returns: WF thresholds
            # (win_rate ≥ 55%, PF ≥ 1.4) were calibrated for real trade P&L.
            # Raw price returns have ~50% win rate by nature → always fails.
            if self._wf_validator is not None and len(returns) >= 130 and not synthetic_returns:
                try:
                    wf_result = self._wf_validator.run(returns)
                    result["wf_passed"] = wf_result.passed
                    result["wf_stability_score"] = wf_result.stability_score
                    result["wf_avg_win_rate"] = wf_result.avg_win_rate
                    result["wf_regime_consistency"] = wf_result.regime_consistency
                    result["wf_avg_profit_factor"] = wf_result.avg_profit_factor
                    # Downgrade validation tier if walk-forward fails
                    if not wf_result.passed:
                        if validation == "PASS":
                            result["validation"] = "CONDITIONAL"
                            validation = "CONDITIONAL"
                        elif validation == "CONDITIONAL":
                            result["validation"] = "FAIL"
                            validation = "FAIL"
                        logger.warning(
                            "[L7] {symbol} WF validation failed — downgraded to {validation}",
                            symbol=symbol,
                            validation=validation,
                        )
                except Exception as wf_exc:
                    logger.warning(
                        "[L7] Walk-forward enrichment failed: {exc}",
                        exc=wf_exc,
                    )
                    # Populate WF fields with defaults so downstream
                    # consumers always see a consistent schema.
                    result.setdefault("wf_passed", None)
                    result.setdefault("wf_stability_score", None)
                    result.setdefault("wf_avg_win_rate", None)
                    result.setdefault("wf_regime_consistency", None)
                    result.setdefault("wf_avg_profit_factor", None)
            elif synthetic_returns and self._wf_validator is not None and len(returns) >= 130:
                logger.info(
                    "[L7] {symbol} WF skipped — returns are candle-derived (synthetic), not real trade P&L",
                    symbol=symbol,
                )
                result["wf_passed"] = None
                result["wf_skipped_reason"] = "synthetic_returns"

            logger.info(
                "[L7] {symbol} -> {validation} | "
                "win={wp:.1f}% pf={pf:.2f} conf12={conf12:.4f} "
                "bayes={bayes:.4f} [{ci_lo:.4f}, {ci_hi:.4f}] "
                "ror={ror:.4f} ev={ev:.2f} dd={dd:.2f} "
                "mc_passed={mc_pass} sims={sims}",
                symbol=symbol,
                validation=validation,
                wp=result["win_probability"],
                pf=result["profit_factor"],
                conf12=result["conf12_raw"],
                bayes=result["bayesian_posterior"],
                ci_lo=result["bayesian_ci_low"],
                ci_hi=result["bayesian_ci_high"],
                ror=result["risk_of_ruin"],
                ev=result["expected_value"],
                dd=result["max_drawdown"],
                mc_pass=result["mc_passed_threshold"],
                sims=result["simulations"],
            )

            return self._apply_constitutional(result, symbol)

        except Exception as exc:
            logger.error(
                "[L7] Monte Carlo/Bayesian failed for {symbol}: {exc}",
                symbol=symbol,
                exc=exc,
            )
            return self._apply_constitutional(
                self._fallback_result(symbol, len(returns)),
                symbol,
            )

    # ── Private helpers ──────────────────────────────────────────────────────

    def _fallback_result(
        self,
        symbol: str,
        available_trades: int,
    ) -> dict[str, Any]:
        """Graceful degradation when MC cannot run.

        Returns a fail-safe result dict with:
        - validation = "FAIL"
        - risk_of_ruin = 1.0 (worst case assumption)
        - All probability fields zeroed
        - ``note`` field explaining the degradation reason

        This ensures downstream gates (Gate 2, L12) will correctly
        block any trade candidate that lacks validated probability data.
        """
        return {
            # ── Core MC outputs (zeroed) ─────────────────────────────
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "risk_of_ruin": 1.0,  # Worst case: fail-safe
            "expected_value": 0.0,
            "mc_passed_threshold": False,
            "simulations": 0,
            # ── Bayesian outputs (zeroed) ────────────────────────────
            "posterior_win_probability": 0.0,
            "confidence_interval": (0.0, 0.0),
            "bayesian_posterior": 0.0,
            "bayesian_ci_low": 0.0,
            "bayesian_ci_high": 0.0,
            # ── Blended / Derived ────────────────────────────────────
            "conf12_raw": 0.0,
            # ── Gate result ──────────────────────────────────────────
            "validation": "FAIL",
            "valid": True,  # Layer executed successfully
            # ── Metadata ─────────────────────────────────────────────
            "symbol": symbol,
            "note": f"insufficient_data_{available_trades}/{_MIN_TRADES}",
        }

    # ── Constitutional Governance Wrapper ────────────────────────────
    def _apply_constitutional(
        self,
        raw_result: dict[str, Any],
        symbol: str,
    ) -> dict[str, Any]:
        """Wrap raw L7 output with constitutional governance envelope.

        Follows the same pattern as L4/L5 constitutional wrappers:
        lazy-import governor → evaluate → merge → map valid.
        """
        try:
            from analysis.layers.L7_constitutional import L7ConstitutionalGovernor

            gov = L7ConstitutionalGovernor()
            upstream = self._upstream_output or {}

            envelope = gov.evaluate(
                l7_analysis=raw_result,
                upstream_output=upstream,
            )

            raw_result["constitutional"] = envelope
            raw_result["continuation_allowed"] = envelope.get(
                "continuation_allowed",
                True,
            )

            status = envelope.get("status", "PASS")
            if status == "FAIL":
                raw_result["valid"] = False
            # WARN degrades but does not block

            logger.info(
                "[L7] {symbol} constitutional: status={status} continuation={cont} band={band}",
                symbol=symbol,
                status=status,
                cont=envelope.get("continuation_allowed", True),
                band=envelope.get("coherence_band", "N/A"),
            )

        except Exception as exc:
            logger.warning(
                "[L7] Constitutional governor failed — raw result preserved: {exc}",
                exc=exc,
            )
            raw_result["constitutional"] = {"error": str(exc)}
            raw_result["continuation_allowed"] = True

        return raw_result
