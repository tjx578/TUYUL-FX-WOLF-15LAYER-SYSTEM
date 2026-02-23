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


def layer12_pipeline(
    trq, intensity, bias_strength, integrity,
    price, vwap, atr, fusion,
    alpha, beta, gamma,
    exhaustion_conf, liquidity,
    mc_win, mc_pf, rr, posterior,
    structural_score,
    atr_mean_20  # <-- Add as argument
):
    atr_current = atr
    atr_ratio = calculate_atr_expansion_ratio(atr_current, atr_mean_20)
    regime = detect_volatility_regime(atr_ratio)
    thresholds = get_thresholds(regime)

    tii = calculate_tii(trq, intensity, bias_strength, integrity, price, vwap, atr)
    if tii is None:
        tii = 0.0
    frpc = calculate_frpc(fusion, trq, intensity, alpha, beta, gamma, integrity)

    # Meta-gate decision
    meta_results = {
        "structural": "PASS" if meta_gate_structural_edge(exhaustion_conf, liquidity) else "FAIL",
        "model_integrity": meta_gate_model_integrity(tii, frpc, integrity, thresholds),
        "statistical": "PASS" if meta_gate_statistical_edge(mc_win, mc_pf, rr, posterior, thresholds) else "FAIL",
    }

    verdict = layer12_verdict_layer(meta_results)
    return {
        "regime": regime,
        "thresholds": thresholds,
        "tii": tii,
        "frpc": frpc,
        "meta_results": meta_results,
        "verdict": verdict,
        "risk_multiplier": thresholds["risk_mult"]
    }
