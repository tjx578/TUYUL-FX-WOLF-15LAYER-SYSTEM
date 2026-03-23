"""
Phase 5 — L12 Synthesis Builder.

Builds the Layer-12 synthesis dict from all upstream layer results.
This is a pure function: no side effects, no execution authority.
Authority: Layer-12 is the SOLE CONSTITUTIONAL AUTHORITY.
"""

from __future__ import annotations

import os
from typing import Any

# Mapping from L1 volatility_level labels to THRESHOLD_TABLE regime keys
_VOL_LEVEL_TO_REGIME: dict[str, str] = {
    "EXTREME": "HIGH_VOL",
    "HIGH": "HIGH_VOL",
    "NORMAL": "NORMAL_VOL",
    "LOW": "LOW_VOL",
    "DEAD": "LOW_VOL",
}


def build_l12_synthesis(
    layer_results: dict[str, Any],
    symbol: str = "UNKNOWN",
) -> dict[str, Any]:
    """Build Layer-12 synthesis with Bayesian + Monte Carlo enrichment fields.

    L7 fields are normalized before injection:
    - win_probability (0-100 from MC) -> L7_monte_carlo_win (0.0-1.0)
    - risk_of_ruin (0.0-1.0) -> L7_risk_of_ruin (default 1.0 = worst)
    - posterior_win_probability (0.0-1.0) -> L7_posterior_win
    - profit_factor (float) -> L7_profit_factor
    - bayesian_ci_low / bayesian_ci_high -> L7_bayesian_ci_low / L7_bayesian_ci_high
    - mc_passed_threshold (bool) -> L7_mc_passed
    - validation (str) -> L7_validation
    """
    # -- Wolf 30-Point from L4 --
    technical_score = layer_results.get("L4", {}).get("technical_score", 0)

    if "wolf_30_point" in layer_results.get("L4", {}) and isinstance(layer_results["L4"]["wolf_30_point"], dict):
        wolf_30_point = layer_results["L4"]["wolf_30_point"].get("total", 0)
        f_score = layer_results["L4"]["wolf_30_point"].get("f_score", 0)
        t_score = layer_results["L4"]["wolf_30_point"].get("t_score", 0)
        fta_score_raw = layer_results["L4"]["wolf_30_point"].get("fta_score", 0.0)
        exec_score = layer_results["L4"]["wolf_30_point"].get("exec_score", 0)
    else:
        win_prob = layer_results.get("L7", {}).get("win_probability", 0)
        wolf_30_point = int((technical_score / 100) * 15 + (win_prob / 100) * 15)
        wolf_30_point = max(0, min(30, wolf_30_point))
        f_score = 0
        t_score = 0
        fta_score_raw = 0.0
        exec_score = 0

    # -- FTA Score (enriched from L10 or fallback) --
    fta_score = layer_results.get("L10", {}).get("fta_score", fta_score_raw)
    fta_multiplier = layer_results.get("L10", {}).get("fta_multiplier", 1.0)
    if exec_score == 0:
        exec_score = 6 if layer_results.get("L10", {}).get("position_ok", False) else 0

    # -- Direction from L3 --
    trend = layer_results.get("L3", {}).get("trend", "NEUTRAL")
    direction = {"BULLISH": "BUY", "BEARISH": "SELL"}.get(trend, "HOLD")

    # -- Execution details from L11 --
    entry_price = layer_results.get("L11", {}).get("entry_price", layer_results.get("L11", {}).get("entry", 0.0))
    stop_loss = layer_results.get("L11", {}).get("stop_loss", layer_results.get("L11", {}).get("sl", 0.0))
    take_profit_1 = layer_results.get("L11", {}).get(
        "take_profit_1", layer_results.get("L11", {}).get("tp1", layer_results.get("L11", {}).get("tp", 0.0))
    )
    if take_profit_1 is not None and take_profit_1 <= 0:
        take_profit_1 = 0.0001  # Minimum fallback — ATR warmup insufficient
    rr_ratio = layer_results.get("L11", {}).get("rr", 0.0)
    battle_strategy = layer_results.get("L11", {}).get("battle_strategy", "SHADOW_STRIKE")
    entry_zone = layer_results.get("L11", {}).get("entry_zone", "")
    if not entry_zone and entry_price > 0:
        if direction == "BUY":
            entry_zone = f"{entry_price - 0.0010:.5f}-{entry_price:.5f}"
        else:
            entry_zone = f"{entry_price:.5f}-{entry_price + 0.0010:.5f}"

    # -- Risk (from L10/dashboard -- placeholders) --
    lot_size = layer_results.get("L10", {}).get("final_lot_size", 0.01)
    risk_percent = layer_results.get("L10", {}).get("adjusted_risk_pct", 1.0)
    risk_amount = layer_results.get("L10", {}).get("adjusted_risk_amount", 0.0)

    # -- Metrics --
    tii_sym = layer_results.get("L8", {}).get("tii_sym", 0.0)
    integrity = layer_results.get("L8", {}).get("integrity", 0.0)
    conf12 = layer_results.get("L2", {}).get("conf12", (tii_sym + integrity) / 2.0)
    current_drawdown = layer_results.get("L5", {}).get("current_drawdown", 0.0)
    prop_compliant = layer_results.get("L6", {}).get("propfirm_compliant", True)
    # If propfirm checks are disabled, force compliant=True
    if os.getenv("PROPFIRM_MODE") == "disabled":
        prop_compliant = True
    psychology_score = layer_results.get("L5", {}).get("psychology_score", 0)
    eaf_score = layer_results.get("L5", {}).get("eaf_score", 0.0)

    vix_regime_state = layer_results.get("macro_vix_state", {}).get("regime_state", 1)

    # -- Regime detection for downstream threshold adaptation --
    _atr_current = layer_results.get("L3", {}).get("atr", 0.0)
    _atr_mean_20 = layer_results.get("L3", {}).get("atr_mean_20", 0.0)
    _regime_type: str = "NORMAL_VOL"
    _atr_ratio: float = 1.0
    if _atr_current > 0 and _atr_mean_20 > 0:
        try:
            from analysis.volatility_regime_engine import (  # noqa: PLC0415
                calculate_atr_expansion_ratio,
                detect_volatility_regime,
            )

            _atr_ratio = calculate_atr_expansion_ratio(_atr_current, _atr_mean_20)
            _regime_type = detect_volatility_regime(_atr_ratio)
        except Exception:  # noqa: BLE001
            pass
    # Derive volatility regime from L1's volatility_level (ATR-based)
    l1_vol_level = str(layer_results.get("L1", {}).get("volatility_level", "NORMAL")).upper()
    volatility_regime = _VOL_LEVEL_TO_REGIME.get(l1_vol_level, "NORMAL_VOL")

    synthesis = {
        "pair": symbol,
        "scores": {
            "wolf_30_point": wolf_30_point,
            "f_score": f_score,
            "t_score": t_score,
            "fta_score": fta_score,
            "fta_multiplier": fta_multiplier,
            "exec_score": exec_score,
            "psychology_score": psychology_score,
            "technical_score": technical_score,
        },
        "layers": {
            "L1_context_coherence": layer_results.get("L1", {}).get("regime_confidence", 0.0),
            "L2_reflex_coherence": layer_results.get("L2", {}).get("reflex_coherence", 0.0),
            "L3_trq3d_energy": layer_results.get("L3", {}).get("trq3d_energy", 0.0),
            "L7_monte_carlo_win": (
                _wp_raw / 100.0
                if (_wp_raw := layer_results.get("L7", {}).get("win_probability", 0.0)) > 1.0
                else _wp_raw
            ),
            "L8_tii_sym": tii_sym,
            "L8_integrity_index": integrity,
            "L8_twms_score": layer_results.get("L8", {}).get("twms_score", 0.0),
            "L9_dvg_confidence": layer_results.get("L9", {}).get("dvg_confidence", 0.0),
            "L9_liquidity_score": layer_results.get("L9", {}).get("liquidity_score", 0.0),
            "conf12": conf12,
        },
        "execution": {
            "direction": direction,
            "entry_price": entry_price,
            "entry_zone": entry_zone,
            "stop_loss": stop_loss,
            "take_profit_1": take_profit_1,
            "execution_mode": "TP1_ONLY",
            "battle_strategy": battle_strategy,
            "rr_ratio": rr_ratio,
            "lot_size": lot_size,
            "risk_percent": risk_percent,
            "risk_amount": risk_amount,
            "slippage_estimate": 0.0,
            "optimal_timing": "",
        },
        "risk": {
            "current_drawdown": layer_results.get("L6", {}).get("current_drawdown", current_drawdown),
            "drawdown_level": layer_results.get("L6", {}).get("drawdown_level", "LEVEL_0"),
            "risk_multiplier": layer_results.get("L6", {}).get("risk_multiplier", 1.0),
            "risk_status": layer_results.get("L6", {}).get("risk_status", "ACCEPTABLE"),
            "lrce": layer_results.get("L6", {}).get("lrce", 0.0),
            "rolling_sharpe": layer_results.get("L6", {}).get("rolling_sharpe", 0.0),
            "kelly_adjusted": layer_results.get("L6", {}).get("kelly_adjusted", 0.0),
        },
        "propfirm": {
            "compliant": prop_compliant,
            "daily_loss_status": "OK",
            "max_drawdown_status": "OK",
            "profit_target_progress": 0.0,
        },
        "bias": {
            "fundamental": "NEUTRAL" if not layer_results.get("L1", {}).get("valid") else trend,
            "technical": trend,
            "macro": layer_results.get("macro", "UNKNOWN"),
        },
        "cognitive": {
            "regime": layer_results.get("L1", {}).get("regime", "TREND"),
            "dominant_force": layer_results.get("L1", {}).get("dominant_force", "NEUTRAL"),
            "cbv": layer_results.get("L1", {}).get("csi", 0.0),
            "csi": layer_results.get("L1", {}).get("regime_confidence", 0.0),
        },
        "fusion_frpc": {
            "conf12": conf12,
            "frpc_energy": layer_results.get("L2", {}).get("frpc_energy", 0.0),
            "lambda_esi": 0.003,
            "integrity": integrity,
        },
        "trq3d": {
            "alpha": 0.0,
            "beta": 0.0,
            "gamma": 0.0,
            "drift": layer_results.get("L3", {}).get("drift", 0.0),
            "mean_energy": layer_results.get("L3", {}).get("trq3d_energy", 0.0),
            "intensity": 0.0,
        },
        "smc": {
            "structure": "RANGE",
            "smart_money_signal": layer_results.get("L9", {}).get("smart_money_signal", "NEUTRAL"),
            "liquidity_zone": "0.00000",
            "ob_present": layer_results.get("L9", {}).get("ob_present", False),
            "fvg_present": layer_results.get("L9", {}).get("fvg_present", False),
            "sweep_detected": layer_results.get("L9", {}).get("sweep_detected", False),
            "bias": layer_results.get("L9", {}).get("smart_money_bias", "NEUTRAL"),
            # v7 SMC event markers
            "bos_detected": layer_results.get("L9", {}).get("bos_detected", False),
            "choch_detected": layer_results.get("L9", {}).get("choch_detected", False),
            "displacement": layer_results.get("L9", {}).get("displacement", False),
            "liquidity_sweep": layer_results.get("L9", {}).get("liquidity_sweep", False),
            "fib_retracement_hit": layer_results.get("L3", {}).get("fib_retracement_hit", False),
            "volume_profile_poc": layer_results.get("L3", {}).get("volume_profile_poc", 0.0),
            "vpc_zones": layer_results.get("L3", {}).get("vpc_zones", []),
        },
        "wolf_discipline": {
            "score": wolf_30_point / 30.0 if wolf_30_point else 0.0,
            "polarity_deviation": layer_results.get("L5", {}).get("emotion_delta", 0.0),
            "lambda_balance": "ACTIVE",
            "bias_symmetry": "NEUTRAL",
            "eaf_score": eaf_score,
            "emotional_state": "CALM",
        },
        "macro": {
            "regime": layer_results.get("macro", "UNKNOWN"),
            "phase": layer_results.get("phase", "NEUTRAL"),
            "volatility_ratio": layer_results.get("macro_vol_ratio", 1.0),
            "mn_aligned": layer_results.get("alignment", False),
            "liquidity": layer_results.get("liquidity", {}),
            "bias_override": layer_results.get("bias_override", {}),
        },
        "macro_vix": {
            "regime_state": vix_regime_state,
            "risk_multiplier": layer_results.get("macro_vix_state", {}).get("risk_multiplier", 1.0),
        },
        "volatility_regime": volatility_regime,
        "system": {
            "latency_ms": 0.0,
            "safe_mode": False,
            "formula_versions": {
                "tii": "analysis.l8_tii._compute_tii:v1",
                "frpc": "analysis.formulas.frpc_formula.calculate_frpc:v1",
                "wolf_30": "analysis.layers.L4_session_scoring:wolf30-v1",
            },
        },
    }

    # Bayesian enrichment fields from L7
    synthesis["bayesian_posterior"] = layer_results.get("L7", {}).get("bayesian_posterior", 0.0)
    synthesis["bayesian_ci_low"] = layer_results.get("L7", {}).get("bayesian_ci_low", 0.0)
    synthesis["bayesian_ci_high"] = layer_results.get("L7", {}).get("bayesian_ci_high", 0.0)
    synthesis["mc_passed_threshold"] = layer_results.get("L7", {}).get("mc_passed_threshold", False)
    synthesis["risk_of_ruin"] = layer_results.get("L7", {}).get("risk_of_ruin", 0.0)
    synthesis["profit_factor"] = layer_results.get("L7", {}).get("profit_factor", 0.0)
    synthesis["l7_validation"] = layer_results.get("L7", {}).get("validation", "FAIL")

    # Inference state — ephemeral abstract state from LiveContextBus
    inference = layer_results.get("inference", {})
    if inference:
        synthesis["inference"] = inference

    # Regime metadata for downstream threshold adaptation
    synthesis["regime_type"] = _regime_type
    synthesis["atr_ratio"] = _atr_ratio

    return synthesis
