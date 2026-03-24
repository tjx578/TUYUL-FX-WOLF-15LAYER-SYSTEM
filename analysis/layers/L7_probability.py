"""
L7 Probability Analyzer -- Real Monte Carlo + Bayesian Validation.

Replaces PLACEHOLDER with production bootstrap Monte Carlo engine
and Bayesian posterior update for adaptive win probability.

Sources:
    engines/monte_carlo_engine.py     -> MonteCarloEngine
    engines/bayesian_update_engine.py -> BayesianProbabilityEngine

Gate Logic:
    IF Win% ≥ 60% AND PF ≥ 1.5  -> PASS      -> continue to L8+
    IF Win% ≥ 55% AND PF ≥ 1.2  -> CONDITIONAL -> continue with caution flag
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

# ── Gate thresholds ──────────────────────────────────────────────────────────
_MC_WIN_THRESHOLD = 0.60  # Win-rate ≥ 60% -> PASS tier
_MC_WIN_CONDITIONAL = 0.55  # Win-rate ≥ 55% -> CONDITIONAL tier
_PF_THRESHOLD = 1.5  # Profit factor ≥ 1.5 -> PASS tier
_PF_CONDITIONAL = 1.2  # Profit factor ≥ 1.2 -> CONDITIONAL tier
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

    # ── Public API ───────────────────────────────────────────────────────────

    def set_trade_history(self, returns: list[float]) -> None:
        """Inject historical trade returns for bootstrap MC.

        Use this when trade_returns cannot be passed per-call (e.g.,
        shared history across multiple symbol analyses).
        """
        if not isinstance(returns, list | tuple):
            raise TypeError(f"Expected list[float], got {type(returns).__name__}")
        self._trade_history = [float(r) for r in returns]

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
            return self._fallback_result(symbol, len(returns))

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
            }

            # ── Walk-Forward Enrichment (optional) ───────────────────
            if _wf_validator is not None and len(returns) >= 130:
                try:
                    wf_result = _wf_validator.run(returns)
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

            return result

        except Exception as exc:
            logger.error(
                "[L7] Monte Carlo/Bayesian failed for {symbol}: {exc}",
                symbol=symbol,
                exc=exc,
            )
            return self._fallback_result(symbol, len(returns))

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
