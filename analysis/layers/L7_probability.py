"""
L7 Probability Analyzer - Monte Carlo FTTC Validation.

Sources:
    engines/monte_carlo_engine.py     → MonteCarloEngine
    engines/bayesian_update_engine.py → BayesianProbabilityEngine
    core_fusion_unified.py            → MonteCarloConfidence, FTTCMonteCarloEngine

Gate Logic:
    IF Win% < 60% OR RR < 1:2 → FAIL → HOLD
    IF Win% ≥ 60% AND RR ≥ 1:2 → PASS → continue

Produces:
    - win_probability (float 0-100)
    - profit_factor (float)
    - conf12_raw (float)      → target ≥ 0.92
    - max_drawdown (float)
    - validation (str)        → PASS | CONDITIONAL | FAIL
    - valid (bool)
    - bayesian_posterior (float)
    - bayesian_ci_low (float)
    - bayesian_ci_high (float)
    - risk_of_ruin (float)
    - expected_value (float)
    - mc_passed_threshold (bool)
"""

from __future__ import annotations

import logging

from typing import Any

logger = logging.getLogger(__name__)

# ── Core fusion (optional, for CONF12 enrichment) ────────────────────────────
try:
    import core.core_fusion_unified as _core_fusion  # pyright: ignore[reportMissingImports]
except ImportError:
    _core_fusion = None  # type: ignore[assignment]

# ── Production engines ───────────────────────────────────────────────────────
from engines.bayesian_update_engine import (  # pyright: ignore[reportMissingImports] # noqa: E402
    BayesianProbabilityEngine,
    BayesianResult,
)

from engines.monte_carlo_engine import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    MonteCarloEngine,
    MonteCarloResult,
)

# ── Gate thresholds ──────────────────────────────────────────────────────────
_WIN_PASS = 60.0          # Win% ≥ 60 → PASS
_WIN_CONDITIONAL = 50.0   # Win% ≥ 50 → CONDITIONAL
_PF_PASS = 1.5            # Profit factor ≥ 1.5 → PASS
_PF_CONDITIONAL = 1.2     # Profit factor ≥ 1.2 → CONDITIONAL
_CONF12_TARGET = 0.92     # Target conf12_raw
_MIN_TRADES = 30          # Minimum sample size for MC


class L7ProbabilityAnalyzer:
    """Layer 7: Monte Carlo FTTC Validation - Probability & Validation zone."""

    def __init__(
        self,
        mc_simulations: int = 1000,
        mc_seed: int | None = 42,
        bayesian_seed: int | None = 42,
    ) -> None:
        self._mc_engine = MonteCarloEngine(
            simulations=mc_simulations, seed=mc_seed
        )
        self._bayesian_engine = BayesianProbabilityEngine(seed=bayesian_seed)
        self._mc_confidence: Any = None
        self._fttc_engine: Any = None

    def _ensure_core_loaded(self) -> None:
        """Attempt lazy-load of core fusion modules for CONF12 enrichment."""
        if self._mc_confidence is not None:
            return
        try:
            if _core_fusion is None:
                raise ImportError("core.core_fusion_unified not available")
            self._mc_confidence = _core_fusion.MonteCarloConfidence()
            self._fttc_engine = _core_fusion.FTTCMonteCarloEngine()
        except Exception as exc:
            logger.debug("[L7] Core fusion modules unavailable: %s", exc)

    def analyze(
        self,
        symbol: str,
        *,
        technical_score: int = 0,
        trade_returns: list[float] | None = None,
        prior_wins: int = 0,
        prior_losses: int = 0,
        coherence: float = 50.0,
        volatility_index: float = 20.0,
        base_bias: float = 0.5,
    ) -> dict[str, Any]:
        """
        Run Monte Carlo + Bayesian probability validation.

        Args:
            symbol: Currency pair / instrument identifier.
            technical_score: Upstream technical score (0-100).
            trade_returns: Historical per-trade P&L list (required for MC).
            prior_wins: Number of prior winning trades (for Bayesian).
            prior_losses: Number of prior losing trades (for Bayesian).
            coherence: Layer coherence score (0-100) for CONF12.
            volatility_index: Volatility index for CONF12.
            base_bias: Base directional bias (0-1) for CONF12.

        Returns:
            dict with keys: win_probability, profit_factor, conf12_raw,
            max_drawdown, validation, valid, bayesian_posterior,
            bayesian_ci_low, bayesian_ci_high, risk_of_ruin,
            expected_value, mc_passed_threshold
        """
        result: dict[str, Any] = {
            "symbol": symbol,
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "conf12_raw": 0.0,
            "max_drawdown": 0.0,
            "validation": "FAIL",
            "valid": True,
            "bayesian_posterior": 0.0,
            "bayesian_ci_low": 0.0,
            "bayesian_ci_high": 0.0,
            "risk_of_ruin": 0.0,
            "expected_value": 0.0,
            "mc_passed_threshold": False,
        }

        # ── Monte Carlo simulation ───────────────────────────────────────
        mc_result: MonteCarloResult | None = None
        if trade_returns and len(trade_returns) >= _MIN_TRADES:
            try:
                mc_result = self._mc_engine.run(trade_returns)
                result["win_probability"] = mc_result.win_probability * 100.0 # pyright: ignore[reportOptionalMemberAccess]
                result["profit_factor"] = mc_result.profit_factor # pyright: ignore[reportOptionalMemberAccess]
                result["max_drawdown"] = abs(mc_result.max_drawdown_mean) # pyright: ignore[reportOptionalMemberAccess]
                result["risk_of_ruin"] = mc_result.risk_of_ruin # pyright: ignore[reportOptionalMemberAccess]
                result["expected_value"] = mc_result.expected_value # pyright: ignore[reportOptionalMemberAccess]
                result["mc_passed_threshold"] = mc_result.passed_threshold # pyright: ignore[reportOptionalMemberAccess]
                logger.info(
                    "[L7] %s MC: win=%.1f%% pf=%.2f dd=%.2f ruin=%.4f",
                    symbol,
                    result["win_probability"],
                    result["profit_factor"],
                    result["max_drawdown"],
                    result["risk_of_ruin"],
                )
            except ValueError as exc:
                logger.warning("[L7] %s MC skipped: %s", symbol, exc)
        else:
            logger.info(
                "[L7] %s MC skipped: insufficient trades (%d < %d)",
                symbol,
                len(trade_returns) if trade_returns else 0,
                _MIN_TRADES,
            )

        # ── Bayesian update ──────────────────────────────────────────────
        evidence_score = technical_score / 100.0 if technical_score > 0 else 0.5
        try:
            bay_result: BayesianResult = self._bayesian_engine.update(
                prior_wins=prior_wins,
                prior_losses=prior_losses,
                new_evidence_score=evidence_score,
            )
            result["bayesian_posterior"] = bay_result.posterior_win_probability
            result["bayesian_ci_low"] = bay_result.confidence_interval_low
            result["bayesian_ci_high"] = bay_result.confidence_interval_high
        except ValueError as exc:
            logger.warning("[L7] %s Bayesian skipped: %s", symbol, exc)

        # ── CONF12 enrichment (optional core fusion) ─────────────────────
        self._ensure_core_loaded()
        if self._mc_confidence is not None:
            try:
                conf_result = self._mc_confidence.run(
                    base_bias=base_bias,
                    coherence=coherence,
                    volatility_index=volatility_index,
                )
                result["conf12_raw"] = conf_result.conf12_raw
            except Exception as exc:
                logger.debug("[L7] %s CONF12 enrichment failed: %s", symbol, exc)

        # ── Gate logic ───────────────────────────────────────────────────
        win_pct = result["win_probability"]
        pf = result["profit_factor"]

        if win_pct >= _WIN_PASS and pf >= _PF_PASS:
            result["validation"] = "PASS"
        elif win_pct >= _WIN_CONDITIONAL and pf >= _PF_CONDITIONAL:
            result["validation"] = "CONDITIONAL"
        else:
            result["validation"] = "FAIL"

        # valid=True always (layer ran successfully; validation carries the gate)
        result["valid"] = True

        logger.info(
            "[L7] %s → %s (win=%.1f%% pf=%.2f conf12=%.4f bayes=%.4f)",
            symbol,
            result["validation"],
            win_pct,
            pf,
            result["conf12_raw"],
            result["bayesian_posterior"],
        )

        return result
