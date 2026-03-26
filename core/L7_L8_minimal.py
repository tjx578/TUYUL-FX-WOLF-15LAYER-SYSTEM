"""
Minimal / pipeline-adapted L7 + L8 analyzers.

Called from pipeline layers when:
- Full engines unavailable (ImportError fallback for L7)
- L8 needs pipeline-compatible calling convention (symbol as first arg)

FIX 1 — L8PipelineAdapter:
    L8TIIIntegrityAnalyzer.analyze(layer_outputs: dict) does not match the
    pipeline's per-layer calling convention (symbol, **kwargs).  The pipeline
    calls ``_timed_layer_call(engine.analyze, "L8", symbol)``, which passes
    ``symbol`` (a string) as ``layer_outputs`` → AttributeError.
    L8PipelineAdapter wraps the real analyzer, accepts (symbol, *, l1, l3,
    market_data, indicators) and builds the proper dict.

FIX 2 — L7MinimalAnalyzer:
    Lightweight L7 without heavy Monte Carlo / Bayesian engine deps.
    Returns same output schema so downstream L12 synthesis is unaffected.
    Used as fallback when ``engines.monte_carlo_engine`` is unavailable.

Zone: core/ -- bridge/adapter module.  No execution side-effects.
"""  # noqa: N999

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, Final

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

__all__ = [
    "L7MinimalAnalyzer",
    "L8PipelineAdapter",
    "get_l7_analyzer",
    "get_l8_adapter",
]


# ═══════════════════════════════════════════════════════════════════════════
# §1  L7 MINIMAL ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

# Gate thresholds (mirror ``analysis.layers.L7_probability``)
_MC_WIN_THRESHOLD: Final[float] = 0.60
_MC_WIN_CONDITIONAL: Final[float] = 0.55
_PF_THRESHOLD: Final[float] = 1.5
_PF_CONDITIONAL: Final[float] = 1.2
_MIN_TRADES: Final[int] = 30


class L7MinimalAnalyzer:
    """Lightweight L7 — statistical heuristic, no Monte Carlo dependency.

    Same ``analyze()`` signature and output schema as
    ``analysis.layers.L7_probability.L7ProbabilityAnalyzer`` so that
    downstream L12 synthesis is unaffected.

    This is a degraded-mode fallback; results are conservative
    (biases toward FAIL / reduced confidence).
    """

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
        """Run lightweight probability estimation.

        Falls back to simple win-rate / profit-factor computation
        directly from trade_returns without Monte Carlo resampling.
        """
        returns = trade_returns or []

        if len(returns) < _MIN_TRADES:
            logger.warning(
                "[L7-minimal] %s insufficient trades (%d/%d) — FAIL fallback",
                symbol,
                len(returns),
                _MIN_TRADES,
            )
            return self._fallback_result(symbol, len(returns))

        try:
            # ── Simple win-rate / PF from raw returns ────────────────
            wins = [r for r in returns if r > 0]
            losses = [r for r in returns if r <= 0]
            n_trades = len(returns)

            win_rate = len(wins) / n_trades if n_trades > 0 else 0.0
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = abs(sum(losses) / len(losses)) if losses else 1.0
            profit_factor = avg_win / avg_loss if avg_loss > 0 else 0.0

            # ── Risk of ruin (simplified Kelly-based estimate) ───────
            if win_rate > 0 and profit_factor > 0:
                edge = win_rate * profit_factor - (1.0 - win_rate)
                risk_of_ruin = max(0.0, min(1.0, math.exp(-2.0 * edge * n_trades / 100.0)))
            else:
                risk_of_ruin = 1.0

            # ── Gate logic (same thresholds as full L7) ──────────────
            if win_rate >= _MC_WIN_THRESHOLD and profit_factor >= _PF_THRESHOLD:
                validation = "PASS"
            elif win_rate >= _MC_WIN_CONDITIONAL and profit_factor >= _PF_CONDITIONAL:
                validation = "CONDITIONAL"
            else:
                validation = "FAIL"

            # ── Bayesian approximation ───────────────────────────────
            total_prior = max(1, prior_wins + prior_losses)
            posterior = (prior_wins + len(wins)) / (total_prior + n_trades)
            ci_half = 1.96 * math.sqrt(posterior * (1 - posterior) / max(1, n_trades))
            ci_low = max(0.0, posterior - ci_half)
            ci_high = min(1.0, posterior + ci_half)

            # Conf12 blend (mirrors full L7 weighting)
            conf12_raw = posterior * 0.6 + win_rate * 0.4

            # ── Expected value ───────────────────────────────────────
            expected_value = sum(returns) / n_trades if n_trades > 0 else 0.0
            max_drawdown = self._estimate_max_drawdown(returns)

            result: dict[str, Any] = {
                "win_probability": round(win_rate * 100.0, 2),
                "profit_factor": round(profit_factor, 4),
                "max_drawdown": round(max_drawdown, 4),
                "risk_of_ruin": round(risk_of_ruin, 4),
                "expected_value": round(expected_value, 4),
                "mc_passed_threshold": validation == "PASS",
                "simulations": 0,
                "posterior_win_probability": round(posterior, 4),
                "confidence_interval": (round(ci_low, 4), round(ci_high, 4)),
                "bayesian_posterior": round(posterior, 4),
                "bayesian_ci_low": round(ci_low, 4),
                "bayesian_ci_high": round(ci_high, 4),
                "conf12_raw": round(conf12_raw, 4),
                "validation": validation,
                "valid": True,
                "symbol": symbol,
                "note": "minimal_analyzer",
            }

            logger.info(
                "[L7-minimal] %s -> %s | win=%.1f%% pf=%.2f conf12=%.4f bayes=%.4f ror=%.4f",
                symbol,
                validation,
                result["win_probability"],
                result["profit_factor"],
                result["conf12_raw"],
                result["bayesian_posterior"],
                result["risk_of_ruin"],
            )
            return result

        except Exception as exc:
            logger.error("[L7-minimal] {} analysis failed: {}", symbol, exc)
            return self._fallback_result(symbol, len(returns))

    @staticmethod
    def _estimate_max_drawdown(returns: list[float]) -> float:
        """Estimate max drawdown from cumulative return curve."""
        if not returns:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for r in returns:
            cumulative += r
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _fallback_result(symbol: str, available: int) -> dict[str, Any]:
        """Fail-safe result matching full L7 schema."""
        return {
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "risk_of_ruin": 1.0,
            "expected_value": 0.0,
            "mc_passed_threshold": False,
            "simulations": 0,
            "posterior_win_probability": 0.0,
            "confidence_interval": (0.0, 0.0),
            "bayesian_posterior": 0.0,
            "bayesian_ci_low": 0.0,
            "bayesian_ci_high": 0.0,
            "conf12_raw": 0.0,
            "validation": "FAIL",
            "valid": True,
            "symbol": symbol,
            "note": f"minimal_fallback_{available}/{_MIN_TRADES}",
        }


# ═══════════════════════════════════════════════════════════════════════════
# §2  L8 PIPELINE ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class L8PipelineAdapter:
    """Pipeline-compatible adapter for L8TIIIntegrityAnalyzer.

    The real ``L8TIIIntegrityAnalyzer.analyze(layer_outputs: dict)`` expects
    a dict, but the pipeline's ``_timed_layer_call`` passes ``symbol`` as the
    first positional arg (matching L1-L7-L9 convention).

    This adapter:
    - Accepts ``(symbol, *, l1=..., l3=..., indicators=..., market_data=...)``
    - Builds the ``layer_outputs`` dict that the inner analyzer expects
    - Delegates to the real L8TIIIntegrityAnalyzer

    If the real analyzer can't be imported, falls back to a minimal TII
    computation using L8's standalone ``analyze_tii`` path.
    """

    def __init__(self, gate_threshold: float = 0.60) -> None:
        self._gate_threshold = gate_threshold
        self._inner: Any = None
        try:
            from analysis.layers.L8_tii_integrity import L8TIIIntegrityAnalyzer

            self._inner = L8TIIIntegrityAnalyzer(gate_threshold=gate_threshold)
        except ImportError:
            logger.warning("[L8-adapter] L8TIIIntegrityAnalyzer unavailable — using minimal path")

    def analyze(
        self,
        symbol_or_outputs: str | dict[str, Any],
        *,
        l1: dict[str, Any] | None = None,
        l3: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        market_data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyze TII with pipeline-compatible calling convention.

        Args:
            symbol_or_outputs: Either a symbol string (pipeline convention)
                or a dict (direct L8 convention).  Both are handled.
            l1: L1 context result (regime_confidence, etc.).
            l3: L3 technical result (trq3d_energy, trend, etc.).
            indicators: Technical indicators (mfi, cci, rsi, momentum).
            market_data: Dict with ``closes`` list.
            **kwargs: Additional layer outputs forwarded to inner analyzer.
        """
        # ── If already a dict, delegate directly ─────────────────────
        if isinstance(symbol_or_outputs, dict):
            layer_outputs = symbol_or_outputs
        else:
            # Build layer_outputs dict from keyword args
            layer_outputs = self._build_layer_outputs(
                l1=l1,
                l3=l3,
                indicators=indicators,
                market_data=market_data,
                **kwargs,
            )

        if self._inner is not None:
            return self._inner.analyze(layer_outputs)

        # Minimal fallback when L8TIIIntegrityAnalyzer unavailable
        return self._minimal_tii(symbol_or_outputs if isinstance(symbol_or_outputs, str) else "UNKNOWN")

    @staticmethod
    def _build_layer_outputs(
        *,
        l1: dict[str, Any] | None = None,
        l3: dict[str, Any] | None = None,
        indicators: dict[str, Any] | None = None,
        market_data: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Build the ``layer_outputs`` dict from individual phase results."""
        outputs: dict[str, Any] = {}

        if market_data:
            outputs["market_data"] = market_data

        if l1:
            outputs["l1"] = l1

        if l3:
            outputs["l3"] = {
                "vwap": l3.get("vwap", 0.0),
                "energy": l3.get("trq3d_energy", l3.get("energy", 0.0)),
                "bias_strength": l3.get("bias_strength", l3.get("trend_strength", 0.0)),
            }
            # If market_data not provided, try to extract closes from L3 context
            if "market_data" not in outputs:
                _closes = l3.get("closes", l3.get("close", []))
                if _closes:
                    outputs["market_data"] = {"closes": _closes}

        if indicators:
            outputs["indicators"] = indicators

        # Forward any extra keys (frpc, tii_score, etc.)
        for k, v in extra.items():
            if v is not None:
                outputs[k] = v

        return outputs

    @staticmethod
    def _minimal_tii(symbol: str) -> dict[str, Any]:
        """Minimal TII result when full analyzer is unavailable."""
        return {
            "tii_sym": 0.50,
            "tii_status": "ACCEPTABLE",
            "tii_grade": "ACCEPTABLE",
            "integrity": 0.50,
            "twms_score": 0.50,
            "gate_status": "CLOSED",
            "gate_passed": False,
            "valid": True,
            "components": {},
            "twms_signals": {},
            "computed_vwap": 0.0,
            "computed_energy": 0.0,
            "computed_bias": 0.0,
            "timestamp": datetime.now(UTC).isoformat(),
            "note": "minimal_fallback",
        }


# ═══════════════════════════════════════════════════════════════════════════
# §3  FACTORY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════


def get_l7_analyzer(**kwargs: Any) -> Any:
    """Return full L7ProbabilityAnalyzer if available, else L7MinimalAnalyzer."""
    try:
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer

        return L7ProbabilityAnalyzer(**kwargs)
    except ImportError:
        logger.warning("[L7_L8_minimal] MonteCarloEngine unavailable — using L7MinimalAnalyzer")
        return L7MinimalAnalyzer()


def get_l8_adapter(gate_threshold: float = 0.60) -> L8PipelineAdapter:
    """Return L8PipelineAdapter (always wraps real analyzer if available)."""
    return L8PipelineAdapter(gate_threshold=gate_threshold)
