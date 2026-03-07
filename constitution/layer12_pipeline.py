from __future__ import annotations

from typing import Any, Literal, TypedDict

from analysis.volatility_regime_engine import calculate_atr_expansion_ratio, detect_volatility_regime
from config.thresholds import get_thresholds
from constitution.verdict_engine import (
    layer12_verdict_layer,
    meta_gate_model_integrity,
    meta_gate_statistical_edge,
    meta_gate_structural_edge,
)
from core.frpc_engine import calculate_frpc
from core.tii_engine import calculate_tii

# ── Type definitions ──────────────────────────────────────────────────────────

RegimeType = Literal["LOW_VOL", "NORMAL_VOL", "HIGH_VOL"]
MetaGateResult = Literal["PASS", "FAIL", "CONDITIONAL"]
VerdictType = Literal["EXECUTE", "EXECUTE_REDUCED_RISK", "HOLD"]


class MetaResults(TypedDict):
    structural: MetaGateResult
    model_integrity: MetaGateResult
    statistical: MetaGateResult


class PipelineResult(TypedDict):
    regime: RegimeType
    thresholds: dict[str, float]
    tii: float
    frpc: float
    meta_results: MetaResults
    verdict: VerdictType
    risk_multiplier: float


def layer12_pipeline(
    trq: float,
    intensity: float,
    bias_strength: float,
    integrity: float,
    price: float,
    vwap: float,
    atr: float,
    fusion: float,
    alpha: float,
    beta: float,
    gamma: float,
    exhaustion_conf: float,
    liquidity: float,
    mc_win: float,
    mc_pf: float,
    rr: float,
    posterior: float,
    structural_score: float,
    atr_mean_20: float,
) -> PipelineResult:
    """Run the Layer-12 constitutional pipeline.

    This is the critical decision path: analysis metrics flow in,
    a single EXECUTE / EXECUTE_REDUCED_RISK / HOLD verdict flows out.
    No execution side-effects — pure computation only.

    Args:
        trq: Trend Quality score.
        intensity: Market intensity metric.
        bias_strength: Directional bias strength.
        integrity: Model integrity score (0–1).
        price: Current price.
        vwap: Volume Weighted Average Price.
        atr: Current ATR value.
        fusion: Exhaustion/divergence fusion score.
        alpha: Alpha regime coefficient.
        beta: Beta regime coefficient.
        gamma: Gamma regime coefficient.
        exhaustion_conf: Exhaustion confidence (0–1).
        liquidity: Liquidity score (0–1).
        mc_win: Monte Carlo win rate.
        mc_pf: Monte Carlo profit factor.
        rr: Risk/Reward ratio.
        posterior: Bayesian posterior probability.
        structural_score: Structural analysis score.
        atr_mean_20: 20-period ATR mean (for regime detection).

    Returns:
        PipelineResult containing regime, thresholds, TII, FRPC,
        meta-gate results, verdict, and risk multiplier.
    """
    atr_current: float = atr
    atr_ratio: float = calculate_atr_expansion_ratio(atr_current, atr_mean_20)
    regime: RegimeType = detect_volatility_regime(atr_ratio)
    thresholds: dict[str, float] = get_thresholds(regime)

    tii_raw: float | None = calculate_tii(trq, intensity, bias_strength, integrity, price, vwap, atr)
    tii: float = tii_raw if tii_raw is not None else 0.0
    frpc: float = calculate_frpc(fusion, trq, intensity, alpha, beta, gamma, integrity)

    # Meta-gate decision
    meta_results: MetaResults = {
        "structural": "PASS" if meta_gate_structural_edge(exhaustion_conf, liquidity) else "FAIL",
        "model_integrity": meta_gate_model_integrity(tii, frpc, integrity, thresholds),
        "statistical": "PASS" if meta_gate_statistical_edge(mc_win, mc_pf, rr, posterior, thresholds) else "FAIL",
    }

    verdict: VerdictType = layer12_verdict_layer(meta_results)
    return PipelineResult(
        regime=regime,
        thresholds=thresholds,
        tii=tii,
        frpc=frpc,
        meta_results=meta_results,
        verdict=verdict,
        risk_multiplier=thresholds["risk_mult"],
    )
